"""AI web research for buyers, competitors and suppliers, with evidence checks before storage.

Guardrails applied to every candidate:
- kept only if its source URL is one the search tool actually returned;
- buying signals kept only if their URL was also retrieved;
- contact details limited to generic company addresses on the company's own domain (no personal data);
- the source page is re-fetched to check the company name appears;
- stored as "candidate" until an analyst verifies it.
"""

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import claude, usage
from app.analytics import prospect_score
from app.db import SessionLocal
from app.models import Company, CompanyEvidence, Country, HSCode, Product, RefreshRun, SourceRecord
from app.services import settings, trade

log = logging.getLogger("trade_intel.research")
KINDS = {"buyers": "buyer", "competitors": "competitor", "suppliers": "supplier"}
ALL_ROLES = {"importer", "distributor", "wholesaler", "retailer", "brand_owner", "manufacturer", "exporter"}
GENERIC_MAILBOXES = {
    "info",
    "sales",
    "contact",
    "contactus",
    "export",
    "exports",
    "import",
    "imports",
    "purchasing",
    "procurement",
    "office",
    "hello",
    "enquiries",
    "enquiry",
    "inquiries",
    "inquiry",
    "orders",
    "order",
    "admin",
    "service",
    "customerservice",
    "support",
    "mail",
    "trade",
    "business",
    "marketing",
    "buying",
    "commercial",
    "general",
}
_TAGS = re.compile(r"<[^>]+>")
_PHONE = re.compile(r"^\+?[\d\s().-]{6,25}$")


def _domain(url: str) -> str:
    host = urlparse(url if "//" in url else f"https://{url}").hostname or ""
    return host.lower().removeprefix("www.")


def clean_contact(raw: object, website: str) -> dict:
    """Keep only generic business contacts on the company's own domain; drop anything personal."""
    raw = raw if isinstance(raw, dict) else {}
    site = _domain(website)
    out: dict[str, str] = {}
    email = str(raw.get("email", "")).strip().lower()
    if "@" in email:
        local, _, dom = email.partition("@")
        if (
            site
            and (dom == site or dom.endswith("." + site) or site.endswith("." + dom))
            and local in GENERIC_MAILBOXES
        ):
            out["email"] = email
    phone = str(raw.get("phone", "")).strip()
    if _PHONE.match(phone):
        out["phone"] = phone
    address = str(raw.get("address", "")).strip()
    if 5 <= len(address) <= 300:
        out["address"] = address
    url = str(raw.get("contact_url", "")).strip()
    if url.startswith(("http://", "https://")) and (not site or _domain(url).endswith(site)):
        out["contact_url"] = url
    return out


def validate_candidates(
    candidates: list[dict], results: dict[str, dict], allowed_roles: list[str] | None = None
) -> tuple[list[dict], list[dict]]:
    """Keep only candidates whose source_url is a URL the search tool actually returned."""
    allowed = set(allowed_roles or ALL_ROLES)
    kept, dropped = [], []
    seen: set[str] = set()
    for c in candidates:
        name = str(c.get("name", "")).strip()
        url_key = claude.norm_url(str(c.get("source_url", "")))
        reason = None
        if not name or len(name) > 200:
            reason = "missing name"
        elif url_key not in results:
            reason = "source_url was not among retrieved search results"
        elif name.casefold() in seen:
            reason = "duplicate"
        if reason:
            dropped.append({"name": name, "reason": reason})
            continue
        seen.add(name.casefold())
        website = str(c.get("website", "")).strip()[:500]
        signals = []
        for sig in c.get("buying_signals") or []:
            if isinstance(sig, dict) and claude.norm_url(str(sig.get("url", ""))) in results and sig.get("text"):
                r = results[claude.norm_url(str(sig["url"]))]
                signals.append({"text": str(sig["text"])[:400], "url": r["url"], "title": r["title"] or ""})
        pl = str(c.get("private_label", "unknown")).lower()
        kept.append(
            {
                "name": name,
                "website": website,
                "roles": [r for r in c.get("roles", []) if r in allowed] or ["unknown"],
                "summary": str(c.get("summary", "")).strip()[:600],
                "product_range": str(c.get("product_range", "")).strip()[:800],
                "product_fit": str(c.get("product_fit", "")).strip()[:800],
                "private_label": pl if pl in ("yes", "possible") else "unknown",
                "private_label_evidence": str(c.get("private_label_evidence", "")).strip()[:600],
                "buying_signals": signals[:6],
                "markets_served": sorted(
                    {
                        m.upper()
                        for m in c.get("markets_served") or []
                        if isinstance(m, str) and re.fullmatch(r"[A-Za-z]{3}", m)
                    }
                )[:30],
                "contact": clean_contact(c.get("contact"), website),
                "source": results[url_key],
                "quote": str(c.get("evidence_quote", "")).strip()[:600],
            }
        )
    return kept, dropped


def _name_on_page(url: str, name: str) -> bool | None:
    if not url.startswith(("http://", "https://")):
        return None
    try:
        r = httpx.get(url, timeout=8, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 TradeIntel/0.1"})
        if r.status_code >= 400:
            return None
        text = _TAGS.sub(" ", r.text).casefold()
        core = re.sub(r"\b(ltd|limited|inc|llc|gmbh|s\.?a\.?|plc|co|corp|b\.?v\.?)\b\.?", "", name.casefold()).strip()
        return core in text if core else None
    except httpx.HTTPError:
        return None


def market_scores(db: Session, hs_codes: list[str]) -> dict[tuple[str, str], float]:
    """(hs, iso3) -> opportunity score, from the deterministic market ranking."""
    out = {}
    for hs in set(hs_codes):
        for r in trade.ranking(db, hs):
            out[(hs, r["iso3"])] = r["score"]
    return out


def rescore(company: Company, scores: dict[tuple[str, str], float]) -> None:
    if company.relationship_type != "buyer":
        company.prospect_score, company.score_components = None, {}
        return
    market = max(
        (scores[(hs, company.country_iso3)] for hs in company.hs_codes if (hs, company.country_iso3) in scores),
        default=None,
    )
    company.prospect_score, company.score_components = prospect_score(
        market_score=market,
        roles=company.roles,
        private_label=company.private_label,
        signals=len(company.buying_signals or []),
        name_on_source=company.name_on_source,
        review_status=company.review_status,
    )


def our_products_text(db: Session, hs: str) -> str:
    rows = db.scalars(select(Product).where(Product.hs_code == hs).order_by(Product.name)).all()
    return "; ".join(f"{p.name} {p.pack_size}".strip() for p in rows[:25]) or "not specified"


def profile_text(db: Session) -> str:
    p = settings.get(db, "company_profile")
    return (
        f"{p.get('name')} (brand {p.get('brand')}), {p.get('country_iso3')}, since {p.get('founded')}. "
        f"{p.get('description')} Labels in {', '.join(p.get('label_languages', []))}."
    )


def run_research(
    run_id: int, hs: str, country_m49: int, kind: str, product_id: int | None, user_id: int | None
) -> None:
    with SessionLocal() as db:
        run = db.get(RefreshRun, run_id)
        run.status, run.started_at = "running", datetime.now(UTC)
        db.commit()
        try:
            country = db.get(Country, country_m49)
            hs_row = db.get(HSCode, hs)
            product = db.get(Product, product_id) if product_id else None
            run.message = f"Searching the web for {kind} in {country.name}"
            db.commit()
            candidates, results, use, roles = claude.research_companies(
                kind=kind,
                country=country.name,
                product=product.name if product else hs_row.description,
                hs=hs,
                hs_desc=hs_row.description,
                profile=profile_text(db),
                our_products=our_products_text(db, hs),
            )
            cost = usage.record(db, user_id, f"research_{kind}", use)
            kept, dropped = validate_candidates(candidates, results, roles)

            run.message = f"Checking {len(kept)} source pages"
            db.commit()
            with ThreadPoolExecutor(max_workers=6) as pool:
                checks = list(pool.map(lambda k: _name_on_page(k["source"]["url"], k["name"]), kept))

            scores = market_scores(db, [hs])
            relationship = KINDS[kind]
            stored = 0
            for k, on_page in zip(kept, checks, strict=True):
                src = SourceRecord(
                    adapter="web_research",
                    url=k["source"]["url"],
                    title=k["source"]["title"] or "",
                    params={"query_kind": kind, "hs": hs, "country": country.iso3},
                    reporting_period=datetime.now(UTC).date().isoformat(),
                    licence="Public web page; content remains property of its publisher.",
                )
                db.add(src)
                db.flush()
                comp = db.scalar(select(Company).where(Company.name == k["name"], Company.country_iso3 == country.iso3))
                if not comp:
                    comp = Company(
                        name=k["name"], country_iso3=country.iso3, relationship_type=relationship, hs_codes=[hs]
                    )
                    db.add(comp)
                comp.website = comp.website or k["website"]
                comp.roles = sorted(set(comp.roles or []) | set(k["roles"]))
                comp.hs_codes = sorted(set(comp.hs_codes or []) | {hs})
                for field in ("summary", "product_range", "product_fit", "private_label_evidence"):
                    setattr(comp, field, getattr(comp, field) or k[field])
                if k["private_label"] != "unknown":
                    comp.private_label = k["private_label"]
                comp.buying_signals = (comp.buying_signals or []) + [
                    s for s in k["buying_signals"] if s["url"] not in {x["url"] for x in comp.buying_signals or []}
                ]
                comp.markets_served = sorted(set(comp.markets_served or []) | set(k["markets_served"]))
                comp.contact = {**k["contact"], **(comp.contact or {})}
                if on_page is not None:
                    comp.name_on_source = bool(comp.name_on_source) or on_page
                db.flush()
                check = {
                    True: "Company name found on source page.",
                    False: "Company name NOT found on source page at check time.",
                    None: "Source page could not be checked automatically.",
                }[on_page]
                quotes = k["source"]["quotes"]
                db.add(
                    CompanyEvidence(
                        company_id=comp.id,
                        source_record_id=src.id,
                        claim=f"Listed as {', '.join(k['roles'])}. {check}",
                        excerpt=(quotes[0] if quotes else k["quote"])[:1000],
                    )
                )
                rescore(comp, scores)
                stored += 1
            run.rows = stored
            run.status = "succeeded"
            run.message = f"Found {stored} companies ({use.get('web_searches', 0)} searches, ${cost:.3f})" + (
                f"; {len(dropped)} rejected without a valid source" if dropped else ""
            )
        except Exception as exc:
            log.exception("research failed")
            db.rollback()
            run = db.get(RefreshRun, run_id)
            run.status, run.message = "failed", "Research failed"
            run.error = getattr(exc, "detail", None) or str(exc)[:2000]
        run.finished_at = datetime.now(UTC)
        db.commit()


def run_news(hs: str, product_name: str, user_id: int | None) -> dict:
    """Synchronous: market developments for one HS code, keeping only items from retrieved sources."""
    from app.models import MarketNews

    with SessionLocal() as db:
        hs_row = db.get(HSCode, hs)
        ov = trade.overview(db, hs)
        markets = ", ".join(m["name"] for m in ov.get("top_importers", [])[:6]) or "major importing countries"
        items, results, use = claude.research_news(
            product=product_name or hs_row.description, hs=hs, hs_desc=hs_row.description, markets=markets
        )
        usage.record(db, user_id, "market_news", use)
        kept = []
        for it in items:
            r = results.get(claude.norm_url(str(it.get("url", ""))))
            if r and it.get("title"):
                kept.append(
                    {
                        "title": str(it["title"])[:300],
                        "summary": str(it.get("summary", ""))[:600],
                        "date": str(it.get("date", ""))[:20],
                        "topic": str(it.get("topic", "other"))[:20],
                        "url": r["url"],
                        "source_title": r["title"] or "",
                    }
                )
        row = MarketNews(hs_code=hs, items=kept[:8])
        db.add(row)
        db.commit()
        return {"items": row.items, "retrieved_at": row.retrieved_at.isoformat(), "rejected": len(items) - len(kept)}
