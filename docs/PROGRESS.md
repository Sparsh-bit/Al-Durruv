# Progress

Brief: "Build prompt: Durra Trade Intelligence Platform (Concilio)". Started 28 Oct 2026. See AUDIT.md (gap matrix)
and DECISIONS.md.

## Phase 1: audit (done)

`docs/AUDIT.md`: inventory, health check, gap matrix, security findings and plan. No secrets in git history or
in the build output. 0 known vulnerabilities in frontend and backend dependencies.

## Phase 2: security fixes (done)

* Admin-only: uploads, ETL triggers, Comtrade fetches, HS mapping changes, market lists, freight, tariffs,
  merges, alert runs.
* CSV-injection guard on every CSV/XLSX export; exports are audit-logged.
* AI rate limits (10/min per user, `LLM_DAILY_LIMIT_PER_USER` per day, monthly budget) and upload limits
  (10/min per user).
* Logins (success and failure) are audit-logged. Unexpected server errors return a generic message.

## Phase 3: schema (done)

Migration `1ebb29a98b78`: `monthly_flows`, `fx_rates`, `tariffs`, `import_batches`, `shipments` (rebuilt from an
unused stub, guarded), `retailer_requirements`, `alerts`, `briefs`; company `aliases` and `normalized_name`;
freight origin and payload; user language; HS status `discrepancy` (15 products). Tested up → down → up on a
scratch copy of the data.

## Phase 4: connectors (done)

Each source was verified against its live API before any parser was written; differences from the brief are in
DECISIONS.md (D6–D10). Recorded real responses are in `backend/tests/fixtures/` and drive the parser tests.

### Live run, 28 Oct 2026 (scratch database, the 8 hero HS codes from the brief)

| Connector | Result | Rows | Time | Notes |
|---|---|---|---|---|
| FX (Frankfurter/ECB) | succeeded | 317 daily EUR→USD rates | 1 s | |
| Eurostat Comext DS-045409 | succeeded | 63,682 monthly rows (27 EU reporters × all partners × 14 months × 8 HS codes) | 269 s | latest month 2026-08 |
| Tariffs (USITC + WITS) | live-verified; first full run stopped by a WITS timeout after 5 codes (now fixed: lookups fail one at a time) | first code: US MFN + US–Jordan FTA lines (USITC), EU MFN 17.6% (WITS, 2023 data) | ~10 min per HS code for the EU (WITS is slow) | run the remaining codes and markets from Data admin → Connectors; results are cached for 30 days |
| US Census | blocked | 0 | | needs `CENSUS_API_KEY` |
| UN Comtrade (annual) | production already loaded | 356,723 observations, 48/48 HS codes | | from 27 Oct |

## Phase 5: HS mapping, entity resolution, seed data (done)

* `discrepancy` status for client codes that point to another product family. The validator notes and the
  client's codes are never overwritten.
* Company names are normalised (case, accents, punctuation, legal suffixes, &/AND, AL/EL, a leading "The"). Matching
  needs an exact normalised name or alias. Suggestions use similarity ≥ 0.82, and an admin merges.
* Section 9 of the brief is applied as a one-time data patch:
  - competitor aliases: Chtoura Garden / Hadayek Chtoura; Heinz / Kraft Heinz
  - Levant (Jordan)
  - GCC region added; Far East placeholders marked unconfirmed
  - client shipper aliases and factory countries
  - answers to the "three countries" and molokhia questions (client-provided)
  - 7 sourced supplier requirements (Kroger ×3, Walmart ×2, FDA ×2), each URL checked live on 28 Oct 2026

## Phase 6: analytics (done)

Buyer metrics are shipments in the last 12 months, active months, median gap between shipments, 6-month trend,
origin mix with concentration (HHI), new-origin detection, and rows without weight.

| Analytic | What it does |
|---|---|
| Fit score | 6 components, adjustable weights |
| Landed cost | per origin, shown component by component, with the best factory |
| Retailer path | direct imports, routes in, requirements checklist |
| Competitor tracker | its buyers; buyers not yet the client's |
| Alerts | new importer, new origin, volume up or down, competitor gains a buyer |

## Phase 7: AI (done)

* `ANTHROPIC_MODEL_BRIEF` and `ANTHROPIC_MODEL_FAST` (both default to Haiku to protect the budget).
* English or Arabic briefs with an email draft and a WhatsApp draft.
* Every number must appear in the facts bundle. A failing draft is retried once with feedback, then rejected,
  and nothing unverified is saved.
* The prompt version and model are stored with each brief, in a history table.
* PDF export with proper Arabic shaping and right-to-left text (Noto Naskh Arabic, OFL).
* Arabic-Indic digits are checked like Western digits.

## Phase 8: UI (done)

New screens:
- Buyer finder
- Landed cost
- Alerts, with an unread badge in the top bar
- Data admin: shipment files, connectors with freshness, tariffs

Extended screens:
- **Account cards:** retailer path or competitor tracker, aliases, and the EN/AR brief
- **Overview:** freshness per source, alerts and top buyers
- **Trade explorer:** monthly-by-origin panel
- **Market intelligence:** Egypt, Jordan and Syria highlighted, with $/kg
- **Logistics:** freight per kg

## Tests and verification

* Backend: **89 passed** (`pytest`). That covers:
  - connector parsers against the recorded real responses
  - name normalisation
  - the upload pipeline: valid, malformed and duplicate files, with entity matching
  - buyer metrics and the fit score
  - competitor tracker, retailer path and requirements
  - alerts and their de-duplication
  - landed cost, best factory and overrides
  - CSV injection, admin-only roles and the daily AI limit
  - login audit
  - brief retry and rejection, the Arabic brief and its PDF
  - all earlier acceptance tests
* Frontend: `tsc` strict, `oxlint`, production build: all clean.
* Browser (in-app, against the scratch database):
  - sign in, upload a **test** shipment file (40 rows, marked TEST), and check Buyer finder
  - merge "Kroger Co" into "The Kroger Co." via suggestions, then check the retailer path (10 direct shipments,
    3 routes in, 5 requirements)
  - Data admin freshness
  - 20 routes swept with 0 console errors
* Not run: Playwright (deferred, D13) and a live AI brief. The local scratch database has no AI key, to protect
  the budget; run one EN and one AR brief in production after deploy, at about $0.01.

## Blockers / needed from the owner

* `CENSUS_API_KEY` (free) for US monthly data.
* Shipment-data licence and export files (ImportGenius, Panjiva or Volza) for Buyer finder, the competitor tracker
  and retailer imports. Without them those screens show empty states.
* Freight quotes (with cargo kg per container) from the forwarder, for landed cost.
* The client's exact legal name for "Levant" (Jordan), the 85-country list, and HS confirmations (see the client
  workspace).
* Approval to deploy: the migration runs on Neon at start-up.

## Fixes after the first live tariff run (28 Oct 2026)

* The cache key dropped any parameter whose name contained "key", so USITC `keyword` searches shared one cache
  entry. Now only real credential names are stripped. Test added.
* One WITS timeout aborted the whole tariff run. Each market and origin lookup now fails on its own, commits
  separately, and is listed as skipped. Test added.
* Several US tariff lines can sit under one HS6 (2103.90: 0–7.5%). Landed cost now uses the highest rate, lists
  the lines and says to confirm the exact line. Test added.
* Tests: 91 passed.
