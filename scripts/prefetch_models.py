"""Download the extraction models at image-build time.

A stateless Cloud Run container has no persistent disk, so if the Docling
layout/TableFormer models and the easyocr weights were fetched lazily they
would be re-downloaded (~1 GB) on every cold start. Building the converter
here forces the exact same models the pipeline uses (DOCLING_LAYOUT_V2 +
TableFormer + easyocr) into the image's model cache.

Runs on CPU — no GPU is present during `docker build`.
"""
import sys

from backend.extraction import docling_engine


def main() -> int:
    # Same code path the worker uses; downloads + loads every model.
    _, ocr = docling_engine._get_converter()
    print(f"prefetched docling models (ocr_enabled={ocr})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
