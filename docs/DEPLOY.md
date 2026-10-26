# Deploying to Railway + Neon

One Railway service runs everything: the Docker image builds the React app and FastAPI serves it together
with the API on the same domain. Neon provides PostgreSQL.

## 1. Neon (database)

1. Create project → **Region: AWS Asia Pacific 1 (Singapore)** (same region as the Railway service).
2. Services: keep **Postgres database** only. Turn **off** Functions, AI gateway, Realtime and Better Auth
   (the app has its own login and calls Claude directly). Object storage: off.
3. The project is linked in this repo (`neon.ts`, project `crimson-moon-36265168`, branch `production`).
   `neon env pull` writes `DATABASE_URL` (pooled) and `DATABASE_URL_UNPOOLED` (direct); copy both into Railway.
   The app uses the pooled URL (prepared statements disabled for PgBouncer); Alembic uses the direct one.

The production branch already holds the schema, the 127 Durra products, the loaded trade data, researched
companies and the admin account. On each start the app runs pending migrations; the seed skips what exists.

## 2. Railway (app)

**Service → Settings**

| Setting | Value |
|---|---|
| Source | GitHub repo `Sparsh-bit/Al-Durruv`, branch `main` |
| Builder | Dockerfile (picked up automatically from `railway.json`) |
| Region | Southeast Asia (Singapore) |
| Replicas | **1** (background jobs run in-process; more replicas would duplicate them) |
| Replica limits | **1 vCPU, 1 GB memory** (measured: ~175 MB idle; a few hundred MB peak during data loads and PDF exports) |
| Healthcheck path | `/api/health` (set by `railway.json`; it also checks the database) |
| Serverless / app sleeping | **Off** (data loading and AI research run in the background) |
| Networking | **Generate Domain** (public HTTPS URL), target port = the `PORT` Railway provides |

**Service → Variables**: see the full list below.

Deploy. The first start takes about a minute (migrations + HS list). Open the generated domain and sign in with
`ADMIN_EMAIL` / `ADMIN_PASSWORD`.

## 3. Environment variables (Railway → Variables)

| Variable | Required | Value |
|---|---|---|
| `ENVIRONMENT` | yes | `production` (already set in the image; harmless to set again) |
| `DATABASE_URL` | yes | Neon **pooled** connection string (host contains `-pooler`), as written by `neon env pull` |
| `DATABASE_URL_UNPOOLED` | yes | Neon **direct** connection string, used for migrations on start |
| `JWT_SECRET` | yes | 64 random hex characters, e.g. output of `openssl rand -hex 32`. Never reuse the local one |
| `ADMIN_EMAIL` | only for an empty database | First admin account (the Neon production branch already has `admin@aldurra.com`) |
| `ADMIN_PASSWORD` | only for an empty database | 8+ characters; ignored once an admin exists |
| `ANTHROPIC_API_KEY` | for AI | Your Claude API key |
| `CLAUDE_MODEL` | no | `claude-haiku-5-5` (default; cheapest) |
| `RESEARCH_MAX_SEARCHES` | no | `5` (web searches per research run; lower = cheaper) |
| `COMTRADE_SUBSCRIPTION_KEY` | recommended | **Primary** key from comtradeplus.un.org → My API portal. With it each product code loads in 3 requests (all years at once, supplier breakdown for every market) instead of ~13, within the free 500 requests/day. The Secondary key shares the same quota; keep it for rotation |
| `HOME_COUNTRY_ISO3` | no | `SYR` (also editable in Administration) |

`PORT` is provided by Railway; do not set it. `CORS_ORIGINS` and `VITE_API_URL` are not needed because the
app and API share one domain.

## 4. After the first deploy

1. Administration → set the **monthly AI budget** (e.g. `8`) and enter the **export markets**.
2. Product catalogue → **Load missing data** to start loading UN Comtrade statistics.
3. Create user accounts for the team (Administration → Users); avoid sharing the admin login.

## Notes

- Redeploys keep all data (it lives in Neon). Background jobs interrupted by a redeploy are marked
  "Interrupted"; press **Load missing data** again.
- The app refuses to start in production with a weak `JWT_SECRET` or a localhost `DATABASE_URL`.
- Security: HTTPS (Railway), HSTS, strict Content-Security-Policy, login rate limiting (10 failed attempts per
  15 minutes), API docs disabled, non-root container user.
