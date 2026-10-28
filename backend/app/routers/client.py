"""Client workspace: manufacturing/export entities, open clarifications, target markets and regions,
and the overview dashboard."""

import io
from datetime import UTC, datetime
from typing import Literal

import pandas as pd
from fastapi import APIRouter, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from app.models import (
    ApiCache,
    Clarification,
    Company,
    Country,
    Entity,
    HsStatus,
    Product,
    RefreshRun,
    SourceRecord,
    TargetMarket,
    TradeObservation,
)
from app.routers.catalogue import MAX_UPLOAD
from app.routers.markets import _run_out
from app.security import DB, Admin, Analyst, CurrentUser
from app.services import audit, settings

router = APIRouter(prefix="/api", tags=["client"])


@router.get("/branding")
def branding(db: DB):
    """Public: the client's display name for the sign-in page (no other profile data)."""
    p = settings.get(db, "company_profile")
    return {"client_name": p.get("name", ""), "client_brand": p.get("brand", "")}


# --- entities -------------------------------------------------------------------------------------


class EntityIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    country_iso3: str = Field("", pattern=r"^([A-Za-z]{3})?$")
    role: Literal["manufacturer", "exporter", "both"] = "manufacturer"
    status: Literal["pending_verification", "verified", "rejected"] = "pending_verification"
    notes: str = Field("", max_length=4000)
    source_note: str = Field("", max_length=2000)


def _entity_out(e: Entity, products: int = 0) -> dict:
    return {
        "id": e.id,
        "name": e.name,
        "country_iso3": e.country_iso3,
        "role": e.role,
        "status": e.status,
        "notes": e.notes,
        "source_note": e.source_note,
        "products": products,
        "created_at": e.created_at.isoformat(),
    }


@router.get("/entities")
def list_entities(_: CurrentUser, db: DB):
    counts = dict(db.execute(select(Product.export_entity_id, func.count()).group_by(Product.export_entity_id)).all())
    return [_entity_out(e, counts.get(e.id, 0)) for e in db.scalars(select(Entity).order_by(Entity.name))]


@router.post("/entities", status_code=201)
def create_entity(body: EntityIn, user: Analyst, db: DB):
    if db.scalar(select(Entity).where(Entity.name == body.name)):
        raise HTTPException(409, f"An entity named {body.name} already exists.")
    e = Entity(**{**body.model_dump(), "country_iso3": body.country_iso3.upper()})
    db.add(e)
    db.flush()
    audit.record(db, user, "create", "entity", e.id, e.name)
    db.commit()
    return _entity_out(e)


@router.put("/entities/{entity_id}")
def update_entity(entity_id: int, body: EntityIn, user: Analyst, db: DB):
    e = db.get(Entity, entity_id)
    if not e:
        raise HTTPException(404, "Entity not found.")
    if db.scalar(select(Entity).where(Entity.name == body.name, Entity.id != entity_id)):
        raise HTTPException(409, f"An entity named {body.name} already exists.")
    before = e.status
    for k, v in {**body.model_dump(), "country_iso3": body.country_iso3.upper()}.items():
        setattr(e, k, v)
    audit.record(db, user, "update", "entity", e.id, f"{e.name}: status {before} -> {e.status}")
    db.commit()
    return _entity_out(e)


# --- clarifications -------------------------------------------------------------------------------

Topic = Literal["hs", "product", "entity", "market", "competitor", "account", "general"]


class ClarificationIn(BaseModel):
    topic: Topic = "general"
    question: str = Field(min_length=5, max_length=4000)
    context: str = Field("", max_length=4000)
    product_id: int | None = None


class ClarificationPatch(BaseModel):
    status: Literal["open", "answered", "closed"] | None = None
    answer: str | None = Field(None, max_length=8000)


def _clar_out(c: Clarification, products: dict[int, str]) -> dict:
    return {
        "id": c.id,
        "topic": c.topic,
        "question": c.question,
        "context": c.context,
        "status": c.status,
        "answer": c.answer,
        "product_id": c.product_id,
        "product": products.get(c.product_id or 0, ""),
        "answered_at": c.answered_at.isoformat() if c.answered_at else None,
        "created_at": c.created_at.isoformat(),
    }


def _product_names(db) -> dict[int, str]:
    return dict(db.execute(select(Product.id, Product.name)).all())


@router.get("/clarifications")
def list_clarifications(_: CurrentUser, db: DB, status: str | None = None, topic: str | None = None):
    stmt = select(Clarification).order_by(Clarification.status != "open", Clarification.topic, Clarification.id)
    if status:
        stmt = stmt.where(Clarification.status == status)
    if topic:
        stmt = stmt.where(Clarification.topic == topic)
    names = _product_names(db)
    return [_clar_out(c, names) for c in db.scalars(stmt)]


@router.post("/clarifications", status_code=201)
def create_clarification(body: ClarificationIn, user: Analyst, db: DB):
    if body.product_id and not db.get(Product, body.product_id):
        raise HTTPException(422, "Unknown product.")
    c = Clarification(**body.model_dump())
    db.add(c)
    db.flush()
    audit.record(db, user, "create", "clarification", c.id, body.question[:120])
    db.commit()
    return _clar_out(c, _product_names(db))


@router.patch("/clarifications/{clar_id}")
def update_clarification(clar_id: int, body: ClarificationPatch, user: Analyst, db: DB):
    c = db.get(Clarification, clar_id)
    if not c:
        raise HTTPException(404, "Clarification not found.")
    if body.answer is not None:
        c.answer = body.answer
    if body.status:
        if body.status == "answered" and not (c.answer or "").strip():
            raise HTTPException(422, "Record the client's answer before marking it answered.")
        c.status = body.status
    if c.status == "answered" and c.answered_at is None:
        c.answered_by, c.answered_at = user.id, datetime.now(UTC)
    audit.record(db, user, "update", "clarification", c.id, f"status {c.status}")
    db.commit()
    return _clar_out(c, _product_names(db))


# --- target markets and regions -------------------------------------------------------------------


def country_index(db) -> tuple[dict[str, str], dict[str, str]]:
    """ISO3 -> name, and lower-case name/ISO3 -> ISO3, from the Comtrade country list."""
    names: dict[str, str] = {}
    lookup: dict[str, str] = {}
    for c in db.scalars(select(Country).order_by(Country.m49)):
        if len(c.iso3) == 3 and c.iso3.isalpha():
            if "(..." not in c.name:  # skip historical names such as "Fed. Rep. of Germany (...1990)"
                names.setdefault(c.iso3, c.name.strip())
            lookup[c.name.strip().lower()] = c.iso3
            lookup[c.iso3.lower()] = c.iso3
    return names, lookup


@router.get("/target-markets")
def list_target_markets(_: CurrentUser, db: DB):
    names, _l = country_index(db)
    regions = settings.get(db, "regions")
    rows = db.scalars(select(TargetMarket).order_by(TargetMarket.segment, TargetMarket.iso3)).all()
    return {
        "markets": [
            {
                "iso3": m.iso3,
                "name": names.get(m.iso3, m.iso3),
                "segment": m.segment,
                "regions": [r for r, members in regions.items() if m.iso3 in members],
                "source": m.source,
                "notes": m.notes,
                "updated_at": m.updated_at.isoformat(),
            }
            for m in rows
        ],
        "counts": {s: sum(1 for m in rows if m.segment == s) for s in ("existing", "expansion")},
    }


@router.post("/target-markets/import")
async def import_target_markets(file: UploadFile, user: Analyst, db: DB):
    """Import the client's country list. Columns: country (name or ISO3), segment (existing/expansion), notes."""
    data = await file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "File is larger than 5 MB.")
    name = (file.filename or "").lower()
    try:
        if name.endswith((".xlsx", ".xls")):
            df = pd.read_excel(io.BytesIO(data), dtype=str)
        elif name.endswith(".csv"):
            df = pd.read_csv(io.BytesIO(data), dtype=str, encoding_errors="replace")
        else:
            raise HTTPException(415, "Upload a .csv or .xlsx file.")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(422, "The file could not be read. Check it is a valid CSV or Excel file.") from None
    df.columns = [str(c).strip().lower() for c in df.columns]
    col = next((c for c in ("country", "iso3", "country_iso3", "name") if c in df.columns), None)
    if not col:
        raise HTTPException(422, "Missing a 'country' column (country name or ISO3 code).")
    _n, lookup = country_index(db)
    rows, errors = {}, []
    for i, r in df.fillna("").iterrows():
        raw = str(r[col]).strip()
        if not raw:
            continue
        iso = lookup.get(raw.lower())
        segment = str(r.get("segment", "")).strip().lower() or "expansion"
        if not iso:
            errors.append({"line": int(i) + 2, "error": f"unknown country '{raw}'"})
        elif segment not in ("existing", "expansion"):
            errors.append({"line": int(i) + 2, "error": f"segment must be existing or expansion, not '{segment}'"})
        else:
            rows[iso] = {
                "iso3": iso,
                "segment": segment,
                "source": file.filename or "upload",
                "notes": str(r.get("notes", "")).strip()[:2000],
                "updated_at": datetime.now(UTC),
            }
    if rows:
        stmt = insert(TargetMarket).values(list(rows.values()))
        db.execute(
            stmt.on_conflict_do_update(
                index_elements=["iso3"],
                set_={k: stmt.excluded[k] for k in ("segment", "source", "notes", "updated_at")},
            )
        )
    audit.record(
        db, user, "import", "target_market", "", f"{file.filename}: {len(rows)} countries, {len(errors)} errors"
    )
    db.commit()
    return {"imported": len(rows), "errors": errors}


class TargetMarketIn(BaseModel):
    segment: Literal["existing", "expansion"]
    notes: str = Field("", max_length=2000)


@router.put("/target-markets/{iso3}")
def put_target_market(iso3: str, body: TargetMarketIn, user: Analyst, db: DB):
    iso3 = iso3.upper()
    names, _l = country_index(db)
    if iso3 not in names:
        raise HTTPException(422, f"Unknown country code {iso3}.")
    m = db.get(TargetMarket, iso3) or TargetMarket(iso3=iso3, source="Entered in the app")
    m.segment, m.notes, m.updated_at = body.segment, body.notes, datetime.now(UTC)
    db.add(m)
    audit.record(db, user, "update", "target_market", iso3, body.segment)
    db.commit()
    return {"iso3": iso3, "segment": m.segment}


@router.delete("/target-markets/{iso3}", status_code=204)
def delete_target_market(iso3: str, user: Analyst, db: DB):
    m = db.get(TargetMarket, iso3.upper())
    if not m:
        raise HTTPException(404, "Not in the market list.")
    db.delete(m)
    audit.record(db, user, "delete", "target_market", m.iso3)
    db.commit()


@router.get("/regions")
def get_regions(_: CurrentUser, db: DB):
    names, _l = country_index(db)
    return [
        {"name": r, "members": [{"iso3": i, "name": names.get(i, i)} for i in members]}
        for r, members in settings.get(db, "regions").items()
    ]


class RegionsIn(BaseModel):
    regions: dict[str, list[str]] = Field(max_length=30)


@router.put("/regions")
def put_regions(body: RegionsIn, user: Admin, db: DB):
    names, _l = country_index(db)
    clean: dict[str, list[str]] = {}
    for region, members in body.regions.items():
        region = region.strip()[:60]
        if not region:
            raise HTTPException(422, "Region names cannot be empty.")
        isos = sorted({m.strip().upper() for m in members if m.strip()})
        unknown = [m for m in isos if m not in names]
        if unknown:
            raise HTTPException(422, f"{region}: unknown country code(s) {', '.join(unknown)}.")
        clean[region] = isos
    settings.put(db, "regions", clean)
    audit.record(db, user, "update", "regions", "", ", ".join(f"{k} ({len(v)})" for k, v in clean.items()))
    db.commit()
    return get_regions(user, db)


# --- overview ---------------------------------------------------------------------------------------


@router.get("/overview")
def overview(_: CurrentUser, db: DB):
    hs_counts = dict(db.execute(select(Product.hs_status, func.count()).group_by(Product.hs_status)).all())
    priority = dict(
        db.execute(
            select(Product.priority_category, func.count())
            .where(Product.priority_category != "")
            .group_by(Product.priority_category)
        ).all()
    )
    accounts = db.execute(
        select(Company.relationship_type, Company.pipeline_stage, func.count()).group_by(
            Company.relationship_type, Company.pipeline_stage
        )
    ).all()
    open_q = dict(
        db.execute(
            select(Clarification.topic, func.count())
            .where(Clarification.status == "open")
            .group_by(Clarification.topic)
        ).all()
    )
    freshness = db.execute(
        select(TradeObservation.hs_code, func.max(SourceRecord.retrieved_at), func.max(TradeObservation.year))
        .join(SourceRecord, SourceRecord.id == TradeObservation.source_record_id)
        .group_by(TradeObservation.hs_code)
    ).all()
    catalogue_hs = set(db.scalars(select(Product.hs_code).where(Product.hs_code.is_not(None))))
    loaded = {hs for hs, _r, _y in freshness}
    last_run = db.scalar(select(RefreshRun).order_by(RefreshRun.id.desc()))
    due = db.scalars(
        select(Company).where(Company.follow_up_on.is_not(None)).order_by(Company.follow_up_on).limit(8)
    ).all()
    oldest = min((r for _h, r, _y in freshness if _h in catalogue_hs), default=None)
    return {
        "products": {
            "total": sum(hs_counts.values()),
            "by_hs_status": {s.value: hs_counts.get(s.value, 0) for s in HsStatus},
            "with_client_code": db.scalar(
                select(func.count()).select_from(Product).where(Product.client_hs_code != "")
            ),
            "priority": priority,
        },
        "trade": {
            "catalogue_hs": len(catalogue_hs),
            "loaded_hs": len(catalogue_hs & loaded),
            "observations": db.scalar(select(func.count()).select_from(TradeObservation)),
            "cached_responses": db.scalar(select(func.count()).select_from(ApiCache)),
            "oldest_retrieval": oldest.isoformat() if oldest else None,
            "latest_year": max((y for _h, _r, y in freshness), default=None),
            "last_run": _run_out(last_run),
        },
        "accounts": [{"relationship": r, "stage": s, "count": n} for r, s, n in accounts],
        "follow_ups": [
            {"id": c.id, "name": c.name, "next_action": c.next_action, "follow_up_on": c.follow_up_on.isoformat()}
            for c in due
        ],
        "clarifications_open": open_q,
        "target_markets": dict(
            db.execute(select(TargetMarket.segment, func.count()).group_by(TargetMarket.segment)).all()
        ),
        "entities": dict(db.execute(select(Entity.status, func.count()).group_by(Entity.status)).all()),
    }
