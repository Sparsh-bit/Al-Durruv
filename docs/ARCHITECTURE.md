# Architecture

## Layers

```
Browser (React SPA, same origin; CSP connect-src 'self')
  │  JWT session; never sees a provider key
FastAPI backend (Railway) ── routers → services → connectors
  │                                       │
  │                                       ├─ official APIs: UN Comtrade, Eurostat Comext, US Census,
  │                                       │  WTO Timeseries, WITS, USITC, Frankfurter (ECB), Maersk reference
  │                                       └─ self-hosted: auto-sea-way (private network, X-Api-Key)
  └─ Postgres (Neon): facts + source_records (provenance) + api_cache + jobs
```

## How the data stays real

* **No invented figures.** Every number on screen is read from a stored row that links to a `source_records`
  entry (URL, query, period, licence, retrieval time). With no row, the UI says "no data". Estimates
  (landed cost, sailing time) are labelled and state their assumptions.
* **Deterministic checks, not AI.** Values are checked by code: HS codes against the HS master, ranges,
  units, and one rate per importer, code, origin and type. Claude never decides whether a number is true. It
  only explains evidence it is given, within a daily budget (D24).
* **Freshness.** Each source has a maximum age and, for monthly trade, a maximum period lag. Stale sources are
  flagged on Overview and in Data admin (D23).

## How it stays up

| Failure | What happens |
|---|---|
| A provider is slow or down | Timeouts and bounded retries on every connector, plus a circuit breaker on the shared HTTP client (Comtrade, Comext, Census, WITS, USITC, FX). The last cached response is used where it is still valid. The screen names the source that is unavailable. |
| A provider rate limit | Client-side pacing below the published limits, and responses cached in `api_cache`. |
| One lookup fails in a batch | That lookup is recorded as failed; the rest of the run continues. |
| auto-sea-way is down or loading | The sea-route panel shows the reason. Nothing else depends on it. |
| A long job dies | Jobs write a heartbeat. A job with no heartbeat is shown as failed, not "running" forever. |
| A bad deploy | Railway health check on `/api/health`. Alembic migrations are tested up → down → up before release. |

## Security

* Keys exist only in server environment variables. They are sent as headers, not URL parameters, and are
  stripped by exact name from cached request records and logs.
* Role-based access (viewer, analyst, admin). Admin actions are written to the audit log.
* Security headers on every response: CSP, HSTS, X-Content-Type-Options, Referrer-Policy, Permissions-Policy, COOP.
* auto-sea-way has no public domain. It is reached only on the private network with a shared key.

## Known limits

* WTO and WITS tariffs lag 1–3 years. US Chapter 99 duties need admin overrides.
* Sea routes have no depth, ice or schedule data. Sailing time is speed-based only.
* There is no per-origin preferential rate from WTO; origin preferences come from WITS.
