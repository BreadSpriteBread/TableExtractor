"""OCR fallback for image-only pages: render with PyMuPDF, read with
tesseract, and cluster words into a row/column grid.

If the tesseract binary is unavailable, `ocr_available()` is False and the
pipeline records a per-page error instead of crashing.
"""
import shutil
import statistics

from backend.config import get_logger

log = get_logger(__name__)

RENDER_DPI = 200


def ocr_available() -> bool:
    try:
        import pytesseract  # noqa: F401
    except ImportError:
        return False
    return shutil.which("tesseract") is not None


def _render_page(pdf_path, page_index):
    import fitz
    with fitz.open(pdf_path) as doc:
        page = doc[page_index]
        pix = page.get_pixmap(dpi=RENDER_DPI)  # applies page rotation
        from PIL import Image
        return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def _cluster_positions(positions, gap):
    """Cluster sorted 1-D positions; new cluster when gap exceeded.
    Returns cluster centers."""
    if not positions:
        return []
    positions = sorted(positions)
    clusters = [[positions[0]]]
    for p in positions[1:]:
        if p - clusters[-1][-1] > gap:
            clusters.append([p])
        else:
            clusters[-1].append(p)
    return [statistics.mean(c) for c in clusters]


def words_to_grid(words):
    """Build a grid from OCR words: [{'text','left','top','width','height','conf'}].

    Rows: cluster word tops. Columns: cluster word left edges across the page.
    Returns (grid, mean_confidence).
    """
    words = [w for w in words if w["text"].strip()]
    if not words:
        return [], 0.0

    heights = [w["height"] for w in words]
    row_gap = max(statistics.median(heights) * 0.8, 4)
    row_centers = _cluster_positions([w["top"] for w in words], row_gap)

    widths = [w["width"] / max(len(w["text"]), 1) for w in words]
    char_w = statistics.median(widths)
    col_gap = char_w * 3
    col_centers = _cluster_positions([w["left"] for w in words], col_gap)

    def nearest(centers, v):
        return min(range(len(centers)), key=lambda i: abs(centers[i] - v))

    grid = [["" for _ in col_centers] for _ in row_centers]
    for w in words:
        r = nearest(row_centers, w["top"])
        c = nearest(col_centers, w["left"])
        grid[r][c] = (grid[r][c] + " " + w["text"].strip()).strip()

    grid = [row for row in grid if any(cell for cell in row)]
    # Drop columns that are empty everywhere
    if grid:
        keep = [i for i in range(len(grid[0])) if any(row[i] for row in grid)]
        grid = [[row[i] for i in keep] for row in grid]

    confs = [w["conf"] for w in words if w["conf"] >= 0]
    mean_conf = round((statistics.mean(confs) / 100.0), 3) if confs else 0.0
    return grid, mean_conf


def ocr_page(pdf_path, page_index):
    """OCR one page (0-based index). Returns (grid, confidence)."""
    import pytesseract

    image = _render_page(pdf_path, page_index)
    data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
    words = []
    for i in range(len(data["text"])):
        words.append({
            "text": data["text"][i],
            "left": data["left"][i],
            "top": data["top"][i],
            "width": data["width"][i],
            "height": data["height"][i],
            "conf": float(data["conf"][i]),
        })
    return words_to_grid(words)
