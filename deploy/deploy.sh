#!/usr/bin/env bash
# Lumi — Cloud Run deployment script.
#
# Builds the container via Cloud Build, then deploys (or updates) the
# `lumi` Cloud Run service. Reads runtime configuration from a
# gitignored `.env.production` file (see CONTEXT.md #6 — no secrets in
# code).
#
# Idempotent: re-running updates the service to the latest image. Safe
# to invoke from CI or locally.
#
# Required env (export before running, or place in .env.production):
#   PROJECT_ID                Google Cloud project ID (required)
#   REGION                    Cloud Run region (default: us-central1)
#   SERVICE_NAME              Cloud Run service name (default: lumi)
#   AR_REPO                   Artifact Registry repo (default: lumi)
#   _DEPLOY_SHA               Image tag (default: short git HEAD)
#
# Optional env in .env.production (forwarded to Cloud Run):
#   GEMINI_API_KEY, GOOGLE_CLOUD_PROJECT, GOOGLE_CLOUD_LOCATION,
#   GOOGLE_GENAI_USE_VERTEXAI, LUMI_LOG_LEVEL, OTEL_EXPORTER, etc.

set -euo pipefail

# --- Config & defaults ----------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

: "${PROJECT_ID:?PROJECT_ID must be exported or set in .env.production}"
REGION="${REGION:-us-central1}"
SERVICE_NAME="${SERVICE_NAME:-lumi}"
AR_REPO="${AR_REPO:-lumi}"
DEPLOY_SHA="${_DEPLOY_SHA:-$(git -C "${REPO_ROOT}" rev-parse --short HEAD 2>/dev/null || echo latest)}"

# --- Load production env (gitignored) -------------------------------------
# .env.production must NEVER be committed (see .gitignore: .env.*).
ENV_FILE="${REPO_ROOT}/.env.production"
if [[ -f "${ENV_FILE}" ]]; then
  # shellcheck disable=SC1090
  set -a
  source "${ENV_FILE}"
  set +a
  echo "Loaded $(grep -cE '^[A-Z_][A-Z0-9_]*=' "${ENV_FILE}" || echo 0) env vars from .env.production"
else
  echo "WARN: ${ENV_FILE} not found. Cloud Run will receive only env vars already in this shell." >&2
fi

# --- Preflight ------------------------------------------------------------
if ! command -v gcloud >/dev/null 2>&1; then
  echo "ERROR: gcloud CLI not found. Install: https://cloud.google.com/sdk/docs/install" >&2
  exit 1
fi

echo "Deploying ${SERVICE_NAME} to Cloud Run"
echo "  project: ${PROJECT_ID}"
echo "  region:  ${REGION}"
echo "  image:   ${REGION}-docker.pkg.dev/${PROJECT_ID}/${AR_REPO}/lumi:${DEPLOY_SHA}"

# --- Build & push via Cloud Build ----------------------------------------
gcloud builds submit "${REPO_ROOT}" \
  --config="${REPO_ROOT}/cloudbuild.yaml" \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --substitutions="_REGION=${REGION},_REPO=${AR_REPO},_PROJECT_ID=${PROJECT_ID},SHORT_SHA=${DEPLOY_SHA}" \
  --timeout=600s

# --- Collect env vars for Cloud Run --------------------------------------
# Forward any GEMINI_*, GOOGLE_*, LUMI_*, OTEL_* vars from the shell
# (loaded above from .env.production) to the running service.
ENV_VARS=()
for var in $(compgen -e | grep -E '^(GEMINI|GOOGLE|LUMI|OTEL)_' | sort -u); do
  # Skip the GOOGLE_APPLICATION_CREDENTIALS path — Cloud Run uses the
  # service account identity, not a local key file.
  if [[ "${var}" == "GOOGLE_APPLICATION_CREDENTIALS" ]]; then
    continue
  fi
  value="${!var}"
  # Cloud Run env-var syntax: KEY=VALUE,KEY=VALUE
  ENV_VARS+=("${var}=${value}")
done
ENV_VARS_CSV=""
if (( ${#ENV_VARS[@]} > 0 )); then
  ENV_VARS_CSV="$(IFS=,; echo "${ENV_VARS[*]}")"
fi

# --- Deploy to Cloud Run --------------------------------------------------
# Flags:
#   --allow-unauthenticated    Demo / Kaggle capstone surface; replace
#                              with --no-allow-unauthenticated + IAM
#                              before opening to the public internet.
#   --cpu-boost                Reduces cold-start latency for the demo.
#   --min-instances=0          Scales to zero (free tier friendly).
#   --max-instances            Caps runaway scaling (cost guardrail).
#                              Override via MAX_INSTANCES env var.
#                              Default 1 for the test-deploy path (Task
#                              27); bump up only if real traffic needs it.
#   --concurrency              One request per instance during test
#                              (avoids pipeline-state interleaving).
#                              Override via CONCURRENCY env var.
#   --memory=1Gi / --cpu=1     Fits all 5 agents comfortably (Task 45
#                              E2E baseline observed ~700 MiB peak).
MAX_INSTANCES="${MAX_INSTANCES:-1}"
CONCURRENCY="${CONCURRENCY:-1}"
DEPLOY_ARGS=(
  run deploy "${SERVICE_NAME}"
  --project="${PROJECT_ID}"
  --region="${REGION}"
  --image="${REGION}-docker.pkg.dev/${PROJECT_ID}/${AR_REPO}/lumi:${DEPLOY_SHA}"
  --platform=managed
  --allow-unauthenticated
  --cpu-boost
  --min-instances=0
  --max-instances="${MAX_INSTANCES}"
  --concurrency="${CONCURRENCY}"
  --port=8080
  --timeout=300
  --memory=1Gi
  --cpu=1
)
if [[ -n "${ENV_VARS_CSV}" ]]; then
  DEPLOY_ARGS+=(--set-env-vars="${ENV_VARS_CSV}")
fi

gcloud "${DEPLOY_ARGS[@]}"

# --- Report ---------------------------------------------------------------
SERVICE_URL="$(gcloud run services describe "${SERVICE_NAME}" \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --format='value(status.url)')"

echo
echo "Deployed: ${SERVICE_URL}"
echo "Logs:     gcloud run services logs tail ${SERVICE_NAME} --project=${PROJECT_ID} --region=${REGION}"
echo "Rollback: gcloud run services rollback ${SERVICE_NAME} --project=${PROJECT_ID} --region=${REGION}"
