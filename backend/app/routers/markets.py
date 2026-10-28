from datetime import UTC, datetime, timedelta
from typing import Literal

import pandas as pd
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.adapters import comtrade
from app.ai import usage
from app.analytics import COMPONENT_LABELS, DEFAULT_WEIGHTS
from app.config import get_settings
from app.models import HSCode, MarketNews, Product, RefreshRun, TargetMarket, TradeObservation
from app.security import DB, Analyst, CurrentUser
from app.services import audit, explore, jobs, opportunities, research, trade

router = APIRouter(prefix="/api/markets", tags=["markets"])


def _run_out(r: RefreshRun | None) -> dict | None:
    if not r:
        return None
    return {
        "id": r.id,
        "adapter": r.adapter,
        "scope": r.scope,
        "status": jobs.effective_status(r),
        "rows": r.rows,
        "message": r.message,
        "error": r.error or (jobs.INTERRUPTED if jobs.effective_status(r) != r.status else ""),
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
    if jobs.is_live(running):
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
    for hs in sorted(set(db.scalars(select(Product.hs_code).where(Product.hs_code.is_not(None)).distinct()))):
        r = latest_run(db, hs)
        if jobs.is_live(r):
            state = "active"
        elif (r and r.status == "succeeded") or (r is None and hs in has_data):
            state = "loaded"
        elif r and jobs.effective_status(r) == "failed":
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
    segments = {t.iso3: t.segment for t in db.scalars(select(TargetMarket))}
    markets = [
        {**m, "segment": segments.get(m["iso3"]), "existing_market": segments.get(m["iso3"]) == "existing"}
        for m in trade.ranking(db, hs, w)
    ]
    return {
        "weights": w,
        "labels": COMPONENT_LABELS,
        "min_value_usd": 1e6,
        "markets": markets,
        "export_markets_set": bool(segments),
    }


@router.get("/{hs}/explore")
def explore_trade(
    hs: str,
    _: CurrentUser,
    db: DB,
    flow: Literal["M", "X"] = "M",
    reporters: list[str] = Query(default=[], max_length=60),
    region: str | None = None,
    partner: str = "WLD",
    year_from: int | None = Query(None, ge=1988, le=2100),
    year_to: int | None = Query(None, ge=1988, le=2100),
):
    _hs(db, hs)
    if year_from and year_to and year_from > year_to:
        raise HTTPException(422, "The start year must not be after the end year.")
    try:
        return explore.explore(
            db, hs, flow=flow, reporters=reporters, region=region, partner=partner, year_from=year_from, year_to=year_to
        )
    except KeyError:
        raise HTTPException(404, f"Unknown region {region}.") from None


class LiveFetchIn(BaseModel):
    flow: Literal["M", "X"] = "M"
    reporters: list[str] = Field(min_length=1, max_length=20)
    partner: str = Field("WLD", max_length=3)
    years: list[int] = Field(min_length=1, max_length=12)


@router.post("/{hs}/explore/fetch")
def explore_fetch(hs: str, body: LiveFetchIn, user: Analyst, db: DB):
    """Pull exactly the chosen slice from UN Comtrade (cached; identical requests are not repeated)."""
    _hs(db, hs)
    this_year = datetime.now(UTC).year
    if any(y < 1988 or y >= this_year for y in body.years):
        raise HTTPException(422, f"Years must be between 1988 and {this_year - 1}.")
    try:
        out = explore.fetch_live(
            db, hs, flow=body.flow, reporters=body.reporters, partner=body.partner, years=body.years
        )
    except explore.Busy:
        raise HTTPException(409, "The same request is already running.") from None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    except comtrade.QuotaExceeded as exc:
        raise HTTPException(
            429,
            f"UN Comtrade call quota is used up; retry in about {exc.wait_s // 60 + 1} min.",
            headers={"Retry-After": str(exc.wait_s)},
        ) from None
    except comtrade.ComtradeError as exc:
        raise HTTPException(502, f"UN Comtrade did not return data: {exc}") from None
    audit.record(db, user, "comtrade_fetch", "market", hs, f"{body.flow} {','.join(body.reporters)} {body.years}")
    db.commit()
    return out


class OpportunityWeights(BaseModel):
    market_size: float | None = Field(None, ge=0, le=100)
    growth: float | None = Field(None, ge=0, le=100)
    retailer_presence: float | None = Field(None, ge=0, le=100)
    private_label_signal: float | None = Field(None, ge=0, le=100)
    evidence: float | None = Field(None, ge=0, le=100)


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


# defined after /{hs}/... routes; single-segment paths do not clash with them
@router.post("/opportunities")
def private_label_opportunities(body: OpportunityWeights, _: CurrentUser, db: DB):
    w = body.model_dump(exclude_none=True)
    result = opportunities.compute(db, w)
    if sum(result["weights"].values()) <= 0:
        raise HTTPException(422, "At least one weight must be above zero.")
    return result


@router.get("/opportunities/export")
def export_opportunities(_: CurrentUser, db: DB):
    result = opportunities.compute(db)
    rows = [
        {
            "category": r["category"],
            "hs_codes": " ".join(r["hs_codes"]),
            "country": r["iso3"],
            "segment": r["segment"],
            "retailer": r["retailer"]["name"] if r["retailer"] else "",
            "retailer_identity": r["retailer"]["identity_status"] if r["retailer"] else "",
            "import_value_usd": r["import_value_usd"],
            "latest_year": r["latest_year"],
            "cagr": r["cagr"],
            **{f"component_{k}": v for k, v in r["components"].items()},
            "missing_components": " ".join(r["missing"]),
            "score": r["score"],
        }
        for r in result["rows"]
    ]
    meta = f"# Weights: {result['weights']}. Source: UN Comtrade (stored observations) and sourced retailer facts.\n"
    body = meta + pd.DataFrame(rows).to_csv(index=False)
    return Response(
        body.encode("utf-8-sig"),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="private-label-opportunities.csv"'},
    )
