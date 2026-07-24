"""Shared test setup.

Environment overrides happen at import time, BEFORE any backend module is
imported, so config picks up throwaway paths and never touches the real
data.db or corpus.
"""
import os
import tempfile
import time

_session_tmp = tempfile.mkdtemp(prefix="thesis-tests-")
os.environ["SCRAPER_STUB"] = "1"
os.environ["THESIS_DB_PATH"] = os.path.join(_session_tmp, "data.db")
os.environ["THESIS_UPLOAD_DIR"] = os.path.join(_session_tmp, "uploads")
os.environ["THESIS_PDF_DIR"] = os.path.join(_session_tmp, "no_corpus")

from pathlib import Path

import pytest

import backend.database as database
import backend.jobs as jobs
import backend.routes.documents as documents_routes
from backend.jobs import JobManager

FIXTURE_PDFS = Path(__file__).parent / "fixtures" / "pdfs"
EXPECTED_DIR = Path(__file__).parent / "fixtures" / "expected"


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    """Throwaway SQLite database, fully isolated per test."""
    p = tmp_path / "test.db"
    monkeypatch.setattr(database, "DB_PATH", p)
    database.init_db()
    return p


@pytest.fixture
def manager(db_path):
    # Generous timeout: each extraction child process loads docling's
    # layout/TableFormer models (~15-30s) before converting anything.
    m = JobManager(db_path=str(db_path), workers=2, timeout_s=180)
    jobs.set_manager(m)
    yield m
    jobs.set_manager(None)
    m.pool.shutdown(wait=True, cancel_futures=True)


@pytest.fixture
def client(db_path, manager, tmp_path, monkeypatch):
    monkeypatch.setattr(documents_routes, "UPLOAD_DIR", tmp_path / "uploads")
    from backend.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture
def corpus_dir(tmp_path, monkeypatch):
    """Corpus mounted outside BASE_DIR, mirroring the Cloud Run bucket layout.

    Prod mounts the GCS bucket at /data while the code lives at /app, so any
    code that resolves a report's ``local_path`` against BASE_DIR silently
    works locally and 404s in prod. Pointing PDF_DIR somewhere unrelated to
    BASE_DIR keeps that class of bug visible in CI.
    """
    import backend.config as config

    root = tmp_path / "saudi_exchange_pdfs"
    (root / "9999_TestCo").mkdir(parents=True)
    monkeypatch.setattr(config, "PDF_DIR", root)
    return root


def wait_for_job(client, job_id, timeout=300):
    """Poll the job endpoint until it reaches a terminal state."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        snap = client.get(f"/api/jobs/{job_id}").get_json()
        if snap["state"] in ("completed", "cancelled"):
            return snap
        time.sleep(0.1)
    raise AssertionError(f"job {job_id} did not finish within {timeout}s")


def upload_pdf(client, path, filename=None):
    """Upload a fixture PDF; returns the document dict."""
    with open(path, "rb") as f:
        data = {"files": (f, filename or Path(path).name)}
        resp = client.post("/api/documents/upload", data=data,
                           content_type="multipart/form-data")
    assert resp.status_code == 200, resp.get_json()
    result = resp.get_json()["results"][0]
    assert "document" in result, result
    return result["document"]
