"""Shipments, buyers, retailer path, competitor tracker, market access, tariffs, requirements, alerts, ETL."""

import hashlib
import json
from datetime import UTC, date, datetime
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select, update

from app import ratelimit
from app.config import get_settings
from app.models import (
    Alert,
    ApiCache,
    Company,
    CompanyEvidence,
    HSCode,
    ImportBatch,
    LogisticsQuote,
    MonthlyFlow,
    ProspectListItem,
    RefreshRun,
    RetailerRequirement,
    Shipment,
    SourceRecord,
    Tariff,
)
from app.routers.markets import _run_out
from app.security import DB, Admin, Analyst, CurrentUser
from app.services import audit, etl, intel, settings, shipments

router = APIRouter(prefix="/api", tags=["intel"])


def _company(db, cid: int) -> Company:
    c = db.get(Company, cid)
    if not c:
        raise HTTPException(404, "Company not found.")
    return c


# --- shipment uploads -----------------------------------------------------------------------------


async def _read(file: UploadFile, user_id: int) -> tuple[bytes, object]:
    ratelimit.hit(f"upload:{user_id}", 10)
    data = await file.read(shipments.MAX_BYTES + 1)
    try:
        return data, shipments.read_table(data, file.filename or "")
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    except Exception:
        raise HTTPException(422, "The file could not be read. Check it is a valid CSV or Excel file.") from None


@router.post("/shipments/preview")
async def preview_shipments(file: UploadFile, user: Admin, db: DB, provider: str = Form(..., max_length=40)):
    _data, df = await _read(file, user.id)
    mapping = shipments.suggest_mapping(list(df.columns), provider, db)
    try:
        parsed = shipments.parse_rows(df.head(50), mapping, shipments.country_lookup(db)) if mapping else None
    except ValueError as exc:
        parsed, error = None, str(exc)
    else:
        error = None
    return {
        "columns": list(df.columns),
        "rows": len(df),
        "fields": shipments.FIELDS,
        "suggested_mapping": mapping,
        "sample": [
            {k: (str(v) if isinstance(v, date) else v) for k, v in r.items()}
            for r in (parsed.rows[:10] if parsed else [])
        ],
        "sample_errors": parsed.errors[:20] if parsed else [],
        "mapping_error": error,
    }


@router.post("/shipments/import")
async def import_shipments(
    file: UploadFile,
    user: Admin,
    db: DB,
    tasks: BackgroundTasks,
    provider: str = Form(..., max_length=40),
    mapping: str = Form(...),
    save_mapping: bool = Form(True),
):
    data, df = await _read(file, user.id)
    try:
        cols = json.loads(mapping)
        assert isinstance(cols, dict) and all(isinstance(v, str) for v in cols.values())
    except (ValueError, AssertionError):
        raise HTTPException(422, "Invalid column mapping.") from None
    cols = {k: v for k, v in cols.items() if k in shipments.FIELDS and v in df.columns}
    sha = hashlib.sha256(data).hexdigest()
    if db.scalar(
        select(ImportBatch).where(
            ImportBatch.file_sha256 == sha, ImportBatch.provider == provider, ImportBatch.status == "completed"
        )
    ):
        raise HTTPException(409, "This exact file was already imported for this provider.")
    try:
        parsed = shipments.parse_rows(df, cols, shipments.country_lookup(db))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    shipments.backfill_normalized(db)
    batch = ImportBatch(
        provider=provider,
        filename=(file.filename or "")[:255],
        file_sha256=sha,
        mapping=cols,
        uploaded_by=user.id,
        status="running",
    )
    db.add(batch)
    db.flush()
    shipments.import_rows(db, batch, parsed)
    if save_mapping:
        saved = settings.get_raw(db, "shipment_mappings") or {}
        settings.put(db, "shipment_mappings", {**saved, provider: cols})
    audit.record(
        db,
        user,
        "upload",
        "shipments",
        batch.id,
        f"{batch.filename}: {batch.inserted} new, {batch.duplicates} duplicates, {len(batch.errors)} issues",
    )
    db.commit()
    intel.generate_alerts(db)
    db.commit()
    return _batch_out(batch)


def _batch_out(b: ImportBatch) -> dict:
    return {
        "id": b.id,
        "provider": b.provider,
        "filename": b.filename,
        "row_count": b.row_count,
        "inserted": b.inserted,
        "duplicates": b.duplicates,
        "errors": b.errors,
        "status": b.status,
        "created_at": b.created_at.isoformat() if b.created_at else None,
    }


@router.get("/shipments/batches")
def batches(_: Admin, db: DB):
    return [_batch_out(b) for b in db.scalars(select(ImportBatch).order_by(ImportBatch.id.desc()).limit(100))]


@router.delete("/shipments/batches/{batch_id}", status_code=204)
def delete_batch(batch_id: int, user: Admin, db: DB):
    b = db.get(ImportBatch, batch_id)
    if not b:
        raise HTTPException(404, "Import not found.")
    audit.record(db, user, "delete", "shipments", b.id, b.filename)
    db.delete(b)
    db.commit()


@router.get("/shipments")
def list_shipments(
    _: CurrentUser, db: DB, company_id: int | None = None, hs: str | None = None, limit: int = Query(200, le=1000)
):
    """Raw rows from licensed files: visible to signed-in users only, never exported in bulk."""
    stmt = select(Shipment).order_by(Shipment.shipped_on.desc()).limit(limit)
    if company_id:
        stmt = stmt.where(or_(Shipment.consignee_company_id == company_id, Shipment.shipper_company_id == company_id))
    if hs:
        stmt = stmt.where(Shipment.hs_code.startswith(hs))
    return [
        {
            "id": s.id,
            "date": s.shipped_on.isoformat(),
            "shipper": s.shipper_name,
            "consignee": s.consignee_name,
            "origin_iso3": s.origin_iso3,
            "destination_iso3": s.destination_iso3,
            "hs_code": s.hs_code,
            "description": s.product_description,
            "weight_kg": s.weight_kg,
            "value_usd": s.value_usd,
            "provider": s.provider,
        }
        for s in db.scalars(stmt)
    ]


# --- analytics on shipments -------------------------------------------------------------------------


@router.get("/buyers")
def buyers(_: CurrentUser, db: DB, hs: str | None = None, market: str | None = None):
    return intel.buyers(db, hs, market)


class FitWeights(BaseModel):
    category_match: float = Field(ge=0, le=100)
    volume: float = Field(ge=0, le=100)
    consistency: float = Field(ge=0, le=100)
    displaceable_origins: float = Field(ge=0, le=100)
    growth: float = Field(ge=0, le=100)
    supplier_change: float = Field(ge=0, le=100)


@router.put("/buyers/weights")
def set_fit_weights(body: FitWeights, user: Admin, db: DB):
    if sum(body.model_dump().values()) <= 0:
        raise HTTPException(422, "At least one weight must be above zero.")
    settings.put(db, "buyer_fit_weights", body.model_dump())
    audit.record(db, user, "update", "settings", "buyer_fit_weights")
    db.commit()
    return body.model_dump()


@router.get("/retailers/{company_id}/path")
def retailer_path(company_id: int, _: CurrentUser, db: DB):
    return intel.retailer_path(db, _company(db, company_id))


@router.get("/competitors/{company_id}/tracker")
def competitor_tracker(company_id: int, _: CurrentUser, db: DB):
    return intel.competitor_tracker(db, _company(db, company_id))


@router.get("/companies/{company_id}/similar")
def similar(company_id: int, _: Analyst, db: DB):
    shipments.backfill_normalized(db)
    db.commit()
    return shipments.similar_companies(db, _company(db, company_id))


class MergeIn(BaseModel):
    into_id: int


@router.post("/companies/{company_id}/merge")
def merge(company_id: int, body: MergeIn, user: Admin, db: DB):
    """Merge a duplicate into another record: its name becomes an alias; shipments and evidence move."""
    src, dst = _company(db, company_id), _company(db, body.into_id)
    if src.id == dst.id:
        raise HTTPException(422, "Choose a different company.")
    dst.aliases = sorted({*(dst.aliases or []), src.name, *(src.aliases or [])} - {dst.name})
    db.execute(update(Shipment).where(Shipment.consignee_company_id == src.id).values(consignee_company_id=dst.id))
    db.execute(update(Shipment).where(Shipment.shipper_company_id == src.id).values(shipper_company_id=dst.id))
    db.execute(update(CompanyEvidence).where(CompanyEvidence.company_id == src.id).values(company_id=dst.id))
    existing = set(db.scalars(select(ProspectListItem.list_id).where(ProspectListItem.company_id == dst.id)))
    for item in db.scalars(select(ProspectListItem).where(ProspectListItem.company_id == src.id)):
        if item.list_id in existing:
            db.delete(item)
        else:
            item.company_id = dst.id
    audit.record(db, user, "merge", "company", dst.id, f"{src.name} (#{src.id}) merged into {dst.name}")
    db.flush()
    db.expire(src)
    db.delete(db.get(Company, src.id))
    db.commit()
    return {"id": dst.id, "name": dst.name, "aliases": dst.aliases}


class AliasesIn(BaseModel):
    aliases: list[str] = Field(max_length=50)


@router.put("/companies/{company_id}/aliases")
def set_aliases(company_id: int, body: AliasesIn, user: Admin, db: DB):
    c = _company(db, company_id)
    c.aliases = sorted({a.strip()[:255] for a in body.aliases if a.strip()})
    audit.record(db, user, "update", "company", c.id, f"aliases: {', '.join(c.aliases)}")
    db.commit()
    return {"id": c.id, "aliases": c.aliases}


# --- market access ------------------------------------------------------------------------------------


@router.get("/access")
def access(
    _: CurrentUser,
    db: DB,
    market: str = Query(pattern="^[A-Za-z]{3}$"),
    hs: str = Query(pattern=r"^\d{6}$"),
    fob: float | None = Query(None, gt=0, le=1000),
    insurance_pct: float = Query(0.5, ge=0, le=10),
):
    if not db.get(HSCode, hs):
        raise HTTPException(404, f"Unknown HS code {hs}.")
    return intel.landed_cost(db, market.upper(), hs, fob, insurance_pct)


def _tariff_out(t: Tariff) -> dict:
    return {
        "id": t.id,
        "importer_iso3": t.importer_iso3,
        "hs_code": t.hs_code,
        "origin_iso3": t.origin_iso3,
        "rate_type": t.rate_type,
        "ad_valorem_pct": t.ad_valorem_pct,
        "specific_rate": t.specific_rate,
        "agreement": t.agreement,
        "data_year": t.data_year,
        "source": t.source,
        "source_url": t.source_url,
        "verified_at": t.verified_at.isoformat() if t.verified_at else None,
        "notes": t.notes,
        "effective_from": t.effective_from.isoformat() if t.effective_from else None,
        "effective_to": t.effective_to.isoformat() if t.effective_to else None,
    }


@router.get("/tariffs")
def tariffs(_: CurrentUser, db: DB, market: str | None = None, hs: str | None = None):
    stmt = select(Tariff).order_by(Tariff.importer_iso3, Tariff.hs_code, Tariff.origin_iso3).limit(500)
    if market:
        stmt = stmt.where(Tariff.importer_iso3 == market.upper())
    if hs:
        stmt = stmt.where(Tariff.hs_code.startswith(hs))
    return [_tariff_out(t) for t in db.scalars(stmt)]


class TariffIn(BaseModel):
    importer_iso3: str = Field(pattern="^[A-Za-z]{3}$")
    hs_code: str = Field(pattern=r"^\d{6,10}$")
    origin_iso3: str = Field("", pattern="^([A-Za-z]{3})?$")
    rate_type: Literal["MFN", "preferential", "additional"]
    ad_valorem_pct: float | None = Field(None, ge=0, le=1000)
    specific_rate: str = Field("", max_length=200)
    agreement: str = Field("", max_length=200)
    effective_from: date | None = None
    effective_to: date | None = None
    source_url: str = Field(pattern=r"^https?://\S+$", max_length=1000)
    notes: str = Field("", max_length=2000)


@router.post("/tariffs", status_code=201)
def add_tariff(body: TariffIn, user: Admin, db: DB):
    """Admin override with its source; wins over connector rates for the same importer/HS/origin/type."""
    t = Tariff(
        **{**body.model_dump(), "importer_iso3": body.importer_iso3.upper(), "origin_iso3": body.origin_iso3.upper()},
        source="override",
        created_by=user.id,
        verified_at=datetime.now(UTC),
    )
    db.add(t)
    db.flush()
    audit.record(db, user, "create", "tariff", t.id, f"{t.importer_iso3} {t.hs_code} {t.origin_iso3} {t.rate_type}")
    db.commit()
    return _tariff_out(t)


@router.delete("/tariffs/{tariff_id}", status_code=204)
def delete_tariff(tariff_id: int, user: Admin, db: DB):
    t = db.get(Tariff, tariff_id)
    if not t:
        raise HTTPException(404, "Tariff not found.")
    audit.record(db, user, "delete", "tariff", t.id, f"{t.importer_iso3} {t.hs_code} {t.source}")
    db.delete(t)
    db.commit()


# --- requirements -------------------------------------------------------------------------------------


class RequirementIn(BaseModel):
    company_id: int | None = None
    market_iso3: str = Field("", pattern="^([A-Za-z]{3})?$")
    title: str = Field(min_length=3, max_length=300)
    detail: str = Field("", max_length=4000)
    source_url: str = Field(pattern=r"^https?://\S+$", max_length=1000)
    verified_at: date | None = None
    status: Literal["todo", "in_progress", "met", "not_applicable"] = "todo"


@router.post("/requirements", status_code=201)
def add_requirement(body: RequirementIn, user: Admin, db: DB):
    r = RetailerRequirement(**{**body.model_dump(), "market_iso3": body.market_iso3.upper()})
    db.add(r)
    db.flush()
    audit.record(db, user, "create", "requirement", r.id, r.title[:120])
    db.commit()
    return {"id": r.id}


class RequirementStatus(BaseModel):
    status: Literal["todo", "in_progress", "met", "not_applicable"]


@router.patch("/requirements/{req_id}")
def set_requirement_status(req_id: int, body: RequirementStatus, user: Analyst, db: DB):
    r = db.get(RetailerRequirement, req_id)
    if not r:
        raise HTTPException(404, "Requirement not found.")
    r.status = body.status
    audit.record(db, user, "update", "requirement", r.id, body.status)
    db.commit()
    return {"id": r.id, "status": r.status}


@router.delete("/requirements/{req_id}", status_code=204)
def delete_requirement(req_id: int, user: Admin, db: DB):
    r = db.get(RetailerRequirement, req_id)
    if not r:
        raise HTTPException(404, "Requirement not found.")
    audit.record(db, user, "delete", "requirement", r.id, r.title[:120])
    db.delete(r)
    db.commit()


# --- alerts -------------------------------------------------------------------------------------------


@router.get("/alerts")
def alerts(_: CurrentUser, db: DB, unread: bool = False, limit: int = Query(100, le=500)):
    stmt = select(Alert).order_by(Alert.created_at.desc()).limit(limit)
    if unread:
        stmt = stmt.where(Alert.read_at.is_(None))
    return [
        {
            "id": a.id,
            "type": a.type,
            "title": a.title,
            "company_id": a.company_id,
            "hs_code": a.hs_code,
            "payload": a.payload,
            "created_at": a.created_at.isoformat(),
            "read_at": a.read_at.isoformat() if a.read_at else None,
        }
        for a in db.scalars(stmt)
    ]


@router.post("/alerts/{alert_id}/read", status_code=204)
def read_alert(alert_id: int, _: CurrentUser, db: DB):
    a = db.get(Alert, alert_id)
    if not a:
        raise HTTPException(404, "Alert not found.")
    a.read_at = a.read_at or datetime.now(UTC)
    db.commit()


@router.post("/alerts/run")
def run_alerts(user: Admin, db: DB):
    n = intel.generate_alerts(db)
    db.commit()
    return {"created": n}


# --- connectors / data freshness --------------------------------------------------------------------


class EtlIn(BaseModel):
    connector: Literal["comext", "census", "tariffs", "fx"]
    hs_codes: list[str] = Field(default_factory=list, max_length=20)
    months_back: int = Field(12, ge=1, le=36)
    markets: list[str] = Field(default_factory=list, max_length=10)
    origins: list[str] = Field(default_factory=list, max_length=10)


@router.post("/admin/etl", status_code=202)
def start_etl(body: EtlIn, user: Admin, db: DB, tasks: BackgroundTasks):
    for hs in body.hs_codes:
        if not (hs.isdigit() and len(hs) in (6, 8, 10)) or not db.get(HSCode, hs[:6]):
            raise HTTPException(422, f"Invalid HS code {hs}.")
    if body.connector != "fx" and not body.hs_codes:
        raise HTTPException(422, "Choose at least one HS code.")
    run = RefreshRun(
        adapter=body.connector, scope=", ".join(body.hs_codes) or "FX", started_by=user.id, message="Queued"
    )
    db.add(run)
    audit.record(db, user, "etl", body.connector, "", json.dumps(body.model_dump()))
    db.commit()
    tasks.add_task(
        etl.run,
        run.id,
        body.connector,
        {
            **body.model_dump(),
            "markets": [m.upper() for m in body.markets],
            "origins": [o.upper() for o in body.origins],
        },
    )
    return _run_out(run)


@router.get("/admin/freshness")
def freshness(_: CurrentUser, db: DB):
    """Latest retrieval and row counts per source, for the overview and Data admin."""
    latest = dict(
        db.execute(
            select(SourceRecord.adapter, func.max(SourceRecord.retrieved_at)).group_by(SourceRecord.adapter)
        ).all()
    )
    monthly = dict(db.execute(select(MonthlyFlow.source, func.count()).group_by(MonthlyFlow.source)).all())
    latest_month = dict(
        db.execute(select(MonthlyFlow.source, func.max(MonthlyFlow.period)).group_by(MonthlyFlow.source)).all()
    )
    tariffs_ = dict(db.execute(select(Tariff.source, func.count()).group_by(Tariff.source)).all())
    last_runs = {
        a: _run_out(
            db.scalar(select(RefreshRun).where(RefreshRun.adapter == a).order_by(RefreshRun.id.desc()).limit(1))
        )
        for a in ("un_comtrade", *etl.CONNECTORS)
    }
    cached = dict(db.execute(select(ApiCache.adapter, func.count()).group_by(ApiCache.adapter)).all())
    return {
        "sources": [
            {
                "key": "un_comtrade",
                "name": "UN Comtrade (annual)",
                "confidence": "official",
                "last_retrieved": _iso(latest.get("un_comtrade")),
                "last_run": last_runs["un_comtrade"],
            },
            {
                "key": "comext",
                "name": "Eurostat Comext (monthly EU)",
                "confidence": "official",
                "rows": monthly.get("comext", 0),
                "latest_period": latest_month.get("comext"),
                "last_retrieved": _iso(latest.get("comext")),
                "last_run": last_runs["comext"],
            },
            {
                "key": "census",
                "name": "US Census (monthly US imports)",
                "confidence": "official",
                "rows": monthly.get("census", 0),
                "latest_period": latest_month.get("census"),
                "last_retrieved": _iso(latest.get("census")),
                "last_run": last_runs["census"],
                "needs": None if get_settings().census_api_key else "CENSUS_API_KEY",
            },
            {
                "key": "tariffs",
                "name": "Tariffs (WITS, USITC, overrides)",
                "confidence": "official",
                "rows": sum(tariffs_.values()),
                "by_source": tariffs_,
                "last_retrieved": _iso(max(filter(None, [latest.get("wits"), latest.get("usitc")]), default=None)),
                "last_run": last_runs["tariffs"],
            },
            {
                "key": "fx",
                "name": "FX rates (ECB via Frankfurter)",
                "confidence": "official",
                "cached": cached.get("frankfurter", 0),
                "last_run": last_runs["fx"],
            },
            {
                "key": "shipments",
                "name": "Shipment records (provider files)",
                "confidence": "licensed",
                "rows": db.scalar(select(func.count()).select_from(Shipment)),
                "last_retrieved": _iso(db.scalar(select(func.max(ImportBatch.created_at)))),
            },
            {
                "key": "freight",
                "name": "Freight routes (admin, estimates)",
                "confidence": "estimate",
                "rows": db.scalar(select(func.count()).select_from(LogisticsQuote)),
            },
        ]
    }


def _iso(v):
    return v.isoformat() if v else None


@router.get("/markets/{hs}/monthly")
def monthly(hs: str, _: CurrentUser, db: DB, reporter: str = Query(pattern="^[A-Za-z]{3}$")):
    rows = db.scalars(
        select(MonthlyFlow)
        .where(MonthlyFlow.hs6 == hs[:6], MonthlyFlow.reporter_iso3 == reporter.upper())
        .order_by(MonthlyFlow.period)
    ).all()
    srcs = {r.source_record_id for r in rows}
    meta = {
        s.id: {
            "id": s.id,
            "url": s.url,
            "retrieved_at": s.retrieved_at.isoformat(),
            "adapter": s.adapter,
            "licence": s.licence,
        }
        for s in db.scalars(select(SourceRecord).where(SourceRecord.id.in_(srcs or {-1})))
    }
    return {
        "hs6": hs[:6],
        "reporter": reporter.upper(),
        "rows": [
            {
                "source": r.source,
                "partner_iso3": r.partner_iso3,
                "partner_name": r.partner_name,
                "product_code": r.product_code,
                "period": r.period,
                "value_usd": r.value_usd,
                "value_native": r.value_native,
                "currency": r.currency,
                "fx_rate": r.fx_rate,
                "net_weight_kg": r.net_weight_kg,
                "quantity": r.quantity,
                "unit": r.unit,
                "source_id": r.source_record_id,
            }
            for r in rows
        ],
        "sources": list(meta.values()),
    }
