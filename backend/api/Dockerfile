# ==============================================================================
# backend/api/Dockerfile
# Multi-stage image for the KB Questionnaire API service
# ==============================================================================

# ── Stage 1: builder ──────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

# Install build tools (needed for some C extensions)
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python deps into a prefix directory
COPY api/requirements.txt ./api/requirements.txt
RUN pip install --no-cache-dir --prefix=/install -r api/requirements.txt

# ── Stage 2: runtime ──────────────────────────────────────────────────────────
FROM python:3.12-slim

LABEL maintainer="platform-team@example.com"
LABEL service="kb-api"

# Non-root user for security
RUN groupadd -r appuser && useradd -r -g appuser appuser

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application source
COPY shared/ ./shared/
COPY api/     ./api/

# Ensure the package roots are importable
ENV PYTHONPATH="/app"
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Cloud Run injects PORT; default to 8080
ENV PORT=8080

USER appuser

EXPOSE ${PORT}

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:${PORT}/health')"

CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT} --workers 2 --loop uvloop"]
