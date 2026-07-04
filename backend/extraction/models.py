"""Data model for extraction results, mirroring the export JSON schema."""
from dataclasses import dataclass, field, asdict


@dataclass
class Table:
    table_id: str
    pages: list          # 1-based page numbers contributing to this table
    spans_pages: bool
    rotated: bool
    nested: bool
    extraction_method: str  # "docling_targeted" | "docling_full"
    confidence: float
    headers: list
    rows: list

    def to_dict(self):
        return asdict(self)


@dataclass
class ExtractionResult:
    status: str                      # "success" | "partial" | "failed"
    page_count: int = 0
    tables: list = field(default_factory=list)   # list[Table]
    errors: list = field(default_factory=list)   # list[str]

    def to_dict(self):
        return {
            "status": self.status,
            "page_count": self.page_count,
            "tables": [t.to_dict() for t in self.tables],
            "errors": self.errors,
        }


def document_json(result_dict: dict, document_id: str, filename: str,
                  source: str, extracted_at: str) -> dict:
    """Wrap an ExtractionResult dict into the per-document export schema."""
    return {
        "document_id": document_id,
        "filename": filename,
        "source": source,
        "extracted_at": extracted_at,
        "status": result_dict["status"],
        "page_count": result_dict["page_count"],
        "tables": result_dict["tables"],
        "errors": result_dict["errors"],
    }
