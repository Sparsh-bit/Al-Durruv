"""Shipment-based analytics (buyers, retailers, competitors), landed cost and alerts.

Every function returns its inputs alongside its result so the UI can show how a number was calculated.
Values from shipment files are the provider's (often declared or estimated); they are labelled as such.
"""

import math
from collections import Counter, defaultdict
from datetime import date, timedelta
from statistics import median

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.analytics import hhi
from app.models import Alert, Company, LogisticsQuote, Product, RetailerRequirement, Shipment, Tariff, TradeObservation
from app.services import settings
from app.services.explore import iso_to_m49
from app.services.shipments import normalize_name

DEFAULT_FIT_WEIGHTS = {
    "category_match": 25,
    "volume": 20,
    "consistency": 15,
    "displaceable_origins": 20,
    "growth": 10,
    "supplier_change": 10,
}
FIT_LABELS = {
    "category_match": "Buys HS codes in the client's catalogue (HS6 match 100, same heading 50)",
    "volume": "Shipped weight in the last 12 months, log-scaled against the other buyers listed",
    "consistency": "Months with shipments in the last 12 (12 of 12 = 100)",
    "displaceable_origins": "Share of volume from origins the client competes with",
    "growth": "Weight in the last 6 months vs the 6 before (-50% → 0, +50% → 100)",
    "supplier_change": "Added a new supplier origin in the last 6 months (yes 100, no 0)",
}
DEFAULT_COMPETITOR_ORIGINS = ["TUR", "LBN", "IND", "CHN", "ESP", "GRC", "ITA", "USA", "MAR", "TUN", "IRN", "VNM"]


def _client_hs(db: Session) -> tuple[set[str], set[str]]:
    hs6, heads = set(), set()
    for p in db.scalars(select(Product)):
        for code in (p.hs_code or "", (p.client_hs_code or "")[:6]):
            if len(code) == 6:
                hs6.add(code)
                heads.add(code[:4])
    return hs6, heads


def buyer_metrics(rows: list[Shipment], today: date) -> dict:
    """Metrics for one consignee from its shipments (any period)."""
    last12 = [s for s in rows if s.shipped_on > today - timedelta(days=365)]
    months = sorted({(s.shipped_on.year, s.shipped_on.month) for s in last12})
    dates = sorted(s.shipped_on for s in rows)
    gaps = [(b - a).days for a, b in zip(dates, dates[1:], strict=False) if (b - a).days > 0]
    six = today - timedelta(days=182)
    recent = sum(s.weight_kg or 0 for s in rows if s.shipped_on > six)
    prior = sum(s.weight_kg or 0 for s in rows if six - timedelta(days=182) < s.shipped_on <= six)
    by_origin: dict[str, float] = defaultdict(float)
    for s in last12:
        by_origin[s.origin_iso3 or "?"] += s.weight_kg or 0
    old_origins = {s.origin_iso3 for s in rows if s.shipped_on <= six and s.origin_iso3}
    new_origins = sorted({s.origin_iso3 for s in rows if s.shipped_on > six and s.origin_iso3} - old_origins)
    with_weight = [s for s in last12 if s.weight_kg]
    return {
        "shipments_12m": len(last12),
        "shipments_total": len(rows),
        "active_months_12m": len(months),
        "median_gap_days": median(gaps) if gaps else None,
        "weight_kg_12m": sum(s.weight_kg or 0 for s in last12),
        "rows_without_weight_12m": len(last12) - len(with_weight),
        "weight_last6_kg": recent,
        "weight_prior6_kg": prior,
        "trend": (recent - prior) / prior if prior else None,
        "origins_12m": dict(sorted(by_origin.items(), key=lambda x: -x[1])),
        "origin_hhi": hhi(list(by_origin.values())) if sum(by_origin.values()) else None,
        "new_origins_6m": new_origins if old_origins else [],
        "first_shipment": dates[0].isoformat() if dates else None,
        "last_shipment": dates[-1].isoformat() if dates else None,
    }


def fit_score(
    m: dict,
    hs_codes: set[str],
    client: tuple[set[str], set[str]],
    competitor_origins: list[str],
    vol_range: tuple[float, float],
    weights: dict,
) -> dict:
    hs6, heads = client
    match = 100.0 if hs_codes & hs6 else 50.0 if {h[:4] for h in hs_codes} & heads else 0.0
    lo, hi = vol_range
    vol = m["weight_kg_12m"]
    volume = None if not vol else (100.0 if hi <= lo else 100 * (math.log10(vol) - lo) / (hi - lo))
    total = sum(m["origins_12m"].values())
    displace = 100 * sum(v for k, v in m["origins_12m"].items() if k in competitor_origins) / total if total else None
    growth = None if m["trend"] is None else max(0.0, min(100.0, (m["trend"] + 0.5) * 100))
    comp = {
        "category_match": match,
        "volume": volume,
        "consistency": 100 * m["active_months_12m"] / 12,
        "displaceable_origins": displace,
        "growth": growth,
        "supplier_change": 100.0 if m["new_origins_6m"] else 0.0,
    }
    used = {k: v for k, v in comp.items() if v is not None and weights.get(k, 0) > 0}
    tw = sum(weights[k] for k in used)
    score = round(sum(comp[k] * weights[k] for k in used) / tw, 1) if tw else None
    return {
        "score": score,
        "components": {k: (round(v, 1) if v is not None else None) for k, v in comp.items()},
        "missing": [k for k, v in comp.items() if v is None],
    }


def buyers(db: Session, hs: str | None = None, market: str | None = None, today: date | None = None) -> dict:
    today = today or date.today()
    stmt = select(Shipment).where(Shipment.consignee_company_id.is_not(None))
    if hs:
        stmt = stmt.where(or_(Shipment.hs6 == hs[:6], Shipment.hs_code.startswith(hs)))
    if market:
        stmt = stmt.where(Shipment.destination_iso3 == market.upper())
    grouped: dict[int, list[Shipment]] = defaultdict(list)
    for s in db.scalars(stmt):
        grouped[s.consignee_company_id].append(s)
    weights = {**DEFAULT_FIT_WEIGHTS, **(settings.get_raw(db, "buyer_fit_weights") or {})}
    origins = settings.get_raw(db, "competitor_origins") or DEFAULT_COMPETITOR_ORIGINS
    client = _client_hs(db)
    metrics = {cid: buyer_metrics(rows, today) for cid, rows in grouped.items()}
    vols = [math.log10(m["weight_kg_12m"]) for m in metrics.values() if m["weight_kg_12m"] > 0]
    vr = (min(vols), max(vols)) if vols else (0.0, 0.0)
    companies = {c.id: c for c in db.scalars(select(Company).where(Company.id.in_(list(grouped))))}
    out = []
    for cid, rows in grouped.items():
        m = metrics[cid]
        suppliers = Counter(s.shipper_name for s in rows if s.shipper_name)
        c = companies[cid]
        out.append(
            {
                "company": {
                    "id": c.id,
                    "name": c.name,
                    "country_iso3": c.country_iso3,
                    "relationship_type": c.relationship_type,
                    "identity_status": c.identity_status,
                },
                "metrics": m,
                "top_suppliers": [{"name": n, "shipments": k} for n, k in suppliers.most_common(5)],
                "hs_codes": sorted({s.hs6 for s in rows if s.hs6}),
                **fit_score(m, {s.hs6 for s in rows if s.hs6}, client, origins, vr, weights),
            }
        )
    out.sort(key=lambda x: (x["score"] is None, -(x["score"] or 0)))
    return {
        "weights": weights,
        "labels": FIT_LABELS,
        "competitor_origins": origins,
        "buyers": out,
        "source_note": "Shipment records from the uploaded provider files (licensed; values as declared).",
    }


def client_shipper_ids(db: Session) -> set[int]:
    aliases = settings.get_raw(db, "client_shipper_aliases") or []
    norms = {normalize_name(a) for a in aliases} - {""}
    if not norms:
        return set()
    return {
        c.id
        for c in db.scalars(select(Company))
        if c.normalized_name in norms or norms & {normalize_name(a) for a in (c.aliases or [])}
    }


def _company_ids(db: Session, company: Company) -> set[int]:
    """The company plus records whose normalised name equals one of its aliases (not fuzzy)."""
    norms = {company.normalized_name} | {normalize_name(a) for a in company.aliases or []}
    return {c.id for c in db.scalars(select(Company)) if c.normalized_name in norms} | {company.id}


def retailer_path(db: Session, company: Company) -> dict:
    ids = _company_ids(db, company)
    client_hs6, _ = _client_hs(db)
    direct = db.scalars(select(Shipment).where(Shipment.consignee_company_id.in_(ids))).all()
    by_supplier: dict[str, dict] = {}
    for s in direct:
        k = s.shipper_name or "Unknown shipper"
        d = by_supplier.setdefault(
            k, {"shipper": k, "origin_iso3": s.origin_iso3, "shipments": 0, "weight_kg": 0.0, "hs_codes": set()}
        )
        d["shipments"] += 1
        d["weight_kg"] += s.weight_kg or 0
        d["hs_codes"].add(s.hs6)
    markets = list({company.country_iso3, *(company.markets_served or [])} - {""})
    route_in = []
    if markets and client_hs6:
        res = buyers(db)
        route_in = [
            b
            for b in res["buyers"]
            if b["company"]["country_iso3"] in markets
            and set(b["hs_codes"]) & client_hs6
            and b["company"]["id"] not in ids
        ][:15]
    reqs = db.scalars(
        select(RetailerRequirement)
        .where(
            or_(
                RetailerRequirement.company_id == company.id,
                (RetailerRequirement.company_id.is_(None)) & (RetailerRequirement.market_iso3.in_(markets)),
            )
        )
        .order_by(RetailerRequirement.id)
    ).all()
    return {
        "company": {"id": company.id, "name": company.name, "markets": markets},
        "direct_importer": bool(direct),
        "direct_shipments": len(direct),
        "direct_client_hs_shipments": sum(1 for s in direct if s.hs6 in client_hs6),
        "suppliers": [
            {**v, "hs_codes": sorted(v["hs_codes"])}
            for v in sorted(by_supplier.values(), key=lambda x: -x["weight_kg"])
        ],
        "route_in": route_in,
        "requirements": [
            {
                "id": r.id,
                "title": r.title,
                "detail": r.detail,
                "source_url": r.source_url,
                "status": r.status,
                "market_iso3": r.market_iso3,
                "verified_at": r.verified_at.isoformat() if r.verified_at else None,
            }
            for r in reqs
        ],
    }


def competitor_tracker(db: Session, company: Company) -> dict:
    ids = _company_ids(db, company)
    rows = db.scalars(select(Shipment).where(Shipment.shipper_company_id.in_(ids))).all()
    ours = client_shipper_ids(db)
    our_buyers = (
        set(
            db.scalars(
                select(Shipment.consignee_company_id).where(
                    Shipment.shipper_company_id.in_(ours), Shipment.consignee_company_id.is_not(None)
                )
            )
        )
        if ours
        else set()
    )
    buyers_: dict[int, dict] = {}
    by_quarter: dict[str, float] = defaultdict(float)
    by_market: dict[str, float] = defaultdict(float)
    names = {c.id: c.name for c in db.scalars(select(Company))}
    for s in rows:
        q = f"{s.shipped_on.year}-Q{(s.shipped_on.month - 1) // 3 + 1}"
        by_quarter[q] += s.weight_kg or 0
        by_market[s.destination_iso3 or "?"] += s.weight_kg or 0
        if s.consignee_company_id:
            b = buyers_.setdefault(
                s.consignee_company_id,
                {
                    "id": s.consignee_company_id,
                    "name": names.get(s.consignee_company_id, ""),
                    "shipments": 0,
                    "weight_kg": 0.0,
                    "first": s.shipped_on,
                    "last": s.shipped_on,
                    "ours": False,
                },
            )
            b["shipments"] += 1
            b["weight_kg"] += s.weight_kg or 0
            b["first"], b["last"] = min(b["first"], s.shipped_on), max(b["last"], s.shipped_on)
            b["ours"] = s.consignee_company_id in our_buyers
    blist = sorted(buyers_.values(), key=lambda x: -x["weight_kg"])
    for b in blist:
        b["first"], b["last"] = b["first"].isoformat(), b["last"].isoformat()
    return {
        "company": {"id": company.id, "name": company.name, "aliases": company.aliases},
        "shipments": len(rows),
        "buyers": blist,
        "not_our_buyers": [b for b in blist if not b["ours"]],
        "by_quarter": dict(sorted(by_quarter.items())),
        "by_market": dict(sorted(by_market.items(), key=lambda x: -x[1])),
        "client_shippers_configured": bool(ours),
    }


# --- market access and landed cost ----------------------------------------------------------------


def _duty(db: Session, market: str, hs6: str, origin: str) -> dict | None:
    """Best known duty for origin into market: admin override > preferential for origin > MFN.
    Additional duties (overrides with rate_type 'additional') are added on top."""
    importers = {market, "EUN"} if market in _eu_members(db) else {market}
    rows = db.scalars(select(Tariff).where(Tariff.importer_iso3.in_(importers), Tariff.hs_code.startswith(hs6))).all()

    def pick(cands):
        return (
            sorted(cands, key=lambda t: (t.source != "override", -(t.data_year or 0), t.hs_code))[0] if cands else None
        )

    pref = pick([t for t in rows if t.rate_type == "preferential" and t.origin_iso3 == origin])
    mfn = pick([t for t in rows if t.rate_type == "MFN" and t.origin_iso3 in ("", origin)])
    base = pref if pref and pref.ad_valorem_pct is not None else mfn
    if not base:
        return None
    extra = [t for t in rows if t.rate_type == "additional" and t.origin_iso3 in ("", origin)]
    return {
        "rate_pct": (base.ad_valorem_pct or 0) + sum(t.ad_valorem_pct or 0 for t in extra),
        "basis": base.rate_type,
        "agreement": base.agreement,
        "specific_rate": base.specific_rate,
        "source": base.source,
        "source_url": base.source_url,
        "data_year": base.data_year,
        "verified_at": base.verified_at.isoformat(),
        "additional": [{"pct": t.ad_valorem_pct, "note": t.notes, "source_url": t.source_url} for t in extra],
        "hs_line": base.hs_code,
    }


def _eu_members(db: Session) -> set[str]:
    return set(settings.get(db, "regions").get("Europe", [])) - {"GBR", "CHE", "NOR", "ISL"}


def unit_value(db: Session, market: str, hs6: str, origin: str | None) -> dict:
    """Import $/kg into market (from origin, or all origins), latest year, with excluded-row count."""
    codes = iso_to_m49(db)
    reporters = codes.get(market, [])
    partners = codes.get(origin, []) if origin else [0]
    obs = db.scalars(
        select(TradeObservation).where(
            TradeObservation.hs_code == hs6,
            TradeObservation.flow == "M",
            TradeObservation.reporter_m49.in_(reporters or [-1]),
            TradeObservation.partner_m49.in_(partners or [-1]),
        )
    ).all()
    if not obs:
        return {"usd_per_kg": None, "year": None, "excluded": 0}
    year = max(o.year for o in obs)
    rows = [o for o in obs if o.year == year]
    good = [o for o in rows if o.net_weight_kg and o.net_weight_kg > 0]
    val, kg = sum(o.value_usd for o in good), sum(o.net_weight_kg for o in good)
    return {
        "usd_per_kg": val / kg if kg else None,
        "year": year,
        "excluded": len(rows) - len(good),
        "source_url": rows[0].source.url,
        "value_usd": val,
        "net_weight_kg": kg,
    }


def landed_cost(
    db: Session, market: str, hs6: str, fob_usd_per_kg: float | None = None, insurance_pct: float = 0.5
) -> dict:
    origins = settings.get_raw(db, "factory_countries") or ["EGY", "JOR", "SYR"]
    world = unit_value(db, market, hs6, None)
    rows = []
    for origin in origins:
        duty = _duty(db, market, hs6, origin)
        quotes = db.scalars(
            select(LogisticsQuote).where(
                LogisticsQuote.origin_iso3 == origin,
                LogisticsQuote.destination_iso3 == market,
                LogisticsQuote.cost_usd.is_not(None),
                LogisticsQuote.payload_kg.is_not(None),
            )
        ).all()
        today = date.today()
        valid = [q for q in quotes if not q.valid_until or q.valid_until.date() >= today]
        q = min(valid, key=lambda q: q.cost_usd / q.payload_kg) if valid else None
        fob = fob_usd_per_kg if fob_usd_per_kg else world["usd_per_kg"]
        freight = q.cost_usd / q.payload_kg if q else None
        insurance = fob * insurance_pct / 100 if fob else None
        duty_usd = (fob + (freight or 0) + (insurance or 0)) * duty["rate_pct"] / 100 if fob and duty else None
        parts = [fob, freight, insurance, duty_usd]
        rows.append(
            {
                "origin_iso3": origin,
                "fob_usd_per_kg": fob,
                "fob_basis": "user-entered" if fob_usd_per_kg else ("benchmark: average import $/kg" if fob else None),
                "freight_usd_per_kg": freight,
                "freight": {
                    "carrier": q.carrier,
                    "mode": q.mode,
                    "container": q.container,
                    "cost_usd": q.cost_usd,
                    "payload_kg": q.payload_kg,
                    "transit_days": q.transit_days,
                    "valid_until": q.valid_until.isoformat() if q.valid_until else None,
                    "confidence": "estimate",
                }
                if q
                else None,
                "insurance_usd_per_kg": insurance,
                "duty": duty,
                "duty_usd_per_kg": duty_usd,
                "landed_usd_per_kg": sum(parts) if all(p is not None for p in parts) else None,
                "missing": [
                    n for n, p in zip(("fob", "freight", "insurance", "duty"), parts, strict=True) if p is None
                ],
                "origin_unit_value": unit_value(db, market, hs6, origin),
            }
        )
    complete = [r for r in rows if r["landed_usd_per_kg"] is not None]
    best = min(complete, key=lambda r: r["landed_usd_per_kg"]) if complete else None
    return {
        "market": market,
        "hs6": hs6,
        "insurance_pct": insurance_pct,
        "benchmark": world,
        "origins": rows,
        "best_origin": best["origin_iso3"] if best else None,
        "formula": "landed $/kg = FOB + freight/kg + insurance (FOB × %) + duty × (FOB + freight + insurance)",
        "note": None if best else "Not enough inputs to compare origins; see 'missing' per origin.",
    }


# --- alerts ---------------------------------------------------------------------------------------


def generate_alerts(db: Session, today: date | None = None, spike_pct: float | None = None) -> int:
    """New importers of client HS codes in target markets, new supplier origins, volume spikes/drops,
    competitors gaining buyers. Idempotent via dedupe keys."""
    from app.models import TargetMarket

    today = today or date.today()
    spike = spike_pct if spike_pct is not None else float(settings.get_raw(db, "alert_spike_pct") or 50)
    client_hs6, _ = _client_hs(db)
    targets = set(db.scalars(select(TargetMarket.iso3))) or None
    alerts = []
    res = buyers(db, today=today)
    for b in res["buyers"]:
        m, c = b["metrics"], b["company"]
        relevant = set(b["hs_codes"]) & client_hs6
        if not relevant or (targets is not None and c["country_iso3"] not in targets):
            continue
        first = date.fromisoformat(m["first_shipment"])
        if first > today - timedelta(days=90):
            alerts.append(
                (
                    "new_importer",
                    c["id"],
                    ",".join(sorted(relevant)),
                    f"New importer: {c['name']} ({c['country_iso3']}) first shipped {first.isoformat()}",
                    {"first_shipment": first.isoformat()},
                    f"new_importer:{c['id']}",
                )
            )
        for o in m["new_origins_6m"]:
            alerts.append(
                (
                    "new_origin",
                    c["id"],
                    ",".join(sorted(relevant)),
                    f"{c['name']} added supplier origin {o}",
                    {"origin": o},
                    f"new_origin:{c['id']}:{o}",
                )
            )
        if m["trend"] is not None and abs(m["trend"]) * 100 >= spike and m["weight_prior6_kg"] > 0:
            kind = "volume_spike" if m["trend"] > 0 else "volume_drop"
            alerts.append(
                (
                    kind,
                    c["id"],
                    ",".join(sorted(relevant)),
                    f"{c['name']}: shipped weight {m['trend']:+.0%} (last 6 months vs previous 6)",
                    {"trend": m["trend"]},
                    f"{kind}:{c['id']}:{today.year}-{(today.month - 1) // 6}",
                )
            )
    for comp in db.scalars(select(Company).where(Company.relationship_type == "competitor")):
        t = competitor_tracker(db, comp)
        for b in t["not_our_buyers"]:
            if date.fromisoformat(b["first"]) > today - timedelta(days=90):
                alerts.append(
                    (
                        "competitor_new_buyer",
                        comp.id,
                        "",
                        f"{comp.name} started supplying {b['name']}",
                        {"buyer_id": b["id"]},
                        f"competitor_new_buyer:{comp.id}:{b['id']}",
                    )
                )
    if not alerts:
        return 0
    stmt = (
        insert(Alert)
        .values(
            [
                {"type": t, "company_id": cid, "hs_code": hs, "title": title, "payload": payload, "dedupe_key": key}
                for t, cid, hs, title, payload, key in alerts
            ]
        )
        .on_conflict_do_nothing(index_elements=["dedupe_key"])
    )
    return len(db.execute(stmt.returning(Alert.id)).all())
