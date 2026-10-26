"""UN Comtrade adapter built on the official `comtradeapicall` client.

The client prints HTTP errors and returns None, so we capture its output and raise
a typed error instead. Responses are cached in Postgres, calls are spaced to respect
rate limits, and transient failures are retried with exponential backoff.
"""

import contextlib
import hashlib
import io
import json
import math
import re
import threading
import time
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import comtradeapicall
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import ApiCache, SourceRecord

ADAPTER = "un_comtrade"
LICENCE = "UN Comtrade Database — UN Comtrade Terms of Use (https://comtradeplus.un.org/)"
KEEP = (
    "refYear",
    "reporterCode",
    "reporterISO",
    "reporterDesc",
    "partnerCode",
    "partnerISO",
    "partnerDesc",
    "flowCode",
    "cmdCode",
    "cmdDesc",
    "primaryValue",
    "netWgt",
    "qty",
    "qtyUnitAbbr",
)


MAX_RECORDS = 500  # free preview cap per request
MAX_RECORDS_KEYED = 100_000  # with a (free) subscription key


def max_records() -> int:
    return MAX_RECORDS_KEYED if get_settings().comtrade_subscription_key else MAX_RECORDS


class ComtradeError(RuntimeError):
    pass


class QuotaExceeded(ComtradeError):
    """The account's call-volume quota is used up; retrying before wait_s seconds is pointless."""

    def __init__(self, message: str, wait_s: int):
        super().__init__(message)
        self.wait_s = wait_s


def _error_from_output(text: str) -> ComtradeError:
    msg = text.strip()[:500] or "Comtrade returned no response"
    if "quota" in msg.lower():
        m = re.search(r"(\d+):(\d{2}):(\d{2})", msg)
        wait = int(m[1]) * 3600 + int(m[2]) * 60 + int(m[3]) if m else 3600
        return QuotaExceeded(msg, wait)
    return ComtradeError(msg)


_lock = threading.Lock()
_last_call = 0.0


def _throttle() -> None:
    global _last_call
    with _lock:
        wait = get_settings().comtrade_min_interval_s - (time.monotonic() - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.monotonic()


def _clean(v):
    if isinstance(v, float) and math.isnan(v):
        return None
    return v


def _call(params: dict, key: str) -> list[dict]:
    """One request through the official client; returns rows or raises ComtradeError."""
    fn = comtradeapicall.getFinalData if key else comtradeapicall.previewFinalData
    kwargs = dict(
        typeCode="C",
        freqCode="A",
        clCode="HS",
        period=params["period"],
        reporterCode=params.get("reporterCode"),
        cmdCode=params["cmdCode"],
        flowCode=params["flowCode"],
        partnerCode=params.get("partnerCode"),
        partner2Code=None,
        customsCode=None,
        motCode=None,
        maxRecords=max_records(),
        format_output="JSON",
        aggregateBy=None,
        breakdownMode="classic",
        countOnly=None,
        includeDesc=True,
    )
    if key:
        kwargs["subscription_key"] = key
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            df = fn(**kwargs)
    except Exception as exc:  # network errors raised inside the client
        raise ComtradeError(f"Comtrade request failed: {exc}") from exc
    if df is None:
        raise _error_from_output(out.getvalue())
    if df.empty:
        return []
    cols = [c for c in KEEP if c in df.columns]
    return [{k: _clean(v) for k, v in row.items()} for row in df[cols].to_dict("records")]


def public_url(params: dict, key: str) -> str:
    base = (
        "https://comtradeapi.un.org/data/v1/get/C/A/HS"
        if key
        else "https://comtradeapi.un.org/public/v1/preview/C/A/HS"
    )
    q = {k: v for k, v in params.items() if v is not None}
    return f"{base}?{urlencode(q)}"


def fetch(
    db: Session,
    *,
    period: int | str,
    cmd: str,
    flow: str,
    reporter: int | None = None,
    partner: int | None = 0,
    retries: int = 3,
    caller=_call,
) -> tuple[list[dict], SourceRecord]:
    """Fetch annual HS6 trade rows. period: a year or comma-separated years.
    partner=0 → World totals; partner=None → all partners. Quota errors are raised immediately."""
    s = get_settings()
    params = {
        "period": str(period),
        "maxRecords": max_records(),
        "cmdCode": cmd,
        "flowCode": flow,
        "reporterCode": None if reporter is None else str(reporter),
        "partnerCode": None if partner is None else str(partner),
    }
    cache_key = hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()
    now = datetime.now(UTC)

    cached = db.get(ApiCache, cache_key)
    if cached and cached.expires_at > now:
        src = db.get(SourceRecord, cached.response["source_record_id"])
        if src:
            return cached.response["rows"], src

    last_err: Exception | None = None
    for attempt in range(retries):
        _throttle()
        try:
            rows = caller(params, s.comtrade_subscription_key)
            break
        except QuotaExceeded:
            raise
        except ComtradeError as exc:
            last_err = exc
            if attempt < retries - 1:
                time.sleep(2 ** (attempt + 1))
    else:
        raise ComtradeError(f"{last_err} (after {retries} attempts)")

    src = SourceRecord(
        adapter=ADAPTER,
        url=public_url(params, s.comtrade_subscription_key),
        title=f"UN Comtrade HS {cmd} {'imports' if flow == 'M' else 'exports'} {period}",
        params=params,
        reporting_period=str(period),
        licence=LICENCE,
    )
    db.add(src)
    db.flush()
    payload = {"rows": rows, "source_record_id": src.id}
    expires = now + timedelta(hours=s.comtrade_cache_ttl_hours)
    if cached:
        cached.response, cached.fetched_at, cached.expires_at = payload, now, expires
    else:
        db.add(ApiCache(key=cache_key, adapter=ADAPTER, response=payload, expires_at=expires))
    db.flush()
    return rows, src
