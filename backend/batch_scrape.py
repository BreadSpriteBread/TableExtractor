"""Live Saudi Exchange scrape entry point — run this LOCALLY, on a desktop.

Deliberately not a Cloud Run job. `services/scraper.py` drives a headed,
stealth-patched Chromium (patchright, spoofed navigator fields, randomised
delays) because Saudi Exchange challenges automated clients; headless Chromium
from a datacenter egress IP gets blocked outright. So the cloud never scrapes:
the deployed service runs with SCRAPER_STUB=1 and its Acquire tab only re-syncs
the corpus from the metadata CSV.

The workflow is:

    python3 -m backend.batch_scrape [N]     # 1. scrape locally (this script)
    deploy/04_sync_corpus.sh                # 2. push PDFs + CSV to the bucket

N is optional: how many company rows to scrape from
``backend/saudi_exchange_company_profiles.csv``. Omit it to scrape every row.
Start small (``5``) — a full run is hours of deliberate rate-limiting.

PDFs are written under THESIS_PDF_DIR, download_metadata.csv is upserted, and
the local corpus tables are re-seeded so the scrape is visible in the local UI
before you push anything.
"""
import argparse
import asyncio
import sys

from backend.config import SCRAPER_STUB, get_logger
from backend.database import setup
from backend.services.scraper import _read_profiles

log = get_logger(__name__)


def run(limit=None) -> int:
    """Scrape `limit` companies (all when None). Returns a process exit code."""
    if SCRAPER_STUB:
        # Fail loudly rather than silently "succeeding" with a CSV re-sync — that
        # stub message is exactly what made this confusing in the deployed UI.
        log.error("SCRAPER_STUB=1 — refusing to run a stub scrape. "
                  "Unset it (or set SCRAPER_STUB=0) to scrape live.")
        return 2

    total = len(_read_profiles())
    if limit is not None:
        if limit < 1:
            log.error("row count must be >= 1 (got %d)", limit)
            return 2
        if limit > total:
            log.warning("requested %d rows but the profiles CSV has %d — "
                        "scraping all %d", limit, total, total)
            limit = total

    setup()  # init schema + seed corpus tables before the scrape writes to them

    # Imported here, not at module top, so this module stays importable without
    # patchright installed (the CPU serving image drops it).
    from backend.services.scraper import _scrape_live

    log.info("scraping companies=%s of %d (headed browser — keep the window open)",
             limit or "all", total)
    downloaded, failed = asyncio.run(_scrape_live(limit=limit))
    log.info("scrape complete downloaded=%d failed=%d", downloaded, failed)

    if not downloaded and failed:
        log.error("nothing downloaded. If the browser showed a challenge/consent "
                  "page, Saudi Exchange flagged the session — retry later or from "
                  "a different network.")
        return 1

    log.info("next: push the results to the bucket with deploy/04_sync_corpus.sh")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(
        description="Live-scrape the Saudi Exchange PDF corpus (run locally; "
                    "opens a real browser window).")
    p.add_argument("rows", nargs="?", type=int, default=None,
                   help="how many company rows to scrape from "
                        "backend/saudi_exchange_company_profiles.csv "
                        "(default: all rows)")
    args = p.parse_args(argv)
    return run(limit=args.rows)


if __name__ == "__main__":
    sys.exit(main())
