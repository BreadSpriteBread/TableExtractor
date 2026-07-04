"""Extraction endpoints: async batch submit, job polling/cancel, cached
result retrieval, search, bulk export and bulk delete."""
import json

from flask import Blueprint, jsonify, request

from backend.config import get_logger
from backend.database import delete_extractions, get_db
from backend.jobs import get_manager

bp = Blueprint("extraction_api", __name__)
log = get_logger(__name__)


@bp.post("/api/extract")
def submit_extraction():
    """Submit a batch. Body: {"document_ids": [...], "force": false}.
    Returns 202 with a job_id immediately; work happens in the background."""
    body = request.get_json(silent=True) or {}
    doc_ids = body.get("document_ids") or []
    force = bool(body.get("force", False))
    if not isinstance(doc_ids, list) or not doc_ids:
        return jsonify({"error": "document_ids (non-empty list) required"}), 400

    conn = get_db()
    try:
        docs, missing = [], []
        for doc_id in dict.fromkeys(doc_ids):  # dedup, preserve order
            row = conn.execute(
                "SELECT document_id, filename, source, file_path FROM documents WHERE document_id = ?",
                (doc_id,)).fetchone()
            if row:
                docs.append(dict(row))
            else:
                missing.append(doc_id)
    finally:
        conn.close()

    if not docs:
        return jsonify({"error": "no known documents in request", "missing": missing}), 400

    job_id = get_manager().submit(docs, force=force)
    return jsonify({"job_id": job_id, "submitted": len(docs), "missing": missing}), 202


@bp.get("/api/jobs/<job_id>")
def job_status(job_id):
    snap = get_manager().get(job_id)
    if snap is None:
        return jsonify({"error": "job not found"}), 404
    return jsonify(snap)


@bp.post("/api/jobs/<job_id>/cancel")
def cancel_job(job_id):
    if not get_manager().cancel(job_id):
        return jsonify({"error": "job not found"}), 404
    return jsonify(get_manager().get(job_id))


@bp.get("/api/extractions")
def search_extractions():
    """Search cached extractions.

    Query params: q (FTS over headers/cells/filename), filename (substring),
    status, date_from, date_to (ISO, on extracted_at), limit, offset.
    """
    q = (request.args.get("q") or "").strip()
    filename = (request.args.get("filename") or "").strip().lower()
    status = (request.args.get("status") or "").strip()
    date_from = (request.args.get("date_from") or "").strip()
    date_to = (request.args.get("date_to") or "").strip()
    limit = min(int(request.args.get("limit", 200)), 1000)
    offset = int(request.args.get("offset", 0))

    sql = """
        SELECT d.document_id, d.filename, d.source, d.acquired_at,
               e.status, e.extracted_at, e.table_count, e.duration_ms, e.error_summary
        FROM extractions e
        JOIN documents d ON d.document_id = e.document_id
        WHERE 1=1
    """
    params = []
    if q:
        sql += """ AND e.document_id IN (
            SELECT document_id FROM table_search WHERE table_search MATCH ?)"""
        # quote for FTS5 so plain words/phrases are safe
        params.append(" ".join(f'"{t}"' for t in q.split()))
    if filename:
        sql += " AND LOWER(d.filename) LIKE ?"
        params.append(f"%{filename}%")
    if status:
        sql += " AND e.status = ?"
        params.append(status)
    if date_from:
        sql += " AND e.extracted_at >= ?"
        params.append(date_from)
    if date_to:
        sql += " AND e.extracted_at <= ?"
        params.append(date_to + ("T23:59:59Z" if len(date_to) == 10 else ""))
    sql += " ORDER BY e.extracted_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    conn = get_db()
    try:
        rows = conn.execute(sql, params).fetchall()
        return jsonify({"results": [dict(r) for r in rows]})
    finally:
        conn.close()


@bp.get("/api/extractions/<path:document_id>")
def get_extraction(document_id):
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT result_json FROM extractions WHERE document_id = ?",
            (document_id,)).fetchone()
        if not row:
            return jsonify({"error": "no cached extraction for document"}), 404
        return jsonify(json.loads(row["result_json"]))
    finally:
        conn.close()


@bp.post("/api/extractions/export")
def export_extractions():
    """Bulk export. Body: {"document_ids": [...]}. Returns {"documents": [...]}."""
    body = request.get_json(silent=True) or {}
    doc_ids = body.get("document_ids") or []
    if not isinstance(doc_ids, list) or not doc_ids:
        return jsonify({"error": "document_ids (non-empty list) required"}), 400

    conn = get_db()
    try:
        documents = []
        for doc_id in dict.fromkeys(doc_ids):
            row = conn.execute(
                "SELECT result_json FROM extractions WHERE document_id = ?",
                (doc_id,)).fetchone()
            if row:
                documents.append(json.loads(row["result_json"]))
        return jsonify({"documents": documents})
    finally:
        conn.close()


@bp.post("/api/extractions/delete")
def bulk_delete_extractions():
    """Bulk delete cached results. Body: {"document_ids": [...]}."""
    body = request.get_json(silent=True) or {}
    doc_ids = body.get("document_ids") or []
    if not isinstance(doc_ids, list) or not doc_ids:
        return jsonify({"error": "document_ids (non-empty list) required"}), 400

    conn = get_db()
    try:
        deleted = delete_extractions(conn, doc_ids)
        conn.commit()
        log.info("extractions deleted count=%d", deleted)
        return jsonify({"deleted": deleted})
    finally:
        conn.close()
