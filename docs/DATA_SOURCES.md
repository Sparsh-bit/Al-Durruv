# Data sources, provenance and dependencies

## Principles enforced in code

| Rule | Where |
|---|---|
| Country-level statistics and company-level records live in separate tables | `trade_observations` vs `companies` / `company_evidence` / `shipments` (`backend/app/models.py`) |
| Every external fact has provenance (URL, retrieval time, reporting period, licence) | `source_records`; FK from observations and company evidence |
| Numbers are computed deterministically in Python, never by the AI | `backend/app/analytics.py`, `backend/app/services/trade.py` |
| AI may only cite supplied evidence; numbers must match cited evidence | `backend/app/ai/grounding.py` (`validate_statements`) |
| Failed statements are never exported to the client | `backend/app/reports.py` (`client_statements`) |
| No invented companies: each must trace to a URL the search tool returned | `backend/app/services/research.py` (`validate_candidates`) |
| Unavailable data is shown as unavailable | `backend/app/adapters/stubs.py`, UI "Not connected" states |

## Integrated sources

### UN Comtrade — country-level trade statistics (connected)
- **Client:** official `comtradeapicall` (MIT) wrapped by `backend/app/adapters/comtrade.py`.
- **Mode:** free public preview API by default (no key, max 500 records/request). Set
  `COMTRADE_SUBSCRIPTION_KEY` to switch to the subscription endpoint automatically.
- **Data pulled per HS6:** annual imports and exports, all reporters, partner World, last 6 years.
  Supplier-country breakdown: with a subscription key, every importing country (one request);
  without a key, the 10 largest import markets.
- **Resilience:** Postgres cache (7-day TTL, `api_cache`), 1.5 s minimum interval between calls,
  3 attempts with exponential backoff. The client prints errors and returns `None`; the adapter
  captures that output and raises `ComtradeError`, recorded in `refresh_runs`.
- **Caveats shown in the UI:** totals are the sum of *reported* imports (non-reporters missing);
  years with < 80% of usual reporters are marked partial and excluded from growth rates.
- **Licence:** UN Comtrade Terms of Use. Redistribution of bulk data may require a licence; the
  report cites the source and retrieval date.

### Public web pages — company discovery (connected when `ANTHROPIC_API_KEY` is set)
- Claude (`claude-haiku-5-5`) with the Anthropic **web search** server tool, capped at
  `RESEARCH_MAX_SEARCHES` searches per run; results cached 7 days per market/role.
- Companies are kept only if their `source_url` is among URLs the search actually returned; the
  page is re-fetched to check the company name appears. All start as **candidate** until an analyst
  verifies them.
- Stored per company: source URL, page title, quoted excerpt, retrieval date.
- Content remains the property of each publisher; we store short excerpts and links only.

## Evaluated, not yet integrated

| Source | Use | Status / licence |
|---|---|---|
| CEPII **BACI** | Reconciled bilateral flows (fills non-reporters via mirror data) | Free for research; Etalab Open Licence 2.0. Large annual CSV bulk download → add as a second adapter writing to `trade_observations` with its own `source_records`. |
| `DrPrettyman/comtrade`, `devbret/baci-data` (MIT) | Reviewed | No code reused: the official client covers fetching; the BACI repo is a visualiser. |
| `mercer14k/SupplyGraphAI` (Apache-2.0) | Reviewed | Pattern adopted (deterministic numbers, AI writes cited claims); no code copied. |
| `kgeyyas/hs-code-classifier` (MIT) | Reviewed | Repository contains only a README; nothing to reuse. HS lookup uses the official UN Comtrade HS reference list. |

## Missing data dependencies and subscriptions

| Need | Why | Options | Approx. cost |
|---|---|---|---|
| **Claude API key** (required for AI) | Analyst, briefs, company research | console.anthropic.com | Haiku 5.5: $0.10 / $0.50 per M tokens + per-search fee; demo < $10 |
| UN Comtrade subscription key (recommended) | Higher limits, full partner breakdowns for all markets | comtradeplus.un.org | Free tier key available; premium tiers paid |
| Company shipment data (bill of lading) | Real importer names, volumes, suppliers per company | ImportGenius, Panjiva (S&P), Volza | ~$1k–10k+/yr |
| Freight rates & transit times | Landed-cost and route comparison | Freightos API, Searates | Usage / subscription based |
| Company firmographics (optional) | Size, revenue, contacts | Kompass, Dun & Bradstreet, OpenCorporates | Subscription |

Adapters for shipments and freight exist as **stubs** (`backend/app/adapters/stubs.py`) that report
"not connected"; adding a provider means implementing one module that writes `shipments` /
`logistics_quotes` rows with a `source_records` entry — no schema change.
