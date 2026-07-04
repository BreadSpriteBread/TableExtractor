"""Central configuration, overridable via environment variables."""
import logging
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent

DB_PATH = Path(os.environ.get("THESIS_DB_PATH", BASE_DIR / "data.db"))
PDF_DIR = Path(os.environ.get("THESIS_PDF_DIR", BASE_DIR / "saudi_exchange_pdfs"))
UPLOAD_DIR = Path(os.environ.get("THESIS_UPLOAD_DIR", BASE_DIR / "uploads"))
METADATA_CSV = PDF_DIR / "download_metadata.csv"

# Bulk extraction job settings
EXTRACT_WORKERS = int(os.environ.get("EXTRACT_WORKERS", "4"))
EXTRACT_TIMEOUT_S = float(os.environ.get("EXTRACT_TIMEOUT_S", "120"))
EXTRACT_MAX_RETRIES = 1  # one automatic retry on crash

# Scraper: set SCRAPER_STUB=1 (e.g. in CI) to avoid live Saudi Exchange traffic
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
