"""AI web research for buyers and competitors, with evidence checks before storage."""

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import httpx
from sqlalchemy import select

from app.ai import claude
from app.db import SessionLocal
from app.models import Company, CompanyEvidence, Country, HSCode, Product, RefreshRun, SourceRecord

log = logging.getLogger("trade_intel.research")
BUYER_ROLES = ["importer", "distributor", "wholesaler", "retailer", "brand_owner"]
COMPETITOR_ROLES = ["manufacturer", "exporter", "brand_owner"]
ALL_ROLES = set(BUYER_ROLES + COMPETITOR_ROLES)
_TAGS = re.compile(r"<[^>]+>")


def validate_candidates(candidates: list[dict], results: dict[str, dict]) -> tuple[list[dict], list[dict]]:
    """Keep only candidates whose source_url is a URL the search tool actually returned."""
    kept, dropped = [], []
    seen: set[str] = set()
    for c in candidates:
        name = str(c.get("name", "")).strip()
        url_key = claude._norm(str(c.get("source_url", "")))
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
        roles = [r for r in c.get("roles", []) if r in ALL_ROLES]
        kept.append(
            {
                "name": name,
                "website": str(c.get("website", "")).strip()[:500],
                "roles": roles or ["unknown"],
                "summary": str(c.get("summary", "")).strip()[:600],
                "source": results[url_key],
                "quote": str(c.get("evidence_quote", "")).strip()[:600],
            }
        )
    return kept, dropped


def _name_on_page(url: str, name: str) -> bool | None:
    try:
        r = httpx.get(url, timeout=8, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 TradeIntel/0.1"})
        if r.status_code >= 400:
            return None
        text = _TAGS.sub(" ", r.text).casefold()
        core = re.sub(r"\b(ltd|limited|inc|llc|gmbh|s\.?a\.?|plc|co|corp|b\.?v\.?)\b\.?", "", name.casefold()).strip()
        return core in text if core else None
    except httpx.HTTPError:
        return None


def run_research(run_id: int, hs: str, country_m49: int, kind: str, product_id: int | None) -> None:
    with SessionLocal() as db:
        run = db.get(RefreshRun, run_id)
        try:
            country = db.get(Country, country_m49)
            hs_row = db.get(HSCode, hs)
            product = db.get(Product, product_id) if product_id else None
            roles = BUYER_ROLES if kind == "buyers" else COMPETITOR_ROLES
            run.message = f"Searching the web for {kind} in {country.name}"
            db.commit()
            candidates, results, usage = claude.research_companies(
                country=country.name,
                product=product.name if product else hs_row.description,
                hs=hs,
                hs_desc=hs_row.description,
                roles=roles,
            )
            kept, dropped = validate_candidates(candidates, results)

            run.message = f"Checking {len(kept)} source pages"
            db.commit()
            with ThreadPoolExecutor(max_workers=6) as pool:
                checks = list(pool.map(lambda k: _name_on_page(k["source"]["url"], k["name"]), kept))

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
                        name=k["name"],
                        country_iso3=country.iso3,
                        website=k["website"],
                        roles=k["roles"],
                        summary=k["summary"],
                        hs_codes=[hs],
                    )
                    db.add(comp)
                    db.flush()
                else:
                    comp.roles = sorted(set(comp.roles) | set(k["roles"]))
                    comp.hs_codes = sorted(set(comp.hs_codes) | {hs})
                    comp.summary = comp.summary or k["summary"]
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
                stored += 1
            run.rows = stored
            run.status = "succeeded"
            run.message = (
                f"Found {stored} companies ({usage['web_searches']} searches, "
                f"{usage['input_tokens'] + usage['output_tokens']} tokens)"
                + (f"; {len(dropped)} rejected without valid source" if dropped else "")
            )
        except Exception as exc:
            log.exception("research failed")
            db.rollback()
            run = db.get(RefreshRun, run_id)
            run.status, run.message = "failed", "Research failed"
            run.error = getattr(exc, "detail", None) or str(exc)[:2000]
        run.finished_at = datetime.now(UTC)
        db.commit()
