"""Extraction engine tests against hand-verified fixture PDFs.

Text-layer fixtures are compared exactly; the scanned (OCR) fixture fuzzily
(word recall).
"""
import json

import pytest

from backend.extraction import docling_engine, extract
from tests.conftest import EXPECTED_DIR, FIXTURE_PDFS
from tests.schema import assert_result_schema

FIXTURES = sorted(p.stem for p in EXPECTED_DIR.glob("*.json"))


def load_expected(name):
    return json.loads((EXPECTED_DIR / f"{name}.json").read_text())


def pdf_for(name):
    return str(FIXTURE_PDFS / f"{name}.pdf")


def _norm_words(cells):
    return {w.lower() for c in cells for w in str(c).split() if w.strip()}


def assert_fuzzy_table(expected_t, actual_t, recall=0.7):
    """OCR comparison: most expected cell words must appear in the output."""
    exp = _norm_words(expected_t["headers"]) | _norm_words(
        c for row in expected_t["rows"] for c in row)
    act = _norm_words(actual_t["headers"]) | _norm_words(
        c for row in actual_t["rows"] for c in row)
    found = len(exp & act) / len(exp)
    assert found >= recall, f"OCR recall {found:.2f} < {recall}: missing {exp - act}"


def assert_exact_table(expected_t, actual_t):
    assert actual_t["headers"] == expected_t["headers"]
    assert actual_t["rows"] == expected_t["rows"]


@pytest.mark.parametrize("name", FIXTURES)
def test_fixture(name):
    expected = load_expected(name)
    if name == "scanned" and not docling_engine.ocr_enabled():
        pytest.skip("docling OCR engine unavailable (scanned path covered by mocked test)")

    result = extract(pdf_for(name)).to_dict()
    assert_result_schema(result)

    assert result["status"] == expected["status"]
    if "page_count" in expected:
        assert result["page_count"] == expected["page_count"]
    if "error_contains" in expected:
        joined = " ".join(result["errors"]).lower()
        assert expected["error_contains"] in joined

    assert len(result["tables"]) == len(expected["tables"])
    for exp_t, act_t in zip(expected["tables"], result["tables"]):
        assert act_t["pages"] == exp_t["pages"]
        assert act_t["spans_pages"] == exp_t["spans_pages"]
        assert act_t["rotated"] == exp_t["rotated"]
        assert act_t["nested"] == exp_t["nested"]
        assert act_t["extraction_method"] == exp_t["extraction_method"]
        if expected.get("match") == "fuzzy":
            assert_fuzzy_table(exp_t, act_t)
        else:
            assert_exact_table(exp_t, act_t)


def test_multipage_merge_details():
    """spans_pages True and contributing pages listed for a table flowing
    across two pages; repeated header not duplicated in rows."""
    result = extract(pdf_for("multipage")).to_dict()
    assert len(result["tables"]) == 1
    t = result["tables"][0]
    assert t["pages"] == [1, 2]
    assert t["spans_pages"] is True
    assert t["headers"] == ["Month", "Sales", "Cost"]
    assert len(t["rows"]) == 44  # no repeated header row
    assert ["Month", "Sales", "Cost"] not in t["rows"]


def test_scanned_page_routes_to_docling_full(monkeypatch):
    """Pages without a text layer are blind to the prescan and must be sent
    to docling as an untargeted full scan -> extraction_method docling_full."""
    calls = []

    def fake_extract_pages(pdf_path, pages):
        calls.append(sorted(pages))
        pt = docling_engine.PageTable(
            page_number=1, grid=[["Item", "Q1"], ["Revenue", "1000"]],
            bbox=(10, 10, 200, 100), page_height=792.0)
        return [pt], {1: 0.88}, []

    monkeypatch.setattr(docling_engine, "ocr_enabled", lambda: True)
    monkeypatch.setattr(docling_engine, "extract_pages", fake_extract_pages)

    result = extract(pdf_for("scanned")).to_dict()
    assert calls == [[1]], "docling should get exactly the single blind page"
    assert result["status"] == "success"
    assert len(result["tables"]) == 1
    t = result["tables"][0]
    assert t["extraction_method"] == "docling_full"
    assert t["confidence"] == 0.88
    assert t["headers"] == ["Item", "Q1"]
    assert t["rows"] == [["Revenue", "1000"]]


def test_flagged_page_routes_to_docling_targeted(monkeypatch):
    """Pages where the prescan sees a table region are extracted by docling
    with extraction_method docling_targeted."""
    calls = []

    def fake_extract_pages(pdf_path, pages):
        calls.append(sorted(pages))
        pt = docling_engine.PageTable(
            page_number=1, grid=[["Item", "Q1"], ["Revenue", "1000"]],
            bbox=(10, 10, 200, 100), page_height=792.0)
        return [pt], {1: 0.95}, []

    monkeypatch.setattr(docling_engine, "extract_pages", fake_extract_pages)

    result = extract(pdf_for("simple")).to_dict()
    assert calls == [[1]], "docling should get exactly the flagged page"
    assert result["status"] == "success"
    assert result["tables"][0]["extraction_method"] == "docling_targeted"


def test_no_table_pages_never_reach_docling(monkeypatch):
    """A prose-only text page is neither flagged nor blind, so docling
    (the expensive stage) must not run at all."""
    monkeypatch.setattr(
        docling_engine, "extract_pages",
        lambda *a: (_ for _ in ()).throw(AssertionError("docling called")))
    result = extract(pdf_for("no_tables")).to_dict()
    assert result["status"] == "success"
    assert result["tables"] == []


def test_prescan_flag_without_docling_table_is_reported(monkeypatch):
    """If the prescan flags a region but docling extracts nothing there, the
    mismatch is auditable via errors and a partial/failed status."""
    monkeypatch.setattr(docling_engine, "extract_pages",
                        lambda pdf_path, pages: ([], {}, []))
    result = extract(pdf_for("simple")).to_dict()
    assert result["status"] == "failed"  # errors and no tables
    assert any("prescan flagged" in e for e in result["errors"])


def test_real_ocr_on_scanned_fixture():
    if not docling_engine.ocr_enabled():
        pytest.skip("docling OCR engine unavailable")
    result = extract(pdf_for("scanned")).to_dict()
    assert result["status"] == "success"
    assert result["tables"], "docling OCR should find the table"
    assert result["tables"][0]["extraction_method"] == "docling_full"


def test_engine_is_swappable():
    from backend import extraction
    from backend.extraction.models import ExtractionResult

    def stub_engine(pdf_path):
        return ExtractionResult(status="success", page_count=0, tables=[], errors=[])

    original = extraction._engine
    try:
        extraction.set_engine(stub_engine)
        assert extraction.extract("anything.pdf").status == "success"
    finally:
        extraction.set_engine(original)
