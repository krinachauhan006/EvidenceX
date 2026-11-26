# EvidenceX API (FastAPI). Production image.
#
# One uvicorn worker on purpose: background processing uses in-process tasks and the
# failed-login throttle is held in process memory (see docs/DEPLOYMENT.md). Scale by
# running one instance per host behind the reverse proxy, not by adding workers.
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Tesseract for image OCR and scanned PDFs. PyAV wheels bundle FFmpeg for audio/video.
RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml ./
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./

# INSTALL_AUDIO=false builds a smaller image without speech recognition.
ARG INSTALL_AUDIO=true
RUN if [ "$INSTALL_AUDIO" = "true" ]; then pip install ".[audio]"; else pip install .; fi

# Unprivileged user; all writable state lives under /data (a mounted volume).
RUN useradd --create-home --uid 10001 evidencex \
 && mkdir -p /data/storage /data/models \
 && chown -R evidencex:evidencex /data
USER evidencex

ENV APP_ENV=production \
    DATABASE_URL=sqlite+pysqlite:////data/evidencex.db \
    STORAGE_ROOT=/data/storage \
    WHISPER_MODEL_DIR=/data/models \
    COOKIE_SECURE=true

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import json,urllib.request,sys; h=json.load(urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=4)); sys.exit(0 if h.get('status')=='ok' else 1)"

# --proxy-headers: trust X-Forwarded-* from the reverse proxy on the private network only.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips", "*"]
