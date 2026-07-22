#!/usr/bin/env bash
# Push a locally-scraped corpus up to the deployment's bucket.
#
# Step 2 of the scraping workflow (step 1 is `python3 -m backend.batch_scrape N`,
# which must run locally — see backend/batch_scrape.py for why the cloud never
# scrapes). Safe to re-run: rsync only uploads what changed, and never deletes.
set -euo pipefail
cd "$(dirname "$0")/.."
source deploy/config.sh

LOCAL_CORPUS="${LOCAL_CORPUS:-saudi_exchange_pdfs}"

if [ ! -d "$LOCAL_CORPUS" ]; then
    echo "!! No local corpus at '$LOCAL_CORPUS'. Scrape first:" >&2
    echo "     python3 -m backend.batch_scrape 5" >&2
    exit 1
fi

if [ ! -f "$LOCAL_CORPUS/download_metadata.csv" ]; then
    echo "!! '$LOCAL_CORPUS/download_metadata.csv' is missing. The deployed app" >&2
    echo "   seeds its corpus tables from that file, so syncing PDFs without it" >&2
    echo "   would leave the new reports invisible in the UI. Scrape first." >&2
    exit 1
fi

PDF_COUNT="$(find "$LOCAL_CORPUS" -name '*.pdf' | wc -l | tr -d ' ')"
echo ">> Syncing $PDF_COUNT local PDFs (+ download_metadata.csv) → gs://$BUCKET/saudi_exchange_pdfs"
echo "   (additive: nothing already in the bucket is deleted)"

# NOTE: deliberately scoped to the corpus directory. data.db is NOT synced —
# the bucket's copy holds every extraction the GPU job has produced, and the
# local data.db would clobber it. New reports reach the DB via the metadata CSV
# re-seed below, which only touches the corpus tables.
gcloud storage rsync -r "$LOCAL_CORPUS" "gs://$BUCKET/saudi_exchange_pdfs"

echo ">> Bucket corpus size:"
gcloud storage du -s "gs://$BUCKET/saudi_exchange_pdfs" || true

# The running service seeds `reports`/`companies` from download_metadata.csv at
# startup. Rather than force a redeploy, poke the Acquire endpoint: with
# SCRAPER_STUB=1 it does exactly one thing — re-seed the corpus from that CSV —
# which is precisely what's needed after a sync.
echo
echo ">> Re-seeding the deployed corpus tables from the synced CSV…"
SERVICE_URL="$(gcloud run services describe "$SERVE_SERVICE" \
    --project "$PROJECT_ID" --region "$REGION" \
    --format='value(status.url)' 2>/dev/null || true)"

if [ -z "$SERVICE_URL" ]; then
    echo "   Service '$SERVE_SERVICE' not found — skipping."
    echo "   It will seed on its own the next time it starts."
else
    if curl -fsS -X POST -H 'Content-Type: application/json' -d '{}' \
            "$SERVICE_URL/api/scrape" >/dev/null; then
        echo "   Triggered. New reports appear in Query Reports within a few seconds."
    else
        echo "   Couldn't reach $SERVICE_URL (cold start or auth?)."
        echo "   Not a problem — just open the app, or re-run:"
        echo "     curl -X POST -H 'Content-Type: application/json' -d '{}' $SERVICE_URL/api/scrape"
    fi
fi

echo
echo ">> Done. Extract the new PDFs with: deploy/03_run_extraction_job.sh"
