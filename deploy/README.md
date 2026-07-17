# Deployment (Cloud Run, `asia-southeast1` / Singapore)

A budget-first deployment split into two workloads so idle time costs ~nothing
and the expensive GPU only bills while it's actually extracting.

| Piece | What | Cost posture |
|---|---|---|
| **Serving service** (`thesis-serve`) | CPU-only Flask + UI, reads/writes SQLite on the bucket | Scale-to-zero → **$0 idle** |
| **Extraction job** (`thesis-extract`) | L4 GPU batch over the corpus, on demand | Per-second, scales to zero when done |
| **Data bucket** (`gs://…-thesis-data`) | Persistent SQLite DB + corpus PDFs + uploads | ~**$0.03/mo** for 1.6 GB |

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

## Cost model (real numbers)

Cloud Run rates (us-central1 tier; Singapore is close): CPU **$0.0864/vCPU-hr**,
memory **$0.009/GiB-hr**, L4 GPU **$0.672/GPU-hr** (no zonal redundancy).

- **Serving, scale-to-zero:** ~$0 when idle; a browsing session is cents. Most
  of it fits in the monthly free tier (180k vCPU-s / 360k GiB-s).
- **One full corpus extraction (437 PDFs) on the L4:** ~5 hrs, **~$6**. Even a
  handful of full re-runs is well under $50.
- **Bucket storage:** 1.6 GB ≈ **$0.03/mo**.
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

## Known caveat

`seed_from_csv()` marks a corpus report `downloaded=1` only if its PDF exists at
`BASE_DIR/local_path` (i.e. `/app/saudi_exchange_pdfs/…`), but in the container
the PDFs live on the bucket at `/data/saudi_exchange_pdfs/…`. So the **Query
Reports** tab may show reports as not-downloaded even though extraction works
(the job walks `THESIS_PDF_DIR` directly and is unaffected). If that tab needs to
reflect the bucket, resolve the existence check against `PDF_DIR` rather than
`BASE_DIR/local_path`. Left as a follow-up to avoid changing corpus semantics
here.
