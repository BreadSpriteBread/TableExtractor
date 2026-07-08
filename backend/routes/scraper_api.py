"""Scraper trigger/status endpoints (stubbed in CI via SCRAPER_STUB=1)."""
from flask import Blueprint, jsonify, request

from backend.services import scraper

bp = Blueprint("scraper_api", __name__)


@bp.get("/api/scrape/companies")
def list_companies():
    """Company profiles from the CSV, each flagged with its scrape state."""
    return jsonify({"companies": scraper.list_companies()})


@bp.post("/api/scrape")
def start_scrape():
    body = request.get_json(silent=True) or {}
    codes = body.get("codes")
    if codes is not None and not isinstance(codes, list):
        return jsonify({"error": "codes must be a list of company codes"}), 400
    limit = int(body.get("limit", 20))
    if not scraper.start_scrape_in_background(codes=codes, limit=limit):
        return jsonify({"error": "scrape already running",
                        "status": scraper.get_status()}), 409
    return jsonify({"started": True, "status": scraper.get_status()}), 202


@bp.get("/api/scrape/status")
def scrape_status():
    return jsonify(scraper.get_status())
