#!/usr/bin/env bash
# One-time setup: enable APIs, create the Artifact Registry repo, create the
# data bucket, and upload the corpus PDFs. Safe to re-run (idempotent-ish).
set -euo pipefail
cd "$(dirname "$0")/.."
source deploy/config.sh

echo ">> Enabling required APIs (run, cloudbuild, artifactregistry, storage)…"
gcloud services enable \
    run.googleapis.com \
    cloudbuild.googleapis.com \
    artifactregistry.googleapis.com \
    storage.googleapis.com \
    --project "$PROJECT_ID"

echo ">> Creating Artifact Registry repo '$REPO' in $REGION (ok if it exists)…"
gcloud artifacts repositories create "$REPO" \
    --repository-format=docker --location="$REGION" \
    --project "$PROJECT_ID" 2>/dev/null || echo "   repo already exists — skipping"

echo ">> Creating bucket gs://$BUCKET in $REGION (ok if it exists)…"
gcloud storage buckets create "gs://$BUCKET" \
    --project "$PROJECT_ID" --location="$REGION" \
    --uniform-bucket-level-access 2>/dev/null || echo "   bucket already exists — skipping"

echo ">> Uploading corpus PDFs (+ download_metadata.csv) to the bucket…"
# rsync so re-runs only push changes. The app reads PDFs read-mostly from here.
gcloud storage rsync -r saudi_exchange_pdfs "gs://$BUCKET/saudi_exchange_pdfs"

echo ">> Done. Bucket contents:"
gcloud storage du -s "gs://$BUCKET/saudi_exchange_pdfs" || true
echo
echo "Next: deploy/02_deploy_service.sh"
