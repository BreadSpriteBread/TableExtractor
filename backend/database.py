"""SQLite layer: corpus tables (companies/reports) + extraction cache
(documents/extractions/table_search FTS5).

Document identity is the SHA-256 of the file bytes, formatted "sha256:<hex>",
so the same file under two names hits the same cache entry.
"""
import csv
import hashlib
import os
import re
import sqlite3
from pathlib import Path

from backend.config import (BASE_DIR, DB_PATH, METADATA_CSV, SQLITE_JOURNAL,
                            get_logger)

log = get_logger(__name__)


def get_db(db_path=None):
    conn = sqlite3.connect(db_path or DB_PATH)
    conn.row_factory = sqlite3.Row
    # journal_mode is an identifier, not a bindable param; SQLITE_JOURNAL is
    # validated against an allowlist in config, so interpolation is safe.
    conn.execute(f"PRAGMA journal_mode={SQLITE_JOURNAL}")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return f"sha256:{h.hexdigest()}"


def sha256_bytes(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


SCHEMA = """
    CREATE TABLE IF NOT EXISTS companies (
        company_code TEXT PRIMARY KEY,
        company_name TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS reports (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        company_code  TEXT NOT NULL,
        company_name  TEXT NOT NULL,
        pdf_url       TEXT,
        local_path    TEXT NOT NULL UNIQUE,
        filename      TEXT NOT NULL,
        published_date TEXT,
        downloaded    INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY (company_code) REFERENCES companies(company_code)
    );

    CREATE TABLE IF NOT EXISTS documents (
        document_id TEXT PRIMARY KEY,          -- "sha256:<hex>"
        filename    TEXT NOT NULL,
        source      TEXT NOT NULL CHECK (source IN ('saudi_exchange', 'upload')),
        file_path   TEXT NOT NULL,
        acquired_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
    );

    -- Latest extraction only (UNIQUE document_id): re-extract overwrites.
    CREATE TABLE IF NOT EXISTS extractions (
        extraction_id INTEGER PRIMARY KEY AUTOINCREMENT,
        document_id   TEXT NOT NULL UNIQUE
                      REFERENCES documents(document_id) ON DELETE CASCADE,
        status        TEXT NOT NULL CHECK (status IN ('success', 'partial', 'failed')),
        extracted_at  TEXT NOT NULL,
        table_count   INTEGER NOT NULL DEFAULT 0,
        duration_ms   INTEGER,
        result_json   TEXT NOT NULL,
        error_summary TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_extractions_status ON extractions(status);
    CREATE INDEX IF NOT EXISTS idx_extractions_date ON extractions(extracted_at);

    -- Full-text search over extracted table content, one row per table.
    CREATE VIRTUAL TABLE IF NOT EXISTS table_search USING fts5(
        document_id UNINDEXED,
        filename,
        headers,
        cells
    );
"""


def init_db(conn=None):
    own = conn is None
    if own:
        conn = get_db()
    conn.executescript(SCHEMA)
    conn.commit()
    if own:
        conn.close()


def index_extraction_for_search(conn, document_id: str, filename: str, tables: list):
    """Replace FTS rows for a document with rows from its latest extraction."""
    conn.execute("DELETE FROM table_search WHERE document_id = ?", (document_id,))
    for t in tables:
        headers = " ".join(str(h) for h in t.get("headers", []))
        cells = " ".join(
            str(c) for row in t.get("rows", []) for c in row if c not in (None, "")
        )
        conn.execute(
            "INSERT INTO table_search (document_id, filename, headers, cells) VALUES (?, ?, ?, ?)",
            (document_id, filename, headers, cells),
        )


def delete_extractions(conn, document_ids: list) -> int:
    """Bulk-delete cached extractions (and their FTS rows). Returns count deleted."""
    deleted = 0
    for doc_id in document_ids:
        cur = conn.execute("DELETE FROM extractions WHERE document_id = ?", (doc_id,))
        deleted += cur.rowcount
        conn.execute("DELETE FROM table_search WHERE document_id = ?", (doc_id,))
    return deleted


def _parse_date_from_filename(filename: str):
    m = re.search(r"(\d{4}-\d{2}-\d{2})", filename)
    return m.group(1) if m else None


def seed_from_csv():
    """Seed companies/reports corpus tables from the scraper metadata CSV."""
    if not METADATA_CSV.exists():
        return

    conn = get_db()
    try:
        with open(METADATA_CSV, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))

        for row in rows:
            conn.execute(
                "INSERT OR IGNORE INTO companies (company_code, company_name) VALUES (?, ?)",
                (row["company_code"], row["company_name"]),
            )
            local_path = row["local_path"]
            filename = Path(local_path).name
            downloaded = row["downloaded"].strip().lower() == "true"
            exists_on_disk = os.path.isfile(str(BASE_DIR / local_path))
            conn.execute(
                """
                INSERT OR IGNORE INTO reports
                    (company_code, company_name, pdf_url, local_path, filename, published_date, downloaded)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["company_code"],
                    row["company_name"],
                    row["pdf_url"],
                    local_path,
                    filename,
                    _parse_date_from_filename(filename),
                    1 if (downloaded and exists_on_disk) else 0,
                ),
            )
        conn.commit()
    finally:
        conn.close()


def setup():
    init_db()
    seed_from_csv()


if __name__ == "__main__":
    setup()
    conn = get_db()
    companies = conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
    reports = conn.execute("SELECT COUNT(*) FROM reports").fetchone()[0]
    downloaded = conn.execute("SELECT COUNT(*) FROM reports WHERE downloaded=1").fetchone()[0]
    docs = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    conn.close()
    print(f"DB ready — {companies} companies, {reports} reports ({downloaded} downloaded), {docs} documents")
