##############################################################################
# backend/ingestion/pipeline/orchestrator.py
# Master ingestion pipeline: download → parse → chunk → embed → index
##############################################################################
from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from datetime import datetime, timezone
from typing import Dict, List, Optional

from google.cloud import storage as gcs

from ingestion.pipeline.chunker import TextChunker
from ingestion.pipeline.embedder import EmbeddingPipeline
from ingestion.processors.document_ai_processor import DocumentAIProcessor
from ingestion.processors.excel_processor import ExcelProcessor
from shared.bigquery_client import BigQueryClient
from shared.config import Settings
from shared.vertex_client import VertexAIClient

logger = logging.getLogger(__name__)

SUPPORTED_TYPES = {
    "application/pdf":                                                                   "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document":           "docx",
    "application/msword":                                                                "doc",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":                "xlsx",
    "application/vnd.ms-excel":                                                         "xls",
}


class IngestionOrchestrator:
    def __init__(self, settings: Settings) -> None:
        self.settings  = settings
        self.bq        = BigQueryClient(settings)
        self.vertex    = VertexAIClient(settings)
        self.gcs       = gcs.Client(project=settings.project_id)
        self.chunker   = TextChunker(
            chunk_size=settings.chunk_size_tokens,
            overlap=settings.chunk_overlap_tokens,
        )
        self.embedder  = EmbeddingPipeline(self.vertex)
        self.doc_ai    = DocumentAIProcessor(settings)
        self.xl_proc   = ExcelProcessor()

    async def process(
        self,
        bucket: str,
        object_path: str,
        document_id: Optional[str] = None,
        content_type: str = "application/octet-stream",
    ) -> None:
        logger.info("Processing gs://%s/%s (doc_id=%s)", bucket, object_path, document_id)

        # Mark document as processing
        if document_id:
            self.bq.update_document_status(document_id, "processing")

        try:
            file_type = SUPPORTED_TYPES.get(content_type)
            if not file_type:
                # Infer from extension
                ext = object_path.rsplit(".", 1)[-1].lower()
                file_type = ext if ext in ("pdf", "docx", "doc", "xlsx", "xls") else None

            if not file_type:
                raise ValueError(f"Unsupported content type: {content_type}")

            # 1. Download from GCS
            with tempfile.NamedTemporaryFile(suffix=f".{file_type}", delete=False) as tmp:
                tmp_path = tmp.name
            blob = self.gcs.bucket(bucket).blob(object_path)
            blob.download_to_filename(tmp_path)
            logger.info("Downloaded to %s", tmp_path)

            # 2. Parse to raw text
            if file_type in ("xlsx", "xls"):
                pages = self.xl_proc.extract(tmp_path)
            else:
                pages = await asyncio.to_thread(
                    self.doc_ai.extract_text, tmp_path, file_type
                )

            full_text = "\n\n".join(p["text"] for p in pages)
            page_count = len(pages)
            word_count = len(full_text.split())

            logger.info("Extracted %d pages, %d words", page_count, word_count)

            # 3. Extract metadata via Gemini
            file_name = object_path.split("/")[-1]
            metadata = self.vertex.extract_document_metadata(full_text, file_name)
            logger.info("Extracted metadata: %s", metadata)

            # 4. Chunk text
            chunks = self.chunker.chunk_pages(pages)
            logger.info("Generated %d chunks", len(chunks))
            chunks = chunks[: self.settings.max_chunks_per_doc]

            # 5. Embed chunks
            chunk_texts = [c["content"] for c in chunks]
            embeddings  = self.embedder.embed_batch(chunk_texts)
            logger.info("Generated %d embeddings", len(embeddings))

            # 6. Index embeddings in Vertex AI Vector Search
            datapoints = [
                {"datapoint_id": c["chunk_id"], "feature_vector": emb}
                for c, emb in zip(chunks, embeddings)
            ]
            try:
                self.vertex.upsert_embeddings(datapoints)
                logger.info("Indexed %d datapoints in Vector Search", len(datapoints))
            except Exception as e:
                logger.warning("Vector Search upsert skipped (index may not be deployed): %s", e)

            # 7. Upload processed JSON to GCS
            processed_uri = self._upload_processed(document_id, file_name, {
                "document_id": document_id,
                "pages": pages,
                "chunks": chunks,
                "metadata": metadata,
            })

            # 8. Write chunks to BigQuery
            bq_chunks = [
                {
                    "chunk_id":      c["chunk_id"],
                    "document_id":   document_id,
                    "chunk_index":   c["index"],
                    "content":       c["content"],
                    "page_number":   c.get("page_number"),
                    "section_title": c.get("section_title"),
                    "token_count":   c.get("token_count"),
                    "embedding_id":  c["chunk_id"],
                }
                for c in chunks
            ]
            self.bq.insert_chunks(bq_chunks)

            # 9. Update document record to ready
            self.bq.update_document_status(
                document_id,
                "ready",
                processed_at=datetime.now(timezone.utc),
                chunk_count=len(chunks),
                processed_uri=processed_uri,
            )

            # Also update metadata fields
            if document_id:
                meta_updates = ", ".join([
                    f"title = '{metadata.get('title', '').replace(chr(39), '')}'" ,
                    f"language = '{metadata.get('language', 'en')}'",
                    f"page_count = {page_count}",
                    f"word_count = {word_count}",
                    f"category = '{metadata.get('category', '')}'",
                ])
                self.bq.client.query(
                    f"UPDATE `{self.settings.project_id}.{self.settings.bq_dataset}.documents` "
                    f"SET {meta_updates} WHERE document_id = '{document_id}'"
                ).result()

            logger.info("Document %s ingested successfully", document_id)

        except Exception as exc:
            logger.exception("Ingestion error for %s: %s", document_id, exc)
            if document_id:
                self.bq.update_document_status(document_id, "failed", error_message=str(exc))
            raise
        finally:
            # Clean up temp file
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    def _upload_processed(self, document_id: str, file_name: str, data: dict) -> str:
        import json
        path = f"processed/{document_id}/{file_name}.json"
        blob = self.gcs.bucket(self.settings.processed_bucket).blob(path)
        blob.upload_from_string(json.dumps(data, default=str), content_type="application/json")
        return f"gs://{self.settings.processed_bucket}/{path}"
