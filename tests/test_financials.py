"""Financials derivation tests — deterministic path only (no network).

The example mirrors a Saudi Exchange financial-summary table as the extractor
would emit it: one header row of periods, one row per line item.
"""
import json

import pytest

from backend.financials.parser import derive_financials, missing_fields
from backend.financials.schema import (detect_scale, extract_periods,
                                       match_field, parse_number)

PERIODS = ["2025-12-31", "2024-12-31", "2023-12-31"]


def _table(headers, rows):
    return {"table_id": "t1", "pages": [1], "spans_pages": False, "rotated": False,
            "nested": False, "extraction_method": "docling_targeted",
            "confidence": 0.9, "headers": headers, "rows": rows}


@pytest.fixture
def summary_result():
    balance = _table(
        ["Balance Sheet", *PERIODS],
        [
            ["Total Assets", "2,551,964,000", "2,423,630,000", "2,477,940,000"],
            ["Total Liabilities", "830,220,000", "772,275,000", "740,848,000"],
            ["Total Shareholders Equity (After Deducting the Minority Equity)",
             "1,491,996,000", "1,458,229,000", "1,534,607,000"],
            ["Total Liabilities and Shareholders Equity",
             "2,551,964,000", "2,423,630,000", "2,477,940,000"],
        ],
    )
    income = _table(
        ["Statement of Income", *PERIODS],
        [
            ["Total Revenue (Sales/Operating)", "1,671,204,000", "1,801,674,000", "1,856,373,000"],
            ["Net Profit (Loss) before Zakat and Tax", "702,860,000", "782,010,000", "888,067,000"],
            ["Zakat and Income Tax", "-352,650,000", "-383,588,000", "-433,303,000"],
            ["Net Profit (Loss) Attributable to Shareholders of the Issuer",
             "348,042,000", "393,891,000", "452,753,000"],
            ["Total Comprehensive Income Attributable to Shareholders of the Issuer",
             "353,850,000", "391,720,000", "451,111,000"],
            ["Profit (Loss) per Share", "1.44", "1.63", "1.87"],
        ],
    )
    cash = _table(
        ["Cash Flows", *PERIODS],
        [
            ["Net Cash From Operating Activities", "510,798,000", "508,888,000", "537,814,000"],
            ["Net Cash From Investing Activities", "-203,902,000", "-2,861,000", "-54,019,000"],
            ["Net Cash From Financing Activities", "-280,439,000", "-488,358,000", "-510,869,000"],
            ["Cash and Cash Equivalents, Beginning of the Period",
             "216,642,000", "198,973,000", "226,047,000"],
            ["Cash and Cash Equivalents, End of the Period",
             "243,099,000", "216,642,000", "198,973,000"],
            ["All Figures in", "Thousands", "Thousands", "Thousands"],
        ],
    )
    return {"status": "success", "page_count": 3,
            "tables": [balance, income, cash], "errors": []}


# --- unit-level primitives -------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("2,551,964,000", 2551964000),
    ("-352,650,000", -352650000),
    ("(433,303)", -433303),
    ("1.44", 1.44),
    ("", None), ("-", None), ("n/a", None), ("foo", None),
])
def test_parse_number(raw, expected):
    assert parse_number(raw) == expected


def test_extract_periods_prefers_full_dates():
    assert extract_periods(["Balance Sheet", *PERIODS]) == PERIODS


def test_detect_scale():
    assert detect_scale(["All Figures in", "Thousands", "Thousands"]) == "Thousands"
    assert detect_scale(["Total Assets", "1,000"]) is None


def test_match_field_disambiguates_totals():
    assert match_field("Total Assets") == ("balance_sheet", "total_assets")
    assert match_field("Total Liabilities") == ("balance_sheet", "total_liabilities")
    assert match_field("Total Liabilities and Shareholders Equity") is None
    assert match_field("Total Shareholders Equity (After Deducting the Minority Equity)") \
        == ("balance_sheet", "total_shareholders_equity")


# --- full derivation -------------------------------------------------------

def test_derive_periods_and_scale(summary_result):
    fin = derive_financials(summary_result)
    assert fin["periods"] == PERIODS
    assert fin["scale"] == "Thousands"
    assert fin["warnings"] == []


def test_derive_all_fields_found(summary_result):
    fin = derive_financials(summary_result)
    assert fin["found_fields"] == fin["total_fields"] == 14
    assert missing_fields(fin) == []


def test_derive_values_aligned_to_periods(summary_result):
    fin = derive_financials(summary_result)
    bs = fin["statements"]["balance_sheet"]
    assert bs["total_assets"]["values"] == [2551964000, 2423630000, 2477940000]
    assert bs["total_liabilities"]["values"] == [830220000, 772275000, 740848000]

    inc = fin["statements"]["income_statement"]
    assert inc["income_tax"]["values"] == [-352650000, -383588000, -433303000]
    assert inc["profit_per_share"]["values"] == [1.44, 1.63, 1.87]

    cf = fin["statements"]["cash_flow"]
    assert cf["net_cash_investing"]["values"] == [-203902000, -2861000, -54019000]
    assert cf["cash_end_of_period"]["values"] == [243099000, 216642000, 198973000]


def test_derive_empty_when_no_financial_tables():
    result = {"status": "success", "page_count": 1, "errors": "".split(),
              "tables": [_table(["Name", "Title"], [["Jane", "CFO"]])]}
    fin = derive_financials(result)
    assert fin["found_fields"] == 0
    assert "No recognisable financial line items were found." in fin["warnings"]


# --- API + caching ---------------------------------------------------------

def _seed_extraction(db_path, document_id, filename, result):
    import backend.database as database
    conn = database.get_db(str(db_path))
    conn.execute("INSERT INTO documents (document_id, filename, source, file_path) "
                 "VALUES (?, ?, 'upload', ?)", (document_id, filename, "/x.pdf"))
    conn.execute(
        """INSERT INTO extractions (document_id, status, extracted_at, table_count,
               duration_ms, result_json) VALUES (?, 'success', ?, ?, 10, ?)""",
        (document_id, "2026-01-01T00:00:00Z", len(result["tables"]), json.dumps(result)))
    conn.commit()
    conn.close()


def test_financials_endpoint_and_cache(client, db_path, summary_result):
    doc_id = "sha256:deadbeef"
    _seed_extraction(db_path, doc_id, "acme.pdf", summary_result)

    resp = client.get(f"/api/financials/{doc_id}")
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert body["method"] == "deterministic"
    assert body["scale"] == "Thousands"
    assert body["found_fields"] == 14

    # second call is served from cache (same figures)
    again = client.get(f"/api/financials/{doc_id}").get_json()
    assert again["statements"] == body["statements"]


def test_financials_404_without_extraction(client):
    resp = client.get("/api/financials/sha256:unknown")
    assert resp.status_code == 404


def test_llm_status_endpoint(client):
    resp = client.get("/api/financials/llm-status")
    assert resp.status_code == 200
    assert "available" in resp.get_json()
