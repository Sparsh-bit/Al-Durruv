from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.adapters.stubs import FREIGHT, SHIPMENTS
from app.ai import usage as ai_usage
from app.config import get_settings
from app.models import (
    AiUsage,
    ApiCache,
    AuditLog,
    Company,
    LogisticsQuote,
    RefreshRun,
    SourceRecord,
    TradeObservation,
)
from app.routers.client import country_index
from app.routers.markets import _run_out
from app.security import DB, Admin, CurrentUser
from app.services import audit, settings

router = APIRouter(prefix="/api", tags=["admin"])


@router.get("/admin/sources")
def sources(_: CurrentUser, db: DB):
    s = get_settings()
    last = db.scalar(select(RefreshRun).where(RefreshRun.adapter == "un_comtrade").order_by(RefreshRun.id.desc()))
    return [
        {
            "key": "un_comtrade",
            "name": "UN Comtrade (country-level trade statistics)",
            "status": "connected",
            "detail": "Subscription API"
            if s.comtrade_subscription_key
            else "Free public preview (no key; max 500 records per request)",
            "observations": db.scalar(select(func.count()).select_from(TradeObservation)),
            "cached_responses": db.scalar(select(func.count()).select_from(ApiCache)),
            "last_run": _run_out(last),
        },
        {
            "key": "claude",
            "name": "Claude AI analyst and web research",
            "status": "connected" if s.ai_enabled else "not_configured",
            "detail": f"Models: {s.model_fast} (fast), {s.model_brief} (briefs)"
            if s.ai_enabled
            else "Set ANTHROPIC_API_KEY in .env to enable AI features.",
            "companies": db.scalar(select(func.count()).select_from(Company)),
        },
        SHIPMENTS,
        FREIGHT,
    ]


@router.get("/admin/runs")
def runs(_: Admin, db: DB, limit: int = 50):
    rows = db.scalars(select(RefreshRun).order_by(RefreshRun.id.desc()).limit(min(limit, 200)))
    return [_run_out(r) for r in rows]


@router.get("/sources/{source_id}")
def source(source_id: int, _: CurrentUser, db: DB):
    s = db.get(SourceRecord, source_id)
    if not s:
        raise HTTPException(404, "Source not found.")
    return {
        "id": s.id,
        "adapter": s.adapter,
        "url": s.url,
        "title": s.title,
        "params": s.params,
        "reporting_period": s.reporting_period,
        "licence": s.licence,
        "retrieved_at": s.retrieved_at.isoformat(),
    }


class QuoteIn(BaseModel):
    origin: str = Field(min_length=2, max_length=120)
    origin_iso3: str = Field("", pattern="^([A-Za-z]{3})?$")
    payload_kg: float | None = Field(None, gt=0, le=100000)
    destination: str = Field(min_length=2, max_length=120)
    destination_iso3: str = Field(min_length=3, max_length=3)
    mode: str = Field(pattern="^(sea|air|road|rail)$")
    container: str = Field("", max_length=40)
    carrier: str = Field("", max_length=120)
    incoterm: str = Field("", pattern="^(|EXW|FCA|FOB|CFR|CIF|CPT|CIP|DAP|DPU|DDP)$")
    assumptions: str = Field("", max_length=2000)
    cost_usd: float | None = Field(None, ge=0)
    transit_days: int | None = Field(None, ge=0, le=365)
    source_note: str = Field(min_length=3, description="Who quoted it and when")
    valid_until: datetime | None = None


def _quote(q: LogisticsQuote) -> dict:
    return {
        "id": q.id,
        "origin": q.origin,
        "origin_iso3": q.origin_iso3,
        "payload_kg": q.payload_kg,
        "cost_per_kg": q.cost_usd / q.payload_kg if q.cost_usd is not None and q.payload_kg else None,
        "destination": q.destination,
        "destination_iso3": q.destination_iso3,
        "mode": q.mode,
        "container": q.container,
        "carrier": q.carrier,
        "incoterm": q.incoterm,
        "assumptions": q.assumptions,
        "cost_usd": q.cost_usd,
        "transit_days": q.transit_days,
        "provenance": q.provenance,
        "source_note": q.source_note,
        "valid_until": q.valid_until.isoformat() if q.valid_until else None,
        "created_at": q.created_at.isoformat(),
    }


@router.get("/logistics")
def logistics(_: CurrentUser, db: DB, destination_iso3: str | None = None):
    stmt = select(LogisticsQuote).order_by(LogisticsQuote.created_at.desc())
    if destination_iso3:
        stmt = stmt.where(LogisticsQuote.destination_iso3 == destination_iso3.upper())
    return {"providers": [FREIGHT, SHIPMENTS], "quotes": [_quote(q) for q in db.scalars(stmt)]}


@router.post("/logistics", status_code=201)
def add_quote(body: QuoteIn, user: Admin, db: DB):
    q = LogisticsQuote(
        **{
            **body.model_dump(),
            "destination_iso3": body.destination_iso3.upper(),
            "origin_iso3": body.origin_iso3.upper(),
        },
        provenance="client_provided",
        created_by=user.id,
    )
    db.add(q)
    db.flush()
    audit.record(db, user, "create", "logistics_quote", q.id, f"{q.origin} → {q.destination} {q.mode}")
    db.commit()
    db.refresh(q)
    return _quote(q)


@router.delete("/logistics/{quote_id}", status_code=204)
def delete_quote(quote_id: int, user: Admin, db: DB):
    q = db.get(LogisticsQuote, quote_id)
    if not q:
        raise HTTPException(404, "Quote not found.")
    db.delete(q)
    audit.record(db, user, "delete", "logistics_quote", quote_id)
    db.commit()


class ProfileIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    brand: str = Field("", max_length=120)
    country_iso3: str = Field(pattern="^[A-Za-z]{3}$")
    founded: str = Field("", max_length=20)
    description: str = Field("", max_length=2000)
    label_languages: list[str] = Field(default_factory=list, max_length=20)
    certifications: list[str] = Field(default_factory=list, max_length=20)


class PrivateLabelWeights(BaseModel):
    market_size: float = Field(ge=0, le=100)
    growth: float = Field(ge=0, le=100)
    retailer_presence: float = Field(ge=0, le=100)
    private_label_signal: float = Field(ge=0, le=100)
    evidence: float = Field(ge=0, le=100)


class SettingsIn(BaseModel):
    company_profile: ProfileIn
    priority_categories: list[str] = Field(default_factory=list, max_length=30)
    private_label_weights: PrivateLabelWeights
    ai_monthly_budget_usd: float = Field(ge=0, le=100000)


def _settings_out(db) -> dict:
    return {k: settings.get(db, k) for k in settings.DEFAULTS}


@router.get("/admin/settings")
def get_app_settings(_: CurrentUser, db: DB):
    return _settings_out(db)


@router.put("/admin/settings")
def put_app_settings(body: SettingsIn, user: Admin, db: DB):
    if sum(body.private_label_weights.model_dump().values()) <= 0:
        raise HTTPException(422, "At least one opportunity weight must be above zero.")
    profile = {**body.company_profile.model_dump(), "country_iso3": body.company_profile.country_iso3.upper()}
    categories = list(dict.fromkeys(c.strip() for c in body.priority_categories if c.strip()))
    settings.put(db, "company_profile", profile)
    settings.put(db, "priority_categories", categories)
    settings.put(db, "private_label_weights", body.private_label_weights.model_dump())
    settings.put(db, "ai_monthly_budget_usd", body.ai_monthly_budget_usd)
    audit.record(
        db,
        user,
        "update",
        "settings",
        "",
        f"{len(categories)} priority categories, budget ${body.ai_monthly_budget_usd:g}",
    )
    db.commit()
    return _settings_out(db)


@router.get("/countries")
def countries(_: CurrentUser, db: DB):
    names, _lookup = country_index(db)  # one row per ISO3 (Comtrade can have several codes per country)
    return [{"iso3": iso, "name": name} for iso, name in sorted(names.items(), key=lambda x: x[1])]


@router.get("/admin/ai-usage")
def ai_usage_report(_: Admin, db: DB):
    start = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    by_feature = db.execute(
        select(
            AiUsage.feature,
            func.count(),
            func.sum(AiUsage.cost_usd),
            func.sum(AiUsage.input_tokens),
            func.sum(AiUsage.output_tokens),
            func.sum(AiUsage.web_searches),
        )
        .where(AiUsage.created_at >= start)
        .group_by(AiUsage.feature)
        .order_by(func.sum(AiUsage.cost_usd).desc())
    ).all()
    recent = db.scalars(select(AiUsage).order_by(AiUsage.id.desc()).limit(30)).all()
    return {
        "month_spend_usd": ai_usage.month_spend(db),
        "budget_usd": float(settings.get(db, "ai_monthly_budget_usd")),
        "model": get_settings().model_brief,
        "by_feature": [
            {
                "feature": f,
                "calls": n,
                "cost_usd": round(c or 0, 4),
                "input_tokens": i or 0,
                "output_tokens": o or 0,
                "web_searches": w or 0,
            }
            for f, n, c, i, o, w in by_feature
        ],
        "recent": [
            {
                "at": r.created_at.isoformat(),
                "feature": r.feature,
                "model": r.model,
                "input_tokens": r.input_tokens,
                "output_tokens": r.output_tokens,
                "cache_read_tokens": r.cache_read_tokens,
                "web_searches": r.web_searches,
                "cost_usd": r.cost_usd,
            }
            for r in recent
        ],
    }


@router.get("/admin/audit")
def audit_log(_: Admin, db: DB, limit: int = 100):
    rows = db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(min(limit, 500)))
    return [
        {
            "at": r.created_at.isoformat(),
            "user": r.user_email,
            "action": r.action,
            "entity": r.entity,
            "entity_id": r.entity_id,
            "detail": r.detail,
        }
        for r in rows
    ]
