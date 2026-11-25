# One-time Vercel setup

The API deploys on Vercel as its own project, separate from the web app, in
the Frankfurt region (`fra1`, set in `vercel.json`) next to the Neon database
(AWS eu-central-1).

- **Code:** Vercel builds and deploys every push. `main` goes to production;
  every pull request gets a preview URL.
- **Migrations:** the `Migrate` GitHub Actions workflow applies them to
  production on every push to `main`. Preview deploys never migrate.

## 1. Create the Vercel project

1. vercel.com > **Add New** > **Project** > import `hasesa-edu/hasesa-api`.
   If the repo isn't listed, use **Adjust GitHub App Permissions** to give
   Vercel access to it.
2. Framework preset: **FastAPI** (detected from `pyproject.toml`).
   Leave the build settings at their defaults.
3. Project name: `hasesa-api`.

## 2. Environment variables

Before the first deploy (or in Project > Settings > Environment Variables,
then redeploy):

| Name | Value | Environments |
|---|---|---|
| `DATABASE_URL` | Neon connection string with **Connection pooling on** (host contains `-pooler`) | Production |
| `ENVIRONMENT` | `production` | Production |
| `DB_NULL_POOL` | `true` | Production, Preview |

For **Preview**, use a **Neon branch** connection string for `DATABASE_URL`,
not production, so pull request previews can't change real data. In Neon:
Branches > New branch (from `main`), then copy its pooled connection string.

## 3. Migration secret (GitHub)

github.com/hasesa-edu/hasesa-api > Settings > Secrets and variables >
Actions > **Secrets** > New repository secret:

| Name | Value |
|---|---|
| `DATABASE_URL_DIRECT` | the production Neon connection string with **Connection pooling off** (no `-pooler`) |

Then run Actions > **Migrate** > Run workflow. On the existing database the
baseline only records itself (adds the `alembic_version` table); no tables
or data change.

## 4. Check it

Open `https://<your-api-domain>/v1/health` and `/v1/health/ready`. Both
should return `{"status":"ok"}`.

Optional: add a custom domain such as `api.<your-domain>` in Project >
Settings > Domains.

## Plan limits to know

- The Hobby plan is for non-commercial use. Move to Pro before charging users.
- Requests have a maximum duration. Long AI grading jobs will run as
  background jobs, not inside a request.
- The `Dockerfile` stays in the repo, so the API can move to any container
  host (Cloud Run, Render, Fly.io) later without code changes.
