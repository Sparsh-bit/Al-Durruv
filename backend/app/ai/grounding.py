"""Retrieval context packs and post-generation validation.

The model only sees facts computed here, each with an evidence ID. After generation,
every statement is checked: cited IDs must exist, and every number in the text must
match a value in the evidence it cites. Failing statements are labelled "unverified".
"""

import re
from dataclasses import asdict, dataclass, field

from sqlalchemy import any_, select
from sqlalchemy.orm import Session

from app.adapters.stubs import FREIGHT, SHIPMENTS
from app.analytics import cagr
from app.models import Company, LogisticsQuote
from app.services import trade

LABELS = ("verified", "estimate", "inference", "unavailable")
REL_TOL = 0.02  # rounding tolerance, e.g. $2.40B vs 2,404,909,000


@dataclass
class Evidence:
    id: str
    kind: str
    text: str
    values: list[float] = field(default_factory=list)
    source: dict | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def fmt_usd(v: float) -> str:
    if abs(v) >= 1e9:
        return f"${v / 1e9:.2f} billion"
    if abs(v) >= 1e6:
        return f"${v / 1e6:.1f} million"
    return f"${v:,.0f}"


def _pct(v: float) -> str:
    return f"{v * 100:.1f}%"


_NUM = re.compile(
    r"(?<![\w.])[$€£]?\s?(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(%|percent|billion|bn|million|mn|m\b|"
    r"thousand|k\b|b\b)?",
    re.IGNORECASE,
)
_MULT = {"billion": 1e9, "bn": 1e9, "b": 1e9, "million": 1e6, "mn": 1e6, "m": 1e6, "thousand": 1e3, "k": 1e3}


def extract_numbers(text: str) -> list[float]:
    out = []
    for m in _NUM.finditer(text):
        raw, unit = m.group(1), (m.group(2) or "").lower()
        n = float(raw.replace(",", ""))
        if unit in ("%", "percent"):
            out.append(n / 100)
        elif unit in _MULT:
            out.append(n * _MULT[unit])
        elif "," not in raw and "." not in raw and (1900 <= n <= 2100 or n <= 20):
            continue  # years and small counts/ordinals
        else:
            out.append(n)
    return out


def _matches(n: float, values: list[float]) -> bool:
    for v in values:
        if v == 0:
            continue
        for candidate in (v, v * 100) if abs(v) < 1 else (v,):  # 0.315 also matches "31.5"
            if abs(n - candidate) <= REL_TOL * abs(candidate) + 1e-9:
                return True
    return False


def validate_statements(statements: list[dict], evidence: list[Evidence]) -> list[dict]:
    by_id = {e.id: e for e in evidence}
    out = []
    for s in statements:
        issues: list[str] = []
        ids = []
        for i in s.get("evidence_ids", []):
            if i in by_id:
                ids.append(i)
            else:
                issues.append(f"unknown_evidence:{i}")
        label = s.get("label") if s.get("label") in LABELS else "inference"
        if label == "verified" and not ids:
            label = "inference"
        cited_values = [v for i in ids for v in by_id[i].values]
        bad = [n for n in extract_numbers(s.get("text", "")) if not _matches(n, cited_values)]
        if bad:
            issues.append("unsupported_number:" + ",".join(f"{n:g}" for n in bad))
            label = "unverified"
        out.append({"text": s.get("text", ""), "label": label, "evidence_ids": ids, "issues": issues})
    return out


def build_context(db: Session, hs: str, focus_m49: int | None = None) -> list[Evidence]:
    """Deterministic facts for one product (HS6), optionally focused on one market."""
    ev: list[Evidence] = []

    def add(kind: str, text: str, values: list[float], source: dict | None = None) -> None:
        ev.append(Evidence(f"E{len(ev) + 1}", kind, text, [float(v) for v in values if v is not None], source))

    ov = trade.overview(db, hs)
    if not ov.get("has_data"):
        add("gap", f"No trade statistics have been loaded for HS {hs} yet.", [])
        return ev

    add(
        "trade_stat",
        f"HS {hs} ({ov['hs_description']}): total imports reported by {ov['reporters']} countries "
        f"in {ov['reference_year']} were {fmt_usd(ov['world_imports_usd'])}.",
        [ov["world_imports_usd"], ov["reporters"]],
        ov["top_importers"][0]["source"],
    )
    for r in ov["top_importers"][:10]:
        uv = f", unit value ${r['unit_value']:.2f}/kg" if r["unit_value"] else ""
        add(
            "trade_stat",
            f"{r['name']} imported {fmt_usd(r['value_usd'])} in {r['year']} "
            f"({_pct(r['share'])} of reported imports){uv}.",
            [r["value_usd"], r["share"], r["unit_value"]],
            r["source"],
        )
    for t in ov["top_importer_trends"]:
        series = {p["year"]: p["value_usd"] for p in t["series"]}
        g = cagr(series)
        if g is not None:
            ys = sorted(series)
            add(
                "trade_stat",
                f"{t['name']} import value CAGR {ys[0]}–{ys[-1]}: {_pct(g)} "
                f"(from {fmt_usd(series[ys[0]])} to {fmt_usd(series[ys[-1]])}).",
                [g, series[ys[0]], series[ys[-1]]],
            )
    if ov["top_exporters"]:
        for r in ov["top_exporters"][:8]:
            add(
                "trade_stat",
                f"Competitor supplier country: {r['name']} exported {fmt_usd(r['value_usd'])} "
                f"in {r['year']} ({_pct(r['share'])} of reported exports).",
                [r["value_usd"], r["share"]],
                r["source"],
            )

    for r in trade.ranking(db, hs)[:10]:
        parts = [f"{c['label']}: {c['normalized']:.2f}" for c in r["components"].values() if c["status"] == "ok"]
        missing = [c["label"] for c in r["components"].values() if c["status"] != "ok"]
        add(
            "score",
            f"Opportunity rank #{r['rank']}: {r['name']} scored {r['score']:.1f}/100 "
            f"({'; '.join(parts)})" + (f"; unavailable: {', '.join(missing)}" if missing else "") + ".",
            [r["score"]] + [c["value"] for c in r["components"].values() if c["status"] == "ok"],
            r["source"],
        )

    focus_ids = [focus_m49] if focus_m49 else [r["m49"] for r in ov["top_importers"][:3]]
    for m49 in focus_ids:
        d = trade.country_detail(db, hs, m49)
        if not d:
            continue
        if d["suppliers"]:
            for s in d["suppliers"][:6]:
                add(
                    "trade_stat",
                    f"In {d['latest_year']}, {d['name']} sourced {fmt_usd(s['value_usd'])} "
                    f"({_pct(s['share'])}) from {s['name']}.",
                    [s["value_usd"], s["share"]],
                    s["source"],
                )
        else:
            add("gap", f"Supplier-country breakdown for {d['name']} is not loaded.", [])
        if d["home_share"] is not None:
            add(
                "trade_stat",
                f"The exporter's home country ({d['home_country']}) holds {_pct(d['home_share'])} "
                f"of {d['name']} imports.",
                [d["home_share"]],
            )

    companies = db.scalars(
        select(Company)
        .where(hs == any_(Company.hs_codes), Company.review_status != "rejected")
        .order_by(Company.review_status.desc(), Company.name)
        .limit(25)
    ).all()
    for c in companies:
        src = c.evidence[0].source if c.evidence else None
        add(
            "company",
            f"Company: {c.name} ({c.country_iso3}), roles: {', '.join(c.roles) or 'unknown'}, "
            f"review status: {c.review_status}. {c.summary}",
            [],
            {"id": src.id, "url": src.url, "retrieved_at": src.retrieved_at.isoformat()} if src else None,
        )
    if not companies:
        add("gap", "No companies have been researched for this product yet.", [])

    quotes = db.scalars(select(LogisticsQuote).limit(10)).all()
    for q in quotes:
        add(
            "logistics",
            f"Client-provided freight quote {q.origin} → {q.destination} by {q.mode}"
            f"{' ' + q.container if q.container else ''}: "
            f"{fmt_usd(q.cost_usd) if q.cost_usd is not None else 'cost not given'}, "
            f"{q.transit_days if q.transit_days is not None else 'transit time not given'} days. "
            f"Source: {q.source_note}.",
            [q.cost_usd, q.transit_days],
        )
    add("gap", f"{FREIGHT['name']}: not connected. {FREIGHT['detail']}", [])
    add(
        "gap",
        f"{SHIPMENTS['name']}: not connected. {SHIPMENTS['detail']} "
        "Company-level purchase volumes, budgets and order quantities are therefore unavailable.",
        [],
    )
    return ev
