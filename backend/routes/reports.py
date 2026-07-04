"""Corpus browsing endpoints: list reports, serve PDFs, stats."""
from flask import Blueprint, abort, jsonify, request, send_file

from backend.config import BASE_DIR
from backend.database import get_db

bp = Blueprint("reports", __name__)


@bp.get("/api/reports")
def list_reports():
    company_code = request.args.get("company_code")
    search = request.args.get("search", "").strip().lower()
    downloaded_only = request.args.get("downloaded_only", "false").lower() == "true"

    sql = "SELECT * FROM reports WHERE 1=1"
    params: list = []
    if company_code:
        sql += " AND company_code = ?"
        params.append(company_code)
    if downloaded_only:
        sql += " AND downloaded = 1"
    if search:
        sql += " AND (LOWER(filename) LIKE ? OR LOWER(company_name) LIKE ? OR published_date LIKE ?)"
        like = f"%{search}%"
        params.extend([like, like, like])
    sql += " ORDER BY published_date DESC, id DESC"

    conn = get_db()
    try:
        rows = conn.execute(sql, params).fetchall()
        return jsonify([dict(r) for r in rows])
    finally:
        conn.close()


@bp.get("/api/reports/<int:report_id>")
def get_report(report_id):
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone()
        if not row:
            abort(404)
        return jsonify(dict(row))
    finally:
        conn.close()


@bp.get("/api/pdf/<int:report_id>")
def serve_pdf(report_id):
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT local_path, filename FROM reports WHERE id = ? AND downloaded = 1",
            (report_id,)).fetchone()
    finally:
        conn.close()

    if not row:
        abort(404)
    abs_path = BASE_DIR / row["local_path"]
    if not abs_path.is_file():
        abort(404)
    return send_file(abs_path, mimetype="application/pdf", download_name=row["filename"])


@bp.get("/api/stats")
def db_stats():
    conn = get_db()
    try:
        stats = {
            "companies": conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0],
            "reports_total": conn.execute("SELECT COUNT(*) FROM reports").fetchone()[0],
            "reports_downloaded": conn.execute(
                "SELECT COUNT(*) FROM reports WHERE downloaded=1").fetchone()[0],
            "documents": conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0],
            "extractions": conn.execute("SELECT COUNT(*) FROM extractions").fetchone()[0],
        }
        return jsonify(stats)
    finally:
        conn.close()
