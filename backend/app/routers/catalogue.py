import io
import re
from typing import Literal

import pandas as pd
from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app import ratelimit
from app.exports import safe_df
from app.models import Entity, HSCode, HsStatus, Product, TradeObservation
from app.security import DB, Admin, Analyst, CurrentUser
from app.services import audit
from app.services.client_data import hs6_of

router = APIRouter(prefix="/api", tags=["catalogue"])
MAX_UPLOAD = 5 * 1024 * 1024
REQUIRED = {"sku", "name"}
HS_STATUSES = tuple(s.value for s in HsStatus)
TEXT_COLUMNS = (
    "name_ar",
    "client_hs_code",
    "ingredients",
    "processing",
    "manufacturing_country",
    "priority_category",
    "brand",
    "category",
    "pack_size",
    "net_unit",
    "packaging",
    "catalogue_page",
    "description",
    "notes",
    "hs_note",
)
EXPORT_COLUMNS = [
    "sku",
    "name",
    "name_ar",
    "brand",
    "category",
    "priority_category",
    "client_hs_code",
    "client_hs_source",
    "hs_code",
    "hs_status",
    "hs_reviewed_at",
    "ingredients",
    "processing",
    "manufacturing_country",
    "pack_size",
    "net_quantity",
    "net_unit",
    "packaging",
    "catalogue_page",
    "description",
    "hs_note",
    "notes",
]


def normalize_hs(raw: object) -> str:
    s = str(raw or "").strip()
    if s.endswith(".0"):  # numeric cells read as "190531.0"
        s = s[:-2]
    digits = re.sub(r"\D", "", s)
    if len(digits) == 5:  # spreadsheets drop the leading zero (e.g. 90111 -> 090111)
        digits = "0" + digits
    return digits[:6]


def hs6_or_none(v: str | None) -> str | None:
    if not (v or "").strip():
        return None
    code = normalize_hs(v)
    if len(code) != 6:
        raise ValueError("HS code must have at least 6 digits")
    return code


class ProductIn(BaseModel):
    sku: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    hs_code: str | None = None
    hs_status: Literal["confirmed", "candidate", "insufficient_info", "unmapped"] = "candidate"
    hs_note: str = Field("", max_length=2000)
    client_hs_code: str = Field("", max_length=14, pattern=r"^[0-9. ]*$")
    name_ar: str = Field("", max_length=255)
    ingredients: str = Field("", max_length=4000)
    processing: str = Field("", max_length=4000)
    manufacturing_country: str = Field("", pattern=r"^([A-Za-z]{3})?$")
    export_entity_id: int | None = None
    priority_category: str = Field("", max_length=60)
    description: str = Field("", max_length=4000)
    category: str = Field("", max_length=120)
    brand: str = Field("", max_length=120)
    pack_size: str = Field("", max_length=80)
    net_quantity: float | None = Field(None, gt=0)
    net_unit: Literal["", "g", "kg", "ml", "L"] = ""
    packaging: str = Field("", max_length=80)
    catalogue_page: str = Field("", max_length=40, pattern=r"^[0-9, ]*$")
    notes: str = Field("", max_length=4000)

    @field_validator("hs_code")
    @classmethod
    def _hs(cls, v: str | None) -> str | None:
        return hs6_or_none(v)

    @field_validator("manufacturing_country")
    @classmethod
    def _iso(cls, v: str) -> str:
        return v.upper()

    def fields(self) -> dict:
        d = self.model_dump()
        if not d["hs_code"]:
            d["hs_status"] = HsStatus.unmapped
        elif d["hs_status"] == HsStatus.unmapped:
            d["hs_status"] = HsStatus.candidate
        d["client_hs_code"] = re.sub(r"\D", "", d["client_hs_code"])
        return d


def hs_check(p: Product, valid: set[str] | None = None) -> dict:
    """Compare the client's code with the HS6 used for analysis. Never changes either value."""
    client6 = hs6_of(p.client_hs_code)
    issues = []
    if not p.client_hs_code:
        issues.append("No client HS code provided.")
    elif valid is not None and client6 and client6 not in valid:
        issues.append(f"Client code prefix {client6} is not an HS6 subheading in the current nomenclature.")
    elif client6 and p.hs_code and client6 != p.hs_code:
        issues.append(f"Client code points to HS {client6}; the analysis uses HS {p.hs_code}.")
    if len(p.client_hs_code) > 6:
        issues.append(
            f"Client code has {len(p.client_hs_code)} digits: a national tariff line that may not map 1:1 to HS6."
        )
    return {"client_hs6": client6, "matches_client": bool(client6 and client6 == p.hs_code), "issues": issues}


def pages(p: Product) -> list[int]:
    return [int(x) for x in re.findall(r"\d+", p.catalogue_page or "")]


def _out(p: Product, has_data: bool = False, valid: set[str] | None = None) -> dict:
    return {
        "id": p.id,
        "sku": p.sku,
        "name": p.name,
        "name_ar": p.name_ar,
        "brand": p.brand,
        "description": p.description,
        "category": p.category,
        "priority_category": p.priority_category,
        "pack_size": p.pack_size,
        "net_quantity": p.net_quantity,
        "net_unit": p.net_unit,
        "packaging": p.packaging,
        "catalogue_page": p.catalogue_page,
        "catalogue_pages": pages(p),
        "notes": p.notes,
        "ingredients": p.ingredients,
        "processing": p.processing,
        "manufacturing_country": p.manufacturing_country,
        "export_entity_id": p.export_entity_id,
        "export_entity": p.export_entity.name if p.export_entity else "",
        "hs_code": p.hs_code,
        "hs_status": p.hs_status,
        "hs_note": p.hs_note,
        "hs_description": p.hs.description if p.hs else "",
        "client_hs_code": p.client_hs_code,
        "client_hs_source": p.client_hs_source,
        "hs_reviewed_at": p.hs_reviewed_at,
        "hs_check": hs_check(p, valid),
        "has_trade_data": has_data,
    }


@router.get("/hs-codes")
def search_hs(_: CurrentUser, db: DB, q: str = "", limit: int = 20):
    q = q.strip()
    stmt = select(HSCode).order_by(HSCode.code).limit(min(limit, 50))
    if q:
        word_start = HSCode.description.op("~*")(r"\m" + re.escape(q))  # "dates" must not match "periodates"
        stmt = stmt.where(or_(HSCode.code.startswith(re.sub(r"\D", "", q) or q), word_start))
    return [{"code": h.code, "description": h.description} for h in db.scalars(stmt)]


@router.get("/products")
def list_products(_: CurrentUser, db: DB):
    with_data = set(db.scalars(select(TradeObservation.hs_code).distinct()))
    valid = set(db.scalars(select(HSCode.code)))
    stmt = select(Product).order_by(Product.category, Product.name, Product.net_quantity)
    return [_out(p, p.hs_code in with_data, valid) for p in db.scalars(stmt)]


@router.get("/products/export")
def export_products(user: CurrentUser, db: DB):
    valid = set(db.scalars(select(HSCode.code)))
    rows = []
    for p in db.scalars(select(Product).order_by(Product.sku)):
        row = {c: getattr(p, c) for c in EXPORT_COLUMNS}
        row["hs_issues"] = " ".join(hs_check(p, valid)["issues"])
        rows.append(row)
    csv = safe_df(pd.DataFrame(rows, columns=[*EXPORT_COLUMNS, "hs_issues"])).to_csv(index=False)
    audit.record(db, user, "export", "product", "", f"{len(rows)} rows")
    db.commit()
    return Response(
        csv.encode("utf-8-sig"),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="product-catalogue.csv"'},
    )


@router.get("/products/{product_id}")
def get_product(product_id: int, _: CurrentUser, db: DB):
    p = db.get(Product, product_id)
    if not p:
        raise HTTPException(404, "Product not found.")
    has = db.scalar(select(func.count()).select_from(TradeObservation).where(TradeObservation.hs_code == p.hs_code)) > 0
    return _out(p, has, set(db.scalars(select(HSCode.code))))


def _check_hs(db, body: ProductIn) -> None:
    if body.hs_code and not db.get(HSCode, body.hs_code):
        raise HTTPException(422, f"HS code {body.hs_code} is not a valid HS6 code in the UN Comtrade classification.")
    if body.export_entity_id and not db.get(Entity, body.export_entity_id):
        raise HTTPException(422, "Unknown export entity.")


@router.post("/products", status_code=201)
def create_product(body: ProductIn, user: Analyst, db: DB):
    _check_hs(db, body)
    if db.scalar(select(Product).where(Product.sku == body.sku)):
        raise HTTPException(409, f"SKU {body.sku} already exists.")
    p = Product(**body.fields())
    db.add(p)
    db.flush()
    audit.record(db, user, "create", "product", p.id, f"{p.sku} {p.name}")
    db.commit()
    db.refresh(p)
    return _out(p)


@router.put("/products/{product_id}")
def update_product(product_id: int, body: ProductIn, user: Analyst, db: DB):
    p = db.get(Product, product_id)
    if not p:
        raise HTTPException(404, "Product not found.")
    _check_hs(db, body)
    clash = db.scalar(select(Product).where(Product.sku == body.sku, Product.id != product_id))
    if clash:
        raise HTTPException(409, f"SKU {body.sku} already exists.")
    fields = body.fields()
    if p.client_hs_code and fields["client_hs_code"] != p.client_hs_code:
        raise HTTPException(422, "The client's HS code is kept exactly as provided and cannot be edited here.")
    if fields["hs_code"] != p.hs_code and user.role != "admin":
        raise HTTPException(403, "Only an administrator can change a product's HS mapping (use HS review).")
    if fields["hs_code"] != p.hs_code and fields["hs_status"] == HsStatus.confirmed:
        fields["hs_status"] = HsStatus.candidate  # a changed code must be confirmed again through review
    changed = [k for k, v in fields.items() if getattr(p, k) != v]
    for k, v in fields.items():
        setattr(p, k, v)
    audit.record(db, user, "update", "product", p.id, f"{p.sku}: {', '.join(changed) or 'no changes'}")
    db.commit()
    db.refresh(p)
    return _out(p)


@router.delete("/products/{product_id}", status_code=204)
def delete_product(product_id: int, user: Analyst, db: DB):
    p = db.get(Product, product_id)
    if not p:
        raise HTTPException(404, "Product not found.")
    audit.record(db, user, "delete", "product", p.id, f"{p.sku} {p.name}")
    db.delete(p)
    db.commit()


class HsReviewIn(BaseModel):
    hs_code: str | None = None
    status: Literal["confirmed", "candidate", "insufficient_info", "unmapped"]
    note: str = Field("", max_length=2000)

    @field_validator("hs_code")
    @classmethod
    def _hs(cls, v: str | None) -> str | None:
        return hs6_or_none(v)


@router.post("/products/{product_id}/hs-review")
def review_hs(product_id: int, body: HsReviewIn, user: Admin, db: DB):
    """Record a reviewer's HS decision. The client's own code is never changed."""
    p = db.get(Product, product_id)
    if not p:
        raise HTTPException(404, "Product not found.")
    if body.status == HsStatus.unmapped:
        body.hs_code = None
    elif not body.hs_code:
        raise HTTPException(422, "Choose an HS6 code, or mark the product as unmapped.")
    elif not db.get(HSCode, body.hs_code):
        raise HTTPException(422, f"HS code {body.hs_code} is not a valid HS6 code in the UN Comtrade classification.")
    before = f"{p.hs_code or '-'} {p.hs_status}"
    p.hs_code, p.hs_status = body.hs_code, body.status
    if body.note:
        p.hs_note = body.note
    p.hs_reviewed_by, p.hs_reviewed_at = user.id, func.now()
    audit.record(db, user, "hs_review", "product", p.id, f"{p.sku}: {before} -> {p.hs_code or '-'} {p.hs_status}")
    db.commit()
    db.refresh(p)
    return _out(p, False, set(db.scalars(select(HSCode.code))))


@router.post("/products/import")
async def import_products(file: UploadFile, user: Admin, db: DB):
    ratelimit.hit(f"upload:{user.id}", 10)
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

    result = apply_catalogue(db, df)
    audit.record(
        db,
        user,
        "import",
        "product",
        "",
        f"{file.filename}: {result['created']} created, {result['updated']} updated, {len(result['errors'])} errors",
    )
    db.commit()
    return result


def _net_quantity(raw: str) -> float | None:
    try:
        v = float(raw)
    except ValueError:
        return None
    return v if v > 0 else None


def apply_catalogue(db: Session, df: pd.DataFrame) -> dict:
    """Create or update products from a catalogue table; rows are validated one by one."""
    df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]
    missing = REQUIRED - set(df.columns)
    if missing:
        raise HTTPException(422, f"Missing required column(s): {', '.join(sorted(missing))}.")

    valid_hs = set(db.scalars(select(HSCode.code)))
    created = updated = 0
    errors: list[dict] = []
    seen: set[str] = set()
    for i, row in df.fillna("").astype(str).iterrows():
        line = int(i) + 2  # header is line 1
        sku, pname, hs = row["sku"].strip(), row["name"].strip(), normalize_hs(row.get("hs_code", ""))
        if not sku or not pname:
            errors.append({"line": line, "error": "sku and name are required"})
            continue
        if sku in seen:
            errors.append({"line": line, "error": f"duplicate SKU '{sku}' in file"})
            continue
        if hs and hs not in valid_hs:
            errors.append({"line": line, "error": f"invalid HS code '{row['hs_code']}'"})
            continue
        seen.add(sku)
        fields = {"name": pname[:255], "hs_code": hs or None}
        fields.update({c: row[c].strip() for c in TEXT_COLUMNS if c in row})
        if "client_hs_code" in fields:
            fields["client_hs_code"] = re.sub(r"\D", "", fields["client_hs_code"])[:14]
        if "manufacturing_country" in fields:
            fields["manufacturing_country"] = fields["manufacturing_country"].upper()[:3]
        if "net_quantity" in row:
            fields["net_quantity"] = _net_quantity(row["net_quantity"].strip())
        status = row.get("hs_status", "").strip().lower().replace("suggested", "candidate")
        if status in HS_STATUSES:
            fields["hs_status"] = status
        if not hs:
            fields["hs_status"] = HsStatus.unmapped
        p = db.scalar(select(Product).where(Product.sku == sku))
        if p and p.client_hs_code and fields.get("client_hs_code", p.client_hs_code) != p.client_hs_code:
            errors.append(
                {
                    "line": line,
                    "error": f"client HS code for '{sku}' differs from the one on file; it is kept unchanged",
                }
            )
            fields.pop("client_hs_code")
        if p and p.hs_code != fields["hs_code"] and fields.get("hs_status") == HsStatus.confirmed:
            fields["hs_status"] = HsStatus.candidate  # a changed code must be confirmed again
        elif p and p.hs_code != fields["hs_code"] and "hs_status" not in fields:
            fields["hs_status"] = HsStatus.candidate
        if p:
            for k, v in fields.items():
                setattr(p, k, v)
            updated += 1
        else:
            db.add(Product(sku=sku, **fields))
            created += 1
    db.commit()
    return {"created": created, "updated": updated, "errors": errors}
