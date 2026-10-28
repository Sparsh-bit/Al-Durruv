"""Admin-editable settings stored in the database, with neutral defaults.

Client-specific values (company profile, priority categories, regions) are loaded from
data/client_setup.json by the seed and edited in Administration; nothing client-specific lives in code.
"""

from datetime import UTC, datetime

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AppSetting

DEFAULTS: dict = {
    "company_profile": {
        "name": "",
        "brand": "",
        "country_iso3": "",
        "founded": "",
        "description": "",
        "label_languages": [],
        "certifications": [],
    },
    "priority_categories": [],
    "regions": {},  # region name -> ISO3 members
    "region_notes": {},  # region name -> caveat shown in the app (e.g. membership unconfirmed)
    "private_label_weights": {
        "market_size": 30,
        "growth": 20,
        "retailer_presence": 20,
        "private_label_signal": 15,
        "evidence": 15,
    },
    "ai_monthly_budget_usd": 8.0,
}


def get(db: Session, key: str):
    row = db.get(AppSetting, key)
    if row is not None and row.value is not None:
        return row.value
    if key == "company_profile" and get_settings().home_country_iso3:
        return {**DEFAULTS[key], "country_iso3": get_settings().home_country_iso3.upper()}
    return DEFAULTS[key]


def get_raw(db: Session, key: str):
    row = db.get(AppSetting, key)
    return row.value if row is not None else None


def put(db: Session, key: str, value) -> None:
    stmt = insert(AppSetting).values(key=key, value=value, updated_at=datetime.now(UTC))
    db.execute(
        stmt.on_conflict_do_update(
            index_elements=["key"], set_={"value": value, "updated_at": stmt.excluded.updated_at}
        )
    )


def home_country(db: Session) -> str:
    return (get(db, "company_profile").get("country_iso3") or "").upper()
