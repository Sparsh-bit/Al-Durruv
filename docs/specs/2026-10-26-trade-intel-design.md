# Global Trade Intelligence & Buyer Discovery Platform — Design

Status: approved for build (2026-10-26). Demo runs locally; production target later is Vercel (UI) + Render (API) + Neon (Postgres).

## Decisions

| Topic | Decision |
|---|---|
| Stack | FastAPI (Python 3.13) + PostgreSQL 16 + React 19 (Vite, TypeScript, Tailwind) |
| Trade statistics | UN Comtrade via official `comtradeapicall` (MIT). Free preview without key; subscription key optional |
| Company discovery | Claude web search with source URLs; only companies tied to a retrieved URL are stored |
| AI model | `claude-haiku-5-5` (cheapest). Single setting `CLAUDE_MODEL` |
| Shipments / freight | Adapter stubs, shown as "Not connected". No values invented |
| Demo products | Sweet biscuits 190531, toilet soap 340111, shampoo 330510 |

Source repo review: `comtradeapicall` used as dependency. `DrPrettyman/comtrade`, `devbret/baci-data` (MIT) not reused: no code beyond what the official client gives. `SupplyGraphAI` (Apache-2.0): pattern only (deterministic numbers, AI writes cited claims); no code copied. `hs-code-classifier`: empty repo. BACI (CEPII, Etalab licence) is a later supplementary source.

## Data model (separation of country vs company data)

- `users` (email, password_hash, role: admin|analyst|viewer)
- `products` (sku, name, description, hs_code → `hs_codes`)
- `hs_codes` (code HS6, description)
- `countries` (m49 code, iso3, name)
- `source_records` — provenance for every external fact: adapter, url, request params, retrieved_at, reporting_period, licence note
- `trade_observations` — COUNTRY-LEVEL only: reporter, partner (0 = World), hs_code, flow (M/X), year, value_usd, net_weight_kg, qty, qty_unit, source_record_id
- `companies` (name, country, website, roles[], review_status: candidate|verified|rejected)
- `company_evidence` (company_id, url, title, excerpt, retrieved_at, source_record_id)
- `shipments` — COMPANY-LEVEL, only from a licensed provider (empty until connected)
- `market_opportunities` — computed scores per (hs_code, country, computed_at) with component breakdown JSON
- `prospect_lists` / `prospect_list_items`
- `reports` (hs_code, content JSON with statements + labels, created_by)
- `api_cache` (key hash, adapter, response JSON, fetched_at, expires_at)
- `refresh_runs` (adapter, started/finished, status, rows, error)

## Opportunity score (deterministic, explainable)

Per importing country for one HS6, using that country's latest reported year (World partner):
- Market size: log10(import value), min-max scaled across candidates — weight 35
- Growth: CAGR over up to 4 years — weight 25
- Openness: 1 − HHI of supplier countries (latest year, top markets only) — weight 20
- Price level: unit value USD/kg vs median of candidates — weight 10
- Data quality: years of data available / 5 — weight 10
Missing component → excluded and weights renormalised; shown as "unavailable". Weights editable per request. Every component value and its source period is returned.

## AI grounding

1. Python builds a context pack; every fact gets an ID `E<n>` linked to a `source_record`.
2. Claude returns structured JSON: statements `{text, label: verified|estimate|inference|unavailable, evidence_ids[]}`.
3. Validator: unknown IDs removed; "verified" with no IDs downgraded to "inference"; any number in a statement not found in its cited evidence → statement flagged `unsupported_number`.
4. No API key → AI endpoints return 503 "AI not configured"; rest of app works.

Company research: Claude + `web_search` returns candidates as JSON; each `source_url` must be one of the URLs the search tool actually returned, else the candidate is dropped. Stored as `candidate` until a user verifies.

## Integration behaviour

All adapters: DB cache with TTL, minimum interval between calls (rate limit), 3 retries with exponential backoff, errors recorded in `refresh_runs`. `comtradeapicall` prints errors and returns None — adapter captures stdout and raises a typed error.

## UI pages

Login · Products (list, add, CSV/Excel import) · Market dashboard (per product: KPIs, trend, top importers map/table, ranking with score breakdown, top exporters/competitor countries, transport-mode share if reported) · Companies (research, evidence, verify/reject) · AI analyst (chat with cited answers) · Reports (generate brief, view labels, export PDF/XLSX) · Admin (data sources, refresh history, users).

## Testing

pytest: scoring maths, CAGR/HHI/unit value, provenance on every observation, adapter error/retry/cache, AI validator (unknown IDs, unsupported numbers, label downgrade), API auth. Frontend: TypeScript strict build, ESLint, browser check of the full workflow with zero console errors.
