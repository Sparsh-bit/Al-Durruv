from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.ai import usage
from app.analytics import COMPONENT_LABELS, DEFAULT_WEIGHTS
from app.config import get_settings
from app.models import HSCode, MarketNews, Product, RefreshRun, TradeObservation
from app.security import DB, Analyst, CurrentUser
from app.services import audit, research, settings, trade

router = APIRouter(prefix="/api/markets", tags=["markets"])
ACTIVE = ("queued", "running")


def _run_out(r: RefreshRun | None) -> dict | None:
    if not r:
        return None
    return {
        "id": r.id,
        "adapter": r.adapter,
        "scope": r.scope,
        "status": r.status,
        "rows": r.rows,
        "message": r.message,
        "error": r.error,
        "started_at": r.started_at.isoformat(),
        "finished_at": r.finished_at.isoformat() if r.finished_at else None,
    }


def _hs(db, code: str) -> HSCode:
    h = db.get(HSCode, code)
    if not h:
        raise HTTPException(404, f"Unknown HS code {code}.")
    return h


def latest_run(db, hs: str) -> RefreshRun | None:
    return db.scalar(
        select(RefreshRun)
        .where(RefreshRun.adapter == "un_comtrade", RefreshRun.scope == f"HS {hs}")
        .order_by(RefreshRun.id.desc())
        .limit(1)
    )


@router.get("/{hs}/overview")
def overview(hs: str, _: CurrentUser, db: DB):
    _hs(db, hs)
    return {**trade.overview(db, hs), "refresh": _run_out(latest_run(db, hs))}


@router.post("/{hs}/refresh", status_code=202)
def refresh(hs: str, user: Analyst, db: DB, tasks: BackgroundTasks):
    _hs(db, hs)
    running = latest_run(db, hs)
    if running and running.status in ACTIVE:
        return _run_out(running)
    run = RefreshRun(adapter="un_comtrade", scope=f"HS {hs}", started_by=user.id, message="Queued")
    db.add(run)
    db.commit()
    tasks.add_task(trade.refresh_hs, run.id, hs)
    return _run_out(run)


def _coverage(db) -> dict[str, tuple[str, RefreshRun | None]]:
    """State of each catalogue HS code: loaded, active (queued/running), failed or missing.

    Jobs run inside the API process and startup marks orphaned runs as failed, so any
    queued/running row is genuinely active."""
    has_data = set(db.scalars(select(TradeObservation.hs_code).distinct()))
    out = {}
    for hs in sorted(set(db.scalars(select(Product.hs_code).distinct()))):
        r = latest_run(db, hs)
        if r and r.status in ACTIVE:
            state = "active"
        elif (r and r.status == "succeeded") or (r is None and hs in has_data):
            state = "loaded"
        elif r and r.status == "failed":
            state = "failed"
        else:
            state = "missing"
        out[hs] = (state, r)
    return out


@router.post("/refresh-missing", status_code=202)
def refresh_missing(user: Analyst, db: DB, tasks: BackgroundTasks):
    """Queue a refresh for every catalogue HS code that is not loaded and not already being refreshed."""
    jobs, already = [], 0
    for hs, (state, _) in _coverage(db).items():
        if state == "active":
            already += 1
        elif state in ("missing", "failed"):
            run = RefreshRun(
                adapter="un_comtrade", scope=f"HS {hs}", started_by=user.id, status="queued", message="Queued"
            )
            db.add(run)
            db.flush()
            jobs.append((run.id, hs))
    db.commit()
    if jobs:
        tasks.add_task(trade.refresh_many, jobs)
    return {"queued": len(jobs), "already_active": already}


@router.get("/status")
def data_status(_: CurrentUser, db: DB):
    """Trade-data coverage of the catalogue's HS codes, for the product catalogue page."""
    cov = _coverage(db)
    states = [state for state, _ in cov.values()]
    return {
        "hs_codes": len(cov),
        "loaded": states.count("loaded"),
        "failed": [hs for hs, (state, _) in cov.items() if state == "failed"],
        "active": [
            {"hs_code": hs, "status": r.status, "message": r.message}
            for hs, (state, r) in cov.items()
            if state == "active"
        ],
    }


@router.get("/runs/{run_id}")
def run_status(run_id: int, _: CurrentUser, db: DB):
    r = db.get(RefreshRun, run_id)
    if not r:
        raise HTTPException(404, "Refresh run not found.")
    return _run_out(r)


class Weights(BaseModel):
    market_size: float = Field(DEFAULT_WEIGHTS["market_size"], ge=0, le=100)
    growth: float = Field(DEFAULT_WEIGHTS["growth"], ge=0, le=100)
    openness: float = Field(DEFAULT_WEIGHTS["openness"], ge=0, le=100)
    price_level: float = Field(DEFAULT_WEIGHTS["price_level"], ge=0, le=100)
    data_quality: float = Field(DEFAULT_WEIGHTS["data_quality"], ge=0, le=100)


@router.post("/{hs}/ranking")
def ranking(hs: str, weights: Weights, _: CurrentUser, db: DB):
    _hs(db, hs)
    w = weights.model_dump()
    if sum(w.values()) <= 0:
        raise HTTPException(422, "At least one weight must be above zero.")
    ours = set(settings.get(db, "export_markets"))
    markets = [{**m, "existing_market": m["iso3"] in ours} for m in trade.ranking(db, hs, w)]
    return {
        "weights": w,
        "labels": COMPONENT_LABELS,
        "min_value_usd": 1e6,
        "markets": markets,
        "export_markets_set": bool(ours),
    }


def _latest_news(db, hs: str) -> MarketNews | None:
    stmt = select(MarketNews).where(MarketNews.hs_code == hs).order_by(MarketNews.retrieved_at.desc()).limit(1)
    return db.scalar(stmt)


@router.get("/{hs}/news")
def news(hs: str, _: CurrentUser, db: DB):
    _hs(db, hs)
    row = _latest_news(db, hs)
    return {"items": row.items if row else [], "retrieved_at": row.retrieved_at.isoformat() if row else None}


class NewsIn(BaseModel):
    product_name: str = Field("", max_length=255)
    force: bool = False


@router.post("/{hs}/news")
def refresh_news(hs: str, body: NewsIn, user: Analyst, db: DB):
    _hs(db, hs)
    if not get_settings().ai_enabled:
        raise HTTPException(503, "AI is not configured. Add ANTHROPIC_API_KEY to the backend .env file.")
    row = _latest_news(db, hs)
    if row and not body.force and datetime.now(UTC) - row.retrieved_at < timedelta(days=7):
        return {"items": row.items, "retrieved_at": row.retrieved_at.isoformat(), "cached": True}
    usage.check_budget(db)
    audit.record(db, user, "research_news", "market", hs)
    db.commit()
    return research.run_news(hs, body.product_name, user.id)


@router.get("/{hs}/countries/{m49}")
def country(hs: str, m49: int, _: CurrentUser, db: DB):
    _hs(db, hs)
    d = trade.country_detail(db, hs, m49)
    if not d:
        raise HTTPException(404, "No trade data for this country and product.")
    return d
