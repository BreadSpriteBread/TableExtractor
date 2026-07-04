"""Document identity endpoints: register corpus reports as documents (by
content hash) and accept user uploads."""
import datetime

from flask import Blueprint, jsonify, request
from werkzeug.utils import secure_filename

from backend.config import BASE_DIR, UPLOAD_DIR, get_logger
from backend.database import get_db, sha256_bytes, sha256_file

bp = Blueprint("documents", __name__)
log = get_logger(__name__)


def _utcnow():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _document_row(conn, document_id):
    row = conn.execute(
        """
        SELECT d.*, e.status AS extraction_status, e.extracted_at, e.table_count
        FROM documents d
        LEFT JOIN extractions e ON e.document_id = d.document_id
        WHERE d.document_id = ?
        """, (document_id,)).fetchone()
    return dict(row) if row else None


def upsert_document(conn, document_id, filename, source, file_path):
    conn.execute(
        """
        INSERT INTO documents (document_id, filename, source, file_path, acquired_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(document_id) DO UPDATE SET
            filename=excluded.filename, file_path=excluded.file_path
        """,
        (document_id, filename, source, str(file_path), _utcnow()),
    )


@bp.post("/api/documents/register")
def register_documents():
    """Turn corpus report ids into content-addressed documents.

    Body: {"report_ids": [1, 2, ...]}
    Returns per-report outcome; missing files reported, batch never aborts.
    """
    body = request.get_json(silent=True) or {}
    report_ids = body.get("report_ids") or []
    if not isinstance(report_ids, list) or not report_ids:
        return jsonify({"error": "report_ids (non-empty list) required"}), 400

    conn = get_db()
    try:
        results = []
        for rid in report_ids:
            row = conn.execute(
                "SELECT * FROM reports WHERE id = ? AND downloaded = 1",
                (rid,)).fetchone()
            if not row:
                results.append({"report_id": rid, "error": "report not found or not downloaded"})
                continue
            abs_path = BASE_DIR / row["local_path"]
            if not abs_path.is_file():
                results.append({"report_id": rid, "error": "PDF missing on disk"})
                continue
            try:
                doc_id = sha256_file(abs_path)
            except OSError as e:
                results.append({"report_id": rid, "error": f"could not read file: {e}"})
                continue
            upsert_document(conn, doc_id, row["filename"], "saudi_exchange", abs_path)
            results.append({"report_id": rid, "document": _document_row(conn, doc_id)})
        conn.commit()
        return jsonify({"results": results})
    finally:
        conn.close()


@bp.post("/api/documents/upload")
def upload_documents():
    """Accept one or more PDF uploads (multipart field name: files)."""
    files = request.files.getlist("files")
    if not files:
        return jsonify({"error": "no files provided (multipart field 'files')"}), 400

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    conn = get_db()
    try:
        results = []
        for f in files:
            filename = secure_filename(f.filename or "upload.pdf")
            if not filename.lower().endswith(".pdf"):
                results.append({"filename": f.filename, "error": "only .pdf files accepted"})
                continue
            try:
                data = f.read()
                doc_id = sha256_bytes(data)
                dest = UPLOAD_DIR / f"{doc_id.split(':', 1)[1]}.pdf"
                if not dest.exists():
                    dest.write_bytes(data)
            except OSError as e:
                log.error("upload write failed filename=%s err=%s", filename, e)
                results.append({"filename": filename, "error": f"could not store file: {e}"})
                continue
            upsert_document(conn, doc_id, filename, "upload", dest)
            results.append({"filename": filename, "document": _document_row(conn, doc_id)})
        conn.commit()
        return jsonify({"results": results})
    finally:
        conn.close()


@bp.get("/api/documents/<path:document_id>")
def get_document(document_id):
    conn = get_db()
    try:
        doc = _document_row(conn, document_id)
        if not doc:
            return jsonify({"error": "document not found"}), 404
        return jsonify(doc)
    finally:
        conn.close()
