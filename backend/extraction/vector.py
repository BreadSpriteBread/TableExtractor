"""Vector (text-layer) table extraction using pdfplumber.

Per page:
  1. Try line-based table detection (bordered tables).
  2. If nothing found, fall back to text-alignment detection (borderless).
  3. Tables whose bbox lies inside another table's bbox are nested: they are
     dropped (their content is already flattened into the outer cell text)
     and the outer table is flagged nested=True.
"""
from backend.config import get_logger

log = get_logger(__name__)

# Fraction of page height treated as "edge" when deciding whether a table
# ends at the bottom of one page and continues at the top of the next.
PAGE_EDGE_FRACTION = 0.18


def _bbox_contains(outer, inner, pad=2.0):
    ox0, oy0, ox1, oy1 = outer
    ix0, iy0, ix1, iy1 = inner
    return (ix0 >= ox0 - pad and iy0 >= oy0 - pad
            and ix1 <= ox1 + pad and iy1 <= oy1 + pad
            and (ix0 > ox0 + pad or iy0 > oy0 + pad
                 or ix1 < ox1 - pad or iy1 < oy1 - pad))


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


def _derotate_grid(grid, rotation):
    """Undo the coordinate skew pdfplumber produces on pages with /Rotate.

    Empirically (pdfplumber 0.11): a 90-degree page yields G[i][j] =
    original[N-1-j][i]; invert that mapping to recover reading order.
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


def _table_confidence(rows, base):
    cells = [c for row in rows for c in row]
    if not cells:
        return 0.0
    filled = sum(1 for c in cells if c != "")
    return round(base * (0.5 + 0.5 * filled / len(cells)), 3)


class PageTable:
    """A table found on a single page, before multi-page merging."""

    def __init__(self, page_number, bbox, grid, page_height, rotated, borderless):
        self.page_number = page_number      # 1-based
        self.bbox = bbox                    # (x0, top, x1, bottom)
        self.grid = grid                    # list[list[str]]
        self.page_height = page_height
        self.rotated = rotated
        self.nested = False
        self.borderless = borderless

    @property
    def n_cols(self):
        return max((len(r) for r in self.grid), default=0)

    def near_page_bottom(self):
        return self.bbox[3] >= self.page_height * (1 - PAGE_EDGE_FRACTION)

    def near_page_top(self):
        return self.bbox[1] <= self.page_height * PAGE_EDGE_FRACTION

    def confidence(self):
        base = 0.75 if self.borderless else 0.9
        return _table_confidence(self.grid, base)


def _find_page_tables(page, page_number):
    """Return list[PageTable] for one pdfplumber page."""
    rotated = (getattr(page, "rotation", 0) or 0) % 360 != 0
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

    tables = []
    for t in found:
        grid = [[_clean_cell(c) for c in row] for row in (t.extract() or [])]
        grid = [row for row in grid if any(c != "" for c in row)]
        if not grid or len(grid[0]) < 2:
            continue
        if borderless:
            # Text-strategy detection is noisy: require most rows to be
            # multi-column and some numeric content so prose blocks
            # (justified text aligns into pseudo-columns) are rejected.
            multi = sum(1 for row in grid if sum(1 for c in row if c != "") >= 2)
            if len(grid) < 2 or multi / len(grid) < 0.5:
                continue
            if _numeric_fraction(grid) < 0.2:
                continue
        if rotated:
            grid = _derotate_grid(grid, (page.rotation or 0) % 360)
        tables.append(PageTable(
            page_number=page_number,
            bbox=t.bbox,
            grid=grid,
            page_height=float(page.height),
            rotated=rotated,
            borderless=borderless,
        ))

    # Nested detection, two forms:
    #  - separate detections where one bbox contains another: drop the inner
    #    table (its text is already inside the outer cell) and flag the outer;
    #  - inner grids merged into the outer by shared line intersections:
    #    recognised by their flattened signature and flagged in place.
    kept = []
    for t in tables:
        if _looks_nested(t.grid):
            t.nested = True
        inner = False
        for other in tables:
            if other is not t and _bbox_contains(other.bbox, t.bbox):
                other.nested = True
                inner = True
                break
        if not inner:
            kept.append(t)
    return kept


def extract_page_tables(pdf_path):
    """Extract per-page tables from every page that has a text layer.

    Returns (page_tables, page_count, pages_without_text, errors).
    """
    import pdfplumber

    page_tables = []
    pages_without_text = []
    errors = []

    with pdfplumber.open(pdf_path) as pdf:
        page_count = len(pdf.pages)
        for i, page in enumerate(pdf.pages, start=1):
            try:
                text = page.extract_text() or ""
                if len(text.strip()) < 10:
                    pages_without_text.append(i)
                    continue
                page_tables.extend(_find_page_tables(page, i))
            except Exception as e:
                errors.append(f"page {i}: vector extraction error: {e}")
                log.warning("vector page error path=%s page=%d err=%s", pdf_path, i, e)
    return page_tables, page_count, pages_without_text, errors


def merge_multipage(page_tables):
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
