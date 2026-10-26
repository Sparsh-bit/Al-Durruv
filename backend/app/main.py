import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import update

from app.config import get_settings
from app.db import SessionLocal
from app.models import RefreshRun
from app.routers import admin, ai, auth, catalogue, companies, markets, reports

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("trade_intel")


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Background jobs run in this process, so none survive a restart: release their runs for re-queuing.
    with SessionLocal() as db:
        n = db.execute(
            update(RefreshRun)
            .where(RefreshRun.status.in_(("queued", "running")))
            .values(
                status="failed",
                error="Interrupted by a server restart. Start the refresh again.",
                message="Interrupted",
                finished_at=datetime.now(UTC),
            )
        ).rowcount
        db.commit()
    if n:
        log.warning("Marked %d interrupted refresh runs as failed", n)
    yield


app = FastAPI(title="Trade Intelligence API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in get_settings().cors_origins.split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    log.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse({"detail": "Something went wrong on the server. The error has been logged."}, 500)


@app.get("/api/health")
def health():
    s = get_settings()
    return {"status": "ok", "ai_enabled": s.ai_enabled, "model": s.claude_model}


for r in (auth, catalogue, markets, companies, ai, reports, admin):
    app.include_router(r.router)

# Catalogue page images (public marketing material; no auth so <img> tags can load them).
app.mount("/api/static", StaticFiles(directory=Path(__file__).parent.parent / "static"), name="static")
