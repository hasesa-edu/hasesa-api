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
  health/      /v1/health (liveness), /v1/health/ready (database)
alembic/       migrations
tests/
docs/          setup guides
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
