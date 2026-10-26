"""Idempotent seed: HS6 reference list, first admin user, demo products.

Run: uv run python -m app.seed
"""

import contextlib
import io

import comtradeapicall
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.config import get_settings
from app.db import SessionLocal
from app.models import HSCode, Product, Role, User
from app.security import hash_password

DEMO_PRODUCTS = [
    (
        "DEMO-BISC-01",
        "Butter cookies (private label)",
        "190531",
        "Bakery",
        "Sweet biscuits in retail packs; private-label ready.",
    ),
    (
        "DEMO-SOAP-01",
        "Toilet soap bar 100 g",
        "340111",
        "Personal care",
        "Moulded toilet soap bars for retail and hospitality.",
    ),
    (
        "DEMO-SHMP-01",
        "Shampoo 400 ml",
        "330510",
        "Personal care",
        "Hair shampoo in retail bottles; private-label ready.",
    ),
]


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


def main() -> None:
    s = get_settings()
    with SessionLocal() as db:
        print(f"HS codes loaded: {load_hs_codes(db)}")
        if not db.scalar(select(User).where(User.role == Role.admin)):
            if len(s.admin_password) < 10:
                raise SystemExit("Set ADMIN_PASSWORD (10+ characters) in .env before seeding.")
            db.add(
                User(
                    email=s.admin_email.lower(),
                    full_name="Administrator",
                    password_hash=hash_password(s.admin_password),
                    role=Role.admin,
                )
            )
            print(f"Admin user created: {s.admin_email}")
        for sku, name, hs, cat, desc in DEMO_PRODUCTS:
            if not db.scalar(select(Product).where(Product.sku == sku)):
                db.add(Product(sku=sku, name=name, hs_code=hs, category=cat, description=desc))
        db.commit()
        print("Demo products ready.")


if __name__ == "__main__":
    main()
