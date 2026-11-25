# One-time Google Cloud setup

The API runs in the **same Google Cloud project as the web app's Google
sign-in client**, so the API, the web app and the mobile apps share one OAuth
consent screen and one set of sign-in settings.

Run the commands in **Cloud Shell**: open console.cloud.google.com, sign in,
and click the `>_` icon at the top right. It is a terminal in the browser with
`gcloud` already installed and signed in; nothing is installed on your machine.
Paste one block at a time and wait for the prompt to come back.

Cloud Shell disconnects after about 20 minutes idle and forgets the Step 0
values. If that happens, paste Step 0 again. Anything already created stays.

## 0. Set your values

Find the existing project's ID (the **PROJECT_ID** column, not the name):

```sh
gcloud projects list
```

Then:

```sh
PROJECT_ID=your-existing-project-id
REGION=europe-west3              # Frankfurt, next to Neon (AWS eu-central-1)
GITHUB_REPO=hasesa-edu/hasesa-api
```

## 1. Select the project, check billing, turn on services

```sh
gcloud config set project "$PROJECT_ID"
gcloud billing projects describe "$PROJECT_ID" --format='value(billingEnabled)'
```

- `True`: continue.
- `False`: link billing first: Console > Billing > My projects > the project's
  ⋮ menu > Change billing. It is required even for the free tier.

```sh
gcloud services enable run.googleapis.com artifactregistry.googleapis.com \
  secretmanager.googleapis.com iamcredentials.googleapis.com \
  cloudscheduler.googleapis.com
```

## 2. Budget alerts (browser)

Console > Billing > Budgets & alerts > Create budget:

- Scope: this project
- Amount: **$100**
- Alert thresholds: **10%, 50%, 100%** (emails at $10 / $50 / $100)

Alerts only send email; they never switch anything off. If the project already
has a budget, keep it and add these thresholds if they're missing.

## 3. Image registry

```sh
gcloud artifacts repositories create hasesa \
  --repository-format=docker --location="$REGION"
```

## 4. Service accounts

```sh
gcloud iam service-accounts create hasesa-api-runtime --display-name="Hasesa API runtime"
gcloud iam service-accounts create hasesa-api-deploy  --display-name="Hasesa API deploy (GitHub)"

RUNTIME_SA="hasesa-api-runtime@$PROJECT_ID.iam.gserviceaccount.com"
DEPLOY_SA="hasesa-api-deploy@$PROJECT_ID.iam.gserviceaccount.com"

for role in roles/run.admin roles/artifactregistry.writer; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$DEPLOY_SA" --role="$role" --condition=None
done

gcloud iam service-accounts add-iam-policy-binding "$RUNTIME_SA" \
  --member="serviceAccount:$DEPLOY_SA" --role=roles/iam.serviceAccountUser
```

`hasesa-api-runtime` is the identity the API runs as. `hasesa-api-deploy` is
what GitHub Actions uses to deploy. Neither can touch the OAuth client or
anything else in the project beyond what is granted here.

## 5. Database connection string

In the Neon console click **Connect**, turn **Connection pooling on** (the host
contains `-pooler`), and copy the string. Paste it between the single quotes:

```sh
printf '%s' 'PASTE_POOLED_CONNECTION_STRING_HERE' | \
  gcloud secrets create database-url --data-file=-

gcloud secrets add-iam-policy-binding database-url \
  --member="serviceAccount:$RUNTIME_SA" --role=roles/secretmanager.secretAccessor
```

It goes straight into Secret Manager. Never paste it into chat or a file.

## 6. Keyless GitHub sign-in (Workload Identity Federation)

```sh
gcloud iam workload-identity-pools create github \
  --location=global --display-name="GitHub"

gcloud iam workload-identity-pools providers create-oidc github \
  --location=global --workload-identity-pool=github \
  --display-name="GitHub Actions" \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
  --attribute-condition="assertion.repository == '$GITHUB_REPO'"

PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')

gcloud iam service-accounts add-iam-policy-binding "$DEPLOY_SA" \
  --role=roles/iam.workloadIdentityUser \
  --member="principalSet://iam.googleapis.com/projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/github/attribute.repository/$GITHUB_REPO"
```

Only workflows in `hasesa-edu/hasesa-api` can use this.

Print the values for step 7 (identifiers, not secrets):

```sh
echo "GCP_PROJECT_ID   = $PROJECT_ID"
echo "GCP_REGION       = $REGION"
echo "GCP_WIF_PROVIDER = projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/github/providers/github"
echo "GCP_DEPLOY_SA    = $DEPLOY_SA"
echo "GCP_RUNTIME_SA   = $RUNTIME_SA"
```

## 7. GitHub settings (browser)

github.com/hasesa-edu/hasesa-api > Settings > Secrets and variables > Actions.

**Variables** tab > New repository variable, once for each line printed above:
`GCP_PROJECT_ID`, `GCP_REGION`, `GCP_WIF_PROVIDER`, `GCP_DEPLOY_SA`,
`GCP_RUNTIME_SA`.

**Secrets** tab > New repository secret:

| Name | Value |
|---|---|
| `DATABASE_URL_DIRECT` | the Neon connection string with **Connection pooling off** (no `-pooler` in the host) |

Setting `GCP_PROJECT_ID` turns deploys on. The next push to `main`, or
Actions > Deploy > Run workflow, builds the image, runs migrations and deploys.
On the existing database the baseline migration only records itself (adds the
`alembic_version` table); no tables or data change.

## If something fails

- **"already exists"**: that step ran before. Stop and check it is ours
  (named as above) before continuing.
- **Billing errors**: billing isn't linked (step 1).
- **A policy error mentioning `allUsers`**: the project belongs to an
  organization that blocks public services; the deploy needs a different
  access setup.
