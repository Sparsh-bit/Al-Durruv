import io
import re

import pandas as pd
from fastapi import APIRouter, HTTPException, UploadFile
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select

from app.models import HSCode, Product, TradeObservation
from app.security import DB, Analyst, CurrentUser

router = APIRouter(prefix="/api", tags=["catalogue"])
MAX_UPLOAD = 5 * 1024 * 1024
REQUIRED = {"sku", "name", "hs_code"}


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
    description: str = ""
    category: str = ""

    @field_validator("hs_code")
    @classmethod
    def _hs(cls, v: str) -> str:
        code = normalize_hs(v)
        if len(code) != 6:
            raise ValueError("HS code must have at least 6 digits")
        return code


def _out(p: Product, has_data: bool = False) -> dict:
    return {
        "id": p.id,
        "sku": p.sku,
        "name": p.name,
        "description": p.description,
        "category": p.category,
        "hs_code": p.hs_code,
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
    return [_out(p, p.hs_code in with_data) for p in db.scalars(select(Product).order_by(Product.name))]


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
def create_product(body: ProductIn, _: Analyst, db: DB):
    _check_hs(db, body.hs_code)
    if db.scalar(select(Product).where(Product.sku == body.sku)):
        raise HTTPException(409, f"SKU {body.sku} already exists.")
    p = Product(**body.model_dump())
    db.add(p)
    db.commit()
    db.refresh(p)
    return _out(p)


@router.put("/products/{product_id}")
def update_product(product_id: int, body: ProductIn, _: Analyst, db: DB):
    p = db.get(Product, product_id)
    if not p:
        raise HTTPException(404, "Product not found.")
    _check_hs(db, body.hs_code)
    clash = db.scalar(select(Product).where(Product.sku == body.sku, Product.id != product_id))
    if clash:
        raise HTTPException(409, f"SKU {body.sku} already exists.")
    for k, v in body.model_dump().items():
        setattr(p, k, v)
    db.commit()
    db.refresh(p)
    return _out(p)


@router.delete("/products/{product_id}", status_code=204)
def delete_product(product_id: int, _: Analyst, db: DB):
    p = db.get(Product, product_id)
    if not p:
        raise HTTPException(404, "Product not found.")
    db.delete(p)
    db.commit()


@router.post("/products/import")
async def import_products(file: UploadFile, _: Analyst, db: DB):
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

    df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]
    missing = REQUIRED - set(df.columns)
    if missing:
        raise HTTPException(422, f"Missing required column(s): {', '.join(sorted(missing))}.")

    valid_hs = set(db.scalars(select(HSCode.code)))
    created = updated = 0
    errors: list[dict] = []
    for i, row in df.fillna("").iterrows():
        line = int(i) + 2  # header is line 1
        sku, pname, hs = str(row["sku"]).strip(), str(row["name"]).strip(), normalize_hs(row["hs_code"])
        if not sku or not pname:
            errors.append({"line": line, "error": "sku and name are required"})
            continue
        if hs not in valid_hs:
            errors.append({"line": line, "error": f"invalid HS code '{row['hs_code']}'"})
            continue
        fields = {
            "name": pname,
            "hs_code": hs,
            "description": str(row.get("description", "")).strip(),
            "category": str(row.get("category", "")).strip(),
        }
        p = db.scalar(select(Product).where(Product.sku == sku))
        if p:
            for k, v in fields.items():
                setattr(p, k, v)
            updated += 1
        else:
            db.add(Product(sku=sku, **fields))
            created += 1
    db.commit()
    return {"created": created, "updated": updated, "errors": errors}
