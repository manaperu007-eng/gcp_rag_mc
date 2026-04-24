##############################################################################
# backend/shared/vertex_client.py
# Vertex AI client: Gemini chat/generation + embeddings + vector search
##############################################################################
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

import vertexai
from vertexai.generative_models import (
    Content,
    GenerationConfig,
    GenerativeModel,
    HarmBlockThreshold,
    HarmCategory,
    Part,
)
from vertexai.language_models import TextEmbeddingInput, TextEmbeddingModel
from google.cloud.aiplatform.matching_engine import MatchingEngineIndexEndpoint

from shared.config import Settings


class VertexAIClient:
    """Wraps Gemini generation, text embeddings, and Vector Search."""

    # Safety settings — lenient for enterprise KB content
    SAFETY_SETTINGS = {
        HarmCategory.HARM_CATEGORY_HATE_SPEECH:      HarmBlockThreshold.BLOCK_ONLY_HIGH,
        HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_ONLY_HIGH,
        HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_ONLY_HIGH,
        HarmCategory.HARM_CATEGORY_HARASSMENT:        HarmBlockThreshold.BLOCK_ONLY_HIGH,
    }

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        vertexai.init(project=settings.project_id, location=settings.region)

        # Generative model
        self._gemini = GenerativeModel(
            model_name=settings.gemini_model,
            safety_settings=self.SAFETY_SETTINGS,
        )

        # Embedding model
        self._embed_model = TextEmbeddingModel.from_pretrained(settings.embedding_model)

        # Vector search endpoint (lazy — only if configured)
        self._index_endpoint: Optional[MatchingEngineIndexEndpoint] = None

    def _get_index_endpoint(self) -> MatchingEngineIndexEndpoint:
        if self._index_endpoint is None and self.settings.vertex_index_endpoint:
            self._index_endpoint = MatchingEngineIndexEndpoint(
                index_endpoint_name=self.settings.vertex_index_endpoint
            )
        return self._index_endpoint

    # ── Embeddings ────────────────────────────────────────────────────────

    def embed_texts(self, texts: List[str], task_type: str = "RETRIEVAL_DOCUMENT") -> List[List[float]]:
        """Generate embeddings for a list of texts. Returns list of float vectors."""
        inputs = [TextEmbeddingInput(text=t, task_type=task_type) for t in texts]
        embeddings = self._embed_model.get_embeddings(inputs)
        return [e.values for e in embeddings]

    def embed_query(self, query: str) -> List[float]:
        """Generate a single query embedding for vector search."""
        result = self._embed_model.get_embeddings(
            [TextEmbeddingInput(text=query, task_type="RETRIEVAL_QUERY")]
        )
        return result[0].values

    # ── Vector Search ─────────────────────────────────────────────────────

    def search_similar_chunks(
        self, query: str, top_k: int = 10
    ) -> List[Tuple[str, float]]:
        """Search for similar document chunks. Returns list of (chunk_id, distance)."""
        endpoint = self._get_index_endpoint()
        if not endpoint:
            return []

        query_embedding = self.embed_query(query)
        response = endpoint.find_neighbors(
            deployed_index_id=self.settings.vertex_deployed_index_id,
            queries=[query_embedding],
            num_neighbors=top_k,
        )

        results: List[Tuple[str, float]] = []
        for neighbors in response:
            for neighbor in neighbors:
                results.append((neighbor.id, neighbor.distance))
        return results

    def upsert_embeddings(
        self, datapoints: List[Dict[str, Any]]
    ) -> None:
        """Upsert embeddings into the Vector Search index.
        datapoints: list of {"datapoint_id": str, "feature_vector": List[float]}
        """
        endpoint = self._get_index_endpoint()
        if endpoint:
            endpoint.upsert_datapoints(datapoints=datapoints)

    def remove_embeddings(self, chunk_ids: List[str]) -> None:
        endpoint = self._get_index_endpoint()
        if endpoint:
            endpoint.remove_datapoints(datapoint_ids=chunk_ids)

    # ── Gemini Generation ─────────────────────────────────────────────────

    def generate(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        max_tokens: int = 2048,
        temperature: float = 0.2,
    ) -> str:
        """Single-turn generation."""
        model = (
            GenerativeModel(
                model_name=self.settings.gemini_model,
                system_instruction=[Part.from_text(system_instruction)],
                safety_settings=self.SAFETY_SETTINGS,
            )
            if system_instruction
            else self._gemini
        )
        response = model.generate_content(
            prompt,
            generation_config=GenerationConfig(
                max_output_tokens=max_tokens,
                temperature=temperature,
            ),
        )
        return response.text

    def chat(
        self,
        history: List[Dict[str, str]],
        new_message: str,
        system_instruction: Optional[str] = None,
        max_tokens: int = 1024,
    ) -> str:
        """Multi-turn chat with history.
        history: [{"role": "user"|"model", "content": str}, ...]
        """
        model = (
            GenerativeModel(
                model_name=self.settings.gemini_model,
                system_instruction=[Part.from_text(system_instruction)],
                safety_settings=self.SAFETY_SETTINGS,
            )
            if system_instruction
            else self._gemini
        )

        contents = [
            Content(
                role=msg["role"],
                parts=[Part.from_text(msg["content"])],
            )
            for msg in history
        ]

        chat_session = model.start_chat(history=contents)
        response = chat_session.send_message(
            new_message,
            generation_config=GenerationConfig(
                max_output_tokens=max_tokens,
                temperature=0.3,
            ),
        )
        return response.text

    # ── KB-specific Prompts ───────────────────────────────────────────────

    def generate_questions_from_chunks(
        self,
        chunks: List[str],
        topic: Optional[str],
        num_questions: int,
        question_types: List[str],
        difficulty: str = "medium",
    ) -> List[Dict[str, Any]]:
        """Use Gemini to generate questionnaire questions from KB chunks."""

        context = "\n\n---\n\n".join(chunks[:20])  # Cap context window
        types_str = ", ".join(question_types)

        prompt = f"""You are an expert assessment designer. Based on the following knowledge base content, 
generate exactly {num_questions} questions for a compliance/knowledge questionnaire.

KNOWLEDGE BASE CONTENT:
{context}

REQUIREMENTS:
- Topic focus: {topic or 'general knowledge from the content above'}
- Difficulty: {difficulty}
- Mix of these question types: {types_str}
- Questions should test genuine understanding, not just memorization

For each question, output a JSON object with this exact structure:
{{
  "question_text": "...",
  "question_type": "free_text|true_false|multiple_choice|multi_select|rating|file_upload|number|date",
  "is_required": true,
  "section": "...",
  "help_text": "...",
  "options": {{
    "choices": [],           // For multiple_choice/multi_select only
    "min_rating": 1,         // For rating only
    "max_rating": 5,         // For rating only
    "rating_labels": []      // For rating only (e.g. ["Poor","Excellent"])
  }},
  "correct_answer_hint": "..."  // Optional: for admin ref only
}}

Return ONLY a valid JSON array of {num_questions} question objects. No other text."""

        raw = self.generate(prompt, temperature=0.4, max_tokens=4096)

        # Extract JSON from response
        match = re.search(r"\[.*\]", raw, re.DOTALL)
        if not match:
            raise ValueError(f"Gemini returned non-JSON response: {raw[:200]}")

        import json
        questions: List[Dict[str, Any]] = json.loads(match.group())
        return questions

    def answer_from_kb(
        self,
        question: str,
        context_chunks: List[str],
        kb_name: str = "Knowledge Base",
    ) -> str:
        """Generate a grounded answer to a question using retrieved KB chunks."""

        context = "\n\n---\n\n".join(context_chunks[:10])
        system = f"""You are a helpful assistant for the {kb_name}. 
Answer questions ONLY based on the provided knowledge base context.
If the answer is not in the context, say "I don't have information on that in the knowledge base."
Be concise and factual."""

        prompt = f"""KNOWLEDGE BASE CONTEXT:
{context}

USER QUESTION:
{question}

Provide a helpful, accurate answer based strictly on the knowledge base above."""

        return self.generate(prompt, system_instruction=system, temperature=0.1)

    def interpret_chat_answer(
        self,
        question_text: str,
        question_type: str,
        options: Optional[Dict[str, Any]],
        user_message: str,
    ) -> Dict[str, Any]:
        """Interpret a free-form chat message as a structured answer for the given question type."""

        options_str = f"\nQuestion options: {options}" if options else ""
        prompt = f"""The user is answering a questionnaire question via chat.

Question: "{question_text}"
Question type: {question_type}{options_str}

User's chat response: "{user_message}"

Extract the user's answer and return a JSON object with these fields:
- "captured": true/false (was an answer successfully captured?)
- "answer_text": string or null
- "answer_boolean": true/false/null
- "answer_number": number or null
- "answer_choices": array of strings (for multiple_choice/multi_select)
- "confidence": "high"/"medium"/"low"
- "clarification_needed": string or null (if confidence is low, what to ask)

Return ONLY valid JSON. No other text."""

        import json
        raw = self.generate(prompt, temperature=0.0, max_tokens=512)
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            return {"captured": False, "clarification_needed": "Could you please rephrase your answer?"}
        return json.loads(match.group())

    def extract_document_metadata(self, text_sample: str, file_name: str) -> Dict[str, Any]:
        """Extract title, author, language, and tags from document text."""
        prompt = f"""Analyze this document excerpt and extract metadata.
File name: {file_name}

Document excerpt (first 2000 chars):
{text_sample[:2000]}

Return a JSON object with:
- "title": string (document title, or derive from file name)
- "author": string or null
- "language": ISO 639-1 code (e.g. "en", "fr")
- "category": string (e.g. "Policy", "Procedure", "Report", "Training", "Compliance")
- "tags": array of strings (max 10 relevant tags)
- "summary": string (2-3 sentence summary)

Return ONLY valid JSON."""

        import json
        raw = self.generate(prompt, temperature=0.0, max_tokens=512)
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            return {"title": file_name, "language": "en", "tags": [], "category": "Document"}
        return json.loads(match.group())
