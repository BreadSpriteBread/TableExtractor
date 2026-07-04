"""Failure handling: bad files never abort a batch; timeout and crash-retry."""
import backend.jobs as jobs_module
from backend.jobs import JobManager
from tests.conftest import FIXTURE_PDFS, upload_pdf, wait_for_job


def test_bad_files_do_not_abort_batch(client):
    """A batch mixing good and broken PDFs completes with per-doc statuses."""
    names = ["simple.pdf", "corrupted.pdf", "zero_byte.pdf", "password.pdf",
             "borderless.pdf"]
    docs = [upload_pdf(client, FIXTURE_PDFS / n) for n in names]
    ids = [d["document_id"] for d in docs]

    job_id = client.post("/api/extract", json={"document_ids": ids}).get_json()["job_id"]
    snap = wait_for_job(client, job_id)

    assert snap["state"] == "completed"
    by_file = {d["filename"]: d for d in snap["documents"]}
    assert by_file["simple.pdf"]["status"] == "success"
    assert by_file["borderless.pdf"]["status"] == "success"
    assert by_file["corrupted.pdf"]["status"] == "failed"
    assert by_file["zero_byte.pdf"]["status"] == "failed"
    assert by_file["password.pdf"]["status"] == "failed"

    # every failed doc is still cached with error details
    for name in ("corrupted.pdf", "zero_byte.pdf", "password.pdf"):
        cached = client.get(f"/api/extractions/{by_file[name]['document_id']}").get_json()
        assert cached["status"] == "failed"
        assert cached["errors"], f"{name} should carry error details"


def test_timeout_produces_failed_result(client, db_path, monkeypatch, manager):
    monkeypatch.setenv("EXTRACT_TEST_SLEEP", "30")
    fast = JobManager(db_path=str(db_path), workers=1, timeout_s=2)
    jobs_module.set_manager(fast)
    try:
        doc = upload_pdf(client, FIXTURE_PDFS / "simple.pdf")
        job_id = client.post("/api/extract", json={
            "document_ids": [doc["document_id"]]}).get_json()["job_id"]
        snap = wait_for_job(client, job_id, timeout=30)

        d = snap["documents"][0]
        assert d["status"] == "failed"
        assert "timed out" in d["error"]

        cached = client.get(f"/api/extractions/{doc['document_id']}").get_json()
        assert cached["status"] == "failed"
        assert any("timed out" in e for e in cached["errors"])
    finally:
        fast.pool.shutdown(wait=True, cancel_futures=True)


def test_crash_gets_one_retry(client, tmp_path, monkeypatch):
    """Child crashes on first attempt, marker file makes the retry succeed."""
    marker = tmp_path / "crash_once.marker"
    monkeypatch.setenv("EXTRACT_TEST_CRASH_ONCE", str(marker))

    doc = upload_pdf(client, FIXTURE_PDFS / "simple.pdf")
    job_id = client.post("/api/extract", json={
        "document_ids": [doc["document_id"]]}).get_json()["job_id"]
    snap = wait_for_job(client, job_id)

    assert marker.exists(), "first attempt should have crashed"
    assert snap["documents"][0]["status"] == "success", "retry should succeed"


def test_persistent_crash_fails_after_retry(client, monkeypatch, tmp_path):
    """If both attempts crash, the document fails with a crash error."""
    # marker path in a non-existent dir: open() fails -> child dies every time
    monkeypatch.setenv("EXTRACT_TEST_CRASH_ONCE", str(tmp_path / "missing" / "m"))

    doc = upload_pdf(client, FIXTURE_PDFS / "simple.pdf")
    job_id = client.post("/api/extract", json={
        "document_ids": [doc["document_id"]]}).get_json()["job_id"]
    snap = wait_for_job(client, job_id)

    d = snap["documents"][0]
    assert d["status"] == "failed"
    assert "crash" in d["error"]
