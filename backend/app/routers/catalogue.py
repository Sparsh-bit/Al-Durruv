import io
import re
from typing import Literal

import pandas as pd
from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import HSCode, Product, TradeObservation
from app.security import DB, Analyst, CurrentUser
from app.services import audit

router = APIRouter(prefix="/api", tags=["catalogue"])
MAX_UPLOAD = 5 * 1024 * 1024
REQUIRED = {"sku", "name", "hs_code"}
TEXT_COLUMNS = (
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
    "brand",
    "category",
    "hs_code",
    "hs_status",
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


class ProductIn(BaseModel):
    sku: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    hs_code: str
    hs_status: Literal["suggested", "confirmed"] = "suggested"
    hs_note: str = Field("", max_length=2000)
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
    def _hs(cls, v: str) -> str:
        code = normalize_hs(v)
        if len(code) != 6:
            raise ValueError("HS code must have at least 6 digits")
        return code


def pages(p: Product) -> list[int]:
    return [int(x) for x in re.findall(r"\d+", p.catalogue_page or "")]


def _out(p: Product, has_data: bool = False) -> dict:
    return {
        "id": p.id,
        "sku": p.sku,
        "name": p.name,
        "brand": p.brand,
        "description": p.description,
        "category": p.category,
        "pack_size": p.pack_size,
        "net_quantity": p.net_quantity,
        "net_unit": p.net_unit,
        "packaging": p.packaging,
        "catalogue_page": p.catalogue_page,
        "catalogue_pages": pages(p),
        "notes": p.notes,
        "hs_code": p.hs_code,
        "hs_status": p.hs_status,
        "hs_note": p.hs_note,
        "hs_description": p.hs.description if p.hs else "",
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
    stmt = select(Product).order_by(Product.category, Product.name, Product.net_quantity)
    return [_out(p, p.hs_code in with_data) for p in db.scalars(stmt)]


@router.get("/products/export")
def export_products(_: CurrentUser, db: DB):
    rows = [{c: getattr(p, c) for c in EXPORT_COLUMNS} for p in db.scalars(select(Product).order_by(Product.sku))]
    csv = pd.DataFrame(rows, columns=EXPORT_COLUMNS).to_csv(index=False)
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
    return _out(p, has)


def _check_hs(db, code: str) -> None:
    if not db.get(HSCode, code):
        raise HTTPException(422, f"HS code {code} is not a valid HS6 code in the UN Comtrade classification.")


@router.post("/products", status_code=201)
def create_product(body: ProductIn, user: Analyst, db: DB):
    _check_hs(db, body.hs_code)
    if db.scalar(select(Product).where(Product.sku == body.sku)):
        raise HTTPException(409, f"SKU {body.sku} already exists.")
    p = Product(**body.model_dump())
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
    _check_hs(db, body.hs_code)
    clash = db.scalar(select(Product).where(Product.sku == body.sku, Product.id != product_id))
    if clash:
        raise HTTPException(409, f"SKU {body.sku} already exists.")
    changed = [k for k, v in body.model_dump().items() if getattr(p, k) != v]
    for k, v in body.model_dump().items():
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


@router.post("/products/import")
async def import_products(file: UploadFile, user: Analyst, db: DB):
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
        sku, pname, hs = row["sku"].strip(), row["name"].strip(), normalize_hs(row["hs_code"])
        if not sku or not pname:
            errors.append({"line": line, "error": "sku and name are required"})
            continue
        if sku in seen:
            errors.append({"line": line, "error": f"duplicate SKU '{sku}' in file"})
            continue
        if hs not in valid_hs:
            errors.append({"line": line, "error": f"invalid HS code '{row['hs_code']}'"})
            continue
        seen.add(sku)
        fields = {"name": pname[:255], "hs_code": hs}
        fields.update({c: row[c].strip() for c in TEXT_COLUMNS if c in row})
        if "net_quantity" in row:
            fields["net_quantity"] = _net_quantity(row["net_quantity"].strip())
        if row.get("hs_status", "").strip().lower() in ("suggested", "confirmed"):
            fields["hs_status"] = row["hs_status"].strip().lower()
        p = db.scalar(select(Product).where(Product.sku == sku))
        if p and p.hs_code != hs and "hs_status" not in fields:
            fields["hs_status"] = "suggested"  # a changed code is no longer the confirmed one
        if p:
            for k, v in fields.items():
                setattr(p, k, v)
            updated += 1
        else:
            db.add(Product(sku=sku, **fields))
            created += 1
    db.commit()
    return {"created": created, "updated": updated, "errors": errors}
