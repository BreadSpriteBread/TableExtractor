"""Extraction engine tests against hand-verified fixture PDFs.

Vector fixtures are compared exactly; OCR fixtures fuzzily (word recall).
"""
import json

import pytest

from backend.extraction import extract, ocr
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
    if name == "scanned" and not ocr.ocr_available():
        pytest.skip("tesseract not installed (OCR path covered by mocked test)")

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


def test_ocr_fallback_invoked_for_scanned_pdf(monkeypatch):
    """Pages without a text layer must route to the OCR engine."""
    calls = []

    def fake_ocr_page(pdf_path, page_index):
        calls.append(page_index)
        return ([["Item", "Q1"], ["Revenue", "1000"]], 0.88)

    monkeypatch.setattr(ocr, "ocr_available", lambda: True)
    monkeypatch.setattr(ocr, "ocr_page", fake_ocr_page)

    result = extract(pdf_for("scanned")).to_dict()
    assert calls == [0], "OCR should be called exactly once for the single scanned page"
    assert result["status"] == "success"
    assert len(result["tables"]) == 1
    t = result["tables"][0]
    assert t["extraction_method"] == "ocr"
    assert t["confidence"] == 0.88
    assert t["headers"] == ["Item", "Q1"]
    assert t["rows"] == [["Revenue", "1000"]]


def test_vector_pdf_does_not_use_ocr(monkeypatch):
    monkeypatch.setattr(ocr, "ocr_page",
                        lambda *a: (_ for _ in ()).throw(AssertionError("OCR called")))
    result = extract(pdf_for("simple")).to_dict()
    assert result["status"] == "success"
    assert all(t["extraction_method"] == "vector" for t in result["tables"])


@pytest.mark.skipif(not ocr.ocr_available(), reason="tesseract not installed")
def test_real_ocr_on_scanned_fixture():
    result = extract(pdf_for("scanned")).to_dict()
    assert result["status"] == "success"
    assert result["tables"], "real OCR should find the table"
    assert result["tables"][0]["extraction_method"] == "ocr"


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
