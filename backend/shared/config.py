##############################################################################
# backend/shared/config.py
# Shared configuration loaded from environment variables / Secret Manager
##############################################################################
from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import List

from google.cloud import secretmanager
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _fetch_secret(secret_id: str, project_id: str) -> str:
    """Fetch a secret value from GCP Secret Manager."""
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{project_id}/secrets/{secret_id}/versions/latest"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("UTF-8")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ── GCP Core ──────────────────────────────────────────────────────────
    project_id: str = Field(..., alias="PROJECT_ID")
    region: str = Field("us-central1", alias="REGION")
    environment: str = Field("dev", alias="ENVIRONMENT")

    # ── BigQuery ──────────────────────────────────────────────────────────
    bq_dataset: str = Field(..., alias="BQ_DATASET")

    # ── GCS Buckets ───────────────────────────────────────────────────────
    document_bucket: str = Field(..., alias="DOCUMENT_BUCKET")
    processed_bucket: str = Field(..., alias="PROCESSED_BUCKET")
    evidence_bucket: str = Field(..., alias="EVIDENCE_BUCKET")
    reports_bucket: str = Field("", alias="REPORTS_BUCKET")

    # ── Vertex AI ─────────────────────────────────────────────────────────
    vertex_index_endpoint: str = Field("", alias="VERTEX_INDEX_ENDPOINT")
    gemini_model: str = Field("gemini-1.5-pro-002", alias="GEMINI_MODEL")
    embedding_model: str = Field("text-embedding-004", alias="EMBEDDING_MODEL")
    vertex_deployed_index_id: str = Field("kb_deployed_dev", alias="VERTEX_DEPLOYED_INDEX_ID")

    # ── Document AI ───────────────────────────────────────────────────────
    document_ai_processor_id: str = Field("", alias="DOCUMENT_AI_PROCESSOR_ID")
    document_ai_location: str = Field("us", alias="DOCUMENT_AI_LOCATION")

    # ── Pub/Sub ───────────────────────────────────────────────────────────
    ingestion_topic: str = Field("", alias="INGESTION_TOPIC")
    questionnaire_events_topic: str = Field("", alias="QUESTIONNAIRE_EVENTS_TOPIC")
    notifications_topic: str = Field("", alias="NOTIFICATIONS_TOPIC")

    # ── Firestore ─────────────────────────────────────────────────────────
    firestore_db: str = Field("(default)", alias="FIRESTORE_DB")

    # ── Auth / Security ───────────────────────────────────────────────────
    jwt_secret: str = Field("changeme-replace-in-secrets-manager", alias="JWT_SECRET")
    jwt_algorithm: str = Field("HS256", alias="JWT_ALGORITHM")
    jwt_expiry_minutes: int = Field(60 * 24, alias="JWT_EXPIRY_MINUTES")  # 24 hours

    # ── CORS ──────────────────────────────────────────────────────────────
    allowed_origins: List[str] = Field(["*"], alias="ALLOWED_ORIGINS")

    # ── Signed URL TTL ────────────────────────────────────────────────────
    signed_url_expiry_minutes: int = Field(15, alias="SIGNED_URL_EXPIRY_MINUTES")

    # ── Chunking ──────────────────────────────────────────────────────────
    chunk_size_tokens: int = Field(512, alias="CHUNK_SIZE_TOKENS")
    chunk_overlap_tokens: int = Field(64, alias="CHUNK_OVERLAP_TOKENS")
    max_chunks_per_doc: int = Field(2000, alias="MAX_CHUNKS_PER_DOC")

    # ── RAG / Search ──────────────────────────────────────────────────────
    top_k_results: int = Field(10, alias="TOP_K_RESULTS")

    # ── Email ─────────────────────────────────────────────────────────────
    sendgrid_api_key: str = Field("", alias="SENDGRID_API_KEY")
    from_email: str = Field("noreply@kb-platform.com", alias="FROM_EMAIL")

    @classmethod
    def from_secret_manager(cls) -> "Settings":
        """Load JWT secret from Secret Manager (for Cloud Run deployments)."""
        project_id = os.environ.get("PROJECT_ID", "")
        if project_id:
            try:
                jwt_secret = _fetch_secret("kb-jwt-secret", project_id)
                os.environ["JWT_SECRET"] = jwt_secret
            except Exception:
                pass  # Fall back to env var
        return cls()

    @property
    def is_prod(self) -> bool:
        return self.environment == "prod"

    @property
    def allowed_origins_list(self) -> List[str]:
        if isinstance(self.allowed_origins, str):
            return [o.strip() for o in self.allowed_origins.split(",")]
        return self.allowed_origins


@lru_cache
def get_settings() -> Settings:
    return Settings()
