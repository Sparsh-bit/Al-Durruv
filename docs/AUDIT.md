# Phase 1 audit (brief: "Durra Trade Intelligence Platform (Concilio)")

Audited 28 Oct 2026 at commit `9594a51` (production on Railway + Neon). The final gap matrix is in §1.3 and is
updated as work lands (see PROGRESS.md).

## 1.1 Inventory

| Area | Finding |
|---|---|
| Backend | Python 3.13, FastAPI, SQLAlchemy 2, Alembic, psycopg 3, pydantic-settings, PyJWT, argon2 (pwdlib), pandas/openpyxl, reportlab, httpx, `comtradeapicall`, `anthropic` SDK. Package manager `uv` |
| Frontend | React 19, Vite 8, TypeScript (strict), Tailwind v4, TanStack Query, react-router 8, Radix, Recharts, sonner, framer-motion (Lightswind components), anime.js. Lint with oxlint |
| Database | Postgres (Neon, production branch, AWS Singapore). 6 Alembic migrations. Seed `python -m app.seed` (HS list, countries, admin, catalogue, client data files) |
| Auth | JWT bearer (Authorization header, not cookies), argon2 hashes, roles `admin` / `analyst` / `viewer`, login rate limit 10 failures per 15 min |
| Hosting | Single Docker image on Railway (`start.sh`: migrate → seed → uvicorn). Health check `/api/health` |
| Tests | pytest (71), against a local Postgres test database. No CI workflow |
| CI | None |

Directory map:

* `backend/app/adapters`: UN Comtrade adapter (cache, throttle, typed quota errors), stubs for unconnected sources
* `backend/app/ai`: Claude client, grounding/evidence builder and number validator, usage/cost
* `backend/app/routers`: HTTP API (auth, catalogue, markets, companies, ai, reports, admin, client)
* `backend/app/services`: trade ETL and queries, research, jobs (heartbeat), settings, explore, opportunities, client data loader, audit
* `backend/data`: catalogue CSV, client HS list, client setup JSON · `backend/static/catalogue`: catalogue page images
* `backend/alembic`: migrations · `backend/tests`: pytest suites and fixtures
* `frontend/src/pages`: screens · `components`: UI kit, layout, drawers, charts · `lib`: API client, auth, types, motion

Screens (all read live API data; none use mock data):
Login · Overview · Products & HS codes · Product workspace (Market intelligence, Buyers & competitors,
AI advisor, Market brief) · Trade explorer · Markets & regions · Private-label engine · Retailers & competitors
· CRM pipeline · Questions & entities · AI reports · Logistics · Integration health · Administration.

API routes (auth level): 66 routes. Public: `POST /api/auth/login`, `GET /api/health`, `GET /api/branding`
(client display name only). All others need a signed-in user. Writes need `analyst`; users, settings, regions,
runs, AI usage and audit log need `admin`. Full list: `backend/app/routers/*.py`.

Environment variables used in code: `ENVIRONMENT`, `DATABASE_URL`, `DATABASE_URL_UNPOOLED`, `JWT_SECRET`,
`JWT_TTL_MINUTES`, `CORS_ORIGINS`, `FRONTEND_DIST`, `ADMIN_EMAIL`, `ADMIN_PASSWORD`, `ANTHROPIC_API_KEY`,
`CLAUDE_MODEL`, `RESEARCH_MAX_SEARCHES`, `COMTRADE_SUBSCRIPTION_KEY`, `COMTRADE_MIN_INTERVAL_S`,
`COMTRADE_CACHE_TTL_HOURS`, `TRADE_YEARS_BACK`, `HOME_COUNTRY_ISO3`. No frontend variable holds a secret (only the
optional `VITE_API_URL`). `.env` is git-ignored; `.env.example` holds names and placeholders only.

Dependency audit: `npm audit --omit=dev` → 0 vulnerabilities; `pip-audit` → no known vulnerabilities.

## 1.2 Health check (at audit time)

| Check | Result |
|---|---|
| Install (uv sync, npm ci) | OK |
| Type-check (`tsc -b`) | OK, 0 errors |
| Lint (`ruff`, `oxlint`) | OK, 0 findings |
| Build (`vite build`) | OK |
| Tests (`pytest`) | 71 passed |
| Local boot + every route | 16 screens loaded, 0 console errors, no overflow at 375 px |
| Production | `/api/health` ok; 146 products; 48/48 HS codes loaded; 356,723 observations |

## 1.3 Gap matrix (requirements in sections 3–8)

`Done` / `Partial` / `Missing` / `Deferred`. The "Work" column says what this round does.

| Req | Item | Status at audit | Work |
|---|---|---|---|
| 3.1 | UN Comtrade connector (annual, batching, cache, quota) | Done (annual; key mode) | Monthly Comtrade not added: Census/Comext cover monthly for priority markets |
| 3.2 | US Census monthly HS10 imports | Missing | Build connector; **blocked on `CENSUS_API_KEY`** (D6) |
| 3.3 | Eurostat Comext monthly CN8 | Missing | Build connector (D7) |
| 3.4 | Tariffs: WITS + USITC + admin overrides with `verified_at` | Missing | Build `tariffs` table, both connectors, overrides UI |
| 3.5 | Shipment-level data: file import with column mapping, saved mappings, preview, validation, dedupe, error report, provider interface | Missing (empty `shipments` stub) | Build pipeline + `import_batches` |
| 3.6 | FX (Frankfurter) with stored rate/date | Missing | Build connector; store rate per value |
| 3.7 | Freight table (estimate, valid-until); Maersk optional | Partial (`logistics_quotes`) | Add origin/payload, label estimate (D12); Maersk deferred (flag) |
| 3.8 | Company web context behind flag | Partial (AI web research exists, on demand) | Add `FEATURE_WEB_CONTEXT` flag |
| 3.1a | HS mapping: declared vs analysis code, validator, never overwrite | Done (previous round) | Add `discrepancy` status (D11) |
| 3.2a | Entity resolution: normalisation, aliases, fuzzy threshold, merge/split UI | Missing | Build normaliser, aliases, suggestions, admin merge |
| 4.1 | Overview: priorities, markets, freshness per source, alerts, top buyers | Partial | Add per-source freshness, alerts, top buyers |
| 4.2 | Market Radar: importers, CAGR, monthly trend, supplier shares (EGY/JOR/SYR vs competitors), $/kg by origin, region filter incl. GCC | Partial (annual; no origin highlight; no monthly) | Add origin highlight, monthly series, GCC region |
| 4.3 | Market Access & Landed Cost, best factory | Missing | Build |
| 4.4 | Buyer Finder + private-label fit score (adjustable weights) | Missing (AI web research only) | Build on shipment data |
| 4.5 | Path to Retailer + requirements checklist (admin-editable, sourced) | Partial (accounts, onboarding links) | Add shipment view, supply routes, checklist |
| 4.6 | Competitor Tracker | Partial (records only) | Build on shipment data |
| 4.7 | Account Brief EN/AR, email + WhatsApp draft, PDF | Partial (EN brief + email) | Add Arabic (RTL), WhatsApp, history, PDF |
| 4.8 | Alerts job | Missing | Build |
| 4.9 | Data admin (uploads, mappings, tariffs, freight, competitors/targets, ETL logs, refresh) | Partial | Build *Data admin* page |
| 4.10 | Settings & users, language preference, i18n-ready | Partial (users) | Add language preference; AI output language |
| 5 | AI: model env vars, facts bundle with IDs, structured output, number guard, retry once, injection defence, caching, per-user/org limits, `llm_usage`, prompt_version | Partial (no env models, no per-user limit, no retry, no prompt_version) | Add |
| 6 | Analytics definitions with tests (size, share, CAGR, unit value with exclusions, landed cost, buyer metrics, HHI, switches) | Partial (annual market metrics) | Add landed cost, buyer metrics, unit-value exclusion counts |
| 7 | Security checklist | Partial | See §1.4 |
| 8 | Tests, live ETL run, RUNBOOK | Partial | Add tests, run connectors live, write RUNBOOK |
| 2.3 | `organizations`, `org_id`, RLS | Missing | **Deferred** (D3) |

UI without backend: none. Backend without UI: `GET /api/sources/{id}` (used in drawers), prospect-list export
(used on Companies).

## 1.4 Security findings

| Sev | Finding | Where | Fix |
|---|---|---|---|
| High | Uploads, ETL triggers and market-list edits allowed for `analyst`; the brief requires `admin` | `routers/catalogue.py` (import, hs-review), `routers/markets.py` (refresh, explore/fetch), `routers/client.py` (target markets), `routers/admin.py` (logistics) | Require admin (D4) |
| Medium | CSV exports do not neutralise cells starting `=,+,-,@` (CSV injection) | products, companies, prospect lists, opportunities exports | Shared sanitiser on every export |
| Medium | No rate limit on AI and upload endpoints (budget cap only) | `routers/ai.py`, `companies.py`, `reports.py`, uploads | Per-user daily AI limit + per-minute limiter |
| Medium | Unhandled exceptions could return framework error text | `main.py` | Generic 500 handler, details logged server-side |
| Low | Logins and exports not in `audit_log` | `routers/auth.py`, exports | Record them |
| Low | No multi-tenant isolation (RLS) | schema | Deferred (D3); single tenant |
| Info | Bundle contains the variable *name* `ANTHROPIC_API_KEY` in a help message, no value | `frontend/dist` | None needed |
| Info | Git history contains only the placeholder `JWT_SECRET=change-me…` from `.env.example`; no real secret found | history scan | None. No rotation needed |
| Info | CSRF: not applicable (bearer token in header, no auth cookies) | — | Documented |

## 1.5 Plan

1. Security fixes (§1.4).
2. Schema: tariffs, monthly flows, FX rates, shipments (extended), import batches, aliases, retailer requirements, alerts, briefs, LLM limits.
3. Connectors: Comext → Census (key) → WITS/USITC → Frankfurter; then the shipment upload pipeline; then freight fields.
4. HS `discrepancy` status, entity resolution, seed updates (§9 of the brief).
5. Analytics: landed cost, buyer metrics, fit score, competitor and retailer views, alerts job.
6. AI: env models, Arabic, WhatsApp, retry, limits, prompt version.
7. UI: Market Radar additions, Market Access, Buyer Finder, Path to Retailer, Competitor Tracker, Alerts, Data admin.
8. Hardening, tests, live connector run, RUNBOOK, PROGRESS.

RLS migration path (deferred, D3): add `organizations` and `org_id` (default the Durra org); connect the app as a
non-owner role; set `app.org_id` per request in a SQLAlchemy `after_begin` hook; enable `FORCE ROW LEVEL SECURITY`
with policy `org_id = current_setting('app.org_id')::int`; give background jobs an explicit org.


## 1.6 Final gap matrix (after implementation, 28 Oct 2026)

| Req | Item | Final status | Where |
|---|---|---|---|
| 3.1 | UN Comtrade connector | Done | `adapters/comtrade.py`, `services/trade.py` |
| 3.2 | US Census monthly | Done (code + tests); **live run blocked on `CENSUS_API_KEY`** | `connectors/sources.py::load_census` |
| 3.3 | Eurostat Comext monthly CN8 | Done, live-verified | `connectors/sources.py::load_comext` |
| 3.4 | Tariffs: WITS + USITC + admin overrides with `verified_at` | Done, live-verified | `connectors/sources.py`, `routers/intel.py` (`/api/tariffs`), Data admin → Tariffs |
| 3.5 | Shipment file import (mapping, saved mappings, preview, validation, dedupe, error report, provider interface) | Done | `services/shipments.py`, `/api/shipments/*`, Data admin → Shipment files |
| 3.6 | FX with stored rate/date | Done, live-verified | `fx_rates`, `monthly_flows.fx_rate` |
| 3.7 | Freight table (estimate, valid-until) | Done; Maersk deferred (flag off, no key) | `logistics_quotes` + origin/payload |
| 3.8 | Company web context behind flag | Done (`FEATURE_WEB_CONTEXT`) | `config.py` |
| 3.1a | HS mapping/validator incl. discrepancy | Done | `routers/catalogue.py::hs_check`, migration `1ebb29a98b78` |
| 3.2a | Entity resolution + merge | Done (exact normalised match, suggestions ≥ 0.82, admin merge, aliases) | `services/shipments.py`, `/api/companies/{id}/similar|merge|aliases` |
| 4.1 | Overview incl. freshness per source, alerts, top buyers | Done | `pages/Overview.tsx`, `/api/admin/freshness` |
| 4.2 | Market Radar (shares with EGY/JOR/SYR highlighted, $/kg by origin, monthly, regions incl. GCC) | Done | Market intelligence, Trade explorer (monthly panel) |
| 4.3 | Market Access & landed cost, best factory | Done | `services/intel.py::landed_cost`, page *Landed cost* |
| 4.4 | Buyer Finder + fit score with adjustable weights | Done | `services/intel.py::buyers`, page *Buyer finder* |
| 4.5 | Path to Retailer + sourced requirements checklist | Done | `/api/retailers/{id}/path`, account cards |
| 4.6 | Competitor Tracker ("customers of competitors not yet ours") | Done | `/api/competitors/{id}/tracker`, account cards |
| 4.7 | Account Brief EN/AR, email + WhatsApp, PDF, history | Done | `routers/companies.py`, `reports.py::render_company_brief_pdf`, `components/AccountBrief.tsx` |
| 4.8 | Alerts job | Done (after every ETL run and upload; dedupe keys) | `services/intel.py::generate_alerts`, page *Alerts* |
| 4.9 | Data admin | Done | page *Data admin* |
| 4.10 | Settings, users, language preference | Done (AI output language per user; UI English, i18n-ready strings in components) | `PATCH /api/auth/me` |
| 5 | AI layer (env models, facts bundle, structured output, number guard with one retry, injection defence, caching, per-user limits, prompt version) | Done | `ai/claude.py`, `ai/grounding.py`, `ai/usage.py` |
| 6 | Analytics definitions with tests | Done (market size/share/CAGR/HHI existing; unit value with exclusion counts; landed cost; buyer metrics; switches) | `analytics.py`, `services/intel.py`, `tests/test_intel.py` |
| 7 | Security checklist | Done except multi-tenant RLS (deferred, D3) | see below |
| 8.3 | Playwright smoke | Deferred (D13); the same path was driven in the in-app browser | PROGRESS.md |
| 2.3 | Organisations / RLS | Deferred (D3) | AUDIT.md §1.5 |

Security checklist (section 7):

* Secrets in env only; `.env` ignored; no secrets in git history; build output contains no secret values. **Done**
* Auth on every route except login, health and branding (display name); server-side role checks. **Done**; RLS deferred
* Admin-only uploads, ETL triggers, tariffs, freight, HS mappings, market lists, users. **Done** (tests in `test_intel.py::test_roles_admin_only_actions`)
* Validation on every input (pydantic); parameterised queries (SQLAlchemy). **Done**
* Uploads: type/size/row limits, values-only parsing, CSV-injection guard on every export. **Done**
* Rate limits: login, AI (per-minute + daily per user + monthly budget), uploads. **Done**
* Security headers (CSP, HSTS, frame-ancestors, Referrer-Policy, nosniff). **Done**; bearer tokens, so CSRF does not apply
* Generic user-facing errors; details logged without secrets. **Done**
* Audit log: logins (success/failure), uploads, edits, exports, merges, brief generation, ETL runs. **Done**
* Dependency audit: 0 known vulnerabilities (npm audit, pip-audit). **Done**
* External calls: timeouts, retries with backoff, circuit breaker, cache, Comtrade quota handling. **Done**
* Versioned migrations; the shipments-table replacement refuses to run if the table holds data. **Done**
