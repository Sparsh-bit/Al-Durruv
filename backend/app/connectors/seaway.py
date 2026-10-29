"""Sea routes from a self-hosted auto-sea-way service (github.com/auto-sea-way/asw, MIT/Apache-2.0).

Contract verified from the v0.10.0 source (crates/asw-serve/src/api.rs, 29 Oct 2026):
GET /route?from=lat,lon&to=lat,lon[&shore_buffer=0..5][&canals=true|false][&arctic=false] with header
X-Api-Key -> {distance_nm, raw_hops, smooth_hops, geometry (GeoJSON LineString), shore_buffer_nm, land_legs};
GET /info -> {nodes, edges, graph_path, version}; GET /ready -> 200 when the graph is loaded.

The graph is built from OpenStreetMap coastlines (ODbL). It gives a realistic water path and its length. It has
no depth, ice-season, schedule, price or transit-time data.
"""

import hashlib
import json
import logging
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy.orm import Session

from app.config import get_settings
from app.connectors.http import ConnectorError
from app.models import ApiCache

log = logging.getLogger("trade_intel.seaway")
ATTRIBUTION = "auto-sea-way (MIT/Apache-2.0); route graph © OpenStreetMap contributors, ODbL"
CAVEATS = [
    "Distance along a computed water path; no depth, draft or seasonal-ice checks.",
    "Not a carrier schedule: real voyages add port calls, transshipment and canal waiting time.",
]


def configured() -> bool:
    s = get_settings()
    return bool(s.asw_base_url and s.asw_api_key)


def _get(path: str, params: dict | None = None, timeout: float = 30.0) -> dict:
    s = get_settings()
    if not configured():
        raise ConnectorError("Sea routing is not configured: set ASW_BASE_URL and ASW_API_KEY on the backend.")
    try:
        r = httpx.get(
            s.asw_base_url.rstrip("/") + path, params=params, headers={"X-Api-Key": s.asw_api_key}, timeout=timeout
        )
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        log.warning("seaway unreachable: %s", type(exc).__name__)
        raise ConnectorError("The sea-routing service is not reachable. Everything else keeps working.") from None
    if r.status_code == 200:
        return r.json()
    if r.status_code == 401:
        raise ConnectorError("The sea-routing service rejected ASW_API_KEY (it must match the service's key).")
    if r.status_code == 503:
        raise ConnectorError("The sea-routing service is starting or at capacity; retry in a few seconds.")
    try:
        msg = r.json().get("error", "")
    except ValueError:
        msg = ""
    raise ConnectorError(f"The sea-routing service could not route this request: {msg or 'HTTP ' + str(r.status_code)}")


def info(db: Session) -> dict:
    """Graph metadata (version identifies the OSM build); cached for a day."""
    return _cached(db, "/info", {}, hours=24, timeout=10)


def _cached(db: Session, path: str, params: dict, hours: int, timeout: float = 30.0, tag: str = "") -> dict:
    """`tag` joins the cache key only (e.g. the graph version); it is never sent upstream."""
    key = hashlib.sha256(json.dumps(["asw", path, params, tag], sort_keys=True).encode()).hexdigest()
    now = datetime.now(UTC)
    row = db.get(ApiCache, key)
    if row and row.expires_at > now:
        return {**row.response, "_cached_at": row.fetched_at.isoformat()}
    body = _get(path, params, timeout)
    if row:
        row.response, row.fetched_at, row.expires_at = body, now, now + timedelta(hours=hours)
    else:
        db.add(ApiCache(key=key, adapter="asw", response=body, expires_at=now + timedelta(hours=hours)))
    db.flush()
    return {**body, "_cached_at": now.isoformat()}


def _coord(lat, lon) -> str:
    lat, lon = float(lat), float(lon)
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ConnectorError("Coordinates are out of range.")
    return f"{lat:.6f},{lon:.6f}"


def route(db: Session, origin: tuple, destination: tuple, *, canals: bool = True, shore_buffer_nm: float = 0.0) -> dict:
    """Route between (lat, lon) pairs. Cached per graph version, so a new graph release recomputes."""
    if not 0 <= shore_buffer_nm <= 5:
        raise ConnectorError("Shore buffer must be between 0 and 5 nautical miles.")
    meta = info(db)
    version = meta.get("graph_version") or meta.get("version", "unknown")
    params = {
        "from": _coord(*origin),
        "to": _coord(*destination),
        "canals": str(canals).lower(),
        "shore_buffer": f"{shore_buffer_nm:g}",
    }
    body = _cached(db, "/route", params, hours=24 * 30, timeout=60, tag=version)
    nm = float(body["distance_nm"])
    return {
        "distance_nm": nm,
        "distance_km": round(nm * 1.852, 1),
        "geometry": body.get("geometry"),
        "land_legs": body.get("land_legs", []),
        "shore_buffer_nm": body.get("shore_buffer_nm", shore_buffer_nm),
        "canals": canals,
        "graph_version": version,
        "computed_at": body.get("_cached_at"),
        "source": ATTRIBUTION,
        "confidence": "calculated",
        "caveats": CAVEATS
        + (
            ["Part of the path crosses land at a port pin; those legs are excluded from the distance."]
            if body.get("land_legs")
            else []
        ),
    }


def sailing_days(distance_nm: float, speed_knots: float) -> float:
    """Pure sailing time at a stated speed. An estimate with that single assumption, never a transit time."""
    if not 1 <= speed_knots <= 40:
        raise ConnectorError("Speed must be between 1 and 40 knots.")
    return round(distance_nm / speed_knots / 24, 1)
