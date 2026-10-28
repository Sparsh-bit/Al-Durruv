# Decisions

Each entry records a decision made while building the platform, with its reason. Newest last.

| # | Date | Decision | Reason |
|---|---|---|---|
| D1 | 2026-10-28 | Keep the existing stack: FastAPI (Python 3.13) + SQLAlchemy/Alembic + Neon Postgres + React/Vite/TypeScript. The Next.js/Supabase default stack in the brief is not used. | The brief says to keep a reasonable existing stack. This one already has auth, migrations, tests and a deployed production. |
| D2 | 2026-10-28 | Stay on Postgres; no move to MongoDB (owner's choice). | The analytics are relational (shares, CAGR, landed cost, buyer metrics). A rewrite would put the 1 Dec launch at risk. |
| D3 | 2026-10-28 | Multi-tenancy (`organizations`, `org_id` on every table, Postgres RLS) is **deferred**. | Single tenant (Durra) for v1. Authorisation is enforced server-side on every route. Adding RLS needs a per-request DB role and setting, and touches every query and job; it would put the launch at risk. Migration path in AUDIT.md §1.5. |
| D4 | 2026-10-28 | Roles stay `admin` / `analyst` / `viewer` (the brief's `sales` maps to `analyst`: works accounts, runs research and briefs). Uploads, ETL triggers, tariffs, freight, HS mappings and market lists are **admin-only**. | Matches the brief's permission rule without renaming existing roles in production. |
| D5 | 2026-10-28 | `ANTHROPIC_MODEL_BRIEF` and `ANTHROPIC_MODEL_FAST` env vars; **both default to `claude-haiku-5-5`**. | The owner asked for the lowest AI cost (about $9 of credit). Set `ANTHROPIC_MODEL_BRIEF=claude-sonnet-5-5` to follow the brief's default when budget allows. |
| D6 | 2026-10-28 | US Census International Trade API **requires a key** (`CENSUS_API_KEY`). | Live check: requests without a key are redirected to `missing_key.html`. The brief said the key was optional. |
| D7 | 2026-10-28 | Eurostat Comext dataset `DS-045409` ("EU trade since 1988 by HS2-4-6 and CN8"), statistics API `.../comext/dissemination/statistics/1.0/data/DS-045409`, JSON-stat 2.0, indicators `VALUE_IN_EUROS`, `QUANTITY_IN_100KG`, flow `1` = import. Months are requested explicitly. | `lastTimePeriod` returns empty future months; `sinceTimePeriod` is rejected (HTTP 400). |
| D8 | 2026-10-28 | FX from `https://api.frankfurter.dev/v1` (ECB). | `api.frankfurter.app` now redirects (301). |
| D9 | 2026-10-28 | WITS (UNCTAD TRAINS): find the latest year with an MFN rate (stepping back up to 5 years), then one preferential request per origin for that same year. EU = reporter `918`. The US uses USITC only. | Data lags 1–3 years; a missing year returns 404 "NoRecordsFound". Stepping back for every origin cost dozens of slow calls per code. |
| D10 | 2026-10-28 | USITC HTS gives US general/special rates per line. Chapter 99 additional duties are **not** included, so they must be entered as admin overrides. | Live response for 2002.90 lists general 11.6% and special "Free (… JO …)" only. |
| D11 | 2026-10-28 | HS status values kept as `confirmed` / `candidate` / `insufficient_info` / `unmapped`, plus `discrepancy`. The UI shows `candidate` as "Needs review". | Maps the brief's `needs_review` / `discrepancy` onto the existing data without renaming stored values. |
| D12 | 2026-10-28 | Freight routes reuse the existing `logistics_quotes` table (adds origin ISO3 and payload kg), always labelled estimate. | Avoids a parallel table holding the same facts. |
| D13 | 2026-10-28 | Playwright end-to-end suite is deferred. The smoke path is verified with the in-app browser and recorded in PROGRESS.md. | Avoids adding a browser-download toolchain to CI before launch. |
