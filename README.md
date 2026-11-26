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
  learning/    answers, test-outs, steps, enrolments, progress, certificates
  guide/       the guide's tracker and tools (feedback, assignments, flags, sign-offs)
  admin/       admin tools (enrol by hand, set roles, subscribers)
  billing/     Chapa checkout, payment checks, webhook, enrolment days
  ai/          the lab assistant: page context, prompt, streaming, daily caps
  analytics/   page views (recorded for the website's server) and the /admin stats
  internal/    scheduled jobs (Vercel Cron)
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

Problem answers and explanations are never sent to apps. The website
downloads the bundle when it builds. After a push to `main` that changes
content, the `Content live` workflow waits for the API deploy and rebuilds the
website through a Vercel deploy hook (secret `WEB_DEPLOY_HOOK_URL`).

## Learning

Answers are checked here (`learning/grade.py`, a port of the website's
`grade.ts` that matches its number parsing and formatting exactly), so they
never reach an app before the student has tried.

| Endpoint | Who |
|---|---|
| `POST /v1/attempts`, `/v1/attempts/testout` | anyone on public units (not saved); enrolled students and guides on the rest (saved) |
| `GET /v1/me/progress`, `/v1/me/attempts?unitId=` | the signed-in student |
| `POST /v1/me/steps`, `/v1/me/enrollments` | enrolled students and guides |
| `POST /v1/me/feedback/{id}/read` | the signed-in student (their own notes only) |
| `GET /v1/certificates/{code}` | anyone |

Error messages (`detail`) are the same as the website's, so it can pass them
straight to students.

## Guide and admin

| Endpoint | Who |
|---|---|
| `GET /v1/guide/roster`, `/v1/guide/students/{id}` | guides (`users.role = 'guide'`) |
| `POST /v1/guide/students/{id}/feedback`, `/assignments`, `/signoffs`; `PUT .../modules/{m}/flag`; `DELETE` assignments and sign-offs | guides |
| `POST /v1/admin/enrolments`, `PUT /v1/admin/roles`, `GET /v1/admin/subscribers` | admins |

Admins are the accounts whose email is in `ADMIN_EMAILS` (comma-separated).
They sign in with Google like everyone else; `/v1/me` returns `admin: true`
for them.

## Billing

| Endpoint | Who |
|---|---|
| `POST /v1/billing/checkout` `{returnUrl}` | the signed-in student; `returnUrl` must be `<an origin the app signs in from>/billing/return` |
| `GET /v1/billing/payments/{txRef}` | the payment's owner: verifies with Chapa, then returns the state |
| `POST /v1/billing/chapa/webhook` | Chapa (signed); `GET` with `?trx_ref=` is Chapa's callback |

Nothing Chapa sends is trusted on its own: each call triggers a fresh verify,
and claiming a payment is idempotent on `tx_ref`, so the website's old webhook
can run alongside this one. Set `CHAPA_SECRET_KEY` and `CHAPA_WEBHOOK_SECRET`
(test key on Preview, live key on Production); the Chapa dashboard's webhook
URL is `<API_BASE_URL>/v1/billing/chapa/webhook`.

## Lab assistant

`POST /v1/chat` (enrolled students and guides) streams Server-Sent Events:
`meta` (`conversationId`, `remaining`) first, then `delta` (`text`) pieces, then
`done`, or `error` if the provider breaks mid-answer. Problems before the
answer starts are normal JSON errors; `X-Error-Code` says `enrol` or
`daily_cap` where a client should react.

Limits: 30 messages a day (Addis Ababa days, the `usage` table) and at most 20
in any 5 minutes, counted from the student's own saved messages so it holds
across every instance. A message the provider never answered is refunded.

`GET /v1/chat/thread?context=`, `GET /v1/chat/conversations`,
`GET|DELETE /v1/chat/conversations/{id}` read and delete history (90 days, or
365 with extended retention). Set `AI_API_KEY` (and optionally `AI_BASE_URL`,
`AI_MODEL`, `AI_REASONING_EFFORT`); the old `GROQ_*` names also work.

## Analytics and jobs

`POST /v1/analytics/views` records a page view. Only the website's server can
call it (HTTP Basic with its client ID and secret), because it passes the
visitor's country and city from Vercel's headers and the signed-in user's id.
`/admin` pages are never counted.

`GET /v1/analytics/stats` (admins) returns sign-ups, traffic and engagement.
Signed-in visits by accounts in `ADMIN_EMAILS` are left out unless
`?includeAdmins=true`; visits made while signed out can't be told apart.

`GET /v1/internal/cleanup` runs daily at 03:00 UTC from Vercel Cron
(`vercel.json`): it deletes lab assistant messages past their retention (90
days, or 365 with extended retention) and conversations left empty. Set
`CRON_SECRET` on the Vercel project; without it the endpoint refuses every call.

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
