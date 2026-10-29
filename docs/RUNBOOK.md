# Runbook

Operating the Durra trade-intelligence platform (Concilio Solutions). For first-time hosting see DEPLOY.md.

## Environment variables (Railway → Variables; local: `.env`, never committed)

| Variable | Required | Purpose |
|---|---|---|
| `DATABASE_URL` / `DATABASE_URL_UNPOOLED` | yes | Neon pooled URL (app) and direct URL (migrations) |
| `JWT_SECRET` | yes | 32+ random characters |
| `ENVIRONMENT` | yes | `production` on Railway |
| `ADMIN_EMAIL`, `ADMIN_PASSWORD` | first start | Creates the first admin if none exists |
| `COMTRADE_SUBSCRIPTION_KEY` | recommended | UN Comtrade keyed API (without it the free preview is used) |
| `ANTHROPIC_API_KEY` | for AI | Claude, server-side only |
| `ANTHROPIC_MODEL_FAST` | optional | Q&A and research model (default `claude-haiku-5-5`) |
| `ANTHROPIC_MODEL_BRIEF` | optional | Briefs and reports (default `claude-haiku-5-5`; `claude-sonnet-5-5` for higher quality) |
| `LLM_DAILY_LIMIT_PER_USER` | optional | AI calls per user per day (default 50). The monthly AI budget is set in Administration |
| `CENSUS_API_KEY` | for US monthly | Free key from https://api.census.gov/data/key_signup.html |
| `FEATURE_WEB_CONTEXT` | optional | `true` (default) allows AI web research for companies and news |
| `MAERSK_CONSUMER_KEY` | for Maersk | Consumer Key of your Maersk Developer Portal app with the Locations and Commodities API products enabled. The Consumer Secret is **not** needed |
| `CORS_ORIGINS`, `HOME_COUNTRY_ISO3`, `TRADE_YEARS_BACK`, `COMTRADE_*` | optional | See `backend/app/config.py` |

No key is ever sent to the browser. Error messages and logs never print keys, and cached request keys strip any
`key` parameter.

## Running the connectors (ETL)

All runs happen in the background, are logged in `refresh_runs`, and are visible under **Data admin → Connectors**
(admin only).

| Source | How | Notes |
|---|---|---|
| UN Comtrade (annual) | Products → *Load missing data*, or per product *Refresh data* | 3 requests per HS code with a key; cached |
| Eurostat Comext (EU monthly) | Data admin → Connectors → Comext, HS codes, months back | All EU-27 reporters and partners; EUR converted at the ECB monthly average |
| US Census (US monthly) | Data admin → Connectors → Census | Needs `CENSUS_API_KEY` |
| Tariffs | Data admin → Connectors → Tariffs, markets (ISO3, `EUN` = EU) | USITC for the US (line rates, Jordan FTA); WITS for others (latest available year, often 1–3 years old) |
| FX | Data admin → Connectors → FX | Daily ECB rates via Frankfurter |

From a shell (same code as the UI):

```bash
cd backend && uv run python -c "from app.db import SessionLocal; from app.models import RefreshRun; from app.services import etl; db = SessionLocal(); r = RefreshRun(adapter='comext', scope='200290'); db.add(r); db.commit(); etl.run(r.id, 'comext', {'hs_codes': ['200290'], 'months_back': 12})"
```

After every connector run or shipment upload, the alerts job runs automatically. To run it again, use
*Alerts → Check now*.

## Uploading shipment data

1. Export bills of lading from ImportGenius, Panjiva or Volza as CSV or Excel. Licence terms apply: raw rows are
   shown only to signed-in users, and there is no bulk export.
2. **Data admin → Shipment files**: choose the provider and the file, then **Preview**.
3. Check the column mapping. The date and a shipper or consignee column are required. The mapping is saved per
   provider.
4. **Import**. Duplicate rows (same provider record id, or the same row content) are skipped. Re-uploading the
   identical file is refused. Rows with problems are listed and skipped.
5. Companies are matched by normalised name (case, punctuation, legal suffixes, "&"/AND, AL/EL, a leading
   "The"). Nothing is merged on fuzzy similarity. To merge a duplicate, an admin uses
   `POST /api/companies/{id}/merge`; candidates come from `GET /api/companies/{id}/similar`. Retailer and
   competitor aliases are edited on the account card.
6. Client shipper names (used for "customers of competitors that are not ours yet") are in the
   `client_shipper_aliases` setting, seeded from `backend/data/client_setup.json`.

## Adding a tariff override

Use an override when no connector carries the rate, for example US Chapter 99 additional duties or a new trade
agreement.

**Data admin → Tariffs → Add override**: importer (ISO3, `EUN` for the EU), HS code (6–10 digits), origin (blank =
any), type (MFN / preferential / additional), ad valorem %, and a **source URL** (required). Overrides win over
connector rates for the same key; additional duties are added on top. The landed-cost page shows the source and
the "verified" date of the rate it used.

## Freight routes

**Logistics → Add quote** (admin): origin port, factory country (EGY/JOR/SYR), destination, mode, container, cost,
**cargo per container (kg)** and valid-until date. Freight is always shown as an estimate. Expired quotes are
ignored in landed cost.

## Rotating keys

1. Create the new key at the provider (Anthropic console, UN Comtrade portal, Census, Neon).
2. Update the variable in Railway → Variables (Railway redeploys automatically) and in local `.env`.
3. Revoke the old key at the provider.
4. Check **Integration health** and `/api/health`.
5. For `JWT_SECRET`, rotating it signs everyone out, which is expected.

No secrets have been found in the git history (AUDIT.md §1.4), so no rotation is outstanding.

## Deploying

Every push to `main` deploys to Railway. On start, `start.sh` runs, in order:
- `alembic upgrade head` (versioned migrations; nothing destructive without a guard)
- the seed (idempotent; client data patches are applied once)
- the API

Before pushing:

```bash
cd backend && uv run pytest -q && uv run ruff check app tests
```

```bash
cd frontend && npx tsc -b && npx oxlint && npm run build
```

Backups: Neon keeps point-in-time history on the production branch. Before a risky migration, create a branch
with `neon branches create --name pre-migration-YYYYMMDD`.

## Client data

`backend/data/client_setup.json` (profile, priorities, regions, entities, accounts, questions, patches) and
`backend/data/client_hs_list.csv` (the client's HS list exactly as given, plus analysis HS6 and findings) are loaded
by the seed. To add new client information, add a new entry under `patches` with a new `id`. It applies once and
never overwrites edits made in the app.

## Maersk reference data

* **Commodity references**: Products → open a product → *Look up in Maersk*. Candidates show the commodity code,
  name, cargo types and the HS codes Maersk lists, next to the client code and the analysis HS6.
  - Analysts save a reference; the client's code is never changed.
  - Admins can also use its HS6 for trade analysis; the status stays "needs review", with source "Maersk
    commodity reference".
* **Route locations**: Logistics → *Route locations*. Search by name, UN/LOCODE or Maersk Geo ID, then save the
  exact port or terminal. Saved locations can be attached to freight quotes as origin or destination.
* Neither API provides prices, schedules, transit times or customs rulings.
* If Maersk is unavailable or not configured, the screens say so and everything else keeps working.

### `.env.example` lines to add (names and placeholders only)

```
# Maersk Developer Portal app (Locations + Commodities). Consumer Secret is not used.
MAERSK_CONSUMER_KEY=
# Optional
ANTHROPIC_MODEL_FAST=claude-haiku-5-5
ANTHROPIC_MODEL_BRIEF=claude-haiku-5-5
LLM_DAILY_LIMIT_PER_USER=50
CENSUS_API_KEY=
FEATURE_WEB_CONTEXT=true
```
