# ==============================================================================
# backend/ingestion/Dockerfile
# Multi-stage image for the KB Ingestion service
# ==============================================================================

# ── Stage 1: builder ──────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libffi-dev \
        # required for pypdf and python-docx C extensions
        libxml2-dev \
        libxslt-dev \
    && rm -rf /var/lib/apt/lists/*

COPY ingestion/requirements.txt ./ingestion/requirements.txt
RUN pip install --no-cache-dir --prefix=/install -r ingestion/requirements.txt

# ── Stage 2: runtime ──────────────────────────────────────────────────────────
FROM python:3.12-slim

LABEL maintainer="platform-team@example.com"
LABEL service="kb-ingestion"

RUN groupadd -r appuser && useradd -r -g appuser appuser

WORKDIR /app

COPY --from=builder /install /usr/local

COPY shared/    ./shared/
COPY ingestion/ ./ingestion/

ENV PYTHONPATH="/app"
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=8080

# Temp dir for downloaded files; Cloud Run uses /tmp by default
ENV TMPDIR=/tmp

USER appuser

EXPOSE ${PORT}

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:${PORT}/health')"

CMD ["sh", "-c", "uvicorn ingestion.main:app --host 0.0.0.0 --port ${PORT} --workers 1 --loop uvloop"]
