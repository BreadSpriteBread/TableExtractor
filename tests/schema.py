"""Assertions for the per-document export JSON schema."""

DOC_KEYS = {"document_id", "filename", "source", "extracted_at", "status",
            "page_count", "tables", "errors"}
TABLE_KEYS = {"table_id", "pages", "spans_pages", "rotated", "nested",
              "extraction_method", "confidence", "headers", "rows"}


def assert_table_schema(t):
    assert TABLE_KEYS <= set(t.keys()), f"missing table keys: {TABLE_KEYS - set(t)}"
    assert isinstance(t["table_id"], str) and t["table_id"]
    assert isinstance(t["pages"], list) and all(isinstance(p, int) for p in t["pages"])
    assert isinstance(t["spans_pages"], bool)
    assert isinstance(t["rotated"], bool)
    assert isinstance(t["nested"], bool)
    assert t["extraction_method"] in ("vector", "ocr")
    assert isinstance(t["confidence"], (int, float)) and 0 <= t["confidence"] <= 1
    assert isinstance(t["headers"], list)
    assert isinstance(t["rows"], list) and all(isinstance(r, list) for r in t["rows"])
    assert t["spans_pages"] == (len(t["pages"]) > 1)


def assert_result_schema(r):
    """Validate an ExtractionResult dict (no document envelope)."""
    assert r["status"] in ("success", "partial", "failed")
    assert isinstance(r["page_count"], int)
    assert isinstance(r["errors"], list)
    for t in r["tables"]:
        assert_table_schema(t)


def assert_document_schema(d):
    """Validate a full per-document export dict."""
    assert DOC_KEYS <= set(d.keys()), f"missing doc keys: {DOC_KEYS - set(d)}"
    assert d["document_id"].startswith("sha256:")
    assert len(d["document_id"]) == len("sha256:") + 64
    assert d["source"] in ("saudi_exchange", "upload")
    assert isinstance(d["extracted_at"], str) and "T" in d["extracted_at"]
    assert_result_schema(d)
