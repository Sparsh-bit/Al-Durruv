#!/bin/sh
# Production entrypoint: migrate, seed (idempotent), then serve.
set -e
alembic upgrade head
python -m app.seed
# One worker on purpose: background jobs (trade refresh, AI research) run in this process.
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" \
  --proxy-headers --forwarded-allow-ips="*" --workers 1 --timeout-graceful-shutdown 10
