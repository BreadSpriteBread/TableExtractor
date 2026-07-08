# syntax=docker/dockerfile:1

# Saudi Exchange table-extraction API — Cloud Run + NVIDIA GPU image
#
# Docling (layout + TableFormer) and easyocr run on the GPU via torch/CUDA.
# The container is stateless: SQLite, uploads and any scraped PDFs live under
# the in-memory /tmp filesystem and are discarded when the instance stops.
# The model weights are baked in at build time so cold starts don't re-download
# ~1 GB of models onto that ephemeral disk.
#
# Build & deploy (GPU is a deploy-time flag, not a Dockerfile setting):
#   gcloud builds submit --tag REGION-docker.pkg.dev/PROJECT/repo/thesis-api
#   gcloud run deploy thesis-api \
#       --image REGION-docker.pkg.dev/PROJECT/repo/thesis-api \
#       --region us-central1 \
#       --gpu 1 --gpu-type nvidia-l4 --no-gpu-zonal-redundancy \
#       --cpu 4 --memory 16Gi --max-instances 1 \
#       --execution-environment gen2 --timeout 3600 --no-cpu-throttling
#
# max-instances 1: job state is held in-process (single server worker), so a
# job submitted to one instance must be polled from the same instance.

# ── Stage 1: build the React frontend (served by Flask in prod) ──
FROM node:22-slim AS frontend
WORKDIR /fe
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ── Stage 2: API + models ──
# CUDA 12.4 + cuDNN runtime matches the torch wheels pulled by docling/easyocr.
FROM nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    # Deterministic, HOME-independent model caches (populated at build time).
    HF_HOME=/opt/models/hf \
    EASYOCR_MODULE_PATH=/opt/models/easyocr

# Ubuntu 22.04 ships Python 3.10 (matches the project's floor). libgl1 +
# libglib2.0-0 are the OpenCV runtime deps easyocr needs.
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-pip python3-venv \
        libgl1 libglib2.0-0 \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV PYTHONPATH=/app

# Dependencies first for layer caching. gunicorn serves the Flask app in prod.
COPY requirements.txt .
RUN python3 -m pip install --upgrade pip \
    && python3 -m pip install -r requirements.txt gunicorn

# Application code (scraper stays importable without the patchright browser)
# and the built frontend — Flask serves it at / (see spa route in app.py).
COPY backend/ ./backend/
COPY scripts/ ./scripts/
COPY --from=frontend /fe/dist ./frontend/dist

# Bake the Docling + easyocr weights into the image (runs on CPU during build).
RUN python3 -m scripts.prefetch_models

# Stateless runtime config: writable in-memory paths, no live scraping, prod Flask.
ENV PORT=8080 \
    FLASK_DEBUG=0 \
    SCRAPER_STUB=1 \
    THESIS_DB_PATH=/tmp/data.db \
    THESIS_UPLOAD_DIR=/tmp/uploads \
    THESIS_PDF_DIR=/tmp/saudi_exchange_pdfs

EXPOSE 8080

# Single worker (in-process job state) with a thread pool for concurrent polls.
# Extraction itself runs in spawned child processes, so the web worker stays free.
CMD exec gunicorn \
    --workers 1 --threads 8 --timeout 120 \
    --bind "0.0.0.0:${PORT}" \
    --access-logfile - --error-logfile - \
    "backend.app:create_app()"
