"""API tests: async batch submit, polling, search, export, delete."""
import json
import shutil
import time

from tests.conftest import FIXTURE_PDFS, upload_pdf, wait_for_job
from tests.schema import assert_document_schema


def test_upload_returns_document(client):
    doc = upload_pdf(client, FIXTURE_PDFS / "simple.pdf")
    assert doc["document_id"].startswith("sha256:")
    assert doc["source"] == "upload"
    assert doc["extraction_status"] is None


def test_upload_rejects_non_pdf(client):
    import io
    resp = client.post(
        "/api/documents/upload",
        data={"files": (io.BytesIO(b"hi"), "notes.txt")},
        content_type="multipart/form-data")
    result = resp.get_json()["results"][0]
    assert "error" in result


def test_submit_batch_returns_immediately(client, monkeypatch):
    monkeypatch.setenv("EXTRACT_TEST_SLEEP", "3")
    doc = upload_pdf(client, FIXTURE_PDFS / "simple.pdf")

    start = time.monotonic()
    resp = client.post("/api/extract", json={"document_ids": [doc["document_id"]]})
    elapsed = time.monotonic() - start

    assert resp.status_code == 202
    assert elapsed < 1.0, "submit must not block on extraction"
    job_id = resp.get_json()["job_id"]

    snap = client.get(f"/api/jobs/{job_id}").get_json()
    assert snap["state"] == "running"
    assert snap["total"] == 1

    snap = wait_for_job(client, job_id)
    assert snap["state"] == "completed"
    assert snap["documents"][0]["status"] == "success"
    assert snap["documents"][0]["table_count"] == 1
    assert snap["documents"][0]["duration_ms"] >= 0


def test_extract_unknown_document_400(client):
    resp = client.post("/api/extract", json={"document_ids": ["sha256:" + "0" * 64]})
    assert resp.status_code == 400


def test_job_not_found_404(client):
    assert client.get("/api/jobs/nope").status_code == 404
    assert client.post("/api/jobs/nope/cancel").status_code == 404


def test_fetch_result_and_schema(client):
    doc = upload_pdf(client, FIXTURE_PDFS / "simple.pdf")
    job_id = client.post("/api/extract", json={
        "document_ids": [doc["document_id"]]}).get_json()["job_id"]
    wait_for_job(client, job_id)

    resp = client.get(f"/api/extractions/{doc['document_id']}")
    assert resp.status_code == 200
    result = resp.get_json()
    assert_document_schema(result)
    assert result["document_id"] == doc["document_id"]
    assert result["filename"] == "simple.pdf"
    assert result["tables"][0]["headers"] == ["Item", "Q1", "Q2", "Total"]


def test_result_404_when_not_extracted(client):
    doc = upload_pdf(client, FIXTURE_PDFS / "simple.pdf")
    assert client.get(f"/api/extractions/{doc['document_id']}").status_code == 404


def _extract_and_wait(client, paths, names=None):
    docs = []
    for i, p in enumerate(paths):
        docs.append(upload_pdf(client, p, (names or {}).get(i)))
    ids = [d["document_id"] for d in docs]
    job_id = client.post("/api/extract", json={"document_ids": ids}).get_json()["job_id"]
    wait_for_job(client, job_id)
    return docs


def test_search_filters(client):
    docs = _extract_and_wait(
        client,
        [FIXTURE_PDFS / "simple.pdf", FIXTURE_PDFS / "corrupted.pdf"])

    all_rows = client.get("/api/extractions").get_json()["results"]
    assert len(all_rows) == 2

    ok = client.get("/api/extractions?status=success").get_json()["results"]
    assert [r["document_id"] for r in ok] == [docs[0]["document_id"]]

    failed = client.get("/api/extractions?status=failed").get_json()["results"]
    assert [r["document_id"] for r in failed] == [docs[1]["document_id"]]
    assert failed[0]["error_summary"]

    by_name = client.get("/api/extractions?filename=simple").get_json()["results"]
    assert len(by_name) == 1

    # full-text over cell content
    fts = client.get("/api/extractions?q=Revenue").get_json()["results"]
    assert [r["document_id"] for r in fts] == [docs[0]["document_id"]]

    fts_miss = client.get("/api/extractions?q=zzzunfindable").get_json()["results"]
    assert fts_miss == []

    # date range
    today = time.strftime("%Y-%m-%d", time.gmtime())  # extracted_at is UTC
    in_range = client.get(f"/api/extractions?date_from={today}&date_to={today}").get_json()["results"]
    assert len(in_range) == 2
    none = client.get("/api/extractions?date_to=2000-01-01").get_json()["results"]
    assert none == []


def test_bulk_export_shape(client):
    docs = _extract_and_wait(
        client, [FIXTURE_PDFS / "simple.pdf", FIXTURE_PDFS / "borderless.pdf"])
    ids = [d["document_id"] for d in docs]

    resp = client.post("/api/extractions/export", json={"document_ids": ids})
    body = resp.get_json()
    assert set(body.keys()) == {"documents"}
    assert len(body["documents"]) == 2
    for d in body["documents"]:
        assert_document_schema(d)


def test_bulk_delete(client):
    docs = _extract_and_wait(
        client, [FIXTURE_PDFS / "simple.pdf", FIXTURE_PDFS / "borderless.pdf"])
    ids = [d["document_id"] for d in docs]

    resp = client.post("/api/extractions/delete", json={"document_ids": ids})
    assert resp.get_json()["deleted"] == 2
    assert client.get("/api/extractions").get_json()["results"] == []
    # FTS rows gone too: search returns nothing
    assert client.get("/api/extractions?q=Revenue").get_json()["results"] == []


def test_cancel_job(client, monkeypatch):
    monkeypatch.setenv("EXTRACT_TEST_SLEEP", "5")
    docs = [upload_pdf(client, FIXTURE_PDFS / "simple.pdf"),
            upload_pdf(client, FIXTURE_PDFS / "borderless.pdf"),
            upload_pdf(client, FIXTURE_PDFS / "landscape_table.pdf"),
            upload_pdf(client, FIXTURE_PDFS / "multipage.pdf")]
    ids = [d["document_id"] for d in docs]
    job_id = client.post("/api/extract", json={"document_ids": ids}).get_json()["job_id"]

    resp = client.post(f"/api/jobs/{job_id}/cancel")
    assert resp.status_code == 200
    snap = wait_for_job(client, job_id, timeout=300)
    assert snap["state"] == "cancelled"
    statuses = {d["status"] for d in snap["documents"]}
    assert "cancelled" in statuses


def test_scrape_stub(client):
    resp = client.post("/api/scrape", json={})
    assert resp.status_code in (202, 409)
    for _ in range(50):
        status = client.get("/api/scrape/status").get_json()
        if status["state"] in ("done", "error", "idle"):
            break
        time.sleep(0.1)
    assert status["state"] == "done"
    # The message must state what actually happened (a CSV re-sync, no network)
    # and where real scraping lives — a bare "stub mode" read as a broken deploy.
    assert "re-synced corpus" in status["message"]
    assert "no live scrape" in status["message"]


def _patch_scrape_live(monkeypatch, db_path):
    """Run batch_scrape's real logic with the browser swapped out.

    Records the `limit` that reaches _scrape_live so the row-count argument can
    be asserted without launching Chromium.
    """
    import backend.batch_scrape as batch_scrape
    import backend.services.scraper as scraper_svc

    seen = {}

    async def fake_scrape_live(codes=None, limit=None):
        seen["limit"] = limit
        return (3, 0)

    monkeypatch.setattr(scraper_svc, "_scrape_live", fake_scrape_live)
    monkeypatch.setattr(batch_scrape, "SCRAPER_STUB", False)
    monkeypatch.setattr(batch_scrape, "setup", lambda: None)
    return batch_scrape, seen


def test_batch_scrape_row_count_argument(monkeypatch, db_path):
    """The optional positional arg caps how many profile CSV rows are scraped."""
    batch_scrape, seen = _patch_scrape_live(monkeypatch, db_path)

    assert batch_scrape.main(["5"]) == 0
    assert seen["limit"] == 5


def test_batch_scrape_defaults_to_all_rows(monkeypatch, db_path):
    """No argument means the whole profiles CSV (limit=None slices everything)."""
    batch_scrape, seen = _patch_scrape_live(monkeypatch, db_path)

    assert batch_scrape.main([]) == 0
    assert seen["limit"] is None


def test_batch_scrape_clamps_oversized_row_count(monkeypatch, db_path):
    """Asking for more rows than the CSV has scrapes all of them, not an error."""
    from backend.services.scraper import _read_profiles
    batch_scrape, seen = _patch_scrape_live(monkeypatch, db_path)

    total = len(_read_profiles())
    assert batch_scrape.main([str(total + 500)]) == 0
    assert seen["limit"] == total


def test_batch_scrape_rejects_nonsense_row_count(monkeypatch, db_path):
    """A zero/negative count is a usage error, not a silent full scrape."""
    batch_scrape, seen = _patch_scrape_live(monkeypatch, db_path)

    assert batch_scrape.main(["0"]) == 2
    assert seen == {}  # never reached the browser


def test_batch_scrape_refuses_stub_mode(monkeypatch, db_path):
    """Guard against the stub silently 'succeeding' with a CSV re-sync."""
    import backend.batch_scrape as batch_scrape
    monkeypatch.setattr(batch_scrape, "SCRAPER_STUB", True)

    assert batch_scrape.main(["5"]) == 2


def test_scrape_companies_list(client):
    resp = client.get("/api/scrape/companies")
    assert resp.status_code == 200
    companies = resp.get_json()["companies"]
    assert companies, "expected companies from the profiles CSV"
    row = companies[0]
    assert {"code", "name", "sector", "folder", "scraped", "pdf_count"} <= row.keys()


def test_scrape_rejects_non_list_codes(client):
    resp = client.post("/api/scrape", json={"codes": "2030"})
    assert resp.status_code == 400
    assert "codes" in resp.get_json()["error"]


def test_register_reports_as_documents(client, db_path, corpus_dir):
    """Query Reports flow: corpus report ids become content-addressed documents.

    ``corpus_dir`` mounts the corpus OUTSIDE BASE_DIR, the way Cloud Run does
    (bucket at /data, code at /app), so report paths must resolve via PDF_DIR
    rather than BASE_DIR.
    """
    from backend.database import get_db

    shutil.copy(FIXTURE_PDFS / "simple.pdf", corpus_dir / "9999_TestCo" / "simple.pdf")
    # Stored exactly as the metadata CSV writes it: corpus-dir-prefixed.
    rel = f"{corpus_dir.name}/9999_TestCo/simple.pdf"
    conn = get_db(db_path)
    conn.execute("INSERT INTO companies (company_code, company_name) VALUES ('9999', 'TestCo')")
    conn.execute(
        """INSERT INTO reports (company_code, company_name, local_path, filename, downloaded)
           VALUES ('9999', 'TestCo', ?, 'simple.pdf', 1)""", (rel,))
    rid = conn.execute("SELECT id FROM reports").fetchone()["id"]
    conn.commit()
    conn.close()

    resp = client.post("/api/documents/register", json={"report_ids": [rid, 999999]})
    assert resp.status_code == 200
    results = resp.get_json()["results"]

    ok = results[0]
    assert ok["document"]["document_id"].startswith("sha256:")
    assert ok["document"]["source"] == "saudi_exchange"
    missing = results[1]
    assert "error" in missing  # unknown report id doesn't abort the batch

    # registered document is immediately extractable
    doc_id = ok["document"]["document_id"]
    job_id = client.post("/api/extract", json={"document_ids": [doc_id]}).get_json()["job_id"]
    snap = wait_for_job(client, job_id)
    assert snap["documents"][0]["status"] == "success"
