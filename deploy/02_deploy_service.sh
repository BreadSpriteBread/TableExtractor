#!/usr/bin/env bash
# Build and deploy the CPU-only serving service. Scale-to-zero (idle cost $0),
# single instance (in-process job state), GCS bucket mounted at /data.
set -euo pipefail
cd "$(dirname "$0")/.."
source deploy/config.sh

echo ">> Building CPU serving image with Cloud Build → $SERVE_IMAGE"
# Inline config so we can select the CPU Dockerfile with -f (a plain --tag build
# only ever uses ./Dockerfile). --tag and --config are mutually exclusive, so the
# image tag/push is declared inside the config via `images:`. .gcloudignore keeps
# the corpus out of the build context.
gcloud builds submit \
    --project "$PROJECT_ID" \
    --config /dev/stdin <<EOF
steps:
  - name: gcr.io/cloud-builders/docker
    args: ['build', '-f', 'Dockerfile.serve', '-t', '$SERVE_IMAGE', '.']
images: ['$SERVE_IMAGE']
options:
  machineType: E2_HIGHCPU_8
EOF

# The financials feature's optional LLM fallback (Google AI Studio / Gemini)
# reads LLM_API_KEY. Pass it through only when set in the deploying shell, so the
# free-tier key never lives in the repo. Deterministic parsing works without it.
# GEMINI_MODEL is optional (defaults to gemini-2.0-flash in code).
SERVE_ENV="$DATA_ENV,EXTRACT_WORKERS=2"
if [ -n "${LLM_API_KEY:-}" ]; then
    SERVE_ENV="$SERVE_ENV,LLM_API_KEY=${LLM_API_KEY}"
    [ -n "${GEMINI_MODEL:-}" ] && SERVE_ENV="$SERVE_ENV,GEMINI_MODEL=${GEMINI_MODEL}"
    echo ">> LLM_API_KEY detected — financials AI fallback will be enabled."
else
    echo ">> LLM_API_KEY not set — deploying with deterministic financials only."
fi

echo ">> Deploying service '$SERVE_SERVICE' to $REGION (scale-to-zero, bucket mount)…"
gcloud run deploy "$SERVE_SERVICE" \
    --image "$SERVE_IMAGE" \
    --project "$PROJECT_ID" --region "$REGION" \
    --execution-environment gen2 \
    --cpu 2 --memory 4Gi \
    --min-instances 0 --max-instances 1 \
    --concurrency 8 --timeout 300 \
    --add-volume=name=data,type=cloud-storage,bucket="$BUCKET" \
    --add-volume-mount=volume=data,mount-path=/data \
    --set-env-vars="$SERVE_ENV" \
    --allow-unauthenticated

echo
echo ">> Service URL:"
gcloud run services describe "$SERVE_SERVICE" \
    --project "$PROJECT_ID" --region "$REGION" \
    --format='value(status.url)'
echo
echo "Reminders:"
echo "  • min-instances=0 → first hit after idle cold-starts (~seconds on this CPU image)."
echo "  • For a demo/defense, warm it:  gcloud run services update $SERVE_SERVICE \\"
echo "        --region $REGION --min-instances 1   (then set back to 0 after)."
echo "  • Bulk-extract the corpus with the GPU job: deploy/03_run_extraction_job.sh"
