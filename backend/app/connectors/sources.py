"""Connectors for official sources, each verified against a live call (see docs/DECISIONS.md D6-D10).

FX (Frankfurter/ECB) · Eurostat Comext DS-045409 (monthly CN8) · US Census intltrade/imports/hs (monthly HS10)
· WITS/UNCTAD TRAINS tariffs · USITC HTS duty rates.
"""

import contextlib
import io
import re
from datetime import UTC, date, datetime
from functools import lru_cache
from statistics import mean

import comtradeapicall
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.config import get_settings
from app.connectors.http import ConnectorError, NoData, fetch_cached, source_record
from app.models import Country, FxRate, MonthlyFlow, Tariff

FRANKFURTER = "https://api.frankfurter.dev/v1"
COMEXT = "https://ec.europa.eu/eurostat/api/comext/dissemination/statistics/1.0/data/DS-045409"
CENSUS = "https://api.census.gov/data/timeseries/intltrade/imports/hs"
WITS = "https://wits.worldbank.org/API/V1/SDMX/V21/datasource/TRN"
USITC = "https://hts.usitc.gov/reststop/search"

EU_WITS_CODE = "918"
# ISO numeric codes differ from Comtrade's reporter codes for a few countries
ISO_NUMERIC_OVERRIDES = {"USA": "840", "FRA": "250", "NOR": "578", "CHE": "756", "IND": "356"}
# USITC "special" column program indicator per origin (US-Jordan FTA). Egypt and Syria have none.
US_PROGRAM_CODES = {"JOR": "JO"}
COMEXT_AGGREGATES = {"WORLD": "WLD", "EXT_EU27_2020": "XEU"}  # world total; imports from outside the EU
EU27 = ("AT BE BG HR CY CZ DK EE FI FR DE GR HU IE IT LV LT LU MT NL PL PT RO SK SI ES SE").split()


# --- reference ------------------------------------------------------------------------------------


@lru_cache(maxsize=1)
def iso2_to_iso3() -> dict[str, str]:
    with contextlib.redirect_stdout(io.StringIO()):
        df = comtradeapicall.getReference("partner")
    if df is None:
        return {}
    df = df[df["entryExpiredDate"].isna()].dropna(subset=["PartnerCodeIsoAlpha2", "PartnerCodeIsoAlpha3"])
    return {r.PartnerCodeIsoAlpha2: r.PartnerCodeIsoAlpha3 for r in df.itertuples()}


def iso_numeric(db: Session, iso3: str) -> str:
    if iso3 == "EUN":
        return EU_WITS_CODE
    if iso3 in ISO_NUMERIC_OVERRIDES:
        return ISO_NUMERIC_OVERRIDES[iso3]
    codes = sorted(c.m49 for c in db.scalars(select(Country).where(Country.iso3 == iso3)))
    if not codes:
        raise ConnectorError(f"Unknown country {iso3}.")
    return f"{codes[0]:03d}"


def name_to_iso3(db: Session) -> dict[str, str]:
    out = {}
    for c in db.scalars(select(Country)):
        if c.iso3 and len(c.iso3) == 3 and c.iso3.isalpha():
            out[c.name.strip().upper()] = c.iso3
    return out


# --- FX ---------------------------------------------------------------------------------------------


def load_fx(db: Session, start: date, end: date, base: str = "EUR", quote: str = "USD") -> int:
    payload, _ = fetch_cached(
        db,
        "frankfurter",
        f"{FRANKFURTER}/{start.isoformat()}..{end.isoformat()}",
        {"base": base, "symbols": quote},
        ttl_hours=24 * 30,
    )
    rows = [
        {"day": date.fromisoformat(d), "base": base, "quote": quote, "rate": float(r[quote])}
        for d, r in parse_fx(payload, quote).items()
    ]
    if rows:
        stmt = insert(FxRate).values(rows)
        db.execute(
            stmt.on_conflict_do_update(index_elements=["day", "base", "quote"], set_={"rate": stmt.excluded.rate})
        )
    return len(rows)


def parse_fx(payload: dict, quote: str) -> dict[str, dict]:
    return {d: r for d, r in (payload.get("rates") or {}).items() if quote in r}


def monthly_rate(db: Session, period: str, base: str = "EUR", quote: str = "USD") -> float | None:
    y, m = map(int, period.split("-"))
    start, end = date(y, m, 1), date(y + (m == 12), m % 12 + 1, 1)
    rates = db.scalars(
        select(FxRate.rate).where(FxRate.base == base, FxRate.quote == quote, FxRate.day >= start, FxRate.day < end)
    ).all()
    return mean(rates) if rates else None


# --- Eurostat Comext --------------------------------------------------------------------------------


def parse_jsonstat(payload: dict) -> list[dict]:
    """Flatten a JSON-stat 2.0 dataset into one dict per observed cell."""
    ids, sizes = payload["id"], payload["size"]
    cats = []
    for dim in ids:
        index = payload["dimension"][dim]["category"]["index"]
        labels = payload["dimension"][dim]["category"].get("label", {})
        ordered = sorted(index, key=index.get)
        cats.append([(code, labels.get(code, code)) for code in ordered])
    strides = [1] * len(sizes)
    for i in range(len(sizes) - 2, -1, -1):
        strides[i] = strides[i + 1] * sizes[i + 1]
    out = []
    for flat, value in payload.get("value", {}).items():
        n, cell = int(flat), {}
        for dim, stride, options in zip(ids, strides, cats, strict=True):
            code, label = options[(n // stride) % len(options)]
            cell[dim], cell[f"{dim}_label"] = code, label
        cell["value"] = value
        out.append(cell)
    return out


def comext_rows(payload: dict, iso2: dict[str, str]) -> list[dict]:
    """Group JSON-stat cells into one row per reporter x partner x product x month, EUR value and kg."""
    rows: dict[tuple, dict] = {}
    for c in parse_jsonstat(payload):
        partner = COMEXT_AGGREGATES.get(c["partner"], iso2.get(c["partner"], ""))
        if not partner and not (len(c["partner"]) == 2 and c["partner"].isalpha()):
            continue  # other aggregates (euro area, intra-EU)
        key = (c["reporter"], c["partner"], c["product"], c["time"])
        r = rows.setdefault(
            key,
            {
                "reporter_iso3": iso2.get(c["reporter"], ""),
                "partner_iso3": partner,
                "partner_name": c["partner_label"],
                "product_code": c["product"],
                "period": c["time"],
                "value_eur": None,
                "kg": None,
            },
        )
        if c["indicators"] == "VALUE_IN_EUROS":
            r["value_eur"] = float(c["value"])
        elif c["indicators"] == "QUANTITY_IN_100KG":
            r["kg"] = float(c["value"]) * 100
    return [r for r in rows.values() if r["reporter_iso3"] and r["value_eur"] is not None]


def load_comext(db: Session, hs: str, reporters_iso3: list[str], months: list[str], partners_iso3=None) -> int:
    iso2 = iso2_to_iso3()
    to_iso2 = {v: k for k, v in iso2.items()}
    params = [
        ("format", "JSON"),
        ("lang", "en"),
        ("freq", "M"),
        ("product", hs),
        ("flow", "1"),
        ("indicators", "VALUE_IN_EUROS"),
        ("indicators", "QUANTITY_IN_100KG"),
    ]
    params += [("reporter", to_iso2[r]) for r in reporters_iso3 if r in to_iso2]
    params += [("partner", to_iso2[p]) for p in partners_iso3 or [] if p in to_iso2]
    params += [("time", m) for m in months]
    payload, _ = fetch_cached(db, "comext", COMEXT, dict(_group(params)), ttl_hours=24 * 7)
    rows = comext_rows(payload, iso2)
    src = source_record(
        db,
        "comext",
        COMEXT,
        dict(_group(params)),
        f"Eurostat Comext DS-045409 CN/HS {hs}",
        f"{months[0]}..{months[-1]}",
        "Eurostat, free re-use with acknowledgement (Commission Decision 2011/833/EU)",
    )
    for start, end in [(min(r["period"] for r in rows), max(r["period"] for r in rows))] if rows else []:
        y0, m0 = map(int, start.split("-"))
        y1, m1 = map(int, end.split("-"))
        load_fx(db, date(y0, m0, 1), date(y1, m1, 28))
    out = []
    for r in rows:
        fx = monthly_rate(db, r["period"])
        out.append(
            {
                "source": "comext",
                "reporter_iso3": r["reporter_iso3"],
                "partner_iso3": r["partner_iso3"],
                "partner_name": r["partner_name"],
                "hs6": hs[:6],
                "product_code": r["product_code"],
                "flow": "M",
                "period": r["period"],
                "value_native": r["value_eur"],
                "currency": "EUR",
                "fx_rate": fx,
                "value_usd": r["value_eur"] * fx if fx else None,
                "net_weight_kg": r["kg"],
                "quantity": None,
                "unit": "kg",
                "source_record_id": src.id,
            }
        )
    return _upsert_monthly(db, out)


def _group(pairs):
    out: dict[str, list] = {}
    for k, v in pairs:
        out.setdefault(k, []).append(v)
    return {k: v if len(v) > 1 else v[0] for k, v in out.items()}


def _upsert_monthly(db: Session, rows: list[dict]) -> int:
    if not rows:
        return 0
    for i in range(0, len(rows), 1000):
        stmt = insert(MonthlyFlow).values(rows[i : i + 1000])
        cols = ("value_usd", "value_native", "fx_rate", "net_weight_kg", "quantity", "unit", "source_record_id")
        db.execute(
            stmt.on_conflict_do_update(
                index_elements=[
                    "source",
                    "reporter_iso3",
                    "partner_iso3",
                    "partner_name",
                    "product_code",
                    "flow",
                    "period",
                ],
                set_={c: stmt.excluded[c] for c in cols},
            )
        )
    return len(rows)


# --- US Census --------------------------------------------------------------------------------------

CENSUS_FIELDS = "CTY_CODE,CTY_NAME,I_COMMODITY,GEN_VAL_MO,GEN_QY1_MO,UNIT_QY1,AIR_WGT_MO,VES_WGT_MO"


def census_rows(payload: list[list[str]], names: dict[str, str]) -> list[dict]:
    """Census returns a header row then data rows. Keep countries and the all-countries total; drop region
    groupings (codes starting with 0)."""
    if not payload:
        return []
    head, out = payload[0], []
    for raw in payload[1:]:
        r = dict(zip(head, raw, strict=False))
        code, name = r.get("CTY_CODE", ""), (r.get("CTY_NAME") or "").strip()
        if code.startswith("0"):
            continue
        total = code == "-" or name.upper().startswith("TOTAL")
        weight = sum(float(r.get(k) or 0) for k in ("AIR_WGT_MO", "VES_WGT_MO")) or None
        out.append(
            {
                "partner_iso3": "WLD" if total else names.get(name.upper(), ""),
                "partner_name": "World" if total else name.title(),
                "product_code": r.get("I_COMMODITY", ""),
                "period": r.get("time", ""),
                "value_usd": float(r["GEN_VAL_MO"]) if r.get("GEN_VAL_MO") not in (None, "") else None,
                "quantity": float(r["GEN_QY1_MO"]) if r.get("GEN_QY1_MO") not in (None, "") else None,
                "unit": r.get("UNIT_QY1") or "",
                "kg": weight,
            }
        )
    return out


def load_census(db: Session, hs: str, months: list[str]) -> int:
    key = get_settings().census_api_key
    if not key:
        raise ConnectorError("US Census needs CENSUS_API_KEY (free at api.census.gov/data/key_signup.html).")
    lvl = {6: "HS6", 8: "HS8", 10: "HS10"}.get(len(hs), "HS6")
    names, total = name_to_iso3(db), 0
    for month in months:
        params = {"get": CENSUS_FIELDS, "I_COMMODITY": hs, "COMM_LVL": lvl, "time": month, "key": key}
        try:
            payload, _ = fetch_cached(db, "census", CENSUS, params, ttl_hours=24 * 7, not_found_is_empty=True)
        except NoData:
            continue
        src = source_record(
            db, "census", CENSUS, params, f"US Census imports HS {hs}", month, "U.S. Census Bureau, public domain"
        )
        rows = [
            {
                "source": "census",
                "reporter_iso3": "USA",
                "partner_iso3": r["partner_iso3"],
                "partner_name": r["partner_name"],
                "hs6": hs[:6],
                "product_code": r["product_code"],
                "flow": "M",
                "period": month,
                "value_usd": r["value_usd"],
                "value_native": r["value_usd"],
                "currency": "USD",
                "fx_rate": 1.0,
                "net_weight_kg": r["kg"],
                "quantity": r["quantity"],
                "unit": r["unit"],
                "source_record_id": src.id,
            }
            for r in census_rows(payload, names)
        ]
        total += _upsert_monthly(db, rows)
    return total


# --- tariffs ----------------------------------------------------------------------------------------


def wits_rate(payload: dict) -> tuple[float, str] | None:
    """(simple-average ad valorem %, tariff type) from a WITS TRAINS SDMX-JSON response."""
    attrs = payload["structure"]["attributes"]["observation"]
    tt = next(i for i, a in enumerate(attrs) if a["id"] == "TARIFFTYPE")
    for series in payload["dataSets"][0]["series"].values():
        for obs in series["observations"].values():
            if obs[0] is None:
                continue
            idx = obs[tt + 1]
            kind = attrs[tt]["values"][idx]["id"] if attrs[tt]["values"] and idx is not None else str(idx)
            return float(obs[0]), kind
    return None


def load_wits(db: Session, importer_iso3: str, hs6: str, origin_iso3: str = "", year: int | None = None):
    """WITS rate for importer x HS6 (x origin). Without a year, steps back to the latest year with data (MFN);
    with a year (from the MFN lookup), makes exactly one request. Returns (tariff or None, year used)."""
    reporter = iso_numeric(db, importer_iso3)
    partner = iso_numeric(db, origin_iso3) if origin_iso3 else "000"
    this_year = datetime.now(UTC).year
    for y in [year] if year else range(this_year - 1, this_year - 6, -1):
        url = f"{WITS}/reporter/{reporter}/partner/{partner}/product/{hs6}/year/{y}/datatype/reported"
        try:
            payload, _ = fetch_cached(db, "wits", url, {"format": "JSON"}, ttl_hours=24 * 30, not_found_is_empty=True)
        except NoData:
            continue
        found = wits_rate(payload)
        if not found:
            continue
        rate, kind = found
        src = source_record(
            db,
            "wits",
            url,
            {"format": "JSON"},
            f"WITS TRAINS {importer_iso3} HS {hs6}",
            str(y),
            "World Bank WITS / UNCTAD TRAINS",
        )
        t = Tariff(
            importer_iso3=importer_iso3,
            hs_code=hs6,
            origin_iso3=origin_iso3,
            rate_type="preferential" if kind.upper().startswith("PREF") else "MFN",
            ad_valorem_pct=rate,
            data_year=y,
            source="wits",
            source_url=src.url,
            source_record_id=src.id,
            notes="Simple average across national tariff lines in this HS6 (WITS reported data).",
        )
        _replace_tariff(db, t)
        return t, y
    return None, None


def parse_percent(text: str | None) -> float | None:
    if not text:
        return None
    if text.strip().lower().startswith("free"):
        return 0.0
    m = re.fullmatch(r"\s*([\d.]+)\s*%\s*", text)
    return float(m.group(1)) if m else None


def usitc_lines(payload: list[dict], hs6: str) -> list[dict]:
    """Rate-bearing HTS lines under an HS6 (rows whose general column is filled)."""
    prefix = f"{hs6[:4]}.{hs6[4:6]}"
    return [r for r in payload if (r.get("htsno") or "").startswith(prefix) and (r.get("general") or "").strip()]


def load_usitc(db: Session, hs6: str) -> list[Tariff]:
    params = {"keyword": f"{hs6[:4]}.{hs6[4:6]}"}
    payload, _ = fetch_cached(db, "usitc", USITC, params, ttl_hours=24 * 7)
    src = source_record(
        db,
        "usitc",
        USITC,
        params,
        f"USITC HTS {params['keyword']}",
        str(datetime.now(UTC).year),
        "U.S. International Trade Commission, public domain",
    )
    out = []
    for line in usitc_lines(payload, hs6):
        general, special = line["general"], line.get("special") or ""
        base = dict(
            importer_iso3="USA",
            hs_code=line["htsno"].replace(".", "")[:10],
            source="usitc",
            source_url=f"https://hts.usitc.gov/search?query={line['htsno']}",
            source_record_id=src.id,
            agreement="",
            notes=line.get("description", ""),
        )
        mfn = Tariff(
            **base,
            origin_iso3="",
            rate_type="MFN",
            ad_valorem_pct=parse_percent(general),
            specific_rate="" if parse_percent(general) is not None else general,
        )
        _replace_tariff(db, mfn)
        out.append(mfn)
        programs = re.findall(r"[A-Z]{1,2}\+?", special.split("(", 1)[-1]) if "(" in special else []
        for origin, code in US_PROGRAM_CODES.items():
            if code in programs:
                pref = Tariff(
                    **{**base, "agreement": f"US special program {code}"},
                    origin_iso3=origin,
                    rate_type="preferential",
                    ad_valorem_pct=parse_percent(special.split("(")[0]),
                )
                _replace_tariff(db, pref)
                out.append(pref)
    db.flush()
    return out


def _replace_tariff(db: Session, t: Tariff) -> None:
    """Connector rows replace earlier connector rows for the same key; admin overrides are never touched."""
    db.query(Tariff).filter(
        Tariff.importer_iso3 == t.importer_iso3,
        Tariff.hs_code == t.hs_code,
        Tariff.origin_iso3 == t.origin_iso3,
        Tariff.rate_type == t.rate_type,
        Tariff.source == t.source,
    ).delete()
    db.add(t)


def months_between(start: str, end: str) -> list[str]:
    y, m = map(int, start.split("-"))
    y1, m1 = map(int, end.split("-"))
    out = []
    while (y, m) <= (y1, m1):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out
