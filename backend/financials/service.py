"""Orchestration + caching for financials derivation.

Deterministic parse first (free, CPU-only). Optionally fill the gaps with the
LLM. Results are cached in the ``financials`` table keyed by document, so the
work is done once per document unless ``force`` is set.
"""
import json

from backend.config import get_logger
from backend.database import get_db, utcnow
from backend.financials import llm as llm_mod
from backend.financials.parser import derive_financials

log = get_logger(__name__)


def _count_found(statements: dict) -> int:
    n = 0
    for fields in statements.values():
        for cell in fields.values():
            if any(v is not None for v in cell.get("values", [])):
                n += 1
    return n


def _apply_llm(det: dict, llm: dict) -> bool:
    """Fill None gaps in ``det`` (in place) from the LLM result. Deterministic
    values always win. Returns True if the LLM contributed anything."""
    periods = list(det["periods"])
    for p in llm.get("periods", []):
        if p not in periods:
            periods.append(p)

    used = False
    for fields in det["statements"].values():
        for key, cell in fields.items():
            vals = list(cell["values"]) + [None] * (len(periods) - len(cell["values"]))
            lvals = llm.get("values", {}).get(key)
            if lvals:
                for i, p in enumerate(periods):
                    if vals[i] is None and lvals.get(p) is not None:
                        vals[i] = lvals[p]
                        used = True
            cell["values"] = vals

    det["periods"] = periods
    if det.get("scale") is None and llm.get("scale"):
        det["scale"] = llm["scale"]
        used = True
    return used


def _load_extraction(conn, document_id: str):
    row = conn.execute(
        """SELECT d.filename, e.result_json
           FROM extractions e JOIN documents d ON d.document_id = e.document_id
           WHERE e.document_id = ?""",
        (document_id,)).fetchone()
    if not row:
        return None, None
    return row["filename"], json.loads(row["result_json"])


def get_cached(conn, document_id: str):
    row = conn.execute(
        "SELECT financials_json FROM financials WHERE document_id = ?",
        (document_id,)).fetchone()
    return json.loads(row["financials_json"]) if row else None


def _save(conn, document_id: str, payload: dict):
    conn.execute(
        """INSERT INTO financials
               (document_id, generated_at, method, scale, periods_json, financials_json)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(document_id) DO UPDATE SET
               generated_at=excluded.generated_at, method=excluded.method,
               scale=excluded.scale, periods_json=excluded.periods_json,
               financials_json=excluded.financials_json""",
        (document_id, payload["generated_at"], payload["method"], payload["scale"],
         json.dumps(payload["periods"]), json.dumps(payload)),
    )


def derive_for_document(document_id: str, force: bool = False,
                        use_llm: bool = False, conn=None) -> dict:
    """Derive (or fetch cached) financials for one document.

    Returns the financials payload, or ``{"error": ...}`` if the document has no
    cached extraction. Cheap and synchronous — no GPU, no job manager.
    """
    own = conn is None
    if own:
        conn = get_db()
    try:
        if not force:
            cached = get_cached(conn, document_id)
            if cached:
                return cached

        filename, result = _load_extraction(conn, document_id)
        if result is None:
            return {"error": "no cached extraction for document"}

        det = derive_financials(result)
        method = "deterministic"

        if use_llm and llm_mod.available():
            llm_out = llm_mod.llm_extract(result.get("tables", []))
            if llm_out and _apply_llm(det, llm_out):
                method = "hybrid"

        payload = {
            "document_id": document_id,
            "filename": filename,
            "generated_at": utcnow(),
            "method": method,
            "scale": det["scale"],
            "periods": det["periods"],
            "statements": det["statements"],
            "found_fields": _count_found(det["statements"]),
            "total_fields": det["total_fields"],
            "warnings": det["warnings"],
        }
        _save(conn, document_id, payload)
        conn.commit()
        log.info("financials derived document_id=%s method=%s found=%d/%d",
                 document_id, method, payload["found_fields"], payload["total_fields"])
        return payload
    finally:
        if own:
            conn.close()
