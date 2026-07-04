"""Caching semantics: content-hash identity, cache hits, re-extract overwrite."""
import json

from backend.database import get_db
from tests.conftest import FIXTURE_PDFS, upload_pdf, wait_for_job


def test_same_bytes_different_filename_same_document(client):
    d1 = upload_pdf(client, FIXTURE_PDFS / "simple.pdf", "report_a.pdf")
    d2 = upload_pdf(client, FIXTURE_PDFS / "simple.pdf", "totally_different.pdf")
    assert d1["document_id"] == d2["document_id"]


def test_cache_hit_skips_reextraction(client):
    doc = upload_pdf(client, FIXTURE_PDFS / "simple.pdf")
    doc_id = doc["document_id"]

    job1 = client.post("/api/extract", json={"document_ids": [doc_id]}).get_json()["job_id"]
    snap1 = wait_for_job(client, job1)
    assert snap1["documents"][0]["status"] == "success"

    # Same bytes under a different name: still one document, cached result.
    upload_pdf(client, FIXTURE_PDFS / "simple.pdf", "renamed.pdf")
    job2 = client.post("/api/extract", json={"document_ids": [doc_id]}).get_json()["job_id"]
    snap2 = wait_for_job(client, job2)
    assert snap2["documents"][0]["status"] == "cached"
    assert snap2["documents"][0]["duration_ms"] == 0


def test_reextract_overwrites_not_duplicates(client, db_path):
    doc = upload_pdf(client, FIXTURE_PDFS / "simple.pdf")
    doc_id = doc["document_id"]

    job1 = client.post("/api/extract", json={"document_ids": [doc_id]}).get_json()["job_id"]
    wait_for_job(client, job1)
    first = client.get(f"/api/extractions/{doc_id}").get_json()

    job2 = client.post("/api/extract", json={
        "document_ids": [doc_id], "force": True}).get_json()["job_id"]
    snap = wait_for_job(client, job2)
    assert snap["documents"][0]["status"] == "success", "force must re-run, not use cache"

    conn = get_db(db_path)
    rows = conn.execute(
        "SELECT * FROM extractions WHERE document_id = ?", (doc_id,)).fetchall()
    conn.close()
    assert len(rows) == 1, "re-extract must overwrite, not duplicate"

    second = client.get(f"/api/extractions/{doc_id}").get_json()
    assert second["extracted_at"] >= first["extracted_at"]
    assert second["tables"] == first["tables"]


def test_failed_docs_are_cached_with_errors(client):
    doc = upload_pdf(client, FIXTURE_PDFS / "corrupted.pdf")
    job = client.post("/api/extract", json={
        "document_ids": [doc["document_id"]]}).get_json()["job_id"]
    wait_for_job(client, job)

    cached = client.get(f"/api/extractions/{doc['document_id']}").get_json()
    assert cached["status"] == "failed"
    assert cached["errors"]

    # and a repeat run hits the cache even for failures
    job2 = client.post("/api/extract", json={
        "document_ids": [doc["document_id"]]}).get_json()["job_id"]
    snap = wait_for_job(client, job2)
    assert snap["documents"][0]["status"] == "cached"
