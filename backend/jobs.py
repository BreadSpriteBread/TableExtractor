"""In-process batch extraction job manager.

- Bounded worker pool (EXTRACT_WORKERS threads); each document runs in a
  child process so it can be killed on timeout (~EXTRACT_TIMEOUT_S) and
  retried once on crash.
- Per-document failures never abort the batch; failed documents are cached
  with error details like any other result.
- Results are written to SQLite per document as they finish, so a 300-doc
  batch never accumulates in memory.
- Jobs are cancellable: queued documents are skipped, running child
  processes are terminated.
"""
import datetime
import json
import multiprocessing
import os
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from backend.config import (EXTRACT_MAX_RETRIES, EXTRACT_TIMEOUT_S,
                            EXTRACT_WORKERS, get_logger)
from backend.database import get_db, index_extraction_for_search
from backend.extraction.models import document_json

log = get_logger(__name__)

_MP_CTX = multiprocessing.get_context("spawn")


def _utcnow():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _kill(proc):
    proc.terminate()
    proc.join(5)
    if proc.is_alive():
        proc.kill()
        proc.join()


def _run_extraction_subprocess(file_path, timeout_s, cancel_event=None):
    """Run one extraction in a killable child process.

    Returns (result_dict | None, error | None, timed_out, cancelled).
    """
    from backend.extraction import worker

    fd, out_path = tempfile.mkstemp(suffix=".json", prefix="extract-")
    os.close(fd)
    try:
        proc = _MP_CTX.Process(target=worker.run, args=(file_path, out_path))
        proc.start()
        deadline = time.monotonic() + timeout_s
        while proc.is_alive() and time.monotonic() < deadline:
            if cancel_event is not None and cancel_event.is_set():
                _kill(proc)
                return None, "cancelled", False, True
            proc.join(0.25)
        if proc.is_alive():
            _kill(proc)
            return None, f"extraction timed out after {int(timeout_s)}s", True, False
        if proc.exitcode != 0:
            return None, f"extraction process crashed (exit code {proc.exitcode})", False, False
        with open(out_path, encoding="utf-8") as f:
            return json.load(f), None, False, False
    except Exception as e:
        return None, f"extraction runner error: {e}", False, False
    finally:
        try:
            os.unlink(out_path)
        except OSError:
            pass


class Job:
    def __init__(self, job_id, documents):
        self.job_id = job_id
        self.created_at = _utcnow()
        self.cancel_event = threading.Event()
        self.lock = threading.Lock()
        # document_id -> per-doc state dict
        self.docs = {
            d["document_id"]: {
                "document_id": d["document_id"],
                "filename": d["filename"],
                "status": "queued",   # queued|running|success|partial|failed|cached|cancelled
                "table_count": None,
                "duration_ms": None,
                "error": None,
            }
            for d in documents
        }

    def snapshot(self):
        with self.lock:
            docs = [dict(v) for v in self.docs.values()]
        done = sum(1 for d in docs
                   if d["status"] in ("success", "partial", "failed", "cached", "cancelled"))
        total = len(docs)
        if self.cancel_event.is_set() and done == total:
            state = "cancelled"
        elif done == total:
            state = "completed"
        else:
            state = "running"
        return {
            "job_id": self.job_id,
            "created_at": self.created_at,
            "state": state,
            "total": total,
            "done": done,
            "progress": round(done / total, 3) if total else 1.0,
            "documents": docs,
        }

    def _set(self, doc_id, **fields):
        with self.lock:
            self.docs[doc_id].update(fields)


class JobManager:
    def __init__(self, db_path=None, workers=EXTRACT_WORKERS,
                 timeout_s=EXTRACT_TIMEOUT_S):
        self.db_path = db_path
        self.timeout_s = timeout_s
        self.pool = ThreadPoolExecutor(max_workers=workers,
                                       thread_name_prefix="extract")
        self.jobs = {}
        self.lock = threading.Lock()

    def _db(self):
        return get_db(self.db_path)

    def submit(self, documents, force=False):
        """documents: list of dicts with document_id, filename, source, file_path.
        Returns job_id immediately; extraction runs on the pool."""
        job = Job(uuid.uuid4().hex[:12], documents)
        with self.lock:
            self.jobs[job.job_id] = job
        for d in documents:
            self.pool.submit(self._process_doc, job, d, force)
        log.info("job submitted job_id=%s docs=%d force=%s",
                 job.job_id, len(documents), force)
        return job.job_id

    def get(self, job_id):
        with self.lock:
            job = self.jobs.get(job_id)
        return job.snapshot() if job else None

    def cancel(self, job_id):
        with self.lock:
            job = self.jobs.get(job_id)
        if not job:
            return False
        job.cancel_event.set()
        with job.lock:
            for state in job.docs.values():
                if state["status"] == "queued":
                    state["status"] = "cancelled"
        log.info("job cancelled job_id=%s", job_id)
        return True

    # ------------------------------------------------------------------

    def _process_doc(self, job, doc, force):
        doc_id = doc["document_id"]
        if job.cancel_event.is_set():
            job._set(doc_id, status="cancelled")
            return
        try:
            self._process_doc_inner(job, doc, force)
        except Exception as e:  # never let one doc kill the batch
            log.error("doc processing error document_id=%s err=%s", doc_id, e)
            job._set(doc_id, status="failed", error=str(e))

    def _process_doc_inner(self, job, doc, force):
        doc_id = doc["document_id"]
        conn = self._db()
        try:
            if not force:
                row = conn.execute(
                    "SELECT status, table_count FROM extractions WHERE document_id = ?",
                    (doc_id,)).fetchone()
                if row:
                    job._set(doc_id, status="cached",
                             table_count=row["table_count"], duration_ms=0)
                    return

            job._set(doc_id, status="running")
            start = time.monotonic()

            result, error, timed_out, cancelled = _run_extraction_subprocess(
                doc["file_path"], self.timeout_s, job.cancel_event)
            if result is None and not timed_out and not cancelled:
                for _ in range(EXTRACT_MAX_RETRIES):  # one retry on crash
                    log.warning("retrying after crash document_id=%s", doc_id)
                    result, error, timed_out, cancelled = _run_extraction_subprocess(
                        doc["file_path"], self.timeout_s, job.cancel_event)
                    if result is not None or timed_out or cancelled:
                        break

            if cancelled:
                job._set(doc_id, status="cancelled")
                return

            duration_ms = int((time.monotonic() - start) * 1000)
            if result is None:
                result = {"status": "failed", "page_count": 0,
                          "tables": [], "errors": [error]}

            extracted_at = _utcnow()
            full = document_json(result, doc_id, doc["filename"],
                                 doc["source"], extracted_at)
            error_summary = "; ".join(result["errors"])[:500] or None

            conn.execute(
                """
                INSERT INTO extractions
                    (document_id, status, extracted_at, table_count,
                     duration_ms, result_json, error_summary)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(document_id) DO UPDATE SET
                    status=excluded.status,
                    extracted_at=excluded.extracted_at,
                    table_count=excluded.table_count,
                    duration_ms=excluded.duration_ms,
                    result_json=excluded.result_json,
                    error_summary=excluded.error_summary
                """,
                (doc_id, result["status"], extracted_at, len(result["tables"]),
                 duration_ms, json.dumps(full), error_summary),
            )
            index_extraction_for_search(conn, doc_id, doc["filename"],
                                        result["tables"])
            conn.commit()

            job._set(doc_id, status=result["status"],
                     table_count=len(result["tables"]),
                     duration_ms=duration_ms, error=error_summary)
        finally:
            conn.close()


_manager = None
_manager_lock = threading.Lock()


def get_manager() -> JobManager:
    global _manager
    with _manager_lock:
        if _manager is None:
            _manager = JobManager()
        return _manager


def set_manager(manager):
    """Test hook: swap the global manager (e.g. for a throwaway DB)."""
    global _manager
    with _manager_lock:
        _manager = manager
