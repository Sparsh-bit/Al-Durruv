"""Idempotent seed: HS6 reference list, first admin user, the Durra product catalogue.

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
from app.models import HSCode, Product, Role, User
from app.routers.catalogue import apply_catalogue
from app.security import hash_password

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


def main(replace_products: bool = False) -> None:
    s = get_settings()
    with SessionLocal() as db:
        if db.scalar(select(func.count()).select_from(HSCode)) > 6000:
            print("HS reference list already loaded.")
        else:
            print(f"HS codes loaded: {load_hs_codes(db)}")
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
            return
        df = pd.read_csv(CATALOGUE, dtype=str, keep_default_na=False)
        if replace_products:
            gone = db.execute(delete(Product).where(Product.sku.not_in(df["sku"].tolist())))
            print(f"Removed {gone.rowcount} products not in the catalogue.")
        result = apply_catalogue(db, df)
        print(f"Catalogue: {result['created']} created, {result['updated']} updated, {len(result['errors'])} errors.")
        for e in result["errors"]:
            print(f"  line {e['line']}: {e['error']}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--replace-products", action="store_true", help="delete products that are not in the catalogue")
    main(ap.parse_args().replace_products)
