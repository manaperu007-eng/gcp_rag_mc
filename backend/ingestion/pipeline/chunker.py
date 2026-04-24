##############################################################################
# backend/ingestion/pipeline/chunker.py
# Token-aware sliding-window text chunker
##############################################################################
from __future__ import annotations

import re
import uuid
from typing import Any, Dict, List, Optional


def _approx_token_count(text: str) -> int:
    """Approximate token count using the ~4 chars/token heuristic."""
    return max(1, len(text) // 4)


def _split_into_sentences(text: str) -> List[str]:
    """Split text on sentence boundaries while preserving whitespace."""
    pattern = r'(?<=[.!?])\s+'
    parts = re.split(pattern, text.strip())
    return [p for p in parts if p]


class TextChunker:
    """
    Sliding-window chunker that operates on a list of page dicts.

    Each page dict must contain at least:
      - ``text``        : the raw text of the page
      - ``page_number`` : 1-based page number (optional)
      - ``section_title``: heading/section label (optional)

    Returns a list of chunk dicts:
      - ``chunk_id``     : UUID string
      - ``index``        : sequential integer
      - ``content``      : chunk text
      - ``page_number``  : originating page (first page of the chunk)
      - ``section_title``: originating section (first page of the chunk)
      - ``token_count``  : approximate token count
    """

    def __init__(self, chunk_size: int = 512, overlap: int = 64) -> None:
        if chunk_size < 1:
            raise ValueError("chunk_size must be >= 1")
        if overlap < 0 or overlap >= chunk_size:
            raise ValueError("overlap must be >= 0 and < chunk_size")
        self.chunk_size = chunk_size
        self.overlap = overlap

    # ── Public API ────────────────────────────────────────────────────────

    def chunk_pages(self, pages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Chunk a list of page dicts into overlapping token windows.
        The chunker respects sentence boundaries when possible.
        """
        # Flatten pages into a sequence of (text, page_number, section_title)
        segments: List[Dict[str, Any]] = []
        for page in pages:
            text = (page.get("text") or "").strip()
            if not text:
                continue
            sentences = _split_into_sentences(text)
            for sent in sentences:
                segments.append({
                    "text": sent,
                    "page_number": page.get("page_number"),
                    "section_title": page.get("section_title"),
                    "token_count": _approx_token_count(sent),
                })

        return self._build_chunks(segments)

    def chunk_text(
        self,
        text: str,
        page_number: Optional[int] = None,
        section_title: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Convenience: chunk a single raw string."""
        page = {"text": text, "page_number": page_number, "section_title": section_title}
        return self.chunk_pages([page])

    # ── Internal ──────────────────────────────────────────────────────────

    def _build_chunks(self, segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        chunks: List[Dict[str, Any]] = []
        chunk_index = 0

        # Sliding window over segments
        i = 0
        while i < len(segments):
            window_texts: List[str] = []
            window_tokens = 0
            first_page = segments[i]["page_number"]
            first_section = segments[i]["section_title"]
            j = i

            # Fill the window up to chunk_size tokens
            while j < len(segments) and window_tokens < self.chunk_size:
                seg = segments[j]
                window_texts.append(seg["text"])
                window_tokens += seg["token_count"]
                j += 1

            content = " ".join(window_texts).strip()
            if content:
                chunks.append({
                    "chunk_id": str(uuid.uuid4()),
                    "index": chunk_index,
                    "content": content,
                    "page_number": first_page,
                    "section_title": first_section,
                    "token_count": window_tokens,
                })
                chunk_index += 1

            # Advance by (chunk_size - overlap) tokens
            skip_tokens = 0
            while i < j and skip_tokens < max(1, self.chunk_size - self.overlap):
                skip_tokens += segments[i]["token_count"]
                i += 1

            # Safety: always advance at least one segment
            if i == 0:
                i = 1

        return chunks
