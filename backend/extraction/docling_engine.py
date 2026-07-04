"""Docling table extraction over selected pages.

The pdfplumber prescan (prescan.py) decides *which* pages Docling sees; this
module runs Docling's layout + TableFormer models on those pages only
(contiguous runs are converted together so multi-page tables stay adjacent)
and returns per-page tables ready for merging in the pipeline.

The layout model is pinned to DOCLING_LAYOUT_V2: the newer heron default
misses small and borderless tables that the prescan correctly flags.

Scanned pages need an OCR engine (easyocr by default). If none can be
initialised the converter is rebuilt without OCR and `ocr_enabled()` returns
False so the pipeline can record a per-page error instead of crashing.
"""
import math
import threading

from backend.config import get_logger

log = get_logger(__name__)

# Fraction of page height treated as "edge" when deciding whether a table
# ends at the bottom of one page and continues at the top of the next.
PAGE_EDGE_FRACTION = 0.18

_lock = threading.Lock()
_converter = None
_ocr_enabled = None


def _build_converter(with_ocr):
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.layout_model_specs import DOCLING_LAYOUT_V2
    from docling.datamodel.pipeline_options import (LayoutOptions,
                                                    PdfPipelineOptions)
    from docling.document_converter import DocumentConverter, PdfFormatOption

    opts = PdfPipelineOptions()
    opts.do_table_structure = True
    opts.table_structure_options.do_cell_matching = True
    opts.layout_options = LayoutOptions(model_spec=DOCLING_LAYOUT_V2)
    opts.do_ocr = with_ocr
    converter = DocumentConverter(format_options={
        InputFormat.PDF: PdfFormatOption(pipeline_options=opts)})
    # Force model load now so an OCR-engine failure surfaces here, not on
    # the first convert().
    converter.initialize_pipeline(InputFormat.PDF)
    return converter


def _get_converter():
    """Build the shared converter once per process."""
    global _converter, _ocr_enabled
    with _lock:
        if _converter is None:
            try:
                _converter = _build_converter(with_ocr=True)
                _ocr_enabled = True
            except Exception as e:
                log.warning("docling OCR engine unavailable, continuing "
                            "without OCR err=%s", e)
                _converter = _build_converter(with_ocr=False)
                _ocr_enabled = False
        return _converter, _ocr_enabled


def ocr_enabled() -> bool:
    """True if the converter can read scanned (image-only) pages."""
    return _get_converter()[1]


class PageTable:
    """A table Docling found on a single page, before multi-page merging."""

    def __init__(self, page_number, grid, bbox, page_height):
        self.page_number = page_number      # 1-based
        self.grid = grid                    # list[list[str]]
        self.bbox = bbox                    # (x0, top, x1, bottom), top-left origin
        self.page_height = page_height
        self.rotated = False                # set by the pipeline from the prescan
        self.nested = False                 # set by the pipeline from the prescan

    @property
    def n_cols(self):
        return max((len(r) for r in self.grid), default=0)

    def near_page_bottom(self):
        return self.bbox[3] >= self.page_height * (1 - PAGE_EDGE_FRACTION)

    def near_page_top(self):
        return self.bbox[1] <= self.page_height * PAGE_EDGE_FRACTION


def _contiguous_runs(pages):
    """[1, 2, 3, 7] -> [(1, 3), (7, 7)]"""
    runs = []
    for p in pages:
        if runs and p == runs[-1][1] + 1:
            runs[-1][1] = p
        else:
            runs.append([p, p])
    return [tuple(r) for r in runs]


def _page_score(page_conf):
    """Collapse Docling's per-page confidence into one 0-1 score: the mean
    of whichever of layout/OCR scores were actually computed."""
    vals = [getattr(page_conf, k, None) for k in ("layout_score", "ocr_score")]
    vals = [v for v in vals if isinstance(v, (int, float)) and math.isfinite(v)]
    return round(sum(vals) / len(vals), 3) if vals else None


def _collect(result, tables, page_scores):
    from docling_core.types.doc import CoordOrigin

    doc = result.document
    conf = getattr(result, "confidence", None)
    if conf is not None:
        for page_idx, pc in getattr(conf, "pages", {}).items():
            score = _page_score(pc)
            if score is not None:
                page_scores[page_idx + 1] = score  # keys are 0-based

    for item in doc.tables:
        if not item.prov:
            continue
        prov = item.prov[0]
        page = doc.pages.get(prov.page_no)
        height = float(page.size.height) if page else 0.0
        bb = prov.bbox
        if bb.coord_origin == CoordOrigin.BOTTOMLEFT:
            bb = bb.to_top_left_origin(height)
        grid = [[" ".join(str(cell.text or "").split()) for cell in row]
                for row in item.data.grid]
        grid = [row for row in grid if any(c != "" for c in row)]
        if not grid:
            continue
        tables.append(PageTable(
            page_number=prov.page_no,
            grid=grid,
            bbox=(bb.l, bb.t, bb.r, bb.b),
            page_height=height,
        ))


def extract_pages(pdf_path, pages):
    """Run Docling on the given 1-based pages.

    Returns (page_tables, page_scores, errors) where page_scores maps
    page number -> Docling's 0-1 confidence for that page.
    """
    converter, _ = _get_converter()
    tables, page_scores, errors = [], {}, []
    for start, end in _contiguous_runs(sorted(set(pages))):
        try:
            result = converter.convert(pdf_path, page_range=(start, end),
                                       raises_on_error=True)
            _collect(result, tables, page_scores)
        except Exception as e:
            errors.append(f"pages {start}-{end}: docling extraction failed: {e}")
            log.warning("docling run error path=%s pages=%d-%d err=%s",
                        pdf_path, start, end, e)
    return tables, page_scores, errors
