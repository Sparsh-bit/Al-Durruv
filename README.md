# TradeScope — Trade Intelligence & Buyer Discovery

Web platform for an exporter / private-label manufacturer: load a product and HS code, see official
trade statistics, rank import markets with an explainable score, discover buyers and competitors with
source evidence, ask a grounded AI analyst, and export a client-ready brief (PDF / Excel).

```
frontend/   React 19 + Vite + TypeScript + Tailwind (dashboard UI)
backend/    FastAPI + SQLAlchemy + Alembic (API, ingestion, analytics, AI layer)
docs/       design spec, data sources & provenance, handover
```

## Prerequisites

- Docker (for PostgreSQL 16), Python 3.13 with [uv](https://docs.astral.sh/uv/), Node 20+.

## First-time setup

```bash
cp .env.example .env            # then fill in ADMIN_PASSWORD, JWT_SECRET and (optionally) ANTHROPIC_API_KEY
docker compose up -d --wait     # Postgres on localhost:5433 (+ test database)
cd backend
uv sync
uv run alembic upgrade head     # create schema
uv run python -m app.seed       # HS6 reference list (6,897 codes), admin user, 3 demo products
cd ../frontend && npm install
```

> **External drive note (ExFAT):** macOS writes `._*` files on ExFAT volumes, which break Python wheel
> installs. If the repo lives on such a drive, keep the virtualenv on the internal disk:
> `uv venv ~/.venvs/trade-intel && ln -s ~/.venvs/trade-intel backend/.venv` before `uv sync`.

## Run

```bash
cd backend && uv run uvicorn app.main:app --port 8000 --reload --reload-dir app --timeout-graceful-shutdown 5
cd frontend && npm run dev      # http://localhost:5173 (proxies /api to :8000)
```

Sign in with `ADMIN_EMAIL` / `ADMIN_PASSWORD`. Open a product → **Load UN Comtrade data** (≈2 min) →
explore markets → research companies → ask the analyst → generate and export the brief.

## Environment variables

| Variable | Required | Purpose |
|---|---|---|
| `DATABASE_URL` | yes | SQLAlchemy URL (`postgresql+psycopg://…`) |
| `JWT_SECRET` | yes | Long random string used to sign sessions |
| `CORS_ORIGINS` | yes | Comma-separated frontend origins |
| `ADMIN_EMAIL`, `ADMIN_PASSWORD` | seed only | First admin account (password ≥ 10 chars) |
| `ANTHROPIC_API_KEY` | for AI | Claude API key. Without it AI features show "not configured" |
| `CLAUDE_MODEL` | no | Default `claude-haiku-5-5` (lowest cost) |
| `RESEARCH_MAX_SEARCHES` | no | Web searches per research run (cost cap), default 5 |
| `COMTRADE_SUBSCRIPTION_KEY` | no | UN Comtrade key; empty = free public preview API |
| `HOME_COUNTRY_ISO3` | no | Exporter's country (e.g. `ARE`); enables "your country's share" |
| `VITE_API_URL` | prod frontend | API base URL when frontend and API are on different hosts |

## Tests and checks

```bash
cd backend && uv run pytest && uv run ruff check app tests
cd frontend && npx tsc -b && npm run lint && npm run build
```

Backend tests use the `trade_intel_test` database (created by `docker compose`) and mock Claude, so
they run offline and cost nothing.

## Migrations

```bash
cd backend
uv run alembic revision --autogenerate -m "describe change"
uv run alembic upgrade head
```

## Deployment

Production runs as one Docker service (Railway) with Neon PostgreSQL: see `docs/DEPLOY.md` for settings,
resources and the full environment-variable list.

See `docs/HANDOVER.md` for what works, what is estimated, and what remains for production.
