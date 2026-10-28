"""Private-label opportunity engine: priority category x target country x retailer.

Every component is 0-100 and shown with its inputs; a component without data is left out and the
remaining weights are renormalised (the row says which ones were missing). A row without market data is not
scored at all. Nothing is estimated.
"""

import math
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics import cagr
from app.models import Company, Product, TargetMarket, TradeObservation
from app.services import settings
from app.services.explore import iso_to_m49

COMPONENTS = {
    "market_size": "Import value of the category's HS codes (latest common year, log-scaled)",
    "growth": "Import growth (CAGR over the stored years), -20% → 0 and +30% → 100",
    "retailer_presence": "A tracked retailer operates in the country (confirmed identity 100, unconfirmed 50)",
    "private_label_signal": "Retailer runs own-brand ranges per its sources (yes 100, possible 50, unknown 0)",
    "evidence": "Sourced facts on file for the retailer (25 per fact, up to 100)",
}
TOP_COUNTRIES_WITHOUT_LIST = 20
IDENTITY_POINTS = {"confirmed": 100.0, "needs_confirmation": 50.0, "unverified": 25.0}
PL_POINTS = {"yes": 100.0, "possible": 50.0, "unknown": 0.0}


def _category_imports(db: Session, hs_codes: list[str]) -> dict[int, dict[int, float]]:
    """reporter m49 -> year -> summed import value over the category's HS codes (World partner).

    A year counts for a reporter only if every HS code of the category is reported for it."""
    per: dict[tuple[int, int], dict[str, float]] = defaultdict(dict)
    for o in db.scalars(
        select(TradeObservation).where(
            TradeObservation.hs_code.in_(hs_codes), TradeObservation.flow == "M", TradeObservation.partner_m49 == 0
        )
    ):
        per[(o.reporter_m49, o.year)][o.hs_code] = o.value_usd
    out: dict[int, dict[int, float]] = defaultdict(dict)
    for (m49, year), vals in per.items():
        if len(vals) == len(hs_codes):
            out[m49][year] = sum(vals.values())
    return out


def compute(db: Session, weights: dict[str, float] | None = None) -> dict:
    w = {**settings.get(db, "private_label_weights"), **(weights or {})}
    categories = settings.get(db, "priority_categories")
    codes = iso_to_m49(db)
    m49_to_iso = {m: iso for iso, ms in codes.items() for m in ms}
    targets = {t.iso3: t.segment for t in db.scalars(select(TargetMarket))}
    retailers = [
        c
        for c in db.scalars(select(Company).where(Company.relationship_type == "retailer"))
        if c.review_status != "rejected"
    ]

    rows, gaps = [], []
    for cat in categories:
        products = db.scalars(select(Product).where(Product.priority_category == cat)).all()
        hs_codes = sorted({p.hs_code for p in products if p.hs_code})
        if not products:
            gaps.append(f"No products are tagged with the priority category '{cat}'.")
            continue
        if not hs_codes:
            gaps.append(f"'{cat}': none of its products has an HS6 code yet.")
            continue
        loaded = set(
            db.scalars(select(TradeObservation.hs_code).where(TradeObservation.hs_code.in_(hs_codes)).distinct())
        )
        if loaded and len(loaded) < len(hs_codes):
            gaps.append(f"'{cat}': trade data not loaded for HS {', '.join(sorted(set(hs_codes) - loaded))}.")
        hs_codes = sorted(loaded) or hs_codes
        series = _category_imports(db, hs_codes)
        by_iso: dict[str, dict[int, float]] = {}
        for m49, ys in series.items():
            iso = m49_to_iso.get(m49)
            if iso and (iso not in by_iso or sum(ys.values()) > sum(by_iso[iso].values())):
                by_iso[iso] = ys
        if not by_iso:
            gaps.append(f"'{cat}': no trade statistics loaded for HS {', '.join(hs_codes)}.")
        countries = (
            list(targets)
            if targets
            else sorted(by_iso, key=lambda i: -by_iso[i][max(by_iso[i])])[:TOP_COUNTRIES_WITHOUT_LIST]
        )
        logs = [
            math.log10(by_iso[i][max(by_iso[i])]) for i in countries if i in by_iso and by_iso[i][max(by_iso[i])] > 0
        ]
        lo, hi = (min(logs), max(logs)) if logs else (0.0, 0.0)
        for iso in countries:
            ys = by_iso.get(iso, {})
            latest = max(ys) if ys else None
            value = ys.get(latest) if latest else None
            growth = cagr(ys) if len(ys) >= 3 else None
            base = {
                "market_size": (100.0 if hi == lo else 100 * (math.log10(value) - lo) / (hi - lo))
                if value and value > 0
                else None,
                "growth": max(0.0, min(100.0, (growth + 0.20) / 0.50 * 100)) if growth is not None else None,
            }
            present = [r for r in retailers if iso == r.country_iso3 or iso in (r.markets_served or [])]
            for r in present or [None]:
                comp = dict(base)
                if r is None:
                    comp.update(retailer_presence=0.0, private_label_signal=None, evidence=None)
                else:
                    comp.update(
                        retailer_presence=IDENTITY_POINTS.get(r.identity_status, 25.0),
                        private_label_signal=PL_POINTS.get(r.private_label, 0.0),
                        evidence=min(100.0, 25.0 * len(r.evidence)),
                    )
                used = {k: v for k, v in comp.items() if v is not None and w.get(k, 0) > 0}
                total_w = sum(w[k] for k in used)
                # without market data a row cannot be ranked: retailer factors alone would inflate it
                scoreable = comp["market_size"] is not None or w.get("market_size", 0) == 0
                score = sum(comp[k] * w[k] for k in used) / total_w if total_w and scoreable else None
                rows.append(
                    {
                        "category": cat,
                        "hs_codes": hs_codes,
                        "products": len(products),
                        "iso3": iso,
                        "segment": targets.get(iso, "unclassified"),
                        "retailer": None
                        if r is None
                        else {"id": r.id, "name": r.name, "identity_status": r.identity_status},
                        "import_value_usd": value,
                        "latest_year": latest,
                        "cagr": growth,
                        "components": {k: (round(v, 1) if v is not None else None) for k, v in comp.items()},
                        "missing": [k for k, v in comp.items() if v is None],
                        "score": round(score, 1) if score is not None else None,
                    }
                )
    rows.sort(key=lambda x: (x["score"] is None, -(x["score"] or 0)))
    return {
        "weights": w,
        "components": COMPONENTS,
        "rows": rows,
        "gaps": gaps,
        "target_list_loaded": bool(targets),
        "note": None
        if targets
        else (
            f"The client's market list has not been imported; showing the top {TOP_COUNTRIES_WITHOUT_LIST} "
            "importing countries per category instead."
        ),
    }
