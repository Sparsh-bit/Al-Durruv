# Handover — demo prototype (26 Oct 2026)

## The demo workflow (end to end)

1. **Products** — select a demo product or add/import your own (CSV/Excel, HS6 validated against the
   official UN Comtrade list of 6,897 codes).
2. **Market intelligence** — load UN Comtrade data (≈2 min, cached), then: reported global imports,
   growth (complete years only), top importers and supplier countries, an explainable 0–100
   opportunity ranking with adjustable weights, and a per-country drawer (trend, volume, unit value,
   supplier shares, logistics).
3. **Companies** — AI web research for buyers (importers, distributors, wholesalers, retailers, brand
   owners) or competitors in a chosen market. Each company shows its source excerpt and link; analysts
   verify/reject and build prospect lists.
4. **AI analyst** — questions answered only from platform data, each statement labelled
   Verified / Estimate / Inference / Unavailable with evidence IDs.
5. **Brief & export** — AI-written market & prospect brief with appendices (ranking, companies,
   evidence) exported as PDF or Excel.

## What works and was verified

- Real UN Comtrade data loaded for all three demo products (≈8,600 observations).
- Ranking, overview, country detail, catalogue import, auth/roles, admin, logistics quotes.
- 27 backend tests passing (calculations, provenance, adapter cache/retry/error handling, grounding
  validator, API auth, report withholding and export); ruff clean.
- Frontend: strict TypeScript, lint clean, production build OK; every page checked in a browser at
  desktop and phone width with zero console errors.

## Not yet verified live — needs the Claude API key

AI paths are implemented and tested with a mocked model, but **no real Claude call has been made**
because no `ANTHROPIC_API_KEY` is configured. After adding the key, run one research, one question and
one brief to confirm: (a) the web search tool works with `claude-haiku-5-5`, (b) structured outputs
parse, (c) costs per run. If Haiku's search quality is not good enough, set `CLAUDE_MODEL=claude-sonnet-5-5`.

## Estimated, simulated or unavailable

| Item | Status |
|---|---|
| Trade statistics | **Verified** official data (UN Comtrade), as reported by countries |
| Opportunity score | **Computed** (transparent formula, adjustable weights) — a prioritisation aid, not a forecast |
| Companies | **Candidates** from public web pages until an analyst verifies them |
| Company purchase volumes, budgets, order quantities | **Unavailable** — needs a licensed shipment provider |
| Freight costs / transit times | **Unavailable** unless entered as client-provided quotes (labelled) |
| Supplier breakdown | Loaded for the top 15 import markets only (free API limits) |

No mock data is presented as real anywhere in the application.

## Remaining for production

1. Deploy (planned: Vercel frontend, Render API, Neon Postgres). Set `VITE_API_URL`, `CORS_ORIGINS`,
   a strong `JWT_SECRET`; run `alembic upgrade head` and `python -m app.seed` on deploy.
2. Move background jobs (refresh, research) from in-process tasks to a worker queue (e.g. RQ/Celery)
   so they survive restarts and scale.
3. Add BACI as a supplementary adapter; consider a Comtrade subscription for full partner coverage.
4. Connect a shipment-data and a freight provider if the client licenses them.
5. Security hardening: password reset, login rate limiting, audit log, HTTPS-only cookies or token
   refresh, regular dependency audits.
6. Remove the local QA account (`qa@example.com`) created for browser testing.
7. Client branding (name "TradeScope" is a placeholder), dark mode, and translations if needed.
