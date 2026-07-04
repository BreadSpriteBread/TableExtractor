"""pdfplumber-based table *presence* prescan.

pdfplumber's cell splitting is not trusted for output anymore; it is purely
a presence detector. Per page it answers:
  - does a table-like region exist (ruling lines, or text-aligned columns)?
  - does the page have a usable text layer at all (scanned pages don't)?
  - metadata Docling doesn't surface: the /Rotate angle and the bboxes of
    outer tables that contain a nested inner table.

Actual cell extraction is done by Docling on the pages flagged here
(see docling_engine.py; orchestration in pipeline.py).
"""
from dataclasses import dataclass, field

from backend.config import get_logger

log = get_logger(__name__)

# Pages with less stripped text than this have no usable text layer: the
# prescan is blind there and the page goes to Docling unconditionally.
MIN_TEXT_CHARS = 10


@dataclass
class PrescanReport:
    page_count: int = 0
    flagged_pages: list = field(default_factory=list)   # table-like region seen
    no_text_pages: list = field(default_factory=list)   # image-only/scanned
    error_pages: list = field(default_factory=list)     # prescan crashed here
    rotations: dict = field(default_factory=dict)       # page -> /Rotate angle
    nested_bboxes: dict = field(default_factory=dict)   # page -> [(x0, top, x1, bottom)]
    errors: list = field(default_factory=list)


def _clean_cell(val):
    if val is None:
        return ""
    return " ".join(str(val).split())


def _numeric_fraction(grid):
    cells = [c for row in grid for c in row if c != ""]
    if not cells:
        return 0.0
    numeric = sum(
        1 for c in cells
        if c.replace(",", "").replace(".", "").replace("-", "").replace("%", "").replace("(", "").replace(")", "").isdigit()
    )
    return numeric / len(cells)


def _bbox_contains(outer, inner, pad=2.0):
    ox0, oy0, ox1, oy1 = outer
    ix0, iy0, ix1, iy1 = inner
    return (ix0 >= ox0 - pad and iy0 >= oy0 - pad
            and ix1 <= ox1 + pad and iy1 <= oy1 + pad
            and (ix0 > ox0 + pad or iy0 > oy0 + pad
                 or ix1 < ox1 - pad or iy1 < oy1 - pad))


def _looks_nested(grid):
    """Detect an inner table that pdfplumber merged into the outer grid:
    header cells left empty above filled body columns, plus continuation
    rows whose first cell is empty."""
    if len(grid) < 2:
        return False
    header, body = grid[0], grid[1:]
    header_gap = any(
        h == "" and any(i < len(row) and row[i] != "" for row in body)
        for i, h in enumerate(header)
    )
    cont_row = any(
        row and row[0] == "" and sum(1 for c in row if c != "") >= 2
        for row in body
    )
    return header_gap and cont_row


def _scan_page(page):
    """Look for table-like regions on one pdfplumber page.

    Returns (has_table, nested_outer_bboxes). Grids are extracted only to
    filter noise (prose aligning into pseudo-columns) and to spot nested
    signatures — they are never used as output.
    """
    found = page.find_tables()
    borderless = False
    if not found:
        found = page.find_tables({
            "vertical_strategy": "text",
            "horizontal_strategy": "text",
            "min_words_vertical": 2,
            "min_words_horizontal": 2,
        })
        borderless = True

    regions = []  # (bbox, grid)
    for t in found:
        grid = [[_clean_cell(c) for c in row] for row in (t.extract() or [])]
        grid = [row for row in grid if any(c != "" for c in row)]
        if not grid or len(grid[0]) < 2:
            continue
        if borderless:
            # Text-strategy detection is noisy: require most rows to be
            # multi-column and some numeric content so prose blocks are
            # rejected instead of being sent to Docling.
            multi = sum(1 for row in grid if sum(1 for c in row if c != "") >= 2)
            if len(grid) < 2 or multi / len(grid) < 0.5:
                continue
            if _numeric_fraction(grid) < 0.2:
                continue
        regions.append((t.bbox, grid))

    # Nested detection, two forms: separate detections where one bbox
    # contains another (the container is the outer table), or an inner grid
    # already flattened into the outer one, recognised by its signature.
    nested_outers = []
    for bbox, grid in regions:
        if _looks_nested(grid) and bbox not in nested_outers:
            nested_outers.append(bbox)
        for other_bbox, _ in regions:
            if (other_bbox is not bbox and _bbox_contains(bbox, other_bbox)
                    and bbox not in nested_outers):
                nested_outers.append(bbox)
    return bool(regions), nested_outers


def prescan(pdf_path) -> PrescanReport:
    """Scan every page for table presence. Raises only if the file itself
    cannot be opened; per-page failures are recorded in the report."""
    import pdfplumber

    report = PrescanReport()
    with pdfplumber.open(pdf_path) as pdf:
        report.page_count = len(pdf.pages)
        for i, page in enumerate(pdf.pages, start=1):
            try:
                rotation = (getattr(page, "rotation", 0) or 0) % 360
                if rotation:
                    report.rotations[i] = rotation
                text = page.extract_text() or ""
                if len(text.strip()) < MIN_TEXT_CHARS:
                    report.no_text_pages.append(i)
                    continue
                has_table, nested_outers = _scan_page(page)
                if has_table:
                    report.flagged_pages.append(i)
                if nested_outers:
                    report.nested_bboxes[i] = nested_outers
            except Exception as e:
                report.error_pages.append(i)
                report.errors.append(f"page {i}: prescan error: {e}")
                log.warning("prescan page error path=%s page=%d err=%s",
                            pdf_path, i, e)
    return report
