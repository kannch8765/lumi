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
  --budget-amount=5USD \
  --threshold-rule=percent=50 \
  --threshold-rule=percent=90 \
  --threshold-rule=percent=100
```

## Test-deploy-then-tear-down (Task 27b–e, 2026-06-22)

The Kaggle brief allows GitHub + setup docs as an alternative to a
live URL, but we ran a one-shot test deploy on a fresh trial-account
project (`lumi-test-deploy`) to capture real gotchas. **Total elapsed:
~2 hours including 4 fix-and-retry cycles and 1 quota investigation.**
The service was torn down at the end of the session — see
[Teardown](#teardown) below.

### What was deployed

- **Project:** `lumi-test-deploy` (Google Cloud free trial)
- **Region:** `us-central1`
- **Service URL (now torn down):** `https://lumi-434649037708.us-central1.run.app`
- **Final revision:** `lumi-00001-z2q` (image `lumi:7c782f1`)
- **Build time:** 1m5s (with `--cache-from lumi:latest` reusing prior
  build layers; would be ~6-8 min cold)
- **Deploy time:** ~1 min after build SUCCESS
- **Cost:** ~$0.05 (build time only; the service was idle the rest of
  the session and torn down before any meaningful traffic)

### Smoke-test results

| Endpoint | Expected | Actual | Status |
|---|---|---|---|
| `GET /list-apps` | `["agents"]` | `["agents"]` | ✅ |
| `GET /docs` | Swagger UI HTML | HTML rendered | ✅ |
| `GET /openapi.json` | JSON paths | 30+ paths including `/run`, `/run_sse`, `/dev-ui` | ✅ |
| `POST /apps/.../sessions` | Create session JSON | `{"id":"sess-1", ...}` | ✅ |
| `POST /run` (real query) | Lumi 5-resource response | `500 Internal Server Error` (Gemini 429) | ⚠️ |

The 500 on `/run` is **not a deploy or wiring bug** — the pipeline
correctly executed L1 → L2 → L3 → L4 (visible in logs) and the LLM
call hit Google's global free-tier rate limit. See [Gotcha #5](#gotcha-5-global-gemini-free-tier-quota-shared-across-projects)
below.

### Gotchas (real, captured during the test deploy)

#### Gotcha #1: `${VAR}` inside bash step misread as Cloud Build substitution

```
ERROR: invalid value for 'build.substitutions': key in the template
'IMAGE' is not a valid built-in substitution
```

Cloud Build's substitution parser scans every `${VAR}` and `$VAR` in
the template. If `VAR` isn't a built-in (`SHORT_SHA`, `BRANCH_NAME`,
`PROJECT_ID`, ...) or user-defined (underscore-prefixed, `^_[A-Z0-9_]+$`),
the template is rejected at submit time — **before any step runs**.

**Fix:** escape bash shell variables with `$${VAR}` (double-dollar) so
the first `$` becomes literal in the rendered script. Bash then
dereferences the variable normally. See `cloudbuild.yaml:75,79` for
the `IMAGE` shell var.

#### Gotcha #2: `${SHORT_SHA:-default}` not matched against substitution data

```
ERROR: key 'SHORT_SHA' in the substitution data is not matched in the template
```

Even after fixing Gotcha #1, the bash parameter-expansion syntax
`${SHORT_SHA:-latest}` doesn't match the literal `${SHORT_SHA}` that
Cloud Build's parser looks for. Same root cause, different error.

**Fix:** drop the bash `:-default` syntax. Rely on Cloud Build to
substitute the value (deploy.sh always passes `SHORT_SHA=...` in
`--substitutions`). For safety, set a default in the substitutions
block — but only with an underscore-prefixed name (see Gotcha #3).

#### Gotcha #3: User-defined substitution names must start with `_`

```
ERROR: substitution key SHORT_SHA does not respect format ^_[A-Z0-9_]+$
```

`SHORT_SHA` is a Cloud Build **built-in** (auto-populated from git
HEAD). If you try to give it a default in the `substitutions:` block
(`SHORT_SHA: "latest"`), Cloud Build re-classifies it as
**user-defined** and validates against `^_[A-Z0-9_]+$`. Without the
underscore, it gets rejected.

**Fix:** leave built-in names out of the `substitutions:` block. Use
bare `${SHORT_SHA}` references; Cloud Build auto-populates from
caller or git HEAD.

#### Gotcha #4: Trial account can't run `E2_HIGHCPU_8` Cloud Build workers

```
ERROR: FAILED_PRECONDITION: due to quota restrictions, Cloud Build
cannot run builds of this machine type in this region
```

Trial accounts have tighter Cloud Build quotas than pay-as-you-go.
The default `E2_HIGHCPU_8` (8 vCPU) requested in `cloudbuild.yaml`
exceeds the trial default.

**Fix:** drop the `machineType` line entirely. Cloud Build uses
`E2_HIGHCPU_2` (2 vCPU / 2 GB) by default on trial, which is plenty
for `uv sync` + `docker build` of the Lumi image (~700 MiB source).
The build is CPU-bound on serial package resolution, not on
parallel fan-out, so the larger machine wouldn't help much anyway.

When migrating to a pay-as-you-go project, add back:
```yaml
options:
  machineType: E2_HIGHCPU_8
```
to make the dependency-install step ~2-3x faster.

#### Gotcha #5: Global Gemini free-tier quota shared across projects

```
google.genai.errors.ClientError: 429 RESOURCE_EXHAUSTED
Quota exceeded for metric: generativelanguage.googleapis.com/
generate_content_free_tier_requests, limit: 15, model: gemini-3.1-flash-lite
```

The 15-RPM limit on `gemini-3.1-flash-lite` free tier is **per API
key, not per project**. The same `GEMINI_API_KEY` was already serving
`paper-scope` and `adk-project` on the same trial account, so any
Lumi query that fires 4 sequential LLM calls (L1 → L2 → L3 → L4) is
likely to bump into the global 15-RPM ceiling.

**Fixes (production):**
1. **Switch to Vertex AI** — set `GOOGLE_GENAI_USE_VERTEXAI=true` in
   `.env.production`, plus `GOOGLE_CLOUD_PROJECT` and
   `GOOGLE_CLOUD_LOCATION`. Vertex uses the project's billing, not
   the shared AI Studio key. No rate limit, but pay-per-token.
2. **Use a dedicated API key** for the deploy project — create a new
   Gemini API key tied only to the deploy project's identity. Gives
   the project its own 15-RPM quota.
3. **Reduce LLM-call count per query** — e.g., batch the L1+L2 calls
   into a single prompt. Halves the RPM pressure but loses the
   schema-as-contract isolation.

For the Kaggle capstone submission, the demo transcript can be
generated from a local `adk run` session (no quota sharing) and
linked in the writeup — no need for a long-running deployed URL.

### Teardown

```bash
# Delete the Cloud Run service (1 command, fully gone, ~10s)
gcloud run services delete lumi \
  --project="${PROJECT_ID}" \
  --region="${REGION:-us-central1}"

# (Optional) Delete the Artifact Registry repo if you don't plan to redeploy
gcloud artifacts repositories delete lumi \
  --project="${PROJECT_ID}" \
  --location="${REGION:-us-central1}"

# (Optional) Delete the test-deploy project entirely
gcloud projects delete lumi-test-deploy
```

After teardown: zero ongoing attack surface, zero ongoing cost, the
container image and Cloud Build logs are retained in Artifact
Registry and Cloud Logging until you delete the project.

## Files

- `cloudbuild.yaml` (repo root) — Cloud Build pipeline.
- `deploy/deploy.sh` — build + deploy driver, idempotent.
- `deploy/README.md` — this file.
