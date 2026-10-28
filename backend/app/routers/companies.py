import io
from datetime import UTC, date, datetime, timedelta
from typing import Literal

import pandas as pd
from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import any_, select

from app.ai import claude, usage
from app.ai.grounding import build_company_context, extract_numbers, validate_statements
from app.config import get_settings
from app.exports import safe_df
from app.models import Brief as BriefRecord
from app.models import Company, Country, HSCode, ProspectList, ProspectListItem, RefreshRun, ReviewStatus, User
from app.reports import render_company_brief_pdf
from app.routers.markets import _run_out
from app.security import DB, Analyst, CurrentUser
from app.services import audit, jobs, research

router = APIRouter(prefix="/api", tags=["companies"])
Relationship = Literal["buyer", "retailer", "competitor", "supplier"]
Identity = Literal["confirmed", "needs_confirmation", "unverified"]
Stage = Literal["identified", "researched", "contacted", "negotiating", "won", "lost"]


def company_out(c: Company, countries: dict[str, str] | None = None) -> dict:
    return {
        "id": c.id,
        "name": c.name,
        "country_iso3": c.country_iso3,
        "country_name": (countries or {}).get(c.country_iso3, c.country_iso3),
        "website": c.website,
        "relationship_type": c.relationship_type,
        "roles": c.roles,
        "summary": c.summary,
        "product_range": c.product_range,
        "product_fit": c.product_fit,
        "private_label": c.private_label,
        "private_label_evidence": c.private_label_evidence,
        "buying_signals": c.buying_signals or [],
        "markets_served": c.markets_served or [],
        "contact": c.contact or {},
        "name_on_source": c.name_on_source,
        "prospect_score": c.prospect_score,
        "score_components": c.score_components or {},
        "pipeline_stage": c.pipeline_stage,
        "identity_status": c.identity_status,
        "aliases": c.aliases or [],
        "vendor_url": c.vendor_url,
        "owner_id": c.owner_id,
        "next_action": c.next_action,
        "follow_up_on": c.follow_up_on.isoformat() if c.follow_up_on else None,
        "notes": c.notes,
        "hs_codes": c.hs_codes,
        "review_status": c.review_status,
        "has_brief": c.brief is not None,
        "brief_generated_at": c.brief_generated_at.isoformat() if c.brief_generated_at else None,
        "evidence": [
            {
                "id": e.id,
                "claim": e.claim,
                "excerpt": e.excerpt,
                "source": {
                    "id": e.source.id,
                    "url": e.source.url,
                    "title": e.source.title,
                    "retrieved_at": e.source.retrieved_at.isoformat(),
                },
            }
            for e in c.evidence
        ],
    }


def _country_names(db) -> dict[str, str]:
    return {c.iso3: c.name for c in db.scalars(select(Country)) if c.iso3}


def _get(db, company_id: int) -> Company:
    c = db.get(Company, company_id)
    if not c:
        raise HTTPException(404, "Company not found.")
    return c


@router.get("/companies")
def list_companies(
    _: CurrentUser,
    db: DB,
    hs: str | None = None,
    country_iso3: str | None = None,
    status: str | None = None,
    role: str | None = None,
    relationship: Relationship | None = None,
):
    stmt = select(Company).order_by(Company.prospect_score.desc().nulls_last(), Company.name)
    if hs:
        stmt = stmt.where(hs == any_(Company.hs_codes))
    if country_iso3:
        stmt = stmt.where(Company.country_iso3 == country_iso3.upper())
    if status:
        stmt = stmt.where(Company.review_status == status)
    if role:
        stmt = stmt.where(role == any_(Company.roles))
    if relationship:
        stmt = stmt.where(Company.relationship_type == relationship)
    names = _country_names(db)
    return [company_out(c, names) for c in db.scalars(stmt)]


class CompanyPatch(BaseModel):
    review_status: ReviewStatus | None = None
    pipeline_stage: Stage | None = None
    relationship_type: Relationship | None = None
    identity_status: Identity | None = None
    vendor_url: str | None = Field(None, max_length=1000, pattern=r"^(https?://\S+)?$")
    owner_id: int | None = None
    next_action: str | None = Field(None, max_length=2000)
    follow_up_on: date | None = None
    notes: str | None = Field(None, max_length=8000)


@router.patch("/companies/{company_id}")
def update_company(company_id: int, body: CompanyPatch, user: Analyst, db: DB):
    c = _get(db, company_id)
    changes = body.model_dump(exclude_unset=True)
    for k in ("review_status", "pipeline_stage", "relationship_type", "identity_status"):
        if k in changes and changes[k] is None:
            changes.pop(k)  # these cannot be cleared
    if changes.get("owner_id") is not None and not db.get(User, changes["owner_id"]):
        raise HTTPException(422, "Unknown owner.")
    for k, v in changes.items():
        setattr(c, k, v)
    if body.review_status is not None:
        c.reviewed_by = user.id
    if {"review_status", "relationship_type"} & changes.keys():
        research.rescore(c, research.market_scores(db, c.hs_codes))
    detail = ", ".join(f"{k}={v}" for k, v in changes.items() if k != "notes")
    audit.record(db, user, "update", "company", c.id, detail + (" (notes edited)" if "notes" in changes else ""))
    db.commit()
    return company_out(c, _country_names(db))


@router.get("/companies/{company_id}/brief")
def get_brief(company_id: int, _: CurrentUser, db: DB):
    c = _get(db, company_id)
    if c.brief is None:
        raise HTTPException(404, "No brief has been generated for this company yet.")
    return c.brief


class BriefIn(BaseModel):
    language: Literal["en", "ar"] | None = None


def _unsupported(brief, evidence) -> list[float]:
    """Numbers in the brief that no cited/available evidence contains (statements, email, WhatsApp)."""
    allowed = [v for e in evidence for v in e.values if v]
    bad = []
    for sec in brief.sections:
        for st in validate_statements([x.model_dump() for x in sec.statements], evidence):
            if st["label"] == "unverified":
                bad += [
                    float(i.split(":")[1].split(",")[0]) for i in st["issues"] if i.startswith("unsupported_number")
                ]
    for text in (brief.outreach_email.subject, brief.outreach_email.body, brief.whatsapp_message):
        bad += [n for n in extract_numbers(text) if not any(abs(n - v) <= 0.02 * abs(v) for v in allowed)]
    return bad


@router.post("/companies/{company_id}/brief")
def generate_brief(company_id: int, user: Analyst, db: DB, body: BriefIn | None = None):
    """Grounded account brief. A draft with numbers that are not in the facts bundle is retried once, then
    rejected; nothing unverified is saved."""
    c = _get(db, company_id)
    language = (body.language if body and body.language else None) or user.language or "en"
    usage.check_budget(db, user.id)
    evidence = build_company_context(db, c)
    feedback, total_cost, brief, use = "", 0.0, None, {}
    for _attempt in range(2):
        brief, use = claude.write_company_brief(c.name, evidence, language, feedback)
        total_cost += usage.record(db, user.id, "company_brief", use)
        db.commit()
        bad = _unsupported(brief, evidence)
        if not bad:
            break
        feedback = "it contained numbers not in the evidence: " + ", ".join(f"{n:g}" for n in bad[:10]) + "."
    else:
        audit.record(db, user, "generate_brief_rejected", "company", c.id, feedback)
        db.commit()
        raise HTTPException(
            502, "The AI draft twice used numbers that are not in the evidence, so it was not saved. Try again later."
        )
    sections = [
        {"title": s.title, "statements": validate_statements([x.model_dump() for x in s.statements], evidence)}
        for s in brief.sections
    ]
    content = {
        "company": c.name,
        "language": language,
        "generated_at": datetime.now(UTC).isoformat(),
        "model": use.get("model"),
        "prompt_version": claude.COMPANY_BRIEF_PROMPT_VERSION,
        "cost_usd": total_cost,
        "sections": sections,
        "outreach_email": {"subject": brief.outreach_email.subject, "body": brief.outreach_email.body, "warnings": []},
        "whatsapp_message": brief.whatsapp_message,
        "evidence": [e.as_dict() for e in evidence],
    }
    c.brief, c.brief_generated_at = content, datetime.now(UTC)
    db.add(
        BriefRecord(
            company_id=c.id,
            language=language,
            content=content,
            facts_bundle=content["evidence"],
            model=use.get("model", ""),
            prompt_version=claude.COMPANY_BRIEF_PROMPT_VERSION,
            input_tokens=use.get("input_tokens", 0),
            output_tokens=use.get("output_tokens", 0),
            cost_usd=total_cost,
            created_by=user.id,
        )
    )
    if c.pipeline_stage == "identified":
        c.pipeline_stage = "researched"
    audit.record(db, user, "generate_brief", "company", c.id, f"{language}, cost ${total_cost:.4f}")
    db.commit()
    return content


@router.get("/companies/{company_id}/briefs")
def brief_history(company_id: int, _: CurrentUser, db: DB):
    _get(db, company_id)
    rows = db.scalars(
        select(BriefRecord)
        .where(BriefRecord.company_id == company_id)
        .order_by(BriefRecord.created_at.desc())
        .limit(20)
    )
    return [
        {
            "id": b.id,
            "language": b.language,
            "model": b.model,
            "prompt_version": b.prompt_version,
            "cost_usd": b.cost_usd,
            "created_at": b.created_at.isoformat(),
        }
        for b in rows
    ]


@router.get("/companies/{company_id}/brief/pdf")
def brief_pdf(company_id: int, user: CurrentUser, db: DB, brief_id: int | None = None):
    c = _get(db, company_id)
    content = c.brief
    if brief_id:
        b = db.get(BriefRecord, brief_id)
        if not b or b.company_id != c.id:
            raise HTTPException(404, "Brief not found.")
        content = b.content
    if not content:
        raise HTTPException(404, "No brief has been generated for this company yet.")
    audit.record(db, user, "export", "brief", c.id, content.get("language", "en"))
    db.commit()
    safe = "".join(ch if ch.isalnum() else "-" for ch in c.name).strip("-").lower() or "company"
    return Response(
        render_company_brief_pdf(content),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="brief-{safe}.pdf"'},
    )


class ResearchIn(BaseModel):
    hs_code: str
    country_m49: int
    kind: Literal["buyers", "competitors", "suppliers"] = "buyers"
    product_id: int | None = None
    force: bool = False


@router.post("/research", status_code=202)
def start_research(body: ResearchIn, user: Analyst, db: DB, tasks: BackgroundTasks):
    if not get_settings().ai_enabled:
        raise HTTPException(503, "AI is not configured. Add ANTHROPIC_API_KEY to the backend .env file.")
    country = db.get(Country, body.country_m49)
    if not country or not db.get(HSCode, body.hs_code):
        raise HTTPException(404, "Unknown country or HS code.")
    scope = f"HS {body.hs_code} · {country.iso3} · {body.kind}"
    prev = db.scalar(
        select(RefreshRun)
        .where(RefreshRun.adapter == "web_research", RefreshRun.scope == scope)
        .order_by(RefreshRun.id.desc())
        .limit(1)
    )
    if jobs.is_live(prev):
        return _run_out(prev)
    recent = prev and datetime.now(UTC) - prev.started_at < timedelta(days=7)
    if prev and prev.status == "succeeded" and recent and not body.force:
        return _run_out(prev)  # cached: avoids paying for the same searches twice
    usage.check_budget(db, user.id)
    run = RefreshRun(adapter="web_research", scope=scope, started_by=user.id, status="queued", message="Queued")
    db.add(run)
    audit.record(db, user, "research", "company", "", scope)
    db.commit()
    tasks.add_task(research.run_research, run.id, body.hs_code, body.country_m49, body.kind, body.product_id, user.id)
    return _run_out(run)


EXPORT_COLUMNS = [
    "name",
    "relationship_type",
    "country_iso3",
    "website",
    "roles",
    "prospect_score",
    "private_label",
    "pipeline_stage",
    "review_status",
    "summary",
    "product_fit",
    "email",
    "phone",
    "address",
    "source_url",
    "source_retrieved",
]


def _csv(companies: list[Company], filename: str) -> Response:
    rows = []
    for c in companies:
        ev = c.evidence[0].source if c.evidence else None
        contact = c.contact or {}
        rows.append(
            {
                "name": c.name,
                "relationship_type": c.relationship_type,
                "country_iso3": c.country_iso3,
                "website": c.website,
                "roles": ", ".join(c.roles),
                "prospect_score": c.prospect_score,
                "private_label": c.private_label,
                "pipeline_stage": c.pipeline_stage,
                "review_status": c.review_status,
                "summary": c.summary,
                "product_fit": c.product_fit,
                "email": contact.get("email", ""),
                "phone": contact.get("phone", ""),
                "address": contact.get("address", ""),
                "source_url": ev.url if ev else "",
                "source_retrieved": ev.retrieved_at.date().isoformat() if ev else "",
            }
        )
    buf = io.StringIO()
    safe_df(pd.DataFrame(rows, columns=EXPORT_COLUMNS)).to_csv(buf, index=False)
    return Response(
        buf.getvalue().encode("utf-8-sig"),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/companies/export")
def export_companies(user: CurrentUser, db: DB, hs: str | None = None, relationship: Relationship | None = None):
    stmt = select(Company).order_by(Company.relationship_type, Company.prospect_score.desc().nulls_last(), Company.name)
    if hs:
        stmt = stmt.where(hs == any_(Company.hs_codes))
    if relationship:
        stmt = stmt.where(Company.relationship_type == relationship)
    rows = list(db.scalars(stmt))
    audit.record(db, user, "export", "company", "", f"{len(rows)} rows ({relationship or 'all'})")
    db.commit()
    return _csv(rows, f"companies{'-' + relationship if relationship else ''}.csv")


class ListIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    hs_code: str | None = None


def _list_companies(db, list_id: int) -> list[Company]:
    items = db.scalars(select(ProspectListItem).where(ProspectListItem.list_id == list_id)).all()
    return [c for c in (db.get(Company, i.company_id) for i in items) if c]


@router.get("/prospect-lists")
def lists(_: CurrentUser, db: DB):
    names = _country_names(db)
    return [
        {
            "id": pl.id,
            "name": pl.name,
            "hs_code": pl.hs_code,
            "created_at": pl.created_at.isoformat(),
            "companies": [company_out(c, names) for c in _list_companies(db, pl.id)],
        }
        for pl in db.scalars(select(ProspectList).order_by(ProspectList.created_at.desc()))
    ]


@router.post("/prospect-lists", status_code=201)
def create_list(body: ListIn, user: Analyst, db: DB):
    pl = ProspectList(name=body.name, hs_code=body.hs_code, created_by=user.id)
    db.add(pl)
    db.flush()
    audit.record(db, user, "create", "prospect_list", pl.id, body.name)
    db.commit()
    return {
        "id": pl.id,
        "name": pl.name,
        "hs_code": pl.hs_code,
        "created_at": pl.created_at.isoformat(),
        "companies": [],
    }


@router.get("/prospect-lists/{list_id}/export")
def export_list(list_id: int, user: CurrentUser, db: DB):
    pl = db.get(ProspectList, list_id)
    if not pl:
        raise HTTPException(404, "List not found.")
    safe = "".join(ch if ch.isalnum() else "-" for ch in pl.name).strip("-").lower() or "list"
    audit.record(db, user, "export", "prospect_list", list_id, pl.name)
    db.commit()
    return _csv(_list_companies(db, list_id), f"prospects-{safe}.csv")


@router.post("/prospect-lists/{list_id}/companies/{company_id}", status_code=204)
def add_to_list(list_id: int, company_id: int, user: Analyst, db: DB):
    if not db.get(ProspectList, list_id) or not db.get(Company, company_id):
        raise HTTPException(404, "List or company not found.")
    exists = db.scalar(
        select(ProspectListItem).where(ProspectListItem.list_id == list_id, ProspectListItem.company_id == company_id)
    )
    if not exists:
        db.add(ProspectListItem(list_id=list_id, company_id=company_id))
        audit.record(db, user, "add_to_list", "prospect_list", list_id, f"company {company_id}")
        db.commit()


@router.delete("/prospect-lists/{list_id}/companies/{company_id}", status_code=204)
def remove_from_list(list_id: int, company_id: int, user: Analyst, db: DB):
    item = db.scalar(
        select(ProspectListItem).where(ProspectListItem.list_id == list_id, ProspectListItem.company_id == company_id)
    )
    if item:
        db.delete(item)
        audit.record(db, user, "remove_from_list", "prospect_list", list_id, f"company {company_id}")
        db.commit()
