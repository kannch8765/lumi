# Lumi — Deployment Guide

This directory contains the Cloud Run deployment pipeline for the Lumi
multi-agent service. The runtime contract (Dockerfile, `pyproject.toml`,
`app/fast_api_app.py`) lives in the repo root and is **not** modified by
this guide.

## Prerequisites

- `gcloud` CLI installed and authenticated (`gcloud auth login`).
- `PROJECT_ID` exported: `export PROJECT_ID=<your-project-id>`.
- A `.env.production` file at the repo root containing the runtime
  secrets listed below (mode `600`, **never committed** — see
  `CONTEXT.md #6`).

## One-time setup

```bash
# 1. Enable the APIs Cloud Run + Cloud Build + Artifact Registry need.
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  --project="${PROJECT_ID}"

# 2. Create the Artifact Registry repository (one-time, per region).
gcloud artifacts repositories create lumi \
  --project="${PROJECT_ID}" \
  --repository-format=docker \
  --location="${REGION:-us-central1}" \
  --description="Lumi agent runtime images"

# 3. Grant Cloud Build's default service account permission to deploy
#    to Cloud Run (only needed if you wire up a push-to-master trigger).
PROJECT_NUMBER="$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')"
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${PROJECT_NUMBER}@cloudbuild.gserviceaccount.com" \
  --role="roles/run.admin"
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${PROJECT_NUMBER}@cloudbuild.gserviceaccount.com" \
  --role="roles/iam.serviceAccountUser"
```

## Deploy

```bash
export PROJECT_ID=<your-project-id>
export REGION=us-central1            # optional, default: us-central1
./deploy/deploy.sh
```

The script will:

1. Load `.env.production` (gitignored) into the current shell.
2. Submit a Cloud Build using `cloudbuild.yaml` (timeout 10 minutes,
   with layer-cache reuse from the previous `lumi:latest` image).
3. Deploy the resulting image to Cloud Run with the env vars in
   `.env.production` (filtered to `GEMINI_*`, `GOOGLE_*`, `LUMI_*`,
   `OTEL_*` prefixes).
4. Print the deployed service URL.

Re-running the script is safe — it always converges to the current
`HEAD` commit.

## Environment variables

`.env.production` (gitignored via `.gitignore: .env.*`) carries the
runtime secrets. Only the prefixes listed above are forwarded to Cloud
Run; the rest stay in the build shell.

| Variable | Required | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | yes (or use Vertex) | Gemini model access |
| `GOOGLE_CLOUD_PROJECT` | yes (Vertex mode) | Vertex AI project |
| `GOOGLE_CLOUD_LOCATION` | yes (Vertex mode) | Vertex AI region |
| `GOOGLE_GENAI_USE_VERTEXAI` | no | `true` to use Vertex instead of AI Studio |
| `LUMI_LOG_LEVEL` | no | `INFO` / `DEBUG` / `WARNING` |
| `OTEL_EXPORTER` | no | `gcp` to ship traces to Cloud Trace |

> **No secrets in code.** `CONTEXT.md #2` and `CONTEXT.md #6` require
> that every API key, OAuth client, or service-account credential live
> exclusively in `.env.production` (mode `600`). The pre-commit
> `semgrep` rules block any string matching `AIza*` / `AQ.*` / `sk-*`
> / `ghp_*` from being committed.

## Rollback

```bash
gcloud run services rollback lumi \
  --project="${PROJECT_ID}" \
  --region="${REGION:-us-central1}"
```

Cloud Run keeps the previous revision and restores it as 100% of
traffic. Use this if a deploy is green-but-broken (5xx spike, bad
prompt regression, etc.).

## Logs

```bash
gcloud run services logs tail lumi \
  --project="${PROJECT_ID}" \
  --region="${REGION:-us-central1}"
```

Structured JSON to Cloud Logging. The `google-cloud-logging` client
ships traces to Cloud Trace when `OTEL_EXPORTER=gcp`. Audit-log entries
follow the PII-stripping rule in `CONTEXT.md #8`.

## Cost

Cloud Run free tier (2M requests/month, 360k GB-seconds, 180k
vCPU-seconds) covers a Kaggle demo comfortably. Set a budget alert at
$5/month before going public:

```bash
gcloud billing budgets create \
  --billing-account="${BILLING_ACCOUNT_ID}" \
  --display-name="Lumi Cloud Run budget" \
  --amount=5 \
  --threshold-rule=percent=50 \
  --threshold-rule=percent=90 \
  --threshold-rule=percent=100
```

## Files

- `cloudbuild.yaml` (repo root) — Cloud Build pipeline.
- `deploy/deploy.sh` — build + deploy driver, idempotent.
- `deploy/README.md` — this file.
