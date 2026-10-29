"""Load client-provided setup data (data/client_setup.json, data/client_hs_list.csv) into the database.

Runs from the seed. Each file version is applied once (tracked by hash), and values already edited in the
app are never overwritten: settings are only set when absent, records only created when missing, and a
product's HS fields only filled while it has no client code and is not confirmed.
"""

import csv
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AppSetting, Clarification, Company, CompanyEvidence, Entity, HSCode, Product, SourceRecord
from app.services import settings

DATA = Path(__file__).resolve().parent.parent.parent / "data"
SETUP = DATA / "client_setup.json"
HS_LIST = DATA / "client_hs_list.csv"
HS_LIST_SOURCE = "Client file 'Hs Code Prouducts list.docx'"
VERSION_KEY = "client_data_version"


def _digest(*paths: Path) -> str:
    h = hashlib.sha256()
    for p in paths:
        h.update(p.read_bytes())
    return h.hexdigest()[:16]


def apply(db: Session, setup_path: Path = SETUP, hs_path: Path = HS_LIST, force: bool = False) -> dict:
    version = _digest(setup_path, hs_path)
    if not force and settings.get_raw(db, VERSION_KEY) == version:
        return {"skipped": True}
    setup = json.loads(setup_path.read_text())
    out = {
        "settings": _apply_settings(db, setup),
        "entities": _apply_entities(db, setup.get("entities", [])),
        "accounts": _apply_accounts(db, setup.get("accounts", [])),
        "clarifications": sum(
            _clarify(db, c["topic"], c["question"], c.get("context", "")) for c in setup.get("clarifications", [])
        ),
    }
    out["hs_list"] = apply_hs_list(db, hs_path, setup.get("company_profile", {}).get("brand", ""))
    out["priority"] = _apply_priority_skus(db, setup.get("priority_skus", {}))
    out["patches"] = apply_patches(db, setup.get("patches", []))
    settings.put(db, VERSION_KEY, version)
    db.commit()
    return out


def _apply_settings(db: Session, setup: dict) -> int:
    n = 0
    for key in ("company_profile", "priority_categories", "regions", "private_label_weights"):
        if key in setup and db.get(AppSetting, key) is None:
            value = setup[key]
            if key == "company_profile":
                value = {k: v for k, v in value.items() if k in settings.DEFAULTS[key] or k == "source"}
            settings.put(db, key, value)
            n += 1
    return n


def _apply_entities(db: Session, entities: list[dict]) -> int:
    n = 0
    for e in entities:
        if not db.scalar(select(Entity).where(Entity.name == e["name"])):
            db.add(
                Entity(
                    name=e["name"],
                    country_iso3=e.get("country_iso3", ""),
                    role=e.get("role", "manufacturer"),
                    status="pending_verification",
                    notes=e.get("notes", ""),
                    source_note="Client-provided",
                )
            )
            n += 1
    db.flush()
    return n


def _apply_accounts(db: Session, accounts: list[dict]) -> int:
    n = 0
    now = datetime.now(UTC)
    for a in accounts:
        stmt = select(Company).where(Company.name == a["name"], Company.country_iso3 == a.get("country_iso3", ""))
        if db.scalar(stmt):
            continue
        c = Company(
            name=a["name"],
            country_iso3=a.get("country_iso3", ""),
            website=a.get("website", ""),
            relationship_type=a["relationship_type"],
            roles=["retailer"] if a["relationship_type"] == "retailer" else [],
            summary=a.get("summary", ""),
            identity_status=a.get("identity_status", "unverified"),
            vendor_url=a.get("vendor_url", ""),
            markets_served=a.get("markets_served", []),
            private_label=a.get("private_label", "unknown"),
            private_label_evidence=a.get("private_label_evidence", ""),
            review_status="verified" if a.get("identity_status") == "confirmed" else "candidate",
            notes="Client-named account.",
        )
        for f in a.get("facts", []):
            src = SourceRecord(
                adapter="official_site",
                url=f["url"],
                title=f.get("title", ""),
                retrieved_at=now,
                licence="Public web page",
            )
            c.evidence.append(CompanyEvidence(claim=f["claim"], excerpt="", source=src))
        db.add(c)
        n += 1
    db.flush()
    return n


def _clarify(db: Session, topic: str, question: str, context: str = "", product_id: int | None = None) -> int:
    if db.scalar(select(Clarification.id).where(Clarification.question == question)):
        return 0
    db.add(Clarification(topic=topic, question=question, context=context, product_id=product_id))
    return 1


def hs6_of(code: str) -> str:
    digits = "".join(ch for ch in code if ch.isdigit())
    return digits[:6] if len(digits) >= 6 else ""


def client_list_skus(path: Path = HS_LIST) -> list[str]:
    with path.open(encoding="utf-8") as f:
        return [r["new_sku"] for r in csv.DictReader(f) if r["new_sku"]]


def apply_hs_list(db: Session, path: Path = HS_LIST, brand: str = "") -> dict:
    valid = set(db.scalars(select(HSCode.code)))
    updated = created = questions = 0
    with path.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        label = r["name_en"] or r["name_ar"]
        source = f"{HS_LIST_SOURCE}, row {r['row_no'] or 'unnumbered'}: {r['client_hs_code']} {label}".strip()
        hs6 = r["analysis_hs6"] if r["analysis_hs6"] in valid else None
        status = r["status"] if hs6 else "unmapped"
        if status == "candidate" and hs6_of(r["client_hs_code"]) != hs6:
            status = "discrepancy"  # the client's code points to another product family
        targets = [db.scalar(select(Product).where(Product.sku == s)) for s in r["skus"].split(";") if s]
        targets = [p for p in targets if p]
        if r["new_sku"]:
            p = db.scalar(select(Product).where(Product.sku == r["new_sku"]))
            if not p:
                p = Product(
                    sku=r["new_sku"],
                    name=r["name_en"] or f"{r['name_ar']} (English name not provided)",
                    brand=brand,
                    category=r["new_category"],
                    notes="Added from the client HS list; not shown in the catalogue PDF.",
                )
                db.add(p)
                created += 1
            targets.append(p)
        for p in targets:
            if p.client_hs_code or p.hs_status == "confirmed":
                continue  # already applied or confirmed by a reviewer
            p.client_hs_code = r["client_hs_code"]
            p.client_hs_source = source
            p.name_ar = p.name_ar or r["name_ar"]
            p.priority_category = p.priority_category or r["priority_category"]
            p.hs_code, p.hs_status, p.hs_note = hs6, status, r["finding"]
            p.hs_source = "client" if hs6 and hs6_of(r["client_hs_code"]) == hs6 else "classification_review"
            updated += 1
        db.flush()
        client6 = hs6_of(r["client_hs_code"])
        if targets and (status == "insufficient_info" or client6 != r["analysis_hs6"]):
            q = f"HS code for '{label}' (client code {r['client_hs_code']}): {r['finding']}"
            questions += _clarify(db, "hs", q, source, targets[0].id)
    return {"rows": len(rows), "products_updated": updated, "products_created": created, "questions": questions}


def _apply_priority_skus(db: Session, mapping: dict[str, list[str]]) -> int:
    n = 0
    for category, skus in mapping.items():
        for p in db.scalars(select(Product).where(Product.sku.in_(skus), Product.priority_category == "")):
            p.priority_category = category
            n += 1
    return n


def apply_patches(db: Session, patches: list[dict]) -> list[str]:
    """One-time updates from later client briefs. Each patch runs once (tracked by id) and only adds information:
    aliases, region members, notes, answers and sourced requirements. Nothing edited in the app is removed."""
    from datetime import date as _date

    from app.models import RetailerRequirement

    done = list(settings.get_raw(db, "client_patches_applied") or [])
    applied = []
    for p in patches:
        if p["id"] in done:
            continue
        merge = p.get("settings_merge", {})
        if "regions" in merge or "settings_replace_region" in p:
            regions = dict(settings.get(db, "regions"))
            for name, members in merge.get("regions", {}).items():
                regions[name] = sorted(set(regions.get(name, [])) | set(members))
            regions.update(p.get("settings_replace_region", {}))
            settings.put(db, "regions", regions)
        if "region_notes" in merge:
            settings.put(db, "region_notes", {**(settings.get_raw(db, "region_notes") or {}), **merge["region_notes"]})
        for key, value in p.get("settings_set_if_missing", {}).items():
            if settings.get_raw(db, key) is None:
                settings.put(db, key, value)
        for name, aliases in p.get("company_aliases", {}).items():
            for c in db.scalars(select(Company).where(Company.name == name)):
                c.aliases = sorted(set(c.aliases or []) | set(aliases))
        for name, note in p.get("company_notes", {}).items():
            for c in db.scalars(select(Company).where(Company.name == name)):
                if note not in (c.notes or ""):
                    c.notes = f"{c.notes}\n{note}".strip()
        for name, fields in p.get("entity_updates", {}).items():
            e = db.scalar(select(Entity).where(Entity.name == name))
            if e:
                e.notes = fields.get("notes", e.notes)
        for needle, answer in p.get("answers", {}).items():
            for q in db.scalars(
                select(Clarification).where(Clarification.question.contains(needle), Clarification.status == "open")
            ):
                q.answer, q.status = answer, "answered"
                q.answered_at = datetime.now(UTC)
        for r in p.get("requirements", []):
            company = db.scalar(select(Company).where(Company.name == r["company"])) if r.get("company") else None
            if r.get("company") and not company:
                continue
            exists = db.scalar(select(RetailerRequirement).where(RetailerRequirement.title == r["title"]))
            if not exists:
                db.add(
                    RetailerRequirement(
                        company_id=company.id if company else None,
                        market_iso3=r.get("market", ""),
                        title=r["title"],
                        detail=r.get("detail", ""),
                        source_url=r["source_url"],
                        verified_at=_date.fromisoformat(r["verified_at"]) if r.get("verified_at") else None,
                    )
                )
        done.append(p["id"])
        applied.append(p["id"])
    settings.put(db, "client_patches_applied", done)
    db.flush()
    return applied
