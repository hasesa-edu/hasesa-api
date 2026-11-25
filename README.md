# hasesa-api

The Hasesa backend. Every Hasesa app (the web app, the mobile app, future
products) talks to this API, and it owns Hasesa Accounts.

- FastAPI, Python 3.12, managed with [uv](https://docs.astral.sh/uv/)
- Postgres on Neon, SQLAlchemy 2 (async), Alembic migrations
- Deployed on Vercel (Frankfurt, `fra1`, next to Neon); a `Dockerfile` keeps it portable to any container host

All routes live under `/v1`. The OpenAPI schema is at `/v1/openapi.json`;
generate typed clients for each app from it.

## Layout

```
hasesa_api/
  main.py      app factory, routers
  config.py    settings from environment variables
  db.py        async engine and per-request session
  models.py    database tables (Alembic owns the schema)
  access.py    access levels (signed-in, enrolled, guide)
  health/      /v1/health (liveness), /v1/health/ready (database)
  identity/    Hasesa Accounts: Google sign-in, tokens, sessions, /v1/me
  content/     course content: loader, validation and endpoints (see below)
content/       the modules and concept units, as Markdown (content/README.md)
alembic/       migrations
tests/
docs/          setup guides, and how apps sign in (docs/accounts.md)
```

New domains (identity, content, learning, guide, billing, ai, analytics,
admin) each get their own package with a `router.py`.

## Run locally

```sh
cp .env.example .env      # fill in DATABASE_URL and DATABASE_URL_DIRECT
uv sync
uv run uvicorn hasesa_api.main:app --reload
uv run pytest
```

Use a **Neon branch** for local work, never the production database.
Database tests are skipped unless `TEST_DATABASE_URL` points at a throwaway
database (they empty its tables); CI runs them against a fresh Postgres.

## Database

Alembic is the only tool that changes the schema. Change `hasesa_api/models.py`,
then:

```sh
uv run alembic revision --autogenerate -m "what changed"
uv run alembic upgrade head
```

The baseline migration (`0001`) adopts the database the web app built: on an
existing database it changes nothing, and on an empty one it creates the
full schema. CI builds the schema from scratch and runs `alembic check` to
confirm the models and migrations agree.

## Content

`content/` is loaded and validated once per instance; a bad file fails the
tests in CI with the file and field named. Endpoints, with the website's
access rules enforced here:

| Endpoint | Who |
|---|---|
| `GET /v1/modules`, `/v1/modules/{id}`, `/v1/concepts`, `/v1/search-index` | anyone (CDN-cached) |
| `GET /v1/concepts/{id}` | anyone if the unit is public, otherwise enrolled students and guides |
| `GET /v1/modules/{id}/steps/{step}` | enrolled students and guides |
| `GET /v1/modules/{id}/guide` | guides |
| `GET /v1/content/bundle` | the website's server only (HTTP Basic with its client secret); includes answers |
| `GET /v1/content/version` | anyone: the deployed commit and a content hash |

Problem answers and explanations are never sent to apps. After a push to
`main` that changes content, the `Content live` workflow waits for the deploy
and asks the website to refresh its cache (secrets `WEB_REVALIDATE_URL` and
`REVALIDATE_SECRET`); the website also refreshes every hour on its own.

## Deploy

Vercel deploys every push: `main` to production, pull requests to preview
URLs. The `Migrate` workflow applies migrations to production on every push to
`main`. Keep migrations additive (expand first, contract later): code and
migration go live at about the same time, and the web app shares the database.
One-time setup: [docs/vercel-setup.md](docs/vercel-setup.md).

On Vercel, `DB_NULL_POOL=true` opens one connection per request through
Neon's pooler instead of keeping a pool in a serverless instance. On a
long-running container host, leave it off and use the pool (5 + 5 per
instance; keep instances x 10 below Neon's pooler limit).
