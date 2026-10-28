"""Trade explorer: user-chosen product, reporters/region, partner, flow and years over stored Comtrade data.

Missing values are returned as null (never zero). Region totals are only summed for years in which every
selected reporter has data; otherwise the year is reported as not comparable.
"""

import threading
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters import comtrade
from app.config import get_settings
from app.models import Country, TradeObservation
from app.services import settings, trade

DEFAULT_TOP = 12
_inflight: set[str] = set()
_inflight_lock = threading.Lock()


class Busy(Exception):
    pass


def iso_to_m49(db: Session) -> dict[str, list[int]]:
    """Comtrade can use more than one code per ISO3 (USA is 840 and 842)."""
    out: dict[str, list[int]] = defaultdict(list)
    for c in db.scalars(select(Country)):
        if c.iso3:
            out[c.iso3.upper()].append(c.m49)
    return out


def resolve_reporters(db: Session, reporters: list[str], region: str | None) -> tuple[list[str], list[str]]:
    """Return (ISO3 list, unknown codes)."""
    wanted = [r.strip().upper() for r in reporters if r.strip()]
    if region:
        regions = settings.get(db, "regions")
        if region not in regions:
            raise KeyError(region)
        wanted += regions[region]
    known = iso_to_m49(db)
    unknown = sorted({w for w in wanted if w not in known})
    return list(dict.fromkeys(w for w in wanted if w in known)), unknown


def explore(
    db: Session,
    hs: str,
    *,
    flow: str = "M",
    reporters: list[str] | None = None,
    region: str | None = None,
    partner: str = "WLD",
    year_from: int | None = None,
    year_to: int | None = None,
) -> dict:
    isos, unknown = resolve_reporters(db, reporters or [], region)
    codes = iso_to_m49(db)
    countries = {c.m49: c for c in db.scalars(select(Country))}
    partner_codes = [trade.WORLD] if partner.upper() in ("WLD", "W00", "WORLD", "") else codes.get(partner.upper(), [])
    if not partner_codes:
        unknown.append(partner.upper())

    stmt = select(TradeObservation).where(
        TradeObservation.hs_code == hs,
        TradeObservation.flow == flow,
        TradeObservation.partner_m49.in_(partner_codes or [-1]),
    )
    if isos:
        stmt = stmt.where(TradeObservation.reporter_m49.in_([m for i in isos for m in codes[i]]))
    if year_from:
        stmt = stmt.where(TradeObservation.year >= year_from)
    if year_to:
        stmt = stmt.where(TradeObservation.year <= year_to)
    obs = db.scalars(stmt).all()

    by_reporter: dict[str, dict[int, TradeObservation]] = defaultdict(dict)
    for o in obs:
        c = countries.get(o.reporter_m49)
        iso = c.iso3.upper() if c and c.iso3 else str(o.reporter_m49)
        prev = by_reporter[iso].get(o.year)
        if prev is None or o.value_usd > prev.value_usd:  # 840 vs 842: keep the fuller report
            by_reporter[iso][o.year] = o

    if not isos:  # default view: the largest reporters in their latest year
        ranked = sorted(by_reporter, key=lambda i: -by_reporter[i][max(by_reporter[i])].value_usd)
        isos = ranked[:DEFAULT_TOP]
    years = sorted({y for i in isos for y in by_reporter.get(i, {})})
    if year_from and year_to:
        years = list(range(year_from, year_to + 1))

    names = {}
    for c in sorted(countries.values(), key=lambda c: c.m49):
        names.setdefault((c.iso3 or "").upper(), c.name)
    for iso, ys in by_reporter.items():  # name a series after the code that actually reported it
        c = countries.get(next(iter(ys.values())).reporter_m49)
        if c:
            names[iso] = c.name
    with_data = [i for i in isos if by_reporter.get(i)]
    with_data.sort(key=lambda i: -by_reporter[i][max(by_reporter[i])].value_usd)
    isos = with_data + [i for i in isos if not by_reporter.get(i)]
    series, sources = [], {}
    for iso in isos:
        ys = by_reporter.get(iso, {})
        latest = max(ys) if ys else None
        for o in ys.values():
            sources[o.source.id] = trade._src(o)
        series.append(
            {
                "iso3": iso,
                "name": names.get(iso, iso),
                "values": {str(y): (ys[y].value_usd if y in ys else None) for y in years},
                "net_weight_kg": {str(y): (ys[y].net_weight_kg if y in ys else None) for y in years},
                "qty_unit": next((o.qty_unit for o in ys.values() if o.qty_unit), ""),
                "latest_year": latest,
                "missing_years": [y for y in years if y not in ys],
                "source_ids": sorted({o.source.id for o in ys.values()}),
            }
        )

    latest_years = {s["latest_year"] for s in series if s["latest_year"]}
    warnings = []
    if len(latest_years) > 1:
        warnings.append(
            f"Reporters' latest years differ ({min(latest_years)}–{max(latest_years)}); compare like-for-like years."
        )
    no_data = [s["iso3"] for s in series if s["latest_year"] is None]
    if no_data:
        warnings.append(f"No stored data for {', '.join(no_data)} with these filters.")
    if unknown:
        warnings.append(f"Unknown country code(s) ignored: {', '.join(sorted(set(unknown)))}.")

    totals = []
    for y in years:
        vals = [s["values"][str(y)] for s in series if s["latest_year"] is not None]
        present = [v for v in vals if v is not None]
        complete = bool(vals) and len(present) == len(vals)
        totals.append(
            {
                "year": y,
                "value_usd": sum(present) if complete else None,
                "reporters_with_data": len(present),
                "reporters": len(vals),
                "comparable": complete,
            }
        )
    common = [t["year"] for t in totals if t["comparable"]]
    return {
        "hs_code": hs,
        "flow": flow,
        "partner": partner.upper() or "WLD",
        "region": region,
        "years": years,
        "series": series,
        "totals": totals,
        "latest_comparable_year": max(common) if common else None,
        "warnings": warnings,
        "sources": sorted(sources.values(), key=lambda s: s["id"]),
        "licence": comtrade.LICENCE,
    }


def fetch_live(db: Session, hs: str, *, flow: str, reporters: list[str], partner: str, years: list[int]) -> dict:
    """One Comtrade request for the chosen reporters/years (cached, throttled, de-duplicated)."""
    codes = iso_to_m49(db)
    m49s = sorted({m for r in reporters for m in codes.get(r.upper(), [])})
    if not m49s:
        raise ValueError("Choose at least one known reporter country.")
    partner_code: int | None
    if partner.upper() in ("WLD", "W00", "WORLD", ""):
        partner_code = trade.WORLD
    elif partner.upper() == "ALL":
        partner_code = None
    else:
        p = codes.get(partner.upper())
        if not p:
            raise ValueError(f"Unknown partner country {partner}.")
        partner_code = p[0]
    key = f"{hs}|{flow}|{m49s}|{partner_code}|{years}"
    with _inflight_lock:
        if key in _inflight:
            raise Busy()
        _inflight.add(key)
    # the free preview API accepts one period per request; a subscription key takes them all at once
    periods = [",".join(map(str, sorted(years)))] if get_settings().comtrade_subscription_key else sorted(years)
    try:
        total = stored = 0
        truncated = False
        for period in periods:
            rows, src = comtrade.fetch(
                db,
                period=period,
                cmd=hs,
                flow=flow,
                reporter=",".join(map(str, m49s)),  # type: ignore[arg-type]
                partner=partner_code,
            )
            stored += trade._store(db, rows, hs, src.id)
            total += len(rows)
            truncated = truncated or len(rows) >= comtrade.max_records()
            db.commit()
        return {
            "rows": total,
            "stored": stored,
            "truncated": truncated,
            "requests": len(periods),
            "source": {"id": src.id, "url": src.url, "retrieved_at": src.retrieved_at.isoformat()},
        }
    finally:
        with _inflight_lock:
            _inflight.discard(key)
