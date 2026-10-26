"""Deterministic market indicators and the explainable opportunity score.

All numbers shown to users or passed to the AI are computed here, never by the model.
"""

import math
from dataclasses import dataclass, field
from statistics import median

DEFAULT_WEIGHTS: dict[str, float] = {
    "market_size": 35,
    "growth": 25,
    "openness": 20,
    "price_level": 10,
    "data_quality": 10,
}

COMPONENT_LABELS = {
    "market_size": "Market size (import value, log scale)",
    "growth": "Growth (CAGR of import value)",
    "openness": "Openness (1 − supplier concentration HHI)",
    "price_level": "Price level (USD/kg vs median market)",
    "data_quality": "Data completeness (years reported, of 5)",
}


def cagr(series: dict[int, float]) -> float | None:
    years = sorted(y for y, v in series.items() if v is not None)
    if len(years) < 2:
        return None
    first, last = series[years[0]], series[years[-1]]
    if first <= 0 or last <= 0:
        return None
    return (last / first) ** (1 / (years[-1] - years[0])) - 1


def hhi(values: list[float]) -> float | None:
    total = sum(values)
    if not values or total <= 0:
        return None
    return sum((v / total) ** 2 for v in values)


def unit_value(value_usd: float, weight_kg: float | None) -> float | None:
    if not weight_kg or weight_kg <= 0:
        return None
    return value_usd / weight_kg


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


@dataclass
class MarketInput:
    m49: int
    iso3: str
    name: str
    series: dict[int, float]  # year -> import value USD (partner World)
    latest_kg: float | None = None
    partner_values: dict[int, float] | None = None  # supplier m49 -> value, latest year


@dataclass
class ScoredMarket:
    m49: int
    iso3: str
    name: str
    score: float
    latest_year: int
    latest_value: float
    components: dict[str, dict] = field(default_factory=dict)


def score_markets(markets: list[MarketInput], weights: dict[str, float] | None = None) -> list[ScoredMarket]:
    weights = {**DEFAULT_WEIGHTS, **(weights or {})}
    markets = [m for m in markets if m.series and max(m.series.values()) > 0]
    if not markets:
        return []

    latest = {m.m49: max(m.series) for m in markets}
    size_logs = {m.m49: math.log10(m.series[latest[m.m49]]) for m in markets}
    lo, hi = min(size_logs.values()), max(size_logs.values())
    uvs = {m.m49: unit_value(m.series[latest[m.m49]], m.latest_kg) for m in markets}
    uv_median = median([v for v in uvs.values() if v]) if any(uvs.values()) else None

    out: list[ScoredMarket] = []
    for m in markets:
        year = latest[m.m49]
        period = str(year)
        comps: dict[str, dict] = {}

        def add(key: str, value: float | None, normalized: float | None, period_: str, unit: str, comps: dict = comps):
            ok = value is not None and normalized is not None
            comps[key] = {
                "label": COMPONENT_LABELS[key],
                "value": value,
                "unit": unit,
                "normalized": round(normalized, 4) if ok else None,
                "weight": weights[key],
                "period": period_,
                "status": "ok" if ok else "unavailable",
            }

        add("market_size", m.series[year], (size_logs[m.m49] - lo) / (hi - lo) if hi > lo else 1.0, period, "USD")
        g = cagr(m.series)
        years = sorted(m.series)
        # -10% CAGR -> 0, +20% CAGR -> 1
        add("growth", g, _clamp01((g + 0.10) / 0.30) if g is not None else None, f"{years[0]}–{years[-1]}", "ratio")
        h = hhi(list(m.partner_values.values())) if m.partner_values else None
        add("openness", 1 - h if h is not None else None, 1 - h if h is not None else None, period, "ratio")
        uv = uvs[m.m49]
        ratio = uv / uv_median if uv and uv_median else None
        # 0.5x median -> 0, 2x median -> 1
        add("price_level", uv, _clamp01((ratio - 0.5) / 1.5) if ratio else None, period, "USD/kg")
        dq = min(len(m.series), 5) / 5
        add("data_quality", len(m.series), dq, f"{years[0]}–{years[-1]}", "years")

        used = [c for c in comps.values() if c["status"] == "ok" and c["weight"] > 0]
        total_w = sum(c["weight"] for c in used)
        score = 100 * sum(c["weight"] * c["normalized"] for c in used) / total_w if total_w else 0.0
        out.append(ScoredMarket(m.m49, m.iso3, m.name, round(score, 2), year, m.series[year], comps))

    return sorted(out, key=lambda r: (-r.score, -r.latest_value))


PROSPECT_WEIGHTS = {"market": 30, "role_fit": 20, "private_label": 20, "evidence": 15, "verification": 15}
ROLE_FIT = {
    "importer": 1.0,
    "distributor": 1.0,
    "wholesaler": 1.0,
    "brand_owner": 0.8,
    "retailer": 0.8,
    "exporter": 0.3,
    "manufacturer": 0.3,
}
PRIVATE_LABEL = {"yes": 1.0, "possible": 0.5}


def prospect_score(
    *,
    market_score: float | None,
    roles: list[str],
    private_label: str,
    signals: int,
    name_on_source: bool | None,
    review_status: str,
) -> tuple[float, dict]:
    """Transparent 0-100 fit score for a potential buyer; every component is returned with its weight."""
    if review_status == "verified":
        verification = 1.0
    elif review_status == "rejected":
        verification = 0.0
    else:
        verification = {True: 0.75, None: 0.4, False: 0.1}[name_on_source]
    raw = {
        "market": (
            market_score / 100 if market_score is not None else None,
            "Opportunity score of the company's market",
        ),
        "role_fit": (
            max((ROLE_FIT.get(r, 0.2) for r in roles), default=0.2),
            "Business type fit (importer/distributor best)",
        ),
        "private_label": (PRIVATE_LABEL.get(private_label, 0.0), "Private-label / own-brand evidence"),
        "evidence": (min(signals, 3) / 3, "Sourced buying signals (up to 3)"),
        "verification": (verification, "Verification (analyst review or name found on source)"),
    }
    comps = {
        k: {
            "label": label,
            "normalized": None if v is None else round(v, 3),
            "weight": PROSPECT_WEIGHTS[k],
            "status": "unavailable" if v is None else "ok",
        }
        for k, (v, label) in raw.items()
    }
    used = [c for c in comps.values() if c["status"] == "ok"]
    total = sum(c["weight"] for c in used)
    return round(100 * sum(c["weight"] * c["normalized"] for c in used) / total, 1), comps
