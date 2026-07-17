#!/usr/bin/env bash
# Shared deployment settings. Override any of these in your shell before running
# the deploy scripts, e.g.  export PROJECT_ID=my-gcp-project
set -euo pipefail

# --- Required: your GCP project. No default on purpose, so nothing deploys to
#     the wrong project by accident. ---
PROJECT_ID="${PROJECT_ID:?set PROJECT_ID (e.g. export PROJECT_ID=my-gcp-project)}"

# Singapore. GCP's name for this region is asia-southeast1 (AWS calls it
# ap-southeast-1). It is one of the five Cloud Run regions with L4 GPUs.
REGION="${REGION:-asia-southeast1}"

# Artifact Registry repo + image names.
REPO="${REPO:-thesis}"
SERVE_IMAGE="${SERVE_IMAGE:-${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/thesis-serve}"
GPU_IMAGE="${GPU_IMAGE:-${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/thesis-extract}"

# Cloud Run service (serving) + job (extraction) names.
SERVE_SERVICE="${SERVE_SERVICE:-thesis-serve}"
EXTRACT_JOB="${EXTRACT_JOB:-thesis-extract}"

# GCS bucket holding the persistent SQLite DB + corpus PDFs + uploads.
# Bucket names are globally unique, so it's project-scoped by default.
BUCKET="${BUCKET:-${PROJECT_ID}-thesis-data}"

# Env vars pointing the app at the mounted bucket. DELETE journal because WAL is
# unusable over GCSFuse. Shared by the service and the job.
DATA_ENV="THESIS_DB_PATH=/data/data.db,THESIS_UPLOAD_DIR=/data/uploads,THESIS_PDF_DIR=/data/saudi_exchange_pdfs,THESIS_SQLITE_JOURNAL=DELETE,SCRAPER_STUB=1"

export PROJECT_ID REGION REPO SERVE_IMAGE GPU_IMAGE SERVE_SERVICE EXTRACT_JOB BUCKET DATA_ENV
