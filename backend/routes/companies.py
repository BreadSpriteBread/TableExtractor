from flask import Blueprint, jsonify
from backend.database import get_db

bp = Blueprint("companies", __name__)


@bp.get("/api/companies")
def list_companies():
    conn = get_db()
    rows = conn.execute("""
        SELECT
            c.company_code,
            c.company_name,
            COUNT(r.id)                              AS report_count,
            SUM(CASE WHEN r.downloaded=1 THEN 1 ELSE 0 END) AS downloaded_count
        FROM companies c
        LEFT JOIN reports r ON r.company_code = c.company_code
        GROUP BY c.company_code, c.company_name
        ORDER BY c.company_name
    """).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])
