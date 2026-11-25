# One-time Google Cloud setup

Run these once, in the Google Cloud Console's **Cloud Shell** (the `>_` icon at
the top right of console.cloud.google.com). Cloud Shell already has `gcloud`
installed and logged in, so nothing needs installing on your machine.

## 0. Pick values

```sh
PROJECT_ID=hasesa-api            # must be globally unique; add a suffix if taken
REGION=europe-west3              # same region as your Neon database (see below)
GITHUB_REPO=hasesa-edu/hasesa-api
```

Match the region to Neon (Neon console > project settings > region):

| Neon region | Cloud Run region |
|---|---|
| AWS eu-central-1 (Frankfurt) | `europe-west3` |
| AWS us-east-1 / us-east-2 | `us-east4` |
| AWS ap-southeast-1 (Singapore) | `asia-southeast1` |
| Azure / other | ask before choosing |

## 1. Project, billing, APIs

```sh
gcloud projects create "$PROJECT_ID" --name="Hasesa API"
gcloud config set project "$PROJECT_ID"
# Link billing (needed even for the free tier):
#   Console > Billing > My projects > hasesa-api > Change billing.
gcloud services enable run.googleapis.com artifactregistry.googleapis.com \
  secretmanager.googleapis.com iamcredentials.googleapis.com \
  cloudscheduler.googleapis.com
```

## 2. Budget alerts

Console > Billing > Budgets & alerts > Create budget: amount **$100**, with
alert emails at **10%, 50% and 100%** ($10 / $50 / $100).

## 3. Image registry

```sh
gcloud artifacts repositories create hasesa --repository-format=docker --location="$REGION"
```

## 4. Service accounts

```sh
# Runs the API.
gcloud iam service-accounts create hasesa-api-runtime
# Used by GitHub Actions to deploy.
gcloud iam service-accounts create hasesa-api-deploy

RUNTIME_SA="hasesa-api-runtime@$PROJECT_ID.iam.gserviceaccount.com"
DEPLOY_SA="hasesa-api-deploy@$PROJECT_ID.iam.gserviceaccount.com"

for role in roles/run.admin roles/artifactregistry.writer; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:$DEPLOY_SA" --role="$role"
done
gcloud iam service-accounts add-iam-policy-binding "$RUNTIME_SA" \
  --member="serviceAccount:$DEPLOY_SA" --role=roles/iam.serviceAccountUser
```

## 5. Database secret

Use the **pooled** Neon connection string (host contains `-pooler`):

```sh
printf '%s' 'postgresql://...-pooler.../neondb?sslmode=require' | \
  gcloud secrets create database-url --data-file=-
gcloud secrets add-iam-policy-binding database-url \
  --member="serviceAccount:$RUNTIME_SA" --role=roles/secretmanager.secretAccessor
```

## 6. Keyless GitHub sign-in (Workload Identity Federation)

```sh
gcloud iam workload-identity-pools create github --location=global
gcloud iam workload-identity-pools providers create-oidc github \
  --location=global --workload-identity-pool=github \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
  --attribute-condition="assertion.repository == '$GITHUB_REPO'"

PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
gcloud iam service-accounts add-iam-policy-binding "$DEPLOY_SA" \
  --role=roles/iam.workloadIdentityUser \
  --member="principalSet://iam.googleapis.com/projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/github/attribute.repository/$GITHUB_REPO"

echo "GCP_WIF_PROVIDER = projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/github/providers/github"
```

## 7. GitHub settings

In github.com/hasesa-edu/hasesa-api > Settings > Secrets and variables > Actions:

**Variables**

| Name | Value |
|---|---|
| `GCP_PROJECT_ID` | your `$PROJECT_ID` |
| `GCP_REGION` | your `$REGION` |
| `GCP_WIF_PROVIDER` | the line printed at the end of step 6 |
| `GCP_DEPLOY_SA` | `hasesa-api-deploy@<PROJECT_ID>.iam.gserviceaccount.com` |
| `GCP_RUNTIME_SA` | `hasesa-api-runtime@<PROJECT_ID>.iam.gserviceaccount.com` |

**Secrets**

| Name | Value |
|---|---|
| `DATABASE_URL_DIRECT` | the **direct** (non-pooled) Neon connection string |

Setting `GCP_PROJECT_ID` turns deploys on: the next push to `main` (or
Actions > Deploy > Run workflow) builds, migrates and deploys.

On the existing database the baseline migration detects the web app's tables
and only records itself as applied. No tables or data change.
