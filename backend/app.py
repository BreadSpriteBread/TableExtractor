from flask import Flask
from flask_cors import CORS

from backend.database import setup
from backend.routes.companies import bp as companies_bp
from backend.routes.documents import bp as documents_bp
from backend.routes.extraction_api import bp as extraction_bp
from backend.routes.reports import bp as reports_bp
from backend.routes.scraper_api import bp as scraper_bp


def create_app():
    app = Flask(__name__)
    CORS(app)

    setup()

    app.register_blueprint(companies_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(documents_bp)
    app.register_blueprint(extraction_bp)
    app.register_blueprint(scraper_bp)

    return app


if __name__ == "__main__":
    import os

    app = create_app()
    # threaded so long polls don't block; extraction itself runs in the
    # job manager's worker pool + child processes.
    app.run(
        debug=os.environ.get("FLASK_DEBUG", "1") == "1",
        port=int(os.environ.get("PORT", "5000")),
        threaded=True,
    )
