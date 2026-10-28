"""Shared HTTP plumbing for connectors: timeouts, retries with backoff, a per-connector circuit breaker,
and a raw-response store (api_cache, keyed by request) so every derived number can be traced back."""

import hashlib
import json
import threading
import time
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import ApiCache, SourceRecord


class ConnectorError(Exception):
    """A failure the user may see. Never contains credentials."""


class NoData(ConnectorError):
    pass


_BREAKER: dict[str, tuple[int, float]] = {}  # connector -> (consecutive failures, open-until monotonic)
_LOCK = threading.Lock()
BREAK_AFTER = 4
BREAK_FOR_S = 300


def _check_breaker(name: str) -> None:
    with _LOCK:
        fails, until = _BREAKER.get(name, (0, 0.0))
    if fails >= BREAK_AFTER and time.monotonic() < until:
        raise ConnectorError(f"{name} is paused after repeated failures; retry in a few minutes.")


def _record(name: str, ok: bool) -> None:
    with _LOCK:
        fails, _ = _BREAKER.get(name, (0, 0.0))
        _BREAKER[name] = (0, 0.0) if ok else (fails + 1, time.monotonic() + BREAK_FOR_S)


def get_json(name: str, url: str, params: dict | None = None, *, retries: int = 3, not_found_is_empty=False):
    """GET JSON with retries. Secrets in params never appear in raised messages."""
    _check_breaker(name)
    last = ""
    for attempt in range(retries):
        try:
            r = httpx.get(url, params=params, timeout=get_settings().http_timeout_s, follow_redirects=False)
            if r.status_code == 404 and not_found_is_empty:
                _record(name, True)
                raise NoData(f"{name}: no records for this request.")
            if r.status_code in (301, 302, 303, 307, 308):
                raise ConnectorError(f"{name} redirected the request (HTTP {r.status_code}); check the API key.")
            if r.status_code >= 500 or r.status_code == 429:
                last = f"HTTP {r.status_code}"
            elif r.status_code >= 400:
                raise ConnectorError(f"{name} rejected the request (HTTP {r.status_code}).")
            else:
                _record(name, True)
                return r.json()
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last = type(exc).__name__
        except ValueError:
            last = "invalid JSON"
        if attempt < retries - 1:
            time.sleep(2 ** (attempt + 1))
    _record(name, False)
    raise ConnectorError(f"{name} did not respond ({last}) after {retries} attempts.")


SECRET_PARAMS = {"key", "api_key", "apikey", "subscription-key", "subscription_key", "token", "access_token"}


def _without_secrets(params: dict | None) -> dict:
    """Drop credential parameters (exact names only: 'keyword' is a search term, not a secret)."""
    return {k: v for k, v in (params or {}).items() if k.lower() not in SECRET_PARAMS}


def cache_key(name: str, url: str, params: dict | None) -> str:
    safe = _without_secrets(params)
    return hashlib.sha256(json.dumps([name, url, safe], sort_keys=True, default=str).encode()).hexdigest()


def fetch_cached(db: Session, name: str, url: str, params: dict | None, ttl_hours: int, **kw) -> tuple[object, bool]:
    """Return (payload, from_cache). The payload is kept as the raw record of what the source returned."""
    key = cache_key(name, url, params)
    now = datetime.now(UTC)
    row = db.get(ApiCache, key)
    if row and row.expires_at > now:
        return row.response, True
    payload = get_json(name, url, params, **kw)
    if row:
        row.response, row.fetched_at, row.expires_at = payload, now, now + timedelta(hours=ttl_hours)
    else:
        db.add(ApiCache(key=key, adapter=name, response=payload, expires_at=now + timedelta(hours=ttl_hours)))
    db.flush()
    return payload, False


def source_record(db: Session, adapter: str, url: str, params: dict, title: str, period: str, licence: str):
    safe = _without_secrets(params)
    src = SourceRecord(
        adapter=adapter,
        url=str(httpx.URL(url, params=safe)),
        title=title,
        params=safe,
        reporting_period=period,
        licence=licence,
    )
    db.add(src)
    db.flush()
    return src
