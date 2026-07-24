"""Central configuration, overridable via environment variables."""
import logging
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent

DB_PATH = Path(os.environ.get("THESIS_DB_PATH", BASE_DIR / "data.db"))
# Built frontend (vite build output). Served by Flask when present (prod
# container); in dev the Vite dev server serves the UI and proxies /api.
FRONTEND_DIST = Path(os.environ.get("THESIS_FRONTEND_DIST",
                                    BASE_DIR / "frontend" / "dist"))
PDF_DIR = Path(os.environ.get("THESIS_PDF_DIR", BASE_DIR / "saudi_exchange_pdfs"))
UPLOAD_DIR = Path(os.environ.get("THESIS_UPLOAD_DIR", BASE_DIR / "uploads"))
METADATA_CSV = PDF_DIR / "download_metadata.csv"


def resolve_corpus_path(local_path) -> Path:
    """Resolve a report's stored ``local_path`` to an absolute path under PDF_DIR.

    The CSV/DB stores repo-relative paths prefixed with the corpus dir name,
    e.g. ``saudi_exchange_pdfs/2030_SARCO/foo.pdf``. Locally PDF_DIR lives under
    BASE_DIR so joining to BASE_DIR happens to work, but on Cloud Run the corpus
    is on the mounted bucket (THESIS_PDF_DIR=/data/saudi_exchange_pdfs) and NOT
    under BASE_DIR (/app). Strip the leading corpus-dir prefix and join to
    PDF_DIR so paths resolve wherever the bucket is mounted.
    """
    p = Path(local_path)
    if p.parts and p.parts[0] == PDF_DIR.name:
        p = Path(*p.parts[1:])
    return PDF_DIR / p

# SQLite journal mode. WAL is best for local disk (concurrent readers), but it
# needs shared-memory mmap that GCSFuse can't provide — so when the DB lives on
# a mounted GCS bucket (single writer, enforced by Cloud Run max-instances=1)
# set THESIS_SQLITE_JOURNAL=DELETE. Restricted to a safe allowlist.
_JOURNAL_MODES = {"WAL", "DELETE", "TRUNCATE", "PERSIST", "MEMORY", "OFF"}
SQLITE_JOURNAL = os.environ.get("THESIS_SQLITE_JOURNAL", "WAL").upper()
if SQLITE_JOURNAL not in _JOURNAL_MODES:
    SQLITE_JOURNAL = "WAL"

# Bulk extraction job settings
EXTRACT_WORKERS = int(os.environ.get("EXTRACT_WORKERS", "4"))
# Docling loads its layout/TableFormer models in each extraction child
# No GPU acceleration avaliable. This process is taking 300+ seconds
EXTRACT_TIMEOUT_S = float(os.environ.get("EXTRACT_TIMEOUT_S", "600"))
EXTRACT_MAX_RETRIES = 1  # one automatic retry on crash

# Scraper: set SCRAPER_STUB=1 (e.g. in CI, and in the deployed service) to avoid
# live Saudi Exchange traffic. Live scraping is a local-only workflow — see
# backend/batch_scrape.py.
SCRAPER_STUB = os.environ.get("SCRAPER_STUB", "0") == "1"

_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def get_logger(name: str) -> logging.Logger:
    """Structured-ish logger: key=value pairs go in the message."""
    logger = logging.getLogger(name)
    if not logging.getLogger().handlers and not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter(_LOG_FORMAT))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger
