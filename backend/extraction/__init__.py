"""Swappable PDF table extraction engine.

Public interface:

    from backend.extraction import extract
    result = extract(pdf_path)   # -> ExtractionResult

Swap the engine by registering a different callable with `set_engine`.
"""
from backend.extraction.models import ExtractionResult, Table
from backend.extraction.pipeline import extract as _default_engine

_engine = _default_engine


def set_engine(fn):
    """Replace the extraction engine (must be `fn(pdf_path) -> ExtractionResult`)."""
    global _engine
    _engine = fn


def extract(pdf_path) -> ExtractionResult:
    return _engine(pdf_path)


__all__ = ["extract", "set_engine", "ExtractionResult", "Table"]
