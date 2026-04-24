##############################################################################
# backend/ingestion/main.py
# Cloud Run service: receives Pub/Sub push messages and processes documents
##############################################################################
from __future__ import annotations

import base64
import json
import logging
import os
from contextlib import asynccontextmanager

import google.cloud.logging
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ingestion.pipeline.orchestrator import IngestionOrchestrator
from shared.config import get_settings
from shared.models import HealthResponse

try:
    google.cloud.logging.Client().setup_logging()
except Exception:
    logging.basicConfig(level=logging.INFO)

logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting KB Ingestion Service — env=%s", settings.environment)
    yield


app = FastAPI(
    title="KB Ingestion Service",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
)


class PubSubMessage(BaseModel):
    message: dict
    subscription: str


@app.post("/ingest", status_code=status.HTTP_200_OK)
async def ingest(request: Request):
    """
    Pub/Sub push endpoint. Receives notification of a new GCS object,
    downloads it, processes it through the full ingestion pipeline.
    """
    try:
        body = await request.json()
        envelope = body.get("message", {})
        data_b64 = envelope.get("data", "")
        if not data_b64:
            logger.warning("Empty Pub/Sub message data")
            return JSONResponse({"status": "ack_empty"})

        payload = json.loads(base64.b64decode(data_b64).decode("utf-8"))
        logger.info("Received ingestion event: %s", payload)

        # GCS notification payload
        bucket_name  = payload.get("bucket", settings.document_bucket)
        object_name  = payload.get("name", "")
        content_type = payload.get("contentType", "application/octet-stream")

        if not object_name:
            logger.warning("No object name in payload")
            return JSONResponse({"status": "ack_no_object"})

        # Extract document_id from GCS path: uploads/{user_id}/{doc_id}/{filename}
        parts = object_name.split("/")
        document_id = parts[2] if len(parts) >= 4 else None

        orchestrator = IngestionOrchestrator(settings)
        await orchestrator.process(
            bucket=bucket_name,
            object_path=object_name,
            document_id=document_id,
            content_type=content_type,
        )

        return JSONResponse({"status": "ok", "document_id": document_id})

    except Exception as exc:
        logger.exception("Ingestion failed: %s", exc)
        # Return 200 to prevent Pub/Sub retry storm — errors recorded in BQ
        return JSONResponse({"status": "error", "detail": str(exc)})


@app.post("/ingest/direct", status_code=status.HTTP_202_ACCEPTED)
async def ingest_direct(payload: dict):
    """
    Direct ingestion trigger (no Pub/Sub wrapper) — for testing or HTTP triggers.
    """
    orchestrator = IngestionOrchestrator(settings)
    await orchestrator.process(
        bucket=payload.get("bucket", settings.document_bucket),
        object_path=payload["object_path"],
        document_id=payload.get("document_id"),
        content_type=payload.get("content_type", "application/octet-stream"),
    )
    return {"status": "processing", "object": payload["object_path"]}


@app.get("/health", response_model=HealthResponse)
def health():
    return HealthResponse(service="kb-ingestion", environment=settings.environment)
