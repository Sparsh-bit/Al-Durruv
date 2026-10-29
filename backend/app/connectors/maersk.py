"""Maersk Developer Portal reference data: Commodities API v1.1 and Locations API v4.

Verified against the official OpenAPI documents (see docs/DECISIONS.md D14):
* Commodities: GET https://api.maersk.com/commodity-classifications
  params commodityName | hsCommodityCode | commodityCode | cargoType; returns {"commodities": [...]};
  404 = no match. Limits per key: 15,000/hour, 250/minute.
* Locations: GET https://api.maersk.com/reference-data/locations (cityName, countryCode, UNLocationCode,
  locationType, limit<=100, page; Next-Page header) and GET .../carrier-locations/{carrierGeoID} (13 chars).
  Limits per key: 36,000/hour, 60/minute.
Both authenticate with the `Consumer-Key` header only; the portal's Consumer Secret is not used.

These are reference data. They do not provide freight prices, schedules, transit times or customs rulings.
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
from app.models import ApiCache

log = logging.getLogger("trade_intel.maersk")

COMMODITIES_URL = "https://api.maersk.com/commodity-classifications"
LOCATIONS_URL = "https://api.maersk.com/reference-data/locations"
GEO_URL = "https://api.maersk.com/reference-data/carrier-locations/{geo_id}"
# Our own ceilings sit below Maersk's published limits so the shared key is never throttled.
LIMITS = {"commodities": (200, 12_000), "locations": (50, 30_000)}  # per minute, per hour
CACHE_HOURS = {"commodities": 24 * 30, "locations": 24 * 7}
LOCATION_TYPES = (
    "CITY",
    "COUNTRY",
    "TERMINAL",
    "BARGE TERMINAL",
    "RAIL TERMINAL",
    "CONTAINER FREIGHT STATION",
    "CUSTOMER LOCATION",
    "DEPOT",
)
GEO_ID = re.compile(r"^[0-9a-zA-Z]{13}$")
UNLOCODE = re.compile(r"^[a-zA-Z]{2}[a-zA-Z0-9]{3}$")
NAME_OK = re.compile(r"^[A-Za-z0-9<>=_.,:;$%^&+*\-'( )/]{2,}$")


class MaerskError(Exception):
    status = 502

    def __init__(self, message: str, retry_after: int | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class NotConfigured(MaerskError):
    status = 503


class AuthError(MaerskError):
    status = 502


class RateLimited(MaerskError):
    status = 429


class BadRequest(MaerskError):
    status = 422


class Unavailable(MaerskError):
    status = 503


_calls: dict[str, deque] = {"commodities": deque(), "locations": deque()}
_lock = threading.Lock()


def _reserve(api: str) -> None:
    per_min, per_hour = LIMITS[api]
    now = time.monotonic()
    with _lock:
        q = _calls[api]
        while q and now - q[0] > 3600:
            q.popleft()
        last_min = sum(1 for t in q if now - t <= 60)
        if last_min >= per_min or len(q) >= per_hour:
            raise RateLimited("Maersk request limit for this hour or minute reached; try again shortly.", 60)
        q.append(now)


def configured() -> bool:
    return bool(get_settings().maersk_consumer_key)


def _request(api: str, url: str, params: dict, retries: int = 2) -> tuple[object, dict]:
    """GET with the Consumer-Key header. Returns (json, headers). 404 -> ([], {}) (the APIs' 'no match')."""
    key = get_settings().maersk_consumer_key
    if not key:
        raise NotConfigured("Maersk is not configured: add MAERSK_CONSUMER_KEY to the backend environment.")
    last = ""
    for attempt in range(retries + 1):
        _reserve(api)
        try:
            r = httpx.get(
                url,
                params=params,
                headers={"Consumer-Key": key, "Accept": "application/json"},
                timeout=get_settings().http_timeout_s,
            )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last = type(exc).__name__
        else:
            if r.status_code == 200:
                return r.json(), dict(r.headers)
            if r.status_code == 404:
                return [], {}
            if r.status_code in (401, 403):
                raise AuthError(
                    f"Maersk rejected the Consumer Key (HTTP {r.status_code}). Check the key and that the "
                    f"{api.title()} API product is enabled for your app in the Maersk Developer Portal."
                )
            if r.status_code == 429:
                wait = int(r.headers.get("Retry-After", "60") or 60)
                raise RateLimited("Maersk rate limit reached; try again in a minute.", wait)
            if r.status_code == 400:
                raise BadRequest(f"Maersk did not accept the search: {_api_message(r)}")
            last = f"HTTP {r.status_code}"
        if attempt < retries:
            time.sleep(2**attempt)
    log.warning("maersk %s unavailable: %s", api, last)  # never logs the key or headers
    raise Unavailable(f"Maersk {api} service did not respond ({last}). Your other data is unaffected.")


def _api_message(r: httpx.Response) -> str:
    try:
        body = r.json()
    except ValueError:
        return "invalid request"
    subs = body.get("subErrors") or []
    detail = "; ".join(f"{s.get('field')}: {s.get('message')}" for s in subs if isinstance(s, dict))
    return (detail or body.get("message") or "invalid request")[:300]


def _cached(db: Session, api: str, url: str, params: dict, force: bool = False) -> tuple[object, dict, datetime]:
    key = hashlib.sha256(json.dumps(["maersk", url, params], sort_keys=True).encode()).hexdigest()
    now = datetime.now(UTC)
    row = db.get(ApiCache, key)
    if row and row.expires_at > now and not force:
        return row.response["body"], row.response.get("headers", {}), row.fetched_at
    body, headers = _request(api, url, params)
    payload = {"body": body, "headers": {k: v for k, v in headers.items() if k.lower() == "next-page"}}
    expires = now + timedelta(hours=CACHE_HOURS[api])
    if row:
        row.response, row.fetched_at, row.expires_at = payload, now, expires
    else:
        db.add(ApiCache(key=key, adapter=f"maersk_{api}", response=payload, expires_at=expires))
    db.flush()
    return body, payload["headers"], now


# --- commodities ------------------------------------------------------------------------------------


def parse_commodities(body) -> list[dict]:
    items = body.get("commodities", []) if isinstance(body, dict) else body or []
    out = []
    for c in items:
        out.append(
            {
                "commodity_code": c.get("commodityCode", ""),
                "commodity_name": c.get("commodityName", ""),
                "cargo_types": c.get("cargoTypes") or [],
                "has_us_flag": bool(c.get("hasUSFlag")),
                "hs_codes": [
                    {"code": h.get("hsCommodityCode", ""), "name": h.get("hsCommodityName", "")}
                    for h in c.get("hsCommodityCodes") or []
                ],
            }
        )
    return out


def search_commodities(db: Session, name: str = "", hs: str = "", force: bool = False) -> dict:
    params = {}
    if name:
        if not NAME_OK.match(name) or sum(ch.isalpha() for ch in name) < 2:
            raise BadRequest("Use at least 2 letters; letters, digits and basic punctuation only.")
        params["commodityName"] = name
    if hs:
        if not re.fullmatch(r"[A-Za-z0-9]{6}", hs):
            raise BadRequest("HS code must be 6 characters.")
        params["hsCommodityCode"] = hs
    if not params:
        raise BadRequest("Give a commodity name or an HS code.")
    body, _h, fetched = _cached(db, "commodities", COMMODITIES_URL, params, force)
    return {
        "query": params,
        "results": parse_commodities(body),
        "retrieved_at": fetched.isoformat(),
        "source": "Maersk Commodities API v1.1 (reference data)",
    }


# --- locations --------------------------------------------------------------------------------------


def parse_location(loc: dict) -> dict:
    return {
        "carrier_geo_id": loc.get("carrierGeoID") or "",
        "un_location_code": loc.get("UNLocationCode") or "",
        "location_name": loc.get("locationName") or "",
        "location_type": loc.get("locationType") or "",
        "city_name": loc.get("cityName") or "",
        "country_code": loc.get("countryCode") or "",
        "country_name": loc.get("countryName") or "",
        "region_code": loc.get("UNRegionCode") or "",
        "region_name": loc.get("UNRegionName") or "",
        "has_cy_service": loc.get("hasCYService"),
        "smdg_facility_code": loc.get("smdgFacilityCode") or "",
        "latitude": loc.get("latitude"),
        "longitude": loc.get("longitude"),
        "aliases": loc.get("alternateAliases") or [],
    }


def search_locations(
    db: Session,
    *,
    query: str = "",
    mode: str = "name",
    country_code: str = "",
    location_type: str = "",
    limit: int = 25,
    page: str | None = None,
    force: bool = False,
) -> dict:
    """mode is explicit ("name" or "unlocode"): 'Cairo' is also a valid UN/LOCODE shape, so never guess."""
    params: dict = {"limit": max(1, min(limit, 100))}
    q = query.strip()
    if mode == "unlocode":
        if not UNLOCODE.match(q):
            raise BadRequest("A UN/LOCODE has 5 characters: 2-letter country + 3 letters/digits, e.g. EGALY.")
        params["UNLocationCode"] = q.upper()
    elif q:
        if sum(ch.isalpha() for ch in q) < 2 or len(q) > 50:
            raise BadRequest("Type at least 2 letters of a city or port name, or a 5-character UN/LOCODE.")
        params["cityName"] = q
    if country_code:
        if not re.fullmatch(r"[A-Za-z]{2}", country_code):
            raise BadRequest("Country must be a 2-letter ISO code.")
        params["countryCode"] = country_code.upper()
    if location_type:
        if location_type.upper() not in LOCATION_TYPES:
            raise BadRequest("Unknown location type.")
        params["locationType"] = location_type.upper()
    if not ({"UNLocationCode", "cityName", "countryCode"} & params.keys()):
        raise BadRequest("Search by city or port name, UN/LOCODE or country.")
    if page:
        params["page"] = page
    body, headers, fetched = _cached(db, "locations", LOCATIONS_URL, params, force)
    results = [parse_location(x) for x in (body if isinstance(body, list) else [])]
    return {
        "query": params,
        "results": results,
        "next_page": headers.get("Next-Page") or headers.get("next-page"),
        "retrieved_at": fetched.isoformat(),
        "source": "Maersk Locations API v4 (reference data)",
    }


def location_by_geo_id(db: Session, geo_id: str, force: bool = False) -> dict | None:
    if not GEO_ID.match(geo_id):
        raise BadRequest("A Maersk Geo ID has 13 letters and digits.")
    body, _h, fetched = _cached(db, "locations", GEO_URL.format(geo_id=geo_id), {"isRequiredAlias": "true"}, force)
    if not body or not isinstance(body, dict):
        return None
    return {**parse_location(body), "retrieved_at": fetched.isoformat()}


def search_commodities_by_code(db: Session, commodity_code: str, force: bool = False) -> dict:
    """Exact lookup by Maersk's 6-digit commodity code (the API does not allow name/HS alongside it)."""
    if not re.fullmatch(r"[0-9]{6}", commodity_code):
        raise BadRequest("A Maersk commodity code has 6 digits.")
    params = {"commodityCode": commodity_code}
    body, _h, fetched = _cached(db, "commodities", COMMODITIES_URL, params, force)
    return {
        "query": params,
        "results": parse_commodities(body),
        "retrieved_at": fetched.isoformat(),
        "source": "Maersk Commodities API v1.1 (reference data)",
    }
