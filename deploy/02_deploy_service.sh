#!/usr/bin/env bash
# Build and deploy the CPU-only serving service. Scale-to-zero (idle cost $0),
# single instance (in-process job state), GCS bucket mounted at /data.
set -euo pipefail
cd "$(dirname "$0")/.."
source deploy/config.sh

echo ">> Building CPU serving image with Cloud Build → $SERVE_IMAGE"
# -f selects the CPU Dockerfile; .gcloudignore keeps the corpus out of the context.
gcloud builds submit --tag "$SERVE_IMAGE" \
    --project "$PROJECT_ID" \
    --config /dev/stdin <<EOF
steps:
  - name: gcr.io/cloud-builders/docker
    args: ['build', '-f', 'Dockerfile.serve', '-t', '$SERVE_IMAGE', '.']
images: ['$SERVE_IMAGE']
options:
  machineType: E2_HIGHCPU_8
EOF

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
    --set-env-vars="$DATA_ENV,EXTRACT_WORKERS=2" \
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
