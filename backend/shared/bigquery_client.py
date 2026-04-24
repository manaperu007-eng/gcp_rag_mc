##############################################################################
# backend/shared/bigquery_client.py
# Thin async-friendly BigQuery client wrapper
##############################################################################
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from google.cloud import bigquery
from google.cloud.bigquery import QueryJobConfig, ScalarQueryParameter

from shared.config import Settings


class BigQueryClient:
    """Project-wide BigQuery client with helper methods for all tables."""

    def __init__(self, settings: Settings) -> None:
        self.client = bigquery.Client(project=settings.project_id)
        self.project = settings.project_id
        self.dataset = settings.bq_dataset
        self._prefix = f"`{settings.project_id}.{settings.bq_dataset}`"

    # ── Generic helpers ──────────────────────────────────────────────────

    def _table(self, name: str) -> str:
        return f"{self._prefix}.{name}"

    def _run(self, query: str, params: Optional[List] = None) -> List[Dict[str, Any]]:
        cfg = QueryJobConfig(query_parameters=params or [])
        job = self.client.query(query, job_config=cfg)
        return [dict(row) for row in job.result()]

    def _insert(self, table: str, rows: List[Dict[str, Any]]) -> None:
        errors = self.client.insert_rows_json(
            f"{self.project}.{self.dataset}.{table}", rows
        )
        if errors:
            raise RuntimeError(f"BigQuery insert errors: {errors}")

    # ── Documents ─────────────────────────────────────────────────────────

    def insert_document(self, doc: Dict[str, Any]) -> str:
        doc_id = doc.get("document_id") or str(uuid.uuid4())
        doc["document_id"] = doc_id
        doc.setdefault("ingested_at", datetime.now(timezone.utc).isoformat())
        doc.setdefault("status", "pending")
        self._insert("documents", [doc])
        return doc_id

    def get_document(self, document_id: str) -> Optional[Dict[str, Any]]:
        rows = self._run(
            f"SELECT * FROM {self._table('documents')} WHERE document_id = @id LIMIT 1",
            [ScalarQueryParameter("id", "STRING", document_id)],
        )
        return rows[0] if rows else None

    def update_document_status(
        self,
        document_id: str,
        status: str,
        processed_at: Optional[datetime] = None,
        chunk_count: Optional[int] = None,
        error_message: Optional[str] = None,
        processed_uri: Optional[str] = None,
    ) -> None:
        updates: List[str] = [f"status = '{status}'"]
        if processed_at:
            updates.append(f"processed_at = TIMESTAMP '{processed_at.isoformat()}'")
        if chunk_count is not None:
            updates.append(f"chunk_count = {chunk_count}")
        if error_message is not None:
            updates.append(f"error_message = '{error_message.replace(chr(39), chr(39)*2)}'")
        if processed_uri:
            updates.append(f"processed_uri = '{processed_uri}'")
        self.client.query(
            f"UPDATE {self._table('documents')} SET {', '.join(updates)} WHERE document_id = @id",
            job_config=QueryJobConfig(
                query_parameters=[ScalarQueryParameter("id", "STRING", document_id)]
            ),
        ).result()

    def list_documents(
        self,
        kb_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        filters: List[str] = []
        if kb_id:
            filters.append(f"'{kb_id}' IN UNNEST(kb_ids)")
        if status:
            filters.append(f"status = '{status}'")
        where = f"WHERE {' AND '.join(filters)}" if filters else ""
        return self._run(
            f"""SELECT * FROM {self._table('documents')}
                {where}
                ORDER BY ingested_at DESC
                LIMIT {limit} OFFSET {offset}"""
        )

    def insert_chunks(self, chunks: List[Dict[str, Any]]) -> None:
        for chunk in chunks:
            chunk.setdefault("chunk_id", str(uuid.uuid4()))
            chunk.setdefault("created_at", datetime.now(timezone.utc).isoformat())
        self._insert("document_chunks", chunks)

    # ── Knowledge Bases ───────────────────────────────────────────────────

    def create_knowledge_base(self, kb: Dict[str, Any]) -> str:
        kb_id = str(uuid.uuid4())
        kb["kb_id"] = kb_id
        kb.setdefault("created_at", datetime.now(timezone.utc).isoformat())
        kb.setdefault("is_active", True)
        kb.setdefault("document_count", 0)
        self._insert("knowledge_bases", [kb])
        return kb_id

    def get_knowledge_base(self, kb_id: str) -> Optional[Dict[str, Any]]:
        rows = self._run(
            f"SELECT * FROM {self._table('knowledge_bases')} WHERE kb_id = @id LIMIT 1",
            [ScalarQueryParameter("id", "STRING", kb_id)],
        )
        return rows[0] if rows else None

    def list_knowledge_bases(self) -> List[Dict[str, Any]]:
        return self._run(
            f"SELECT * FROM {self._table('knowledge_bases')} WHERE is_active = TRUE ORDER BY created_at DESC"
        )

    # ── Questionnaires ────────────────────────────────────────────────────

    def create_questionnaire(self, q: Dict[str, Any]) -> str:
        q_id = str(uuid.uuid4())
        q["questionnaire_id"] = q_id
        q.setdefault("created_at", datetime.now(timezone.utc).isoformat())
        q.setdefault("version", 1)
        q.setdefault("status", "draft")
        self._insert("questionnaires", [q])
        return q_id

    def get_questionnaire(self, questionnaire_id: str) -> Optional[Dict[str, Any]]:
        rows = self._run(
            f"SELECT * FROM {self._table('questionnaires')} WHERE questionnaire_id = @id LIMIT 1",
            [ScalarQueryParameter("id", "STRING", questionnaire_id)],
        )
        return rows[0] if rows else None

    def list_questionnaires(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        where = f"WHERE status = '{status}'" if status else ""
        return self._run(
            f"SELECT * FROM {self._table('questionnaires')} {where} ORDER BY created_at DESC"
        )

    def publish_questionnaire(self, questionnaire_id: str) -> None:
        self.client.query(
            f"""UPDATE {self._table('questionnaires')}
                SET status = 'published', published_at = CURRENT_TIMESTAMP()
                WHERE questionnaire_id = @id""",
            job_config=QueryJobConfig(
                query_parameters=[ScalarQueryParameter("id", "STRING", questionnaire_id)]
            ),
        ).result()

    # ── Questions ─────────────────────────────────────────────────────────

    def create_question(self, question: Dict[str, Any]) -> str:
        q_id = str(uuid.uuid4())
        question["question_id"] = q_id
        question.setdefault("created_at", datetime.now(timezone.utc).isoformat())
        # Serialize nested options struct
        if "options" in question and isinstance(question["options"], dict):
            question["options"] = question["options"]  # BQ accepts dicts for RECORD
        self._insert("questions", [question])
        return q_id

    def list_questions(self, questionnaire_id: str) -> List[Dict[str, Any]]:
        return self._run(
            f"""SELECT * FROM {self._table('questions')}
                WHERE questionnaire_id = @qid
                ORDER BY order_index ASC""",
            [ScalarQueryParameter("qid", "STRING", questionnaire_id)],
        )

    # ── User Assignments ──────────────────────────────────────────────────

    def create_assignment(self, assignment: Dict[str, Any]) -> str:
        a_id = str(uuid.uuid4())
        assignment["assignment_id"] = a_id
        assignment.setdefault("assigned_at", datetime.now(timezone.utc).isoformat())
        assignment.setdefault("status", "not_started")
        assignment.setdefault("completion_pct", 0.0)
        self._insert("user_assignments", [assignment])
        return a_id

    def get_assignment(self, assignment_id: str) -> Optional[Dict[str, Any]]:
        rows = self._run(
            f"SELECT * FROM {self._table('user_assignments')} WHERE assignment_id = @id LIMIT 1",
            [ScalarQueryParameter("id", "STRING", assignment_id)],
        )
        return rows[0] if rows else None

    def get_user_assignment(self, user_id: str, questionnaire_id: str) -> Optional[Dict[str, Any]]:
        rows = self._run(
            f"""SELECT * FROM {self._table('user_assignments')}
                WHERE user_id = @uid AND questionnaire_id = @qid LIMIT 1""",
            [
                ScalarQueryParameter("uid", "STRING", user_id),
                ScalarQueryParameter("qid", "STRING", questionnaire_id),
            ],
        )
        return rows[0] if rows else None

    def update_assignment_completion(
        self, assignment_id: str, completion_pct: float, status: str
    ) -> None:
        self.client.query(
            f"""UPDATE {self._table('user_assignments')}
                SET completion_pct = @pct, status = @status,
                    started_at = CASE WHEN started_at IS NULL AND @pct > 0
                                 THEN CURRENT_TIMESTAMP() ELSE started_at END,
                    submitted_at = CASE WHEN @status = 'submitted'
                                   THEN CURRENT_TIMESTAMP() ELSE submitted_at END
                WHERE assignment_id = @id""",
            job_config=QueryJobConfig(
                query_parameters=[
                    ScalarQueryParameter("pct", "FLOAT64", completion_pct),
                    ScalarQueryParameter("status", "STRING", status),
                    ScalarQueryParameter("id", "STRING", assignment_id),
                ]
            ),
        ).result()

    def list_user_assignments(self, user_id: str) -> List[Dict[str, Any]]:
        return self._run(
            f"""SELECT ua.*, q.title AS questionnaire_title
                FROM {self._table('user_assignments')} ua
                JOIN {self._table('questionnaires')} q
                  ON ua.questionnaire_id = q.questionnaire_id
                WHERE ua.user_id = @uid
                ORDER BY ua.assigned_at DESC""",
            [ScalarQueryParameter("uid", "STRING", user_id)],
        )

    # ── Responses ─────────────────────────────────────────────────────────

    def insert_response(self, response: Dict[str, Any]) -> str:
        r_id = str(uuid.uuid4())
        response["response_id"] = r_id
        response.setdefault("responded_at", datetime.now(timezone.utc).isoformat())
        self._insert("responses", [response])
        return r_id

    def upsert_response(self, assignment_id: str, question_id: str, data: Dict[str, Any]) -> str:
        """Delete existing draft + insert new response."""
        self.client.query(
            f"""DELETE FROM {self._table('responses')}
                WHERE assignment_id = @aid AND question_id = @qid AND is_draft = TRUE""",
            job_config=QueryJobConfig(
                query_parameters=[
                    ScalarQueryParameter("aid", "STRING", assignment_id),
                    ScalarQueryParameter("qid", "STRING", question_id),
                ]
            ),
        ).result()
        return self.insert_response(data)

    def get_answered_question_ids(self, assignment_id: str) -> List[str]:
        rows = self._run(
            f"""SELECT DISTINCT question_id FROM {self._table('responses')}
                WHERE assignment_id = @aid AND (is_draft IS NULL OR is_draft = FALSE)""",
            [ScalarQueryParameter("aid", "STRING", assignment_id)],
        )
        return [r["question_id"] for r in rows]

    def get_responses(self, assignment_id: str) -> List[Dict[str, Any]]:
        return self._run(
            f"""SELECT * FROM {self._table('responses')}
                WHERE assignment_id = @aid
                ORDER BY responded_at ASC""",
            [ScalarQueryParameter("aid", "STRING", assignment_id)],
        )

    # ── Users ─────────────────────────────────────────────────────────────

    def create_user(self, user: Dict[str, Any]) -> str:
        user_id = str(uuid.uuid4())
        user["user_id"] = user_id
        user.setdefault("created_at", datetime.now(timezone.utc).isoformat())
        user.setdefault("is_active", True)
        self._insert("users", [user])
        return user_id

    def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        rows = self._run(
            f"SELECT * FROM {self._table('users')} WHERE email = @email LIMIT 1",
            [ScalarQueryParameter("email", "STRING", email)],
        )
        return rows[0] if rows else None

    def get_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        rows = self._run(
            f"SELECT * FROM {self._table('users')} WHERE user_id = @id LIMIT 1",
            [ScalarQueryParameter("id", "STRING", user_id)],
        )
        return rows[0] if rows else None

    def list_users(self, role: Optional[str] = None) -> List[Dict[str, Any]]:
        where = f"WHERE role = '{role}'" if role else ""
        return self._run(
            f"SELECT * FROM {self._table('users')} {where} ORDER BY created_at DESC"
        )

    # ── Admin Reporting ───────────────────────────────────────────────────

    def get_completion_report(self, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        conditions: List[str] = []
        if filters.get("questionnaire_id"):
            conditions.append(f"questionnaire_id = '{filters['questionnaire_id']}'")
        if filters.get("region"):
            conditions.append(f"region = '{filters['region']}'")
        if filters.get("country"):
            conditions.append(f"country = '{filters['country']}'")
        if filters.get("city"):
            conditions.append(f"city = '{filters['city']}'")
        if filters.get("department"):
            conditions.append(f"department = '{filters['department']}'")
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        return self._run(
            f"SELECT * FROM {self._table('vw_questionnaire_completion')} {where} ORDER BY completion_rate_pct DESC"
        )

    def get_overdue_assignments(self, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        conditions: List[str] = []
        for k in ("region", "country", "department"):
            if filters.get(k):
                conditions.append(f"{k} = '{filters[k]}'")
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        return self._run(
            f"SELECT * FROM {self._table('vw_overdue_assignments')} {where}"
        )

    def get_response_summary(self, questionnaire_id: str) -> List[Dict[str, Any]]:
        return self._run(
            f"""SELECT * FROM {self._table('vw_response_summary')}
                WHERE questionnaire_id = @qid""",
            [ScalarQueryParameter("qid", "STRING", questionnaire_id)],
        )

    # ── Audit Logs ────────────────────────────────────────────────────────

    def log_event(
        self,
        action: str,
        user_id: Optional[str] = None,
        user_email: Optional[str] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        row = {
            "log_id": str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "user_id": user_id,
            "user_email": user_email,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "details": json.dumps(details) if details else None,
        }
        self._insert("audit_logs", [row])
