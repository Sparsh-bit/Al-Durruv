"""Admin-editable settings stored in the database, with defaults.

The company profile defaults come from the client's catalogue (Durra Products Profile 2023) and are
editable in Administration.
"""

from datetime import UTC, datetime

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AppSetting

DEFAULTS: dict = {
    "company_profile": {
        "name": "ALDurra Food Products Co.",
        "brand": "Durra",
        "country_iso3": "SYR",
        "founded": "1979",
        "description": "Manufacturer and exporter of preserved and packaged Middle Eastern foods: jams, olives, "
        "pickles, canned beans and hummus, tahina and halawa, syrups, sauces, spices, pasta, oils and Arabic "
        "sweets. Offers private-label manufacturing.",
        "label_languages": ["Arabic", "English", "French", "German", "Swedish"],
        "certifications": ["Halal (meat products)"],
    },
    "export_markets": [],  # ISO3 codes of countries the client already exports to
    "ai_monthly_budget_usd": 20.0,
}


def get(db: Session, key: str):
    row = db.get(AppSetting, key)
    if row is not None and row.value is not None:
        return row.value
    if key == "company_profile" and get_settings().home_country_iso3:
        return {**DEFAULTS[key], "country_iso3": get_settings().home_country_iso3.upper()}
    return DEFAULTS[key]


def put(db: Session, key: str, value) -> None:
    stmt = insert(AppSetting).values(key=key, value=value, updated_at=datetime.now(UTC))
    db.execute(
        stmt.on_conflict_do_update(
            index_elements=["key"], set_={"value": value, "updated_at": stmt.excluded.updated_at}
        )
    )


def home_country(db: Session) -> str:
    return (get(db, "company_profile").get("country_iso3") or "").upper()
