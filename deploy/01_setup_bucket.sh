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

echo ">> Granting the runtime service account write access to the bucket…"
# The Cloud Run service AND job run as the default compute service account,
# which can read but not write the bucket by default. SQLite needs to create and
# delete objects (data.db + the DELETE-mode journal), so grant objectAdmin.
# Without this the container dies with: sqlite3.OperationalError: disk I/O error
# (GCSFuse surfaces the underlying 403 storage.objects.create as an I/O error).
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
RUNTIME_SA="${RUNTIME_SA:-${PROJECT_NUMBER}-compute@developer.gserviceaccount.com}"
gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" \
    --member="serviceAccount:${RUNTIME_SA}" \
    --role=roles/storage.objectAdmin \
    --project "$PROJECT_ID" >/dev/null
echo "   granted roles/storage.objectAdmin to ${RUNTIME_SA}"

echo ">> Uploading corpus PDFs (+ download_metadata.csv) to the bucket…"
# rsync so re-runs only push changes. The app reads PDFs read-mostly from here.
gcloud storage rsync -r saudi_exchange_pdfs "gs://$BUCKET/saudi_exchange_pdfs"

echo ">> Done. Bucket contents:"
gcloud storage du -s "gs://$BUCKET/saudi_exchange_pdfs" || true
echo
echo "Next: deploy/02_deploy_service.sh"
