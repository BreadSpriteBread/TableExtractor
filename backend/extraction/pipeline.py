"""Default extraction pipeline: pdfplumber presence prescan, Docling extraction.

extract(pdf_path) -> ExtractionResult

Flow:
  1. Probe: file is a readable, non-encrypted PDF (PyMuPDF).
  2. Prescan (pdfplumber): flag pages holding a table-like region. Purely a
     presence detector — its cell splitting is never used as output.
  3. Docling extracts tables from the flagged pages ("docling_targeted").
     Pages the prescan is blind on — no text layer (scanned/image-only) or a
     prescan error — also go to Docling as an untargeted full scan of the
     page ("docling_full"). extraction_method records which path each table
     took, for auditing.
  4. Post-processing: multi-page merge, derotation, nested flag, confidence.

Status semantics:
  success  — no errors
  partial  — some tables extracted but some pages/errors failed
  failed   — unreadable file or nothing extractable and errors present
"""
import os
import time

from backend.config import get_logger
from backend.extraction import docling_engine, prescan
from backend.extraction.models import ExtractionResult, Table

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


def _derotate_grid(grid, rotation):
    """Undo the reading-order skew on pages carrying /Rotate.

    Empirically (Docling 2.55, V2 layout — same mapping pdfplumber showed):
    a 90-degree page yields G[i][j] = original[N-1-j][i]; invert that
    mapping to recover reading order.
    """
    if not grid:
        return grid
    width = max(len(r) for r in grid)
    g = [row + [""] * (width - len(row)) for row in grid]
    if rotation == 90:
        return [[g[c][width - 1 - r] for c in range(len(g))] for r in range(width)]
    if rotation == 270:
        return [[g[len(g) - 1 - c][r] for c in range(len(g))] for r in range(width)]
    if rotation == 180:
        return [row[::-1] for row in g[::-1]]
    return grid


def _merge_multipage(page_tables):
    """Merge tables that continue across consecutive pages.

    Heuristic: same column count, earlier table ends near its page bottom,
    later table starts near its page top, on consecutive pages. A repeated
    header row on the continuation page is dropped.
    Returns list of merged groups: each group is a list[PageTable].
    """
    groups = []
    by_page = sorted(page_tables, key=lambda t: (t.page_number, t.bbox[1]))
    for t in by_page:
        merged = False
        if groups:
            last = groups[-1][-1]
            if (t.page_number == last.page_number + 1
                    and t.n_cols == last.n_cols
                    and last.near_page_bottom()
                    and t.near_page_top()):
                if t.grid and last.grid and t.grid[0] == last.grid[0]:
                    t.grid = t.grid[1:]  # drop repeated header
                groups[-1].append(t)
                merged = True
        if not merged:
            groups.append([t])
    return groups


def _is_nested(page_table, nested_bboxes):
    """True if this Docling table sits on a prescan-detected nested-outer
    region (>= 50% of its area inside the outer bbox)."""
    x0, top, x1, bottom = page_table.bbox
    area = max(x1 - x0, 0) * max(bottom - top, 0)
    if area <= 0:
        return False
    for ox0, otop, ox1, obottom in nested_bboxes.get(page_table.page_number, []):
        overlap = (max(0, min(x1, ox1) - max(x0, ox0))
                   * max(0, min(bottom, obottom) - max(top, otop)))
        if overlap / area >= 0.5:
            return True
    return False


def _tables_from_groups(groups, targeted_pages, page_scores):
    tables = []
    for idx, group in enumerate(groups, start=1):
        pages = sorted({t.page_number for t in group})
        rows = [row for t in group for row in t.grid]
        if not rows:
            continue
        headers, body = rows[0], rows[1:]
        method = ("docling_targeted"
                  if all(p in targeted_pages for p in pages)
                  else "docling_full")
        scores = [page_scores[p] for p in pages if p in page_scores]
        conf = round(sum(scores) / len(scores), 3) if scores else 0.5
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


def extract(pdf_path) -> ExtractionResult:
    """Extract all tables from a PDF. Never raises for bad input files."""
    start = time.monotonic()
    page_count, probe_error = _probe(pdf_path)
    if probe_error:
        return ExtractionResult(status="failed", page_count=0,
                                tables=[], errors=[probe_error])

    try:
        report = prescan.prescan(pdf_path)
    except Exception as e:
        return ExtractionResult(status="failed", page_count=max(page_count, 0),
                                tables=[], errors=[f"could not open PDF: {e}"])

    errors = list(report.errors)
    targeted = set(report.flagged_pages)
    blind = set(report.no_text_pages) | set(report.error_pages)
    docling_pages = sorted(targeted | blind)

    tables = []
    if docling_pages:
        try:
            if blind and not docling_engine.ocr_enabled():
                errors.append(f"pages {sorted(blind)}: no text layer and OCR "
                              "unavailable (docling OCR engine failed to initialise)")
            page_tables, page_scores, dl_errors = docling_engine.extract_pages(
                pdf_path, docling_pages)
            errors.extend(dl_errors)
        except Exception as e:  # e.g. docling not installed / models missing
            log.error("docling engine unavailable path=%s err=%s", pdf_path, e)
            errors.append(f"docling engine unavailable: {e}")
            page_tables, page_scores = [], {}

        for pt in page_tables:
            rotation = report.rotations.get(pt.page_number)
            if rotation:
                pt.grid = _derotate_grid(pt.grid, rotation)
                pt.rotated = True
            pt.nested = _is_nested(pt, report.nested_bboxes)

        groups = _merge_multipage(page_tables)
        tables = _tables_from_groups(groups, targeted, page_scores)
        tables.sort(key=lambda t: t.pages[0])
        for i, t in enumerate(tables, start=1):
            t.table_id = f"t{i}"

        covered = {p for t in tables for p in t.pages}
        for p in sorted(targeted - covered):
            errors.append(f"page {p}: prescan flagged a table-like region "
                          "but docling extracted no table")

    if errors and tables:
        status = "partial"
    elif errors:
        status = "failed"
    else:
        status = "success"

    log.info("extracted path=%s status=%s tables=%d pages=%d ms=%d",
             pdf_path, status, len(tables), report.page_count,
             int((time.monotonic() - start) * 1000))
    return ExtractionResult(status=status, page_count=report.page_count,
                            tables=tables, errors=errors)
