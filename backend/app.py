from flask import Flask, abort, send_from_directory
from flask_cors import CORS

from backend.config import FRONTEND_DIST, get_logger
from backend.database import setup
from backend.routes.companies import bp as companies_bp
from backend.routes.documents import bp as documents_bp
from backend.routes.extraction_api import bp as extraction_bp
from backend.routes.reports import bp as reports_bp
from backend.routes.scraper_api import bp as scraper_bp

log = get_logger(__name__)


def _log_gpu_status():
    """Log whether torch sees a CUDA GPU, so GPU pickup is visible in the
    Cloud Run logs on first boot. Extraction runs in child processes that
    share this container's driver, so the parent's view is representative.
    Defensive: a torch import/probe failure must never block app startup.
    """
    try:
        import torch
        if torch.cuda.is_available():
            log.info("gpu available=True device=%s count=%d cuda=%s",
                     torch.cuda.get_device_name(0), torch.cuda.device_count(),
                     torch.version.cuda)
        else:
            log.warning("gpu available=False — extraction will run on CPU")
    except Exception as e:
        log.warning("gpu probe failed err=%s", e)


def create_app():
    app = Flask(__name__)
    CORS(app)

    setup()
    _log_gpu_status()

    app.register_blueprint(companies_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(documents_bp)
    app.register_blueprint(extraction_bp)
    app.register_blueprint(scraper_bp)

    # Serve the built frontend (prod container). In dev the Vite server owns
    # the UI, FRONTEND_DIST doesn't exist, and these routes just 404.
    @app.get("/")
    @app.get("/<path:path>")
    def spa(path="index.html"):
        if path.startswith("api/"):
            abort(404)  # unknown API route — don't mask it with index.html
        if (FRONTEND_DIST / path).is_file():
            return send_from_directory(FRONTEND_DIST, path)
        if (FRONTEND_DIST / "index.html").is_file():
            return send_from_directory(FRONTEND_DIST, "index.html")
        abort(404)

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
