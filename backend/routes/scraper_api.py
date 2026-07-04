"""Scraper trigger/status endpoints (stubbed in CI via SCRAPER_STUB=1)."""
from flask import Blueprint, jsonify, request

from backend.services import scraper

bp = Blueprint("scraper_api", __name__)


@bp.post("/api/scrape")
def start_scrape():
    body = request.get_json(silent=True) or {}
    limit = int(body.get("limit", 20))
    if not scraper.start_scrape_in_background(limit=limit):
        return jsonify({"error": "scrape already running",
                        "status": scraper.get_status()}), 409
    return jsonify({"started": True, "status": scraper.get_status()}), 202


@bp.get("/api/scrape/status")
def scrape_status():
    return jsonify(scraper.get_status())
