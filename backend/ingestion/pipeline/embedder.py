##############################################################################
# backend/ingestion/pipeline/embedder.py
# Batched text embedding pipeline using Vertex AI
##############################################################################
from __future__ import annotations

import logging
import time
from typing import List

from shared.vertex_client import VertexAIClient

logger = logging.getLogger(__name__)

# Vertex AI text-embedding-004 supports up to 250 texts per batch
_DEFAULT_BATCH_SIZE = 100
_RETRY_ATTEMPTS = 3
_RETRY_DELAY_S = 2.0


class EmbeddingPipeline:
    """
    Wraps VertexAIClient to embed large lists of texts in safe batches,
    with exponential-backoff retries on transient errors.
    """

    def __init__(
        self,
        vertex: VertexAIClient,
        batch_size: int = _DEFAULT_BATCH_SIZE,
    ) -> None:
        self.vertex = vertex
        self.batch_size = batch_size

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """
        Embed a list of texts and return their embedding vectors.
        Maintains the same order as the input list.
        Texts that are empty strings are replaced with a zero vector.
        """
        if not texts:
            return []

        all_embeddings: List[List[float]] = []

        for batch_start in range(0, len(texts), self.batch_size):
            batch = texts[batch_start : batch_start + self.batch_size]
            batch_embeddings = self._embed_with_retry(batch)
            all_embeddings.extend(batch_embeddings)
            logger.debug(
                "Embedded batch %d-%d of %d texts",
                batch_start,
                batch_start + len(batch),
                len(texts),
            )

        return all_embeddings

    # ── Internal ──────────────────────────────────────────────────────────

    def _embed_with_retry(self, texts: List[str]) -> List[List[float]]:
        """Embed a single batch with exponential-backoff retries."""
        # Replace empty texts with a placeholder to maintain index alignment
        safe_texts = [t if t.strip() else "N/A" for t in texts]

        last_exc: Exception = RuntimeError("No attempts made")
        for attempt in range(1, _RETRY_ATTEMPTS + 1):
            try:
                embeddings = self.vertex.embed_texts(safe_texts, task_type="RETRIEVAL_DOCUMENT")
                return embeddings
            except Exception as exc:
                last_exc = exc
                wait = _RETRY_DELAY_S * (2 ** (attempt - 1))
                logger.warning(
                    "Embedding attempt %d/%d failed: %s — retrying in %.1fs",
                    attempt,
                    _RETRY_ATTEMPTS,
                    exc,
                    wait,
                )
                time.sleep(wait)

        logger.error("All embedding attempts exhausted for batch of %d texts", len(texts))
        raise last_exc
