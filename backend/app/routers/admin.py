from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.adapters.stubs import FREIGHT, SHIPMENTS
from app.config import get_settings
from app.models import ApiCache, Company, LogisticsQuote, RefreshRun, SourceRecord, TradeObservation
from app.routers.markets import _run_out
from app.security import DB, Admin, Analyst, CurrentUser

router = APIRouter(prefix="/api", tags=["admin"])


@router.get("/admin/sources")
def sources(_: Admin, db: DB):
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
            "detail": f"Model {s.claude_model}"
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
    destination: str = Field(min_length=2, max_length=120)
    destination_iso3: str = Field(min_length=3, max_length=3)
    mode: str = Field(pattern="^(sea|air|road|rail)$")
    container: str = ""
    cost_usd: float | None = Field(None, ge=0)
    transit_days: int | None = Field(None, ge=0, le=365)
    source_note: str = Field(min_length=3, description="Who quoted it and when")
    valid_until: datetime | None = None


def _quote(q: LogisticsQuote) -> dict:
    return {
        "id": q.id,
        "origin": q.origin,
        "destination": q.destination,
        "destination_iso3": q.destination_iso3,
        "mode": q.mode,
        "container": q.container,
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
def add_quote(body: QuoteIn, user: Analyst, db: DB):
    q = LogisticsQuote(
        **{**body.model_dump(), "destination_iso3": body.destination_iso3.upper()},
        provenance="client_provided",
        created_by=user.id,
    )
    db.add(q)
    db.commit()
    db.refresh(q)
    return _quote(q)


@router.delete("/logistics/{quote_id}", status_code=204)
def delete_quote(quote_id: int, _: Analyst, db: DB):
    q = db.get(LogisticsQuote, quote_id)
    if not q:
        raise HTTPException(404, "Quote not found.")
    db.delete(q)
    db.commit()
