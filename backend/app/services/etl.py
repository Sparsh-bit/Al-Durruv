"""Connector runs as background jobs (logged in refresh_runs, kept alive by heartbeat)."""

import logging
import threading
from datetime import UTC, date, datetime

from app.connectors import sources
from app.connectors.http import ConnectorError
from app.db import SessionLocal
from app.models import RefreshRun
from app.services import intel, jobs

log = logging.getLogger("trade_intel.etl")
CONNECTORS = ("comext", "census", "tariffs", "fx")


def _months_back(n: int) -> list[str]:
    today = date.today()
    y, m = today.year, today.month
    out = []
    for _ in range(n):
        m -= 1
        if m == 0:
            y, m = y - 1, 12
        out.append(f"{y:04d}-{m:02d}")
    return sorted(out)


def run(run_id: int, connector: str, params: dict) -> None:
    stop = threading.Event()

    def keepalive():
        while not stop.wait(60):
            jobs.beat([run_id])

    threading.Thread(target=keepalive, daemon=True).start()
    with SessionLocal() as db:
        r = db.get(RefreshRun, run_id)
        r.status, r.message = "running", "Running"
        db.commit()
        try:
            rows = _dispatch(db, connector, params)
            r.status, r.rows = "succeeded", rows
            r.message = f"{rows} rows"
            db.commit()
            intel.generate_alerts(db)
        except ConnectorError as exc:
            db.rollback()
            r = db.get(RefreshRun, run_id)
            r.status, r.error = "failed", str(exc)
        except Exception:
            log.exception("connector %s failed", connector)
            db.rollback()
            r = db.get(RefreshRun, run_id)
            r.status, r.error = "failed", "Unexpected error; see server logs."
        finally:
            stop.set()
            r.finished_at = datetime.now(UTC)
            db.commit()


def _dispatch(db, connector: str, p: dict) -> int:
    months = p.get("months") or _months_back(int(p.get("months_back", 12)))
    hs_codes = p.get("hs_codes") or []
    total = 0
    if connector == "fx":
        total = sources.load_fx(db, date.fromisoformat(months[0] + "-01"), date.today())
    elif connector == "comext":
        reporters = p.get("reporters") or [sources.iso2_to_iso3()[c] for c in sources.EU27]
        for hs in hs_codes:
            total += sources.load_comext(db, hs, reporters, months)
            db.commit()
    elif connector == "census":
        for hs in hs_codes:
            total += sources.load_census(db, hs, months)
            db.commit()
    elif connector == "tariffs":
        markets = p.get("markets") or ["USA"]
        origins = p.get("origins") or ["EGY", "JOR", "SYR"]
        for hs in hs_codes:
            for market in markets:
                if market == "USA":
                    total += len(sources.load_usitc(db, hs))  # line rates + US-Jordan FTA; no WITS needed
                    continue
                mfn, year = sources.load_wits(db, market, hs)
                total += 1 if mfn else 0
                if year:
                    for origin in origins:  # one request each, for the same year as the MFN rate
                        pref, _ = sources.load_wits(db, market, hs, origin, year)
                        total += 1 if pref else 0
                db.commit()
    else:
        raise ConnectorError(f"Unknown connector {connector}.")
    db.commit()
    return total
