"""Financials endpoints: derive canonical statements from a document's cached
extraction. Cheap and synchronous (CPU-only text processing); the LLM fallback
is opt-in per request."""
from flask import Blueprint, jsonify, request

from backend.config import get_logger
from backend.database import get_db
from backend.financials import llm as llm_mod
from backend.financials.service import derive_for_document

bp = Blueprint("financials_api", __name__)
log = get_logger(__name__)


def _truthy(v: str) -> bool:
    return str(v).lower() in ("1", "true", "yes", "on")


@bp.get("/api/financials/llm-status")
def llm_status():
    """Whether the LLM fallback is configured (drives the UI toggle)."""
    return jsonify({"available": llm_mod.available()})


@bp.get("/api/financials/<path:document_id>")
def get_financials(document_id):
    """Return derived financials, computing (and caching) on demand.
    Query params: force=1 to re-derive, use_llm=1 to fill gaps with the LLM."""
    force = _truthy(request.args.get("force", ""))
    use_llm = _truthy(request.args.get("use_llm", ""))
    result = derive_for_document(document_id, force=force, use_llm=use_llm)
    if "error" in result:
        return jsonify(result), 404
    return jsonify(result)


@bp.post("/api/financials/derive")
def derive_financials_batch():
    """Derive financials for many documents at once.
    Body: {"document_ids": [...], "force": false, "use_llm": false}."""
    body = request.get_json(silent=True) or {}
    doc_ids = body.get("document_ids") or []
    if not isinstance(doc_ids, list) or not doc_ids:
        return jsonify({"error": "document_ids (non-empty list) required"}), 400
    force = bool(body.get("force", False))
    use_llm = bool(body.get("use_llm", False))

    conn = get_db()
    try:
        results, missing = [], []
        for doc_id in dict.fromkeys(doc_ids):
            out = derive_for_document(doc_id, force=force, use_llm=use_llm, conn=conn)
            if "error" in out:
                missing.append(doc_id)
            else:
                results.append(out)
        return jsonify({"derived": len(results), "missing": missing,
                        "results": results})
    finally:
        conn.close()
