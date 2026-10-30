from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import any_, select

from app import reports as render
from app.ai import claude
from app.ai import usage as ai_usage
from app.ai.grounding import build_context, validate_statements
from app.analytics import DEFAULT_WEIGHTS
from app.models import Company, HSCode, Product, Report
from app.routers.companies import _country_names, company_out
from app.security import DB, Analyst, CurrentUser
from app.services import audit, trade

router = APIRouter(prefix="/api/reports", tags=["reports"])


def _summary(r: Report) -> dict:
    v = r.content.get("validation", {})
    return {
        "id": r.id,
        "title": r.title,
        "hs_code": r.hs_code,
        "product_id": r.product_id,
        "created_at": r.created_at.isoformat(),
        "validation": v,
    }


class GenerateIn(BaseModel):
    product_id: int


@router.get("")
def list_reports(_: CurrentUser, db: DB):
    return [_summary(r) for r in db.scalars(select(Report).order_by(Report.created_at.desc()))]


@router.post("", status_code=201)
def generate(body: GenerateIn, user: Analyst, db: DB):
    product = db.get(Product, body.product_id)
    if not product:
        raise HTTPException(404, "Product not found.")
    hs = product.hs_code
    if not hs:
        raise HTTPException(409, "This product has no HS6 code yet. Map it in the catalogue first.")
    if not trade.overview(db, hs).get("has_data"):
        raise HTTPException(409, "Load trade statistics for this product before generating a brief.")
    ai_usage.check_budget(db, user.id)
    evidence = build_context(db, hs)
    brief, usage = claude.write_brief(product.name, hs, evidence)
    usage["cost_usd"] = ai_usage.record(db, user.id, "market_brief", usage)
    sections = [
        {"title": s.title, "statements": validate_statements([x.model_dump() for x in s.statements], evidence)}
        for s in brief.sections
    ]
    all_st = [s for sec in sections for s in sec["statements"]]
    withheld = sum(1 for s in all_st if s["label"] == "unverified")
    names = _country_names(db)
    companies = db.scalars(
        select(Company)
        .where(hs == any_(Company.hs_codes), Company.review_status != "rejected")
        .order_by(Company.review_status.desc(), Company.name)
    ).all()
    title = f"Market & Prospect Brief — {product.name}"
    content = {
        "title": title,
        "product": product.name,
        "hs_code": hs,
        "hs_description": db.get(HSCode, hs).description,
        "generated_at": datetime.now(UTC).isoformat(),
        "usage": usage,
        "sections": sections,
        "evidence": [e.as_dict() for e in evidence],
        "ranking": [
            {k: r[k] for k in ("rank", "name", "iso3", "score", "latest_value_usd", "latest_year")}
            for r in trade.ranking(db, hs)[:15]
        ],
        "weights": DEFAULT_WEIGHTS,
        "companies": [company_out(c, names) for c in companies],
        "validation": {"statements": len(all_st), "exported": len(all_st) - withheld, "withheld": withheld},
    }
    r = Report(
        title=title, hs_code=hs, product_id=product.id, content=content, model=usage["model"], created_by=user.id
    )
    db.add(r)
    db.flush()
    audit.record(db, user, "generate", "report", r.id, f"{title} (cost ${usage['cost_usd']:.4f})")
    db.commit()
    return {**_summary(r), "content": content}


def _get(db, report_id: int) -> Report:
    r = db.get(Report, report_id)
    if not r:
        raise HTTPException(404, "Report not found.")
    return r


@router.get("/{report_id}")
def get_report(report_id: int, _: CurrentUser, db: DB):
    r = _get(db, report_id)
    return {**_summary(r), "content": {k: v for k, v in r.content.items() if k != "model"}}


@router.get("/{report_id}/export")
def export(report_id: int, _: CurrentUser, db: DB, format: str = "pdf"):
    r = _get(db, report_id)
    data = {"content": r.content}
    if format == "pdf":
        body, mime = render.render_pdf(data), "application/pdf"
    elif format == "xlsx":
        body, mime = render.render_xlsx(data), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        raise HTTPException(400, "format must be pdf or xlsx")
    return Response(
        body,
        media_type=mime,
        headers={"Content-Disposition": f'attachment; filename="{render.filename(data, format)}"'},
    )


@router.delete("/{report_id}", status_code=204)
def delete_report(report_id: int, _: Analyst, db: DB):
    db.delete(_get(db, report_id))
    db.commit()
