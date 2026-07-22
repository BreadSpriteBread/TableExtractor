# Deployment (Cloud Run, `asia-southeast1` / Singapore)

A budget-first deployment split into two workloads so idle time costs ~nothing
and the expensive GPU only bills while it's actually extracting.

| Piece | What | Cost posture |
|---|---|---|
| **Serving service** (`thesis-serve`) | CPU-only Flask + UI, reads/writes SQLite on the bucket | Scale-to-zero → **$0 idle** |
| **Extraction job** (`thesis-extract`) | L4 GPU batch over the corpus, on demand | Per-second, scales to zero when done |
| **Data bucket** (`gs://…-thesis-data`) | Persistent SQLite DB + corpus PDFs + uploads | ~**$0.03/mo** for 1.6 GB |

Scraping is **not** a cloud workload — it runs on your desktop and the results
are pushed up (see [Scraping new reports](#scraping-new-reports-local-then-sync)).

Why the split: extraction is GPU-heavy and bursty; serving is light and must be
responsive. Running them separately means the L4 is never sitting idle on the
clock — that's the one thing that can blow the $350/90-day budget (a warm L4 is
~$1.16/hr ≈ the whole budget in **12 days**).

## Prerequisites

- `gcloud` authenticated (`gcloud auth login`) with a billing-enabled project.
- Set your project once: `export PROJECT_ID=your-gcp-project`
  (all scripts read `deploy/config.sh`; override `REGION`, `BUCKET`, etc. there
  or via env vars).

## First deploy

```bash
export PROJECT_ID=your-gcp-project

deploy/01_setup_bucket.sh          # APIs, Artifact Registry, bucket, upload PDFs
deploy/02_deploy_service.sh        # build + deploy the scale-to-zero CPU service
deploy/03_run_extraction_job.sh --limit 3   # smoke-test extraction on 3 PDFs
deploy/03_run_extraction_job.sh    # full corpus once the smoke test looks right
```

The service URL is printed at the end of step 2. After step 3 the extracted
tables appear in the UI immediately — the job and the service share the one
SQLite DB on the bucket.

## Scraping new reports (local, then sync)

**Scraping never runs in the cloud.** `services/scraper.py` drives a *headed*,
stealth-patched Chromium (patchright, spoofed `navigator` fields, randomised
delays) because Saudi Exchange challenges automated clients — headless Chromium
from a datacenter egress IP gets blocked outright. Cloud Run also throttles CPU
for background threads outside a request and would kill a scrape at the 300s
request timeout. So both cloud images keep `SCRAPER_STUB=1` permanently.

Two steps, from your desktop:

```bash
python3 -m backend.batch_scrape 5      # 1. scrape 5 companies (opens a browser)
deploy/04_sync_corpus.sh               # 2. push PDFs + CSV to the bucket
```

The argument is how many rows to take from
`backend/saudi_exchange_company_profiles.csv` (260 rows); omit it to scrape all
of them. Start small — a full run is hours of deliberate rate-limiting.

`04_sync_corpus.sh` rsyncs the corpus up (additive — it never deletes) and then
POSTs `/api/scrape` on the running service. With `SCRAPER_STUB=1` that endpoint
does exactly one thing: re-seed the corpus tables from `download_metadata.csv`.
So new reports appear in **Query Reports** without a redeploy. Follow with
`deploy/03_run_extraction_job.sh` to extract them.

> **`data.db` is deliberately not synced.** The bucket's copy holds every
> extraction the GPU job has produced; pushing your local DB would clobber it.
> New reports reach the deployed DB through the CSV re-seed, which only touches
> the corpus tables.

If the browser shows a challenge or consent page and nothing downloads, the
session was flagged — retry later or from a different network.

## Cost model (real numbers)

Cloud Run rates (us-central1 tier; Singapore is close): CPU **$0.0864/vCPU-hr**,
memory **$0.009/GiB-hr**, L4 GPU **$0.672/GPU-hr** (no zonal redundancy).

- **Serving, scale-to-zero:** ~$0 when idle; a browsing session is cents. Most
  of it fits in the monthly free tier (180k vCPU-s / 360k GiB-s).
- **One full corpus extraction (437 PDFs) on the L4:** ~5 hrs, **~$6**. Even a
  handful of full re-runs is well under $50.
- **Bucket storage:** 1.6 GB ≈ **$0.03/mo**.
- **Scraping:** **$0** — it runs on your machine; only the resulting upload
  (egress-free, ingress is free) touches GCP.
- **Demo/defense week** with the service warmed (`--min-instances 1`, 2 vCPU/4
  GiB): ~$16 for the week.

Expected total over 90 days: **well under $100**, leaving most of the $350 as
buffer. The budget risk is operational, not usage — see guardrails.

## Budget guardrails (do these)

1. **Set a billing budget + alert** so a mistake can't run for days unnoticed:
   ```bash
   # Find your billing account:  gcloud billing accounts list
   gcloud billing budgets create \
       --billing-account=XXXXXX-XXXXXX-XXXXXX \
       --display-name="thesis-90day" \
       --budget-amount=350 \
       --threshold-rule=percent=0.5 \
       --threshold-rule=percent=0.9
   ```
2. **Never leave the GPU warm.** The job scales to zero on its own; do **not**
   give it `--min-instances`, and don't deploy the GPU image as a *service*.
3. **Warm the serving service only around a demo**, then put it back:
   ```bash
   gcloud run services update thesis-serve --region asia-southeast1 --min-instances 1
   # …after the demo…
   gcloud run services update thesis-serve --region asia-southeast1 --min-instances 0
   ```
4. **Check what's running** if a bill looks off:
   `gcloud run services list` and `gcloud run jobs executions list --region asia-southeast1`.

## Why these specific settings

- **`THESIS_SQLITE_JOURNAL=DELETE`** — SQLite WAL needs a shared-memory mmap that
  GCSFuse can't provide; DELETE (rollback) journal is the supported single-writer
  pattern over a bucket. `max-instances 1` enforces the single writer.
- **`max-instances 1`** on the service — job/progress state is held in-process,
  so a job must be polled from the instance that started it.
- **CPU image (`Dockerfile.serve`)** — drops the CUDA stack (`torch` CPU build,
  no `nvidia-*`/`triton`), so the serving image is ~2-3 GB instead of ~8-10 GB
  → much faster cold starts. Extraction still works here on CPU as a fallback.
- **GPU image (`Dockerfile`)** — unchanged; used only by the job, which
  overrides the entrypoint to `python3 -m backend.batch_extract`.
- **No scraper image at all** — Chromium (~400 MB) would slow the cold start
  every visitor pays, to run a browser that Saudi Exchange blocks from cloud IPs
  anyway. Scraping stays local; `04_sync_corpus.sh` carries the result up.

## Troubleshooting

**`sqlite3.OperationalError: disk I/O error` at `setup()` / `init_db()`** — the
runtime service account can't write the bucket. GCSFuse mounts read-only-capable
by default and surfaces the underlying `403 storage.objects.create denied` as an
I/O error. `01_setup_bucket.sh` now grants `roles/storage.objectAdmin` to the
default compute SA; if you skipped it or use a custom SA:

```bash
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
gcloud storage buckets add-iam-policy-binding "gs://${PROJECT_ID}-thesis-data" \
    --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
    --role=roles/storage.objectAdmin
```

Then re-run without rebuilding: `gcloud run jobs execute thesis-extract --region asia-southeast1 --wait`.
`objectAdmin` (not just `objectViewer`) is required because SQLite's DELETE
journal creates *and deletes* `data.db-journal` on every commit.

## Resolved: corpus paths vs. the bucket mount

*(Was a known caveat; fixed.)* Corpus reports store `local_path` as
`saudi_exchange_pdfs/<company>/<file>.pdf`. Resolving that against `BASE_DIR`
gives `/app/saudi_exchange_pdfs/…`, but in the container the PDFs are on the
bucket at `/data/saudi_exchange_pdfs/…`. Locally the two coincide, so this only
ever broke in prod — the **Query Reports** cart failed with
*"0 document(s) added to cart; 1 failed (PDF missing on disk)"*.

All corpus lookups now go through `config.resolve_corpus_path()`, which strips
the corpus-dir prefix and joins to `PDF_DIR`, so paths resolve wherever the
bucket is mounted. Call sites: `routes/documents.py` (cart registration),
`routes/reports.py` (PDF serving), `database.py` (`seed_from_csv` downloaded
flag), `services/scraper.py` (metadata CSV writes — corpus-relative, so a
locally-scraped CSV resolves correctly once synced to the bucket).

The `corpus_dir` test fixture mounts the corpus **outside** `BASE_DIR` to keep
this class of bug visible in CI, where it previously passed.
