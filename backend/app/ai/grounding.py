"""Retrieval context packs and post-generation validation.

The model only sees facts computed here, each with an evidence ID. After generation,
every statement is checked: cited IDs must exist, and every number in the text must
match a value in the evidence it cites. Failing statements are labelled "unverified".
"""

import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import date

from sqlalchemy import any_, select
from sqlalchemy.orm import Session

from app.adapters.stubs import FREIGHT, SHIPMENTS
from app.analytics import cagr
from app.models import Company, LogisticsQuote, MarketNews, Product, TargetMarket
from app.services import settings, trade

LABELS = ("verified", "client_provided", "calculated", "estimate", "inference", "unavailable")
CALC_KINDS = ("score", "trade_stat")
CLIENT_KINDS = ("client", "catalogue")
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
    r"(?<![\w./])[$€£]?\s?(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(%|percent|billion|bn|million|mn|m\b|"
    r"thousand|k\b|b\b)?",
    re.IGNORECASE,
)
_OUT_OF = re.compile(r"\bout of 100\b", re.IGNORECASE)
_DATE = re.compile(r"\b\d{4}-\d{2}(?:-\d{2})?\b")
_HS_PREFIX = re.compile(r"\bHS(?:\s*code)?\s*$", re.IGNORECASE)
_MULT = {"billion": 1e9, "bn": 1e9, "b": 1e9, "million": 1e6, "mn": 1e6, "m": 1e6, "thousand": 1e3, "k": 1e3}


ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹٫٬", "01234567890123456789.,")


def extract_numbers(text: str) -> list[float]:
    text = text.translate(ARABIC_DIGITS)  # Arabic-Indic digits count as numbers too
    out = []
    text = _DATE.sub(" ", text)  # "2026-09-25" is a date, not three quantities
    text = _OUT_OF.sub(" ", text)  # "out of 100" is a scale, not a claim
    for m in _NUM.finditer(text):
        if _HS_PREFIX.search(text[max(0, m.start() - 12) : m.start()]):
            continue  # "HS 190531" is a product code, not a quantity
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
        candidates = [v]
        if abs(v) < 1:  # shares: 0.315 also matches "31.5", and 0.0000187 matches the displayed "0.0%"
            pct = round(v * 100, 1)
            candidates += [v * 100, pct, pct / 100]
        for c in candidates:
            if c == 0:
                if n == 0:
                    return True
            elif abs(n - c) <= REL_TOL * abs(c) + 1e-9:
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
        if label == "calculated" and not any(by_id[i].kind in CALC_KINDS for i in ids):
            label = "inference"  # a calculated value must cite the platform's computed evidence
        if label == "client_provided" and not any(by_id[i].kind in CLIENT_KINDS for i in ids):
            label = "inference"  # nothing from the client's own information was cited
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

    _add_client(db, add, hs)
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
            [r["score"]]
            + [c["value"] for c in r["components"].values() if c["status"] == "ok"]
            + [c["normalized"] for c in r["components"].values() if c["status"] == "ok"],
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

    _add_companies(db, add, hs)
    _add_news(db, add, hs)
    _add_logistics(db, add)
    return ev


def _src(sr) -> dict | None:
    return {"id": sr.id, "url": sr.url, "retrieved_at": sr.retrieved_at.isoformat()} if sr else None


def _add_client(db: Session, add, hs: str) -> None:
    """What the AI must know about the client: profile, own products, existing export markets."""
    p = settings.get(db, "company_profile")
    add(
        "client",
        f"Our company: {p.get('name')} (brand {p.get('brand')}), based in {p.get('country_iso3')}, "
        f"since {p.get('founded')}. {p.get('description')} "
        f"Labels printed in {', '.join(p.get('label_languages', []))}. "
        f"Certifications stated: {', '.join(p.get('certifications', [])) or 'none recorded'}.",
        [],
    )
    products = db.scalars(select(Product).where(Product.hs_code == hs).order_by(Product.name)).all()
    if products:
        add(
            "catalogue",
            f"Our products under HS {hs}: "
            + "; ".join(f"{x.name} ({x.pack_size or 'size n/a'}, {x.packaging or 'pack n/a'})" for x in products[:30])
            + ".",
            [x.net_quantity for x in products[:30]],
        )
        statuses = sorted({x.hs_status for x in products})
        client_codes = sorted({x.client_hs_code for x in products if x.client_hs_code})
        add(
            "catalogue",
            f"HS classification status of these products: {', '.join(statuses)}. "
            + (
                f"Client-provided national codes: {', '.join(client_codes)}."
                if client_codes
                else "The client has not provided an HS code for them."
            ),
            [],
        )
        sources = sorted({x.hs_source for x in products})
        add(
            "catalogue",
            f"Source of the analysis HS6 {hs}: {', '.join(s.replace('_', ' ') for s in sources)} "
            "(none of these is a customs ruling).",
            [],
        )
        for x in products[:10]:
            m = x.maersk_commodity
            if m:
                add(
                    "maersk_reference",
                    f"Maersk commodity reference chosen by a reviewer for {x.name}: {m['commodity_code']} "
                    f'"{m["commodity_name"]}", HS codes listed by Maersk: '
                    f"{', '.join(h['code'] for h in m.get('hs_codes', [])) or 'none'}. Carrier reference data, "
                    "not a customs classification.",
                    [],
                    {
                        "url": "https://developer.maersk.com/api-catalogue/Commodities",
                        "retrieved_at": m.get("retrieved_at"),
                    },
                )
        priority = sorted({x.priority_category for x in products if x.priority_category})
        if priority:
            add("client", f"Client priority private-label categories covered: {', '.join(priority)}.", [])
        entities = sorted({f"{x.export_entity.name} ({x.export_entity.status})" for x in products if x.export_entity})
        if entities:
            add("client", f"Export/manufacturing entities named for these products: {', '.join(entities)}.", [])
    targets = db.scalars(select(TargetMarket).order_by(TargetMarket.iso3)).all()
    existing = [t.iso3 for t in targets if t.segment == "existing"]
    expansion = [t.iso3 for t in targets if t.segment == "expansion"]
    if targets:
        add(
            "client",
            f"Client market list: existing markets (ISO3) {', '.join(existing) or 'none'}; "
            f"expansion markets {', '.join(expansion) or 'none'}.",
            [],
        )
    else:
        add("gap", "The client's list of existing and expansion markets has not been imported yet.", [])


def _add_companies(db: Session, add, hs: str) -> None:
    labels = {
        "buyer": "Potential buyer",
        "retailer": "Retailer account",
        "competitor": "Competitor",
        "supplier": "Supplier (market supply side)",
    }
    for rel, label in labels.items():
        scope = Company.relationship_type == rel if rel == "retailer" else hs == any_(Company.hs_codes)
        companies = db.scalars(
            select(Company)
            .where(scope, Company.review_status != "rejected", Company.relationship_type == rel)
            .order_by(Company.prospect_score.desc().nulls_last(), Company.review_status.desc(), Company.name)
            .limit(12)
        ).all()
        for c in companies:
            src = c.evidence[0].source if c.evidence else None
            score = f" Prospect fit score {c.prospect_score:.1f}/100." if c.prospect_score is not None else ""
            add(
                "company",
                f"{label}: {c.name} ({c.country_iso3}), business type: {', '.join(c.roles) or 'unknown'}, "
                f"review status: {c.review_status}, identity: {c.identity_status}, outreach stage: "
                f"{c.pipeline_stage}. {c.summary} Private label: {c.private_label}.{score}",
                [c.prospect_score],
                _src(src),
            )
        if not companies:
            add("gap", f"No {label.lower()} companies have been researched for this product yet.", [])


def _add_news(db: Session, add, hs: str) -> None:
    news = db.scalar(
        select(MarketNews).where(MarketNews.hs_code == hs).order_by(MarketNews.retrieved_at.desc()).limit(1)
    )
    if not news:
        add("gap", "Recent market news has not been researched for this product.", [])
        return
    for it in news.items:
        add(
            "news",
            f"Market development ({it.get('date') or 'date not stated'}): {it['title']}. {it.get('summary', '')}",
            extract_numbers(it.get("summary", "")),
            {"url": it["url"], "retrieved_at": news.retrieved_at.isoformat()},
        )


def _route_text(db: Session, q: LogisticsQuote) -> str:
    from app.models import RouteLocation

    parts = []
    for label, loc_id in (("origin", q.origin_location_id), ("destination", q.destination_location_id)):
        loc = db.get(RouteLocation, loc_id) if loc_id else None
        if loc:
            parts.append(
                f"{label} {loc.location_name} (Maersk Geo ID {loc.carrier_geo_id}"
                f"{', UN/LOCODE ' + loc.un_location_code if loc.un_location_code else ''})"
            )
    return (" Route locations from the Maersk Locations API: " + "; ".join(parts) + ".") if parts else ""


def _add_logistics(db: Session, add, destination_iso3: str | None = None) -> None:
    stmt = select(LogisticsQuote).order_by(LogisticsQuote.created_at.desc()).limit(10)
    if destination_iso3:
        stmt = stmt.where(LogisticsQuote.destination_iso3 == destination_iso3)
    for q in db.scalars(stmt):
        route = _route_text(db, q)
        add(
            "logistics",
            f"Client-provided freight quote {q.origin} → {q.destination} ({q.destination_iso3}) by {q.mode}"
            f"{' ' + q.container if q.container else ''}{', carrier ' + q.carrier if q.carrier else ''}"
            f"{', ' + q.incoterm if q.incoterm else ''}: "
            f"{fmt_usd(q.cost_usd) if q.cost_usd is not None else 'cost not given'}, "
            f"{q.transit_days if q.transit_days is not None else 'transit time not given'} days. "
            f"Source: {q.source_note}.{' Assumptions: ' + q.assumptions if q.assumptions else ''}{route} "
            "Freight figures are estimates, not live prices.",
            [q.cost_usd, q.transit_days],
        )
    add("gap", f"{FREIGHT['name']}: not connected. {FREIGHT['detail']}", [])
    add(
        "gap",
        f"{SHIPMENTS['name']}: not connected. {SHIPMENTS['detail']} "
        "Company-level purchase volumes, budgets and order quantities are therefore unavailable.",
        [],
    )


def build_company_context(db: Session, company: Company) -> list[Evidence]:
    """Evidence for a single-company brief: its record and sources, its market, our products, gaps."""
    ev: list[Evidence] = []

    def add(kind: str, text: str, values: list[float], source: dict | None = None) -> None:
        ev.append(Evidence(f"E{len(ev) + 1}", kind, text, [float(v) for v in values if v is not None], source))

    hs = company.hs_codes[0] if company.hs_codes else None
    if hs:
        _add_client(db, add, hs)
    c = company
    add(
        "company",
        f"{c.name} ({c.country_iso3}) is recorded as a {c.relationship_type}; business type: "
        f"{', '.join(c.roles) or 'unknown'}; review status: {c.review_status}; identity: {c.identity_status}; "
        f"outreach stage: {c.pipeline_stage}. {c.summary}",
        [],
        _src(c.evidence[0].source) if c.evidence else None,
    )
    if c.identity_status != "confirmed":
        add("gap", f"{c.name}'s legal identity is not confirmed; do not attribute other companies' facts to it.", [])
    if c.vendor_url:
        add("company", f"Official supplier/vendor onboarding page: {c.vendor_url}", [], {"url": c.vendor_url})
    for e in c.evidence:
        if e.source.adapter == "official_site":
            add("company", f"Official source: {e.claim}", [], _src(e.source))
    if c.product_range:
        add("company", f"{c.name} product range (from public sources): {c.product_range}", [])
    if c.product_fit:
        add("company", f"Researcher's note on fit with our products: {c.product_fit}", [])
    add("company", f"Private-label evidence: {c.private_label}. {c.private_label_evidence}".strip(), [])
    if c.markets_served:
        add("company", f"Markets served according to public sources (ISO3): {', '.join(c.markets_served)}.", [])
    for e in c.evidence[:5]:
        add(
            "company",
            f'Source excerpt about {c.name}: "{e.excerpt}" ({e.claim})',
            extract_numbers(e.excerpt),
            _src(e.source),
        )
    for sig in (c.buying_signals or [])[:6]:
        add("company", f"Buying signal: {sig['text']}", extract_numbers(sig["text"]), {"url": sig["url"]})
    if c.contact:
        add("company", "Public business contact details are on file: " + ", ".join(sorted(c.contact)) + ".", [])
    if c.prospect_score is not None:
        parts = [f"{v['label']} {v['normalized']}" for v in c.score_components.values() if v["status"] == "ok"]
        normalized = [v["normalized"] for v in c.score_components.values() if v["status"] == "ok"]
        add(
            "score",
            f"Prospect fit score {c.prospect_score:.1f}/100 ({'; '.join(parts)}).",
            [c.prospect_score, *normalized],
        )
    if hs:
        rank = next((r for r in trade.ranking(db, hs) if r["iso3"] == c.country_iso3), None)
        if rank:
            add(
                "score",
                f"{rank['name']} market for HS {hs}: opportunity rank #{rank['rank']}, score {rank['score']:.1f}/100, "
                f"imports {fmt_usd(rank['latest_value_usd'])} in {rank['latest_year']}.",
                [rank["score"], rank["latest_value_usd"]],
                rank["source"],
            )
            d = trade.country_detail(db, hs, rank["m49"])
            for s in (d or {}).get("suppliers", [])[:5]:
                add(
                    "trade_stat",
                    f"In {d['latest_year']}, {d['name']} sourced {fmt_usd(s['value_usd'])} ({_pct(s['share'])}) "
                    f"of HS {hs} from {s['name']}.",
                    [s["value_usd"], s["share"]],
                    s["source"],
                )
        _add_news(db, add, hs)
    _add_logistics(db, add, c.country_iso3)
    _add_shipments(db, add, c)
    return ev


def _add_shipments(db: Session, add, c: Company) -> None:
    """Facts from licensed shipment files: buyer metrics, suppliers and matching catalogue products."""
    from app.models import ImportBatch, Shipment
    from app.services.intel import buyer_metrics

    rows = db.scalars(select(Shipment).where(Shipment.consignee_company_id == c.id)).all()
    shipped = db.scalars(select(Shipment).where(Shipment.shipper_company_id == c.id)).all()
    if not rows and not shipped:
        add(
            "gap",
            f"No shipment records for {c.name} in the uploaded provider files: order frequency, "
            "volumes and spend are unknown.",
            [],
        )
        return
    batches = {b.id: b for b in db.scalars(select(ImportBatch))}
    first = batches.get((rows or shipped)[0].import_batch_id)
    src = {"url": "", "title": f"{first.provider} shipment file {first.filename} (licensed)"} if first else None
    if rows:
        m = buyer_metrics(rows, date.today())
        add(
            "shipment",
            f"Shipment records (licensed provider data; weights as declared) show {c.name} received "
            f"{m['shipments_12m']} shipments weighing {m['weight_kg_12m']:,.0f} kg in the last 12 months, "
            f"in {m['active_months_12m']} different months; last shipment {m['last_shipment']}.",
            [m["shipments_12m"], m["weight_kg_12m"], m["active_months_12m"]],
            src,
        )
        if m["origins_12m"]:
            add(
                "shipment",
                "Origins of its shipments in the last 12 months by weight (kg): "
                + ", ".join(f"{k} {v:,.0f}" for k, v in m["origins_12m"].items())
                + ".",
                list(m["origins_12m"].values()),
                src,
            )
        if m["new_origins_6m"]:
            add(
                "shipment",
                f"It added supplier origins in the last 6 months: {', '.join(m['new_origins_6m'])}.",
                [],
                src,
            )
        sup = Counter(s.shipper_name for s in rows if s.shipper_name).most_common(5)
        if sup:
            add(
                "shipment",
                "Its main shippers in the records: " + "; ".join(f"{n} ({k} shipments)" for n, k in sup) + ".",
                [k for _n, k in sup],
                src,
            )
        hs6 = {s.hs6 for s in rows if s.hs6}
        fit = db.scalars(select(Product).where(Product.hs_code.in_(hs6 or {"-"}))).all()
        if fit:
            add(
                "catalogue",
                "Our catalogue products under the HS codes it imports: "
                + "; ".join(f"{p.name} ({p.pack_size or 'size n/a'})" for p in fit[:12])
                + ".",
                [],
            )
    if shipped:
        buyers = Counter(s.consignee_name for s in shipped if s.consignee_name).most_common(5)
        add(
            "shipment",
            f"As a shipper, {c.name} appears in {len(shipped)} shipment records; main consignees: "
            + "; ".join(f"{n} ({k})" for n, k in buyers)
            + ".",
            [len(shipped), *[k for _n, k in buyers]],
            src,
        )
