import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.config import get_settings
from app.db import SessionLocal
from app.routers import admin, ai, auth, catalogue, client, companies, intel, maersk, markets, reports
from app.services import jobs

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("trade_intel")


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Jobs left behind by stopped processes are marked failed; live jobs of other processes
    # (rolling deploy, a second machine on the same database) keep running.
    with SessionLocal() as db:
        n = jobs.sweep(db)
    if n:
        log.warning("Marked %d abandoned background jobs as failed", n)
    yield


settings = get_settings()
app = FastAPI(
    title="Trade Intelligence API",
    version="1.0.0",
    lifespan=lifespan,
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None,
    openapi_url=None if settings.is_production else "/openapi.json",
)
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)


CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
    "font-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    h = response.headers
    h.setdefault("X-Content-Type-Options", "nosniff")
    h.setdefault("X-Frame-Options", "DENY")
    h.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    h.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=(), usb=()")
    h.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    h.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if settings.is_production:
        h.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        h.setdefault("Content-Security-Policy", CSP)
    path = request.url.path
    if path.startswith("/assets/"):
        h["Cache-Control"] = "public, max-age=31536000, immutable"  # hashed file names
    elif path.startswith("/api/") and not path.startswith("/api/static/"):
        h.setdefault("Cache-Control", "no-store")
    return response


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    log.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse({"detail": "Something went wrong on the server. The error has been logged."}, 500)


@app.get("/api/health")
def health():
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
    except Exception:
        log.exception("Health check: database unreachable")
        return JSONResponse({"status": "error", "detail": "Database unreachable."}, 503)
    return {
        "status": "ok",
        "ai_enabled": settings.ai_enabled,
        "model": settings.model_fast,
        "model_brief": settings.model_brief,
    }


for r in (auth, catalogue, markets, companies, ai, reports, admin, client, intel, maersk):
    app.include_router(r.router)

# Catalogue page images (public marketing material; no auth so <img> tags can load them).
app.mount("/api/static", StaticFiles(directory=Path(__file__).parent.parent / "static"), name="static")

# Built React app (single-service deployment). In development the Vite server serves it instead.
FRONTEND_DIST = (
    Path(settings.frontend_dist) if settings.frontend_dist else Path(__file__).parents[2] / "frontend" / "dist"
)
if (FRONTEND_DIST / "index.html").is_file():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/") or path == "api":
            return JSONResponse({"detail": "Not found."}, 404)
        file = (FRONTEND_DIST / path).resolve()
        if path and file.is_file() and FRONTEND_DIST.resolve() in file.parents:
            return FileResponse(file)
        return FileResponse(FRONTEND_DIST / "index.html", headers={"Cache-Control": "no-cache"})
