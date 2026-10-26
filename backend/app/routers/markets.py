from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.analytics import COMPONENT_LABELS, DEFAULT_WEIGHTS
from app.models import HSCode, RefreshRun
from app.security import DB, Analyst, CurrentUser
from app.services import trade

router = APIRouter(prefix="/api/markets", tags=["markets"])
STALE_RUN = timedelta(minutes=20)


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
    if running and running.status == "running" and datetime.now(UTC) - running.started_at < STALE_RUN:
        return _run_out(running)
    run = RefreshRun(adapter="un_comtrade", scope=f"HS {hs}", started_by=user.id, message="Queued")
    db.add(run)
    db.commit()
    tasks.add_task(trade.refresh_hs, run.id, hs)
    return _run_out(run)


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
    return {"weights": w, "labels": COMPONENT_LABELS, "min_value_usd": 1e6, "markets": trade.ranking(db, hs, w)}


@router.get("/{hs}/countries/{m49}")
def country(hs: str, m49: int, _: CurrentUser, db: DB):
    _hs(db, hs)
    d = trade.country_detail(db, hs, m49)
    if not d:
        raise HTTPException(404, "No trade data for this country and product.")
    return d
