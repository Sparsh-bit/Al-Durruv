"""Trade-statistics ingestion and country-level queries."""

from collections import defaultdict
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.adapters import comtrade
from app.analytics import DEFAULT_WEIGHTS, MarketInput, cagr, score_markets, unit_value
from app.config import get_settings
from app.db import SessionLocal
from app.models import Country, HSCode, MarketOpportunity, RefreshRun, TradeObservation

TOP_MARKETS_FOR_PARTNERS = 15
WORLD = 0


def _years() -> list[int]:
    this_year = datetime.now(UTC).year
    return list(range(this_year - get_settings().trade_years_back, this_year))


def _store(db: Session, rows: list[dict], hs: str, src_id: int) -> int:
    n = 0
    for r in rows:
        if r.get("primaryValue") is None or r.get("reporterCode") is None:
            continue
        for code, iso, name in (
            (r["reporterCode"], r.get("reporterISO"), r.get("reporterDesc")),
            (r.get("partnerCode"), r.get("partnerISO"), r.get("partnerDesc")),
        ):
            if code is None or int(code) == WORLD:
                continue
            db.execute(
                insert(Country).values(m49=int(code), iso3=iso or "", name=name or str(code)).on_conflict_do_nothing()
            )
        kg = r.get("netWgt")
        values = dict(
            value_usd=float(r["primaryValue"]),
            net_weight_kg=float(kg) if kg else None,
            qty=r.get("qty"),
            qty_unit=r.get("qtyUnitAbbr") or "",
            source_record_id=src_id,
        )
        stmt = insert(TradeObservation).values(
            reporter_m49=int(r["reporterCode"]),
            partner_m49=int(r.get("partnerCode") or 0),
            hs_code=hs,
            flow=r["flowCode"],
            year=int(r["refYear"]),
            **values,
        )
        db.execute(
            stmt.on_conflict_do_update(
                index_elements=["reporter_m49", "partner_m49", "hs_code", "flow", "year"], set_=values
            )
        )
        n += 1
    return n


def refresh_hs(run_id: int, hs: str) -> None:
    """Background job: pull imports/exports for all reporters, then supplier detail for top markets."""
    with SessionLocal() as db:
        run = db.get(RefreshRun, run_id)
        try:
            total = 0
            for flow in ("M", "X"):
                for year in _years():
                    run.message = f"Fetching {'imports' if flow == 'M' else 'exports'} {year}"
                    db.commit()
                    rows, src = comtrade.fetch(db, period=year, cmd=hs, flow=flow, partner=WORLD)
                    total += _store(db, rows, hs, src.id)
                    run.rows = total
                    db.commit()
            for i, (m49, year) in enumerate(_top_importers(db, hs, TOP_MARKETS_FOR_PARTNERS)):
                run.message = f"Supplier breakdown {i + 1}/{TOP_MARKETS_FOR_PARTNERS}"
                db.commit()
                rows, src = comtrade.fetch(db, period=year, cmd=hs, flow="M", reporter=m49, partner=None)
                total += _store(db, rows, hs, src.id)
                run.rows = total
                db.commit()
            snapshot_ranking(db, hs)
            run.status, run.message = "succeeded", f"Stored {total} observations"
        except Exception as exc:
            db.rollback()
            run = db.get(RefreshRun, run_id)
            run.status, run.error, run.message = "failed", str(exc)[:2000], "Refresh failed"
        run.finished_at = datetime.now(UTC)
        db.commit()


def _world_series(db: Session, hs: str, flow: str) -> dict[int, dict[int, TradeObservation]]:
    obs = db.scalars(
        select(TradeObservation).where(
            TradeObservation.hs_code == hs, TradeObservation.flow == flow, TradeObservation.partner_m49 == WORLD
        )
    ).all()
    out: dict[int, dict[int, TradeObservation]] = defaultdict(dict)
    for o in obs:
        out[o.reporter_m49][o.year] = o
    return out


def _top_importers(db: Session, hs: str, n: int) -> list[tuple[int, int]]:
    series = _world_series(db, hs, "M")
    latest = [(m49, max(ys), ys[max(ys)].value_usd) for m49, ys in series.items()]
    return [(m49, y) for m49, y, _ in sorted(latest, key=lambda t: -t[2])[:n]]


def _partners(db: Session, hs: str, reporter: int, year: int) -> list[TradeObservation]:
    return list(
        db.scalars(
            select(TradeObservation)
            .where(
                TradeObservation.hs_code == hs,
                TradeObservation.flow == "M",
                TradeObservation.reporter_m49 == reporter,
                TradeObservation.year == year,
                TradeObservation.partner_m49 != WORLD,
            )
            .order_by(TradeObservation.value_usd.desc())
        ).all()
    )


def _countries(db: Session) -> dict[int, Country]:
    return {c.m49: c for c in db.scalars(select(Country)).all()}


def _src(o: TradeObservation) -> dict:
    s = o.source
    return {
        "id": s.id,
        "url": s.url,
        "retrieved_at": s.retrieved_at.isoformat(),
        "period": s.reporting_period,
        "adapter": s.adapter,
    }


def overview(db: Session, hs: str) -> dict:
    countries = _countries(db)
    imports, exports = _world_series(db, hs, "M"), _world_series(db, hs, "X")
    if not imports:
        return {"hs_code": hs, "has_data": False}

    def block(series: dict[int, dict[int, TradeObservation]], limit: int):
        latest_year = max(max(ys) for ys in series.values())
        rows = [ys[latest_year] for ys in series.values() if latest_year in ys]
        total = sum(o.value_usd for o in rows)
        rows.sort(key=lambda o: -o.value_usd)
        return (
            latest_year,
            total,
            len(rows),
            [
                {
                    "m49": o.reporter_m49,
                    "iso3": countries[o.reporter_m49].iso3,
                    "name": countries[o.reporter_m49].name,
                    "value_usd": o.value_usd,
                    "net_weight_kg": o.net_weight_kg,
                    "share": o.value_usd / total if total else None,
                    "unit_value": unit_value(o.value_usd, o.net_weight_kg),
                    "year": o.year,
                    "source": _src(o),
                }
                for o in rows[:limit]
            ],
        )

    # Use the most recent year with broad coverage so totals compare like-for-like.
    years = sorted({y for ys in imports.values() for y in ys})
    counts = {y: sum(1 for ys in imports.values() if y in ys) for y in years}
    best = max(counts.values())
    ref_year = max(y for y in years if counts[y] >= 0.8 * best)
    trimmed = {m: {y: o for y, o in ys.items() if y <= ref_year} for m, ys in imports.items()}
    trimmed = {m: ys for m, ys in trimmed.items() if ys}
    m_year, m_total, m_count, top_importers = block(trimmed, 25)

    x_years = sorted({y for ys in exports.values() for y in ys})
    x_counts = {y: sum(1 for ys in exports.values() if y in ys) for y in x_years}
    x_ref = max(y for y in x_years if x_counts[y] >= 0.8 * max(x_counts.values())) if x_years else None
    x_trim = {m: {y: o for y, o in ys.items() if y <= x_ref} for m, ys in exports.items()} if x_ref else {}
    x_trim = {m: ys for m, ys in x_trim.items() if ys}
    x_block = block(x_trim, 15) if x_trim else (None, None, 0, [])

    trend = [
        {
            "year": y,
            "value_usd": sum(ys[y].value_usd for ys in imports.values() if y in ys),
            "reporters": counts[y],
            "complete": counts[y] >= 0.8 * best,
        }
        for y in years
    ]
    complete = {t["year"]: t["value_usd"] for t in trend if t["complete"]}
    world_cagr = cagr(complete)
    top5 = [r["m49"] for r in top_importers[:5]]
    top_trends = [
        {
            "m49": m,
            "name": countries[m].name,
            "series": [{"year": y, "value_usd": o.value_usd} for y, o in sorted(imports[m].items())],
        }
        for m in top5
    ]
    hs_row = db.get(HSCode, hs)
    return {
        "hs_code": hs,
        "hs_description": hs_row.description if hs_row else "",
        "has_data": True,
        "reference_year": m_year,
        "reporters": m_count,
        "world_imports_usd": m_total,
        "trend": trend,
        "world_cagr": world_cagr,
        "world_cagr_period": f"{min(complete)}–{max(complete)}" if world_cagr is not None else None,
        "top_importers": top_importers,
        "top_importer_trends": top_trends,
        "exporters_year": x_block[0],
        "world_exports_usd": x_block[1],
        "top_exporters": x_block[3],
        "note": "Sum of imports reported by countries to UN Comtrade; non-reporting countries are not included.",
    }


def country_detail(db: Session, hs: str, m49: int) -> dict | None:
    countries = _countries(db)
    series = _world_series(db, hs, "M").get(m49)
    if not series or m49 not in countries:
        return None
    year = max(series)
    latest = series[year]
    partners = _partners(db, hs, m49, year)
    total = sum(p.value_usd for p in partners) or None
    home = get_settings().home_country_iso3.upper()
    home_share = None
    if home and partners and total:
        home_share = (
            sum(p.value_usd for p in partners if countries.get(p.partner_m49) and countries[p.partner_m49].iso3 == home)
            / total
        )
    return {
        "m49": m49,
        "iso3": countries[m49].iso3,
        "name": countries[m49].name,
        "hs_code": hs,
        "series": [
            {
                "year": y,
                "value_usd": o.value_usd,
                "net_weight_kg": o.net_weight_kg,
                "unit_value": unit_value(o.value_usd, o.net_weight_kg),
                "source": _src(o),
            }
            for y, o in sorted(series.items())
        ],
        "latest_year": year,
        "latest_value_usd": latest.value_usd,
        "suppliers": [
            {
                "m49": p.partner_m49,
                "name": countries[p.partner_m49].name if p.partner_m49 in countries else str(p.partner_m49),
                "iso3": countries[p.partner_m49].iso3 if p.partner_m49 in countries else "",
                "value_usd": p.value_usd,
                "share": p.value_usd / total if total else None,
                "unit_value": unit_value(p.value_usd, p.net_weight_kg),
                "source": _src(p),
            }
            for p in partners[:15]
        ],
        "supplier_data_available": bool(partners),
        "home_country": home or None,
        "home_share": home_share,
    }


def ranking(db: Session, hs: str, weights: dict[str, float] | None = None, min_value_usd: float = 1e6) -> list[dict]:
    countries = _countries(db)
    inputs, src = [], {}
    for m49, ys in _world_series(db, hs, "M").items():
        year = max(ys)
        if ys[year].value_usd < min_value_usd or m49 not in countries:
            continue
        partners = _partners(db, hs, m49, year)
        inputs.append(
            MarketInput(
                m49=m49,
                iso3=countries[m49].iso3,
                name=countries[m49].name,
                series={y: o.value_usd for y, o in ys.items()},
                latest_kg=ys[year].net_weight_kg,
                partner_values={p.partner_m49: p.value_usd for p in partners} or None,
            )
        )
        src[m49] = _src(ys[year])
    return [
        {
            "rank": i + 1,
            "m49": r.m49,
            "iso3": r.iso3,
            "name": r.name,
            "score": r.score,
            "latest_year": r.latest_year,
            "latest_value_usd": r.latest_value,
            "components": r.components,
            "source": src[r.m49],
        }
        for i, r in enumerate(score_markets(inputs, weights))
    ]


def snapshot_ranking(db: Session, hs: str) -> None:
    db.query(MarketOpportunity).filter(MarketOpportunity.hs_code == hs).delete()
    for r in ranking(db, hs):
        db.add(
            MarketOpportunity(
                hs_code=hs, country_m49=r["m49"], score=r["score"], components=r["components"], weights=DEFAULT_WEIGHTS
            )
        )
