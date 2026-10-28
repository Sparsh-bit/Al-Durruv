"""Idempotent seed: HS6 reference list, first admin user, the product catalogue and client setup data.

Run: uv run python -m app.seed
     uv run python -m app.seed --replace-products   # also delete products not in the catalogue file
"""

import argparse
import contextlib
import io
from pathlib import Path

import comtradeapicall
import pandas as pd
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert

from app.config import get_settings
from app.db import SessionLocal
from app.models import Country, HSCode, Product, Role, User
from app.routers.catalogue import apply_catalogue
from app.security import hash_password
from app.services import client_data

CATALOGUE = Path(__file__).parent.parent / "data" / "durra_catalogue.csv"


def load_hs_codes(db) -> int:
    with contextlib.redirect_stdout(io.StringIO()):
        df = comtradeapicall.getReference("cmd:HS")
    if df is None:
        raise SystemExit("Could not download the HS reference list from UN Comtrade.")
    six = df[df["id"].str.len() == 6]
    rows = [{"code": r.id, "description": r.text.split(" - ", 1)[-1]} for r in six.itertuples()]
    stmt = insert(HSCode).values(rows)
    db.execute(stmt.on_conflict_do_update(index_elements=["code"], set_={"description": stmt.excluded.description}))
    return len(rows)


def load_countries(db) -> int:
    """Comtrade's country list (several M49 codes can share an ISO3, e.g. USA 840/842)."""
    with contextlib.redirect_stdout(io.StringIO()):
        df = comtradeapicall.getReference("partner")
    if df is None:
        print("Could not download the Comtrade country list; countries load with trade data instead.")
        return 0
    current = df["entryExpiredDate"].isna()  # drop historical entries such as "Fed. Rep. of Germany (...1990)"
    df = df[current & (~df["isGroup"].astype(bool)) & df["PartnerCodeIsoAlpha3"].fillna("").str.fullmatch(r"[A-Z]{3}")]
    rows = [
        {"m49": int(r.PartnerCode), "iso3": r.PartnerCodeIsoAlpha3, "name": str(r.PartnerDesc).strip()}
        for r in df.itertuples()
        if int(r.PartnerCode) != 0
    ]
    db.execute(insert(Country).values(rows).on_conflict_do_nothing())
    return len(rows)


def main(replace_products: bool = False) -> None:
    s = get_settings()
    with SessionLocal() as db:
        if db.scalar(select(func.count()).select_from(HSCode)) > 6000:
            print("HS reference list already loaded.")
        else:
            print(f"HS codes loaded: {load_hs_codes(db)}")
        if db.scalar(select(func.count()).select_from(Country)) < 200:
            print(f"Countries loaded: {load_countries(db)}")
        if not db.scalar(select(User).where(User.role == Role.admin)):
            if len(s.admin_password) < 8:
                raise SystemExit("Set ADMIN_PASSWORD (8+ characters) before seeding.")
            db.add(
                User(
                    email=s.admin_email.lower(),
                    full_name="Administrator",
                    password_hash=hash_password(s.admin_password),
                    role=Role.admin,
                )
            )
            print(f"Admin user created: {s.admin_email}")
        db.commit()
        if db.scalar(select(Product.id).limit(1)) and not replace_products:
            print("Products already exist; catalogue not re-imported (use --replace-products to sync).")
        else:
            df = pd.read_csv(CATALOGUE, dtype=str, keep_default_na=False)
            if replace_products:
                keep = df["sku"].tolist() + client_data.client_list_skus()
                gone = db.execute(delete(Product).where(Product.sku.not_in(keep)))
                print(f"Removed {gone.rowcount} products not in the catalogue.")
            result = apply_catalogue(db, df)
            print(
                f"Catalogue: {result['created']} created, {result['updated']} updated, {len(result['errors'])} errors."
            )
            for e in result["errors"]:
                print(f"  line {e['line']}: {e['error']}")
        print(f"Client data: {client_data.apply(db)}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--replace-products", action="store_true", help="delete products that are not in the catalogue")
    main(ap.parse_args().replace_products)
