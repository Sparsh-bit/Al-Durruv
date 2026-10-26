"""Liveness of background jobs (trade refreshes, AI research) shared by every app process.

Each process keeps its own jobs alive by updating `heartbeat_at`. A queued or running job whose
heartbeat is older than STALE belonged to a process that stopped (redeploy, crash). This works when
several processes share one database: a rolling deploy, or a laptop and the live site on Neon.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import RefreshRun

ACTIVE = ("queued", "running")
STALE = timedelta(minutes=5)
INTERRUPTED = "Interrupted: the process running it stopped (restart or redeploy). Start it again."


def beat(run_ids: list[int]) -> None:
    """Mark these jobs as still owned by a live process."""
    if not run_ids:
        return
    with SessionLocal() as db:
        db.execute(
            update(RefreshRun)
            .where(RefreshRun.id.in_(run_ids), RefreshRun.status.in_(ACTIVE))
            .values(heartbeat_at=datetime.now(UTC))
        )
        db.commit()


def is_live(run: RefreshRun | None) -> bool:
    if run is None or run.status not in ACTIVE:
        return False
    return run.heartbeat_at is not None and datetime.now(UTC) - run.heartbeat_at < STALE


def effective_status(run: RefreshRun) -> str:
    return "failed" if run.status in ACTIVE and not is_live(run) else run.status


def sweep(db: Session) -> int:
    """Mark jobs abandoned by stopped processes as failed; live jobs of other processes are untouched."""
    cutoff = datetime.now(UTC) - STALE
    n = db.execute(
        update(RefreshRun)
        .where(RefreshRun.status.in_(ACTIVE))
        .where((RefreshRun.heartbeat_at.is_(None)) | (RefreshRun.heartbeat_at < cutoff))
        .values(status="failed", error=INTERRUPTED, message="Interrupted", finished_at=datetime.now(UTC))
    ).rowcount
    db.commit()
    return n
