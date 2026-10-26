import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.routers import admin, ai, auth, catalogue, companies, markets, reports

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("trade_intel")

app = FastAPI(title="Trade Intelligence API", version="0.1.0")
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
