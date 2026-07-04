"""Default extraction pipeline: vector first, OCR fallback per page.

extract(pdf_path) -> ExtractionResult

Status semantics:
  success  — no errors
  partial  — some tables extracted but some pages/errors failed
  failed   — unreadable file or nothing extractable and errors present
"""
import os
import time

from backend.config import get_logger
from backend.extraction import ocr
from backend.extraction.models import ExtractionResult, Table
from backend.extraction import vector

log = get_logger(__name__)


def _probe(pdf_path):
    """Validate the file is a readable, non-encrypted PDF.
    Returns (page_count, error_or_None)."""
    if not os.path.isfile(pdf_path):
        return 0, "file not found"
    if os.path.getsize(pdf_path) == 0:
        return 0, "zero-byte file"

    try:
        import fitz
    except ImportError:
        return -1, None  # can't probe; let pdfplumber try

    try:
        with fitz.open(pdf_path) as doc:
            if doc.needs_pass:
                return 0, "password-protected PDF"
            return doc.page_count, None
    except Exception as e:
        return 0, f"corrupted or unreadable PDF: {e}"


def _tables_from_groups(groups, method="vector"):
    tables = []
    for idx, group in enumerate(groups, start=1):
        pages = sorted({t.page_number for t in group})
        rows = [row for t in group for row in t.grid]
        if not rows:
            continue
        headers, body = rows[0], rows[1:]
        conf = round(sum(t.confidence() for t in group) / len(group), 3)
        tables.append(Table(
            table_id=f"t{idx}",
            pages=pages,
            spans_pages=len(pages) > 1,
            rotated=any(t.rotated for t in group),
            nested=any(t.nested for t in group),
            extraction_method=method,
            confidence=conf,
            headers=headers,
            rows=body,
        ))
    return tables


def _ocr_pages(pdf_path, page_numbers, errors):
    """OCR the given 1-based pages. Returns list[Table]."""
    tables = []
    if not page_numbers:
        return tables
    if not ocr.ocr_available():
        errors.append(
            f"pages {page_numbers}: no text layer and OCR unavailable "
            "(tesseract not installed)")
        return tables

    for page_no in page_numbers:
        try:
            grid, conf = ocr.ocr_page(pdf_path, page_no - 1)
            grid = [row for row in grid if any(c for c in row)]
            if len(grid) >= 2 and max(len(r) for r in grid) >= 2:
                tables.append(Table(
                    table_id="",  # renumbered by caller
                    pages=[page_no],
                    spans_pages=False,
                    rotated=False,
                    nested=False,
                    extraction_method="ocr",
                    confidence=conf,
                    headers=grid[0],
                    rows=grid[1:],
                ))
            else:
                errors.append(f"page {page_no}: OCR found no table structure")
        except Exception as e:
            errors.append(f"page {page_no}: OCR failed: {e}")
            log.warning("ocr page error path=%s page=%d err=%s", pdf_path, page_no, e)
    return tables


def extract(pdf_path) -> ExtractionResult:
    """Extract all tables from a PDF. Never raises for bad input files."""
    start = time.monotonic()
    page_count, probe_error = _probe(pdf_path)
    if probe_error:
        return ExtractionResult(status="failed", page_count=0,
                                tables=[], errors=[probe_error])

    errors = []
    try:
        page_tables, page_count, pages_without_text, vec_errors = \
            vector.extract_page_tables(pdf_path)
        errors.extend(vec_errors)
    except Exception as e:
        return ExtractionResult(status="failed", page_count=max(page_count, 0),
                                tables=[], errors=[f"could not open PDF: {e}"])

    groups = vector.merge_multipage(page_tables)
    tables = _tables_from_groups(groups, method="vector")
    ocr_tables = _ocr_pages(pdf_path, pages_without_text, errors)

    tables.extend(ocr_tables)
    tables.sort(key=lambda t: t.pages[0])
    for i, t in enumerate(tables, start=1):
        t.table_id = f"t{i}"

    if errors and tables:
        status = "partial"
    elif errors:
        status = "failed"
    else:
        status = "success"

    log.info("extracted path=%s status=%s tables=%d pages=%d ms=%d",
             pdf_path, status, len(tables), page_count,
             int((time.monotonic() - start) * 1000))
    return ExtractionResult(status=status, page_count=page_count,
                            tables=tables, errors=errors)
