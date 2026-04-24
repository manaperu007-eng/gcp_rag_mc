# ==============================================================================
# backend/notifications/Dockerfile
# ==============================================================================

FROM python:3.12-slim AS builder

WORKDIR /build
COPY notifications/requirements.txt ./
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ── Runtime ───────────────────────────────────────────────────────────────────
FROM python:3.12-slim

LABEL service="kb-notifications"

RUN groupadd -r appuser && useradd -r -g appuser appuser

WORKDIR /app
COPY --from=builder /install /usr/local
COPY shared/        ./shared/
COPY notifications/ ./notifications/

ENV PYTHONPATH="/app"
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=8080

USER appuser
EXPOSE ${PORT}

CMD ["sh", "-c", "uvicorn notifications.main:app --host 0.0.0.0 --port ${PORT} --workers 1"]
