#!/usr/bin/env bash
# Build the GPU image and run bulk extraction as a Cloud Run Job on an L4.
# The job scales to zero when done — you pay only for the minutes it runs.
#
# Pass extra args straight through to backend.batch_extract, e.g.:
#   deploy/03_run_extraction_job.sh --limit 5      # smoke test on 5 PDFs
#   deploy/03_run_extraction_job.sh --force        # re-extract everything
set -euo pipefail
cd "$(dirname "$0")/.."
source deploy/config.sh

EXTRACT_ARGS=("$@")

echo ">> Building GPU extraction image with Cloud Build → $GPU_IMAGE"
# Reuses the CUDA-based Dockerfile (the app's original GPU image). Inline config
# (not --tag) so the -f Dockerfile and the image tag/push live together; --tag and
# --config can't be combined.
gcloud builds submit \
    --project "$PROJECT_ID" \
    --config /dev/stdin <<EOF
steps:
  - name: gcr.io/cloud-builders/docker
    args: ['build', '-f', 'Dockerfile', '-t', '$GPU_IMAGE', '.']
images: ['$GPU_IMAGE']
options:
  machineType: E2_HIGHCPU_8
EOF

# Build --args for the job: python3 -m backend.batch_extract [passthrough…]
JOB_ARGS="-m,backend.batch_extract"
for a in "${EXTRACT_ARGS[@]:-}"; do
    [ -n "$a" ] && JOB_ARGS="${JOB_ARGS},${a}"
done

echo ">> Creating/updating job '$EXTRACT_JOB' (L4 GPU, bucket mount)…"
# `jobs deploy` creates or updates in place. EXTRACT_WORKERS=2: two Docling
# child processes share the single 24 GB L4; raise only if VRAM allows.
gcloud run jobs deploy "$EXTRACT_JOB" \
    --image "$GPU_IMAGE" \
    --project "$PROJECT_ID" --region "$REGION" \
    --gpu 1 --gpu-type nvidia-l4 --no-gpu-zonal-redundancy \
    --cpu 4 --memory 16Gi \
    --max-retries 1 --task-timeout 3600 \
    --add-volume=name=data,type=cloud-storage,bucket="$BUCKET" \
    --add-volume-mount=volume=data,mount-path=/data \
    --set-env-vars="$DATA_ENV,EXTRACT_WORKERS=2" \
    --command python3 \
    --args "$JOB_ARGS"

echo ">> Executing the job now (blocking until it finishes)…"
gcloud run jobs execute "$EXTRACT_JOB" \
    --project "$PROJECT_ID" --region "$REGION" --wait

echo
echo ">> Extraction finished. Results are in gs://$BUCKET/data.db and visible in the"
echo "   serving UI immediately (same DB). Job is now scaled to zero — no further cost."
