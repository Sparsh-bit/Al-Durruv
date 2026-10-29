"""WTO Timeseries API v1 tariffs (https://apiportal.wto.org, product "Timeseries API - v1").

Verified 29 Oct 2026 from the portal's API metadata:
* Base https://api.wto.org/timeseries/v1; data at GET /data?i=&r=&pc=&ps=&fmt=json&head=M&max=
* Auth: subscription key in the `Ocp-Apim-Subscription-Key` header (a `subscription-key` query parameter is
  also accepted; we use the header so the key never appears in URLs or logs).
* Tariff indicators still in the API (WTO Stats, 29 Oct 2026): "HS MFN - Simple average ad valorem duty",
  "HS MFN - Maximum ad valorem duty", "HS MFN - Number of NAV tariff lines" (all at HS 2/4/6) and
  "Lowest preferential tariff - simple average ad valorem tariff at HS 6-digit". Indicator and reporter codes
  are looked up at run time from /indicators and /reporters by those names, never hard-coded.
* There is no per-partner preferential rate: the "lowest preferential" figure is the lowest across all
  preference schemes, so it is stored for information only and is never used as an origin's duty.
"""

import hashlib
import json
import logging
import re
import threading
import time
from collections import deque
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy.orm import Session

from app.config import get_settings
from app.connectors.http import ConnectorError, source_record
from app.models import ApiCache, Tariff

log = logging.getLogger("trade_intel.wto")
BASE = "https://api.wto.org/timeseries/v1"
LICENCE = "WTO Timeseries API (WTO Stats); WTO terms of use"
INDICATORS = {
    "mfn_avg": "hs mfn - simple average ad valorem duty",
    "mfn_max": "hs mfn - maximum ad valorem duty",
    "nav_lines": "hs mfn - number of nav tariff lines",
    "lowest_pref": "lowest preferential tariff - simple average ad valorem tariff at hs 6-digit",
}
PER_SECOND, PER_HOUR = 1, 500  # conservative client-side pacing; WTO publishes no figure for free keys
_calls: deque = deque()
_lock = threading.Lock()


def configured() -> bool:
    return bool(get_settings().wto_api_key)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _pace() -> None:
    with _lock:
        now = time.monotonic()
        while _calls and now - _calls[0] > 3600:
            _calls.popleft()
        if len(_calls) >= PER_HOUR:
            raise ConnectorError("WTO request limit for this hour reached; try again later.")
        if _calls and now - _calls[-1] < 1 / PER_SECOND:
            time.sleep(1 / PER_SECOND - (now - _calls[-1]))
        _calls.append(time.monotonic())


def _get(path: str, params: dict, retries: int = 2):
    key = get_settings().wto_api_key
    if not key:
        raise ConnectorError("WTO is not configured: add WTO_API_KEY to the backend environment.")
    last = ""
    for attempt in range(retries + 1):
        _pace()
        try:
            r = httpx.get(
                f"{BASE}{path}",
                params=params,
                headers={"Ocp-Apim-Subscription-Key": key},
                timeout=get_settings().http_timeout_s,
            )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last = type(exc).__name__
        else:
            if r.status_code == 200:
                return r.json() if r.content else []
            if r.status_code == 204 or r.status_code == 404:
                return []
            if r.status_code in (401, 403):
                raise ConnectorError(
                    f"WTO rejected the subscription key (HTTP {r.status_code}). Check WTO_API_KEY "
                    "and that your subscription includes the Timeseries API."
                )
            if r.status_code == 429:
                raise ConnectorError("WTO rate limit reached; try again later.")
            if r.status_code == 400:
                raise ConnectorError(f"WTO did not accept the request: {r.text[:200]}")
            last = f"HTTP {r.status_code}"
        if attempt < retries:
            time.sleep(2**attempt)
    log.warning("wto unavailable: %s", last)
    raise ConnectorError(f"WTO did not respond ({last}).")


def _cached(db: Session, path: str, params: dict, hours: int):
    key = hashlib.sha256(json.dumps(["wto", path, params], sort_keys=True).encode()).hexdigest()
    now = datetime.now(UTC)
    row = db.get(ApiCache, key)
    if row and row.expires_at > now:
        return row.response["body"], row.fetched_at
    body = _get(path, params)
    expires = now + timedelta(hours=hours)
    if row:
        row.response, row.fetched_at, row.expires_at = {"body": body}, now, expires
    else:
        db.add(ApiCache(key=key, adapter="wto", response={"body": body}, expires_at=expires))
    db.flush()
    return body, now


def _rows(body) -> list[dict]:
    """The data endpoint returns a list or {"Dataset": [...]}; keys vary in case with the heading style."""
    if isinstance(body, dict):
        body = body.get("Dataset") or body.get("dataset") or body.get("data") or []
    return [{k.lower(): v for k, v in r.items()} for r in body if isinstance(r, dict)]


def indicator_codes(db: Session) -> dict[str, str]:
    body, _ = _cached(db, "/indicators", {"lang": 1}, 24 * 30)
    by_name = {_norm(r.get("name", "")): r.get("code") for r in _rows(body)}
    found = {k: by_name.get(name) for k, name in INDICATORS.items()}
    if not found["mfn_avg"]:
        raise ConnectorError("The WTO API no longer lists 'HS MFN - Simple average ad valorem duty'.")
    return {k: v for k, v in found.items() if v}


def reporter_code(db: Session, iso3: str) -> str | None:
    body, _ = _cached(db, "/reporters", {"lang": 1}, 24 * 30)
    rows = _rows(body)
    if iso3 == "EUN":
        hit = next((r for r in rows if _norm(r.get("name", "")) == "european union"), None)
    else:
        hit = next((r for r in rows if (r.get("iso3a") or r.get("iso3A") or "").upper() == iso3), None)
    return str(hit["code"]) if hit else None


def latest(rows: list[dict]) -> dict | None:
    rows = [r for r in rows if r.get("value") is not None]
    return max(rows, key=lambda r: int(r.get("year") or 0)) if rows else None


def load_tariffs(db: Session, importer_iso3: str, hs6: str) -> list[Tariff]:
    """Latest WTO HS6 MFN rate for an importer (with max rate and non-ad-valorem line count as caveats), plus the
    lowest preferential rate for information. Returns the stored rows."""
    codes = indicator_codes(db)
    reporter = reporter_code(db, importer_iso3)
    if not reporter:
        raise ConnectorError(f"WTO has no reporting economy for {importer_iso3}.")
    values: dict[str, dict] = {}
    for key, code in codes.items():
        params = {
            "i": code,
            "r": reporter,
            "pc": hs6,
            "ps": "all",
            "fmt": "json",
            "mode": "full",
            "head": "M",
            "max": 500,
            "lang": 1,
        }
        body, _ = _cached(db, "/data", params, 24 * 30)
        hit = latest(_rows(body))
        if hit:
            values[key] = hit
    if "mfn_avg" not in values:
        return []
    avg = values["mfn_avg"]
    year = int(avg.get("year") or 0) or None
    src = source_record(
        db,
        "wto",
        f"{BASE}/data",
        {"i": codes["mfn_avg"], "r": reporter, "pc": hs6},
        f"WTO HS MFN simple average, {importer_iso3} HS {hs6}",
        str(year or ""),
        LICENCE,
    )
    caveats = []
    if "mfn_max" in values and values["mfn_max"]["value"] != avg["value"]:
        caveats.append(f"lines under this HS6 range up to {float(values['mfn_max']['value']):g}%")
    if "nav_lines" in values and float(values["nav_lines"]["value"] or 0) > 0:
        caveats.append(
            f"{int(float(values['nav_lines']['value']))} line(s) carry non-ad-valorem (e.g. per-kg) duties "
            "not included in the percentage"
        )
    out = []
    mfn = Tariff(
        importer_iso3=importer_iso3,
        hs_code=hs6,
        origin_iso3="",
        rate_type="MFN",
        ad_valorem_pct=float(avg["value"]),
        data_year=year,
        source="wto",
        source_url="https://stats.wto.org/",
        source_record_id=src.id,
        notes="WTO HS MFN simple average ad valorem duty" + (f"; {'; '.join(caveats)}" if caveats else "") + ".",
    )
    out.append(mfn)
    if "lowest_pref" in values:
        lp = values["lowest_pref"]
        out.append(
            Tariff(
                importer_iso3=importer_iso3,
                hs_code=hs6,
                origin_iso3="",
                rate_type="lowest_pref",
                ad_valorem_pct=float(lp["value"]),
                data_year=int(lp.get("year") or 0) or None,
                source="wto",
                source_url="https://stats.wto.org/",
                source_record_id=src.id,
                notes="Lowest preferential rate under any scheme. Information only: not specific to an "
                "origin, so never used as Egypt's, Jordan's or Syria's duty.",
            )
        )
    for t in out:
        db.query(Tariff).filter(
            Tariff.importer_iso3 == t.importer_iso3,
            Tariff.hs_code == t.hs_code,
            Tariff.origin_iso3 == "",
            Tariff.rate_type == t.rate_type,
            Tariff.source == "wto",
        ).delete()
        db.add(t)
    db.flush()
    return out
