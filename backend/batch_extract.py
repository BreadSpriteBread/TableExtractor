"""Bulk corpus extraction entry point — the command run by the GPU Cloud Run Job.

Rationale: the interactive `/api/extract` path holds job state in-process, so it
can't be driven from a separate GPU instance. This script does the same work
headlessly: it registers every PDF under THESIS_PDF_DIR as a content-addressed
document, then runs the normal extraction pipeline over the ones lacking a
cached result (or all of them with --force), writing to the same SQLite DB the
serving service reads (both point THESIS_DB_PATH at the mounted GCS bucket).

It reuses JobManager and upsert_document verbatim, so timeout/retry/persistence
and the resulting rows are identical to the web path — this is purely a
different trigger, not a second extraction implementation.

Usage (inside the container):
    python3 -m backend.batch_extract [--force] [--limit N] [--workers N]

On a single GPU keep --workers low (1-2): each document runs Docling in its own
child process and they share the one GPU's memory.
"""
import argparse
import sys
import time

from backend.config import EXTRACT_WORKERS, PDF_DIR, get_logger
from backend.database import get_db, setup, sha256_file
from backend.jobs import JobManager
from backend.routes.documents import upsert_document

log = get_logger(__name__)


def register_corpus(conn) -> int:
    """Content-address every PDF under PDF_DIR into the documents table.

    Idempotent: upsert_document is keyed on the content hash, so re-runs and
    files that moved/renamed don't create duplicates. Returns the count seen.
    """
    pdfs = sorted(PDF_DIR.rglob("*.pdf"))
    for path in pdfs:
        try:
            doc_id = sha256_file(path)
        except OSError as e:
            log.warning("skip unreadable pdf path=%s err=%s", path, e)
            continue
        upsert_document(conn, doc_id, path.name, "saudi_exchange", path.resolve())
    conn.commit()
    log.info("corpus registered pdfs=%d dir=%s", len(pdfs), PDF_DIR)
    return len(pdfs)


def pending_documents(conn, force: bool, limit=None) -> list:
    """Documents to extract: all when force, else those without a cached row."""
    if force:
        rows = conn.execute(
            "SELECT document_id, filename, source, file_path FROM documents "
            "ORDER BY acquired_at").fetchall()
    else:
        rows = conn.execute(
            "SELECT d.document_id, d.filename, d.source, d.file_path "
            "FROM documents d "
            "LEFT JOIN extractions e ON e.document_id = d.document_id "
            "WHERE e.document_id IS NULL ORDER BY d.acquired_at").fetchall()
    docs = [dict(r) for r in rows]
    return docs[:limit] if limit else docs


def run(force=False, limit=None, workers=None) -> int:
    """Extract the corpus. Returns a process exit code (0 unless all failed)."""
    setup()  # init schema + seed corpus tables from the metadata CSV
    conn = get_db()
    try:
        register_corpus(conn)
        docs = pending_documents(conn, force, limit)
    finally:
        conn.close()

    if not docs:
        log.info("nothing to extract (all documents already cached)")
        return 0

    workers = workers or EXTRACT_WORKERS
    log.info("starting batch docs=%d workers=%d force=%s", len(docs), workers, force)
    manager = JobManager(workers=workers)
    job_id = manager.submit(docs, force=force)

    last_done = -1
    while True:
        snap = manager.get(job_id)
        if snap["done"] != last_done:
            log.info("progress %d/%d (%.0f%%)", snap["done"], snap["total"],
                     snap["progress"] * 100)
            last_done = snap["done"]
        if snap["state"] != "running":
            break
        time.sleep(2)

    docs_final = snap["documents"]
    counts = {}
    for d in docs_final:
        counts[d["status"]] = counts.get(d["status"], 0) + 1
    log.info("batch complete state=%s counts=%s", snap["state"], counts)

    failed = counts.get("failed", 0)
    # Non-zero exit only if nothing succeeded, so the Job is marked failed only
    # on a total wipeout — partial/failed individual docs are cached, not fatal.
    succeeded = counts.get("success", 0) + counts.get("partial", 0) + counts.get("cached", 0)
    return 0 if succeeded or not failed else 1


def main(argv=None):
    p = argparse.ArgumentParser(description="Bulk-extract the Saudi Exchange PDF corpus.")
    p.add_argument("--force", action="store_true",
                   help="re-extract documents that already have a cached result")
    p.add_argument("--limit", type=int, default=None,
                   help="cap the number of documents (useful for a smoke test)")
    p.add_argument("--workers", type=int, default=None,
                   help="concurrent extraction child processes (default EXTRACT_WORKERS; "
                        "keep at 1-2 on a single GPU)")
    args = p.parse_args(argv)
    return run(force=args.force, limit=args.limit, workers=args.workers)


if __name__ == "__main__":
    sys.exit(main())
