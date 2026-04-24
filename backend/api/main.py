##############################################################################
# backend/api/main.py
# FastAPI application entry point
##############################################################################
from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from typing import Any

import google.cloud.logging
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from opentelemetry import trace
from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from api.routers import admin, assignments, auth, chat, documents, questionnaires, responses
from shared.config import get_settings
from shared.models import HealthResponse

# ── Cloud Logging ──────────────────────────────────────────────────────────
try:
    cloud_logging_client = google.cloud.logging.Client()
    cloud_logging_client.setup_logging()
except Exception:
    logging.basicConfig(level=logging.INFO)

logger = logging.getLogger(__name__)
settings = get_settings()


# ── OpenTelemetry tracing ──────────────────────────────────────────────────
def _setup_tracing() -> None:
    try:
        provider = TracerProvider()
        provider.add_span_processor(BatchSpanProcessor(CloudTraceSpanExporter()))
        trace.set_tracer_provider(provider)
    except Exception:
        pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting KB Questionnaire API — env=%s", settings.environment)
    _setup_tracing()
    yield
    logger.info("Shutting down KB Questionnaire API")


# ── FastAPI app ────────────────────────────────────────────────────────────
app = FastAPI(
    title="KB Questionnaire Platform API",
    description=(
        "Knowledge-base powered questionnaire platform. "
        "Supports document ingestion, AI question generation, "
        "multi-format responses, and geographic admin reporting."
    ),
    version="1.0.0",
    docs_url="/docs" if not settings.is_prod else None,
    redoc_url="/redoc" if not settings.is_prod else None,
    lifespan=lifespan,
)

# ── CORS ───────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── GZip ───────────────────────────────────────────────────────────────────
app.add_middleware(GZipMiddleware, minimum_size=1000)

# ── Request logging middleware ─────────────────────────────────────────────
@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start) * 1000
    logger.info(
        "method=%s path=%s status=%d duration_ms=%.1f",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
    )
    return response


# ── Global exception handler ───────────────────────────────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled exception: %s", exc)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error", "path": str(request.url.path)},
    )


# ── Routers ────────────────────────────────────────────────────────────────
API_PREFIX = "/api/v1"

app.include_router(auth.router,           prefix=API_PREFIX)
app.include_router(documents.router,      prefix=API_PREFIX)
app.include_router(questionnaires.router, prefix=API_PREFIX)
app.include_router(assignments.router,    prefix=API_PREFIX)
app.include_router(responses.router,      prefix=API_PREFIX)
app.include_router(admin.router,          prefix=API_PREFIX)
app.include_router(chat.router,           prefix=API_PREFIX)

# ── Health check ───────────────────────────────────────────────────────────
@app.get("/health", response_model=HealthResponse, tags=["health"])
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        service="kb-api",
        environment=settings.environment,
    )


@app.get("/", include_in_schema=False)
def root() -> dict[str, Any]:
    return {
        "service": "KB Questionnaire Platform API",
        "version": "1.0.0",
        "environment": settings.environment,
        "docs": "/docs",
    }


# ── OpenTelemetry instrumentation (must be after route setup) ─────────────
FastAPIInstrumentor.instrument_app(app)
