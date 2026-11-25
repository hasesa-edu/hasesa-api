# hasesa-api

The Hasesa backend. Every Hasesa app (the web app, the mobile app, future
products) talks to this API, and it owns Hasesa Accounts.

- FastAPI, Python 3.12, managed with [uv](https://docs.astral.sh/uv/)
- Postgres on Neon, SQLAlchemy 2 (async), Alembic migrations
- Deployed to Google Cloud Run from GitHub Actions

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

Pushing to `main` builds the image, runs migrations and deploys to Cloud Run.
One-time setup: [docs/gcp-setup.md](docs/gcp-setup.md).

Scaling defaults (set in `.github/workflows/deploy.yml`): 80 concurrent
requests per instance, 1 vCPU / 512 MiB, 0 to 10 instances, and a database
pool of 5 + 5 per instance. Keep max instances x 10 below Neon's pooler limit.
