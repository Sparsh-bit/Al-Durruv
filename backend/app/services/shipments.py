"""Shipment (bill-of-lading) file imports and company entity resolution.

Files come from licensed providers (ImportGenius, Panjiva, Volza) as CSV/XLSX. A provider adapter is just a
saved column mapping, so an API-based provider can later write the same rows without schema changes.
Only cell values are read (no formulas are evaluated).
"""

import difflib
import hashlib
import io
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date

import pandas as pd
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import Company, ImportBatch, Shipment
from app.services import settings

MAX_BYTES = 15 * 1024 * 1024
MAX_ROWS = 200_000
FIELDS = {
    "shipped_on": "Arrival or shipment date",
    "shipper_name": "Shipper / exporter",
    "consignee_name": "Consignee / importer",
    "origin": "Origin country",
    "destination": "Destination country",
    "hs_code": "HS code as filed",
    "product_description": "Product description",
    "weight_kg": "Weight (kg)",
    "quantity": "Quantity",
    "value_usd": "Value (USD)",
    "port_of_lading": "Port of lading",
    "port_of_unlading": "Port of unlading",
    "carrier": "Carrier",
    "record_id": "Provider record id",
}
REQUIRED = ("shipped_on",)
SYNONYMS = {
    "shipped_on": ["arrival date", "actual arrival date", "date", "shipment date", "bill of lading date", "b/l date"],
    "shipper_name": ["shipper", "shipper name", "exporter", "supplier", "shipper declared"],
    "consignee_name": ["consignee", "consignee name", "importer", "buyer"],
    "origin": ["country of origin", "origin country", "origin", "shipper country", "foreign country"],
    "destination": ["destination country", "destination", "consignee country", "importer country"],
    "hs_code": ["hs code", "hs", "harmonized code", "hts code", "commodity code"],
    "product_description": ["product description", "description", "goods description", "commodity"],
    "weight_kg": ["weight (kg)", "weight kg", "gross weight (kg)", "weight", "net weight"],
    "quantity": ["quantity", "qty"],
    "value_usd": ["value (usd)", "value usd", "declared value", "value"],
    "port_of_lading": ["port of lading", "foreign port", "loading port"],
    "port_of_unlading": ["port of unlading", "us port", "discharge port", "unloading port"],
    "carrier": ["carrier", "carrier name", "vessel"],
    "record_id": ["record id", "bill of lading number", "bol number", "master bill of lading", "id"],
}
LEGAL_SUFFIXES = (
    "LLC L L C INC INCORPORATED CORP CORPORATION CO COMPANY LTD LIMITED SARL S A L SAL SA S A FZE FZCO FZ LLC "
    "GMBH BV B V NV PLC LLP LP PTE PVT PRIVATE SPA SRL AG AB AS OY KG CIE TRADING EST ESTABLISHMENT"
).split()


def normalize_name(name: str) -> str:
    """Upper-case, strip accents and punctuation, unify '&'/AND and Arabic article variants, drop legal suffixes."""
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().upper()
    s = s.replace("&", " AND ")
    s = re.sub(r"[^A-Z0-9 ]+", " ", s)
    words = s.split()
    words = ["AL" if w in ("EL", "AL") else w for w in words]
    if len(words) > 1 and words[0] == "THE":
        words = words[1:]
    while words and words[-1] in LEGAL_SUFFIXES:
        words.pop()
    s = " ".join(words)
    return re.sub(r"\bAL (?=[A-Z])", "AL", s)  # "AL DURRA" == "ALDURRA"


def similar_companies(db: Session, company: Company, threshold: float = 0.82, limit: int = 8) -> list[dict]:
    """Merge suggestions only; nothing is merged automatically."""
    out = []
    for c in db.scalars(select(Company).where(Company.id != company.id)):
        ratio = difflib.SequenceMatcher(None, company.normalized_name, c.normalized_name).ratio()
        if ratio >= threshold:
            out.append({"id": c.id, "name": c.name, "country_iso3": c.country_iso3, "similarity": round(ratio, 3)})
    return sorted(out, key=lambda x: -x["similarity"])[:limit]


def resolve_company(db: Session, name: str, country_iso3: str, role: str, cache: dict) -> Company | None:
    """Exact match on normalised name or alias; otherwise a new unverified company. Never fuzzy-merges."""
    norm = normalize_name(name)
    if not norm:
        return None
    key = (norm, country_iso3)
    if key in cache:
        return cache[key]
    c = db.scalar(select(Company).where(Company.normalized_name == norm, Company.country_iso3 == country_iso3))
    if not c:
        c = db.scalar(select(Company).where(Company.normalized_name == norm))
    if not c:
        c = next((a for a in _with_aliases(db, cache) if norm in {normalize_name(x) for x in a.aliases}), None)
    if not c:
        c = Company(
            name=name.strip()[:255],
            normalized_name=norm,
            country_iso3=country_iso3,
            relationship_type="buyer" if role == "consignee" else "supplier",
            roles=["importer"] if role == "consignee" else ["exporter"],
            summary="Created from shipment records.",
            identity_status="unverified",
        )
        db.add(c)
        db.flush()
    cache[key] = c
    return c


def _with_aliases(db: Session, cache: dict) -> list[Company]:
    if "__aliased" not in cache:
        cache["__aliased"] = list(db.scalars(select(Company).where(Company.aliases != [])))
    return cache["__aliased"]


def backfill_normalized(db: Session) -> int:
    """Recompute stored normalised names (cheap; keeps them in step with normalize_name)."""
    changed = 0
    for c in db.scalars(select(Company)):
        n = normalize_name(c.name)
        if c.normalized_name != n:
            c.normalized_name, changed = n, changed + 1
    return changed


def read_table(data: bytes, filename: str) -> pd.DataFrame:
    if len(data) > MAX_BYTES:
        raise ValueError("File is larger than 15 MB.")
    name = filename.lower()
    if name.endswith((".xlsx", ".xls")):
        df = pd.read_excel(io.BytesIO(data), dtype=str)  # cached cell values only; formulas are not evaluated
    elif name.endswith(".csv"):
        df = pd.read_csv(io.BytesIO(data), dtype=str, encoding_errors="replace", on_bad_lines="error")
    else:
        raise ValueError("Upload a .csv or .xlsx file.")
    if len(df) > MAX_ROWS:
        raise ValueError(f"File has {len(df):,} rows; the limit is {MAX_ROWS:,} per upload.")
    df.columns = [str(c).strip() for c in df.columns]
    return df.fillna("")


def suggest_mapping(columns: list[str], provider: str, db: Session) -> dict[str, str]:
    saved = (settings.get_raw(db, "shipment_mappings") or {}).get(provider)
    if saved and all(v in columns for v in saved.values()):
        return saved
    lower = {c.lower().strip(): c for c in columns}
    out = {}
    for f, names in SYNONYMS.items():
        for n in names:
            if n in lower:
                out[f] = lower[n]
                break
    return out


def _num(v: str) -> float | None:
    v = re.sub(r"[,\s$]", "", v or "")
    try:
        x = float(v)
    except ValueError:
        return None
    return x if x >= 0 else None


def _date(v: str) -> date | None:
    v = (v or "").strip()
    if not v:
        return None
    try:
        d = pd.to_datetime(v, dayfirst=False, errors="raise")
    except (ValueError, OverflowError):
        return None
    return d.date()


@dataclass
class Parsed:
    rows: list[dict] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)


def parse_rows(df: pd.DataFrame, mapping: dict[str, str], countries: dict[str, str]) -> Parsed:
    missing = [f for f in REQUIRED if f not in mapping]
    if missing or not ({"shipper_name", "consignee_name"} & mapping.keys()):
        raise ValueError("Map at least the date column and a shipper or consignee column.")
    out = Parsed()
    for i, r in enumerate(df.to_dict("records")):
        line = i + 2

        def get(f: str, r=r) -> str:
            return str(r.get(mapping[f], "")).strip() if f in mapping else ""

        d = _date(get("shipped_on"))
        if not d:
            out.errors.append({"line": line, "error": f"unreadable date '{get('shipped_on')}'"})
            continue
        shipper, consignee = get("shipper_name"), get("consignee_name")
        if not shipper and not consignee:
            out.errors.append({"line": line, "error": "no shipper or consignee name"})
            continue
        origin, dest = get("origin"), get("destination")
        o3 = countries.get(origin.upper(), "") if origin else ""
        d3 = countries.get(dest.upper(), "") if dest else ""
        if origin and not o3:
            out.errors.append({"line": line, "error": f"unknown origin country '{origin}' (row kept, origin blank)"})
        hs = re.sub(r"\D", "", get("hs_code"))[:12]
        row = {
            "shipped_on": d,
            "shipper_name": shipper[:500],
            "consignee_name": consignee[:500],
            "origin_iso3": o3,
            "destination_iso3": d3,
            "hs_code": hs,
            "hs6": hs[:6] if len(hs) >= 6 else "",
            "product_description": get("product_description")[:2000],
            "weight_kg": _num(get("weight_kg")),
            "quantity": _num(get("quantity")),
            "value_usd": _num(get("value_usd")),
            "port_of_lading": get("port_of_lading")[:200],
            "port_of_unlading": get("port_of_unlading")[:200],
            "carrier": get("carrier")[:200],
        }
        rid = get("record_id")
        row["row_key"] = rid[:80] if rid else hashlib.sha1(repr(sorted(row.items())).encode()).hexdigest()
        out.rows.append(row)
    return out


def country_lookup(db: Session) -> dict[str, str]:
    from app.routers.client import country_index

    _names, lookup = country_index(db)
    out = {k.upper(): v for k, v in lookup.items()}
    for alias, iso in COUNTRY_ALIASES.items():
        out.setdefault(alias, iso)
    return out


# Names shipment providers commonly use that differ from the UN Comtrade spelling.
COUNTRY_ALIASES = {
    "TURKEY": "TUR",
    "UNITED STATES": "USA",
    "UNITED STATES OF AMERICA": "USA",
    "US": "USA",
    "U.S.A.": "USA",
    "UK": "GBR",
    "UNITED KINGDOM": "GBR",
    "GREAT BRITAIN": "GBR",
    "SOUTH KOREA": "KOR",
    "KOREA": "KOR",
    "RUSSIA": "RUS",
    "VIETNAM": "VNM",
    "VIET NAM": "VNM",
    "IRAN": "IRN",
    "SYRIA": "SYR",
    "UAE": "ARE",
    "UNITED ARAB EMIRATES": "ARE",
    "CZECH REPUBLIC": "CZE",
    "HOLLAND": "NLD",
    "TAIWAN": "TWN",
}


def import_rows(db: Session, batch: ImportBatch, parsed: Parsed) -> ImportBatch:
    cache: dict = {}
    values = []
    for r in parsed.rows:
        shipper = (
            resolve_company(db, r["shipper_name"], r["origin_iso3"], "shipper", cache) if r["shipper_name"] else None
        )
        consignee = (
            resolve_company(db, r["consignee_name"], r["destination_iso3"], "consignee", cache)
            if r["consignee_name"]
            else None
        )
        values.append(
            {
                **r,
                "provider": batch.provider,
                "shipper_company_id": shipper.id if shipper else None,
                "consignee_company_id": consignee.id if consignee else None,
                "import_batch_id": batch.id,
            }
        )
    inserted = 0
    for i in range(0, len(values), 1000):
        stmt = (
            insert(Shipment).values(values[i : i + 1000]).on_conflict_do_nothing(index_elements=["provider", "row_key"])
        )
        inserted += len(db.execute(stmt.returning(Shipment.id)).all())
    batch.row_count = len(parsed.rows) + sum(1 for e in parsed.errors if "row kept" not in e["error"])
    batch.inserted = inserted
    batch.duplicates = len(values) - inserted
    batch.errors = parsed.errors[:500]
    batch.status = "completed"
    return batch
