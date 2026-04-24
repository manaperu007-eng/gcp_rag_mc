##############################################################################
# backend/api/routers/responses.py
# Submit answers (all types), file upload URLs, save drafts, KB hints
##############################################################################
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import List

from fastapi import APIRouter, HTTPException, status
from google.cloud import storage as gcs

from api.core.dependencies import BQDep, CurrentUser, SettingsDep, VertexDep
from shared.models import (
    AnswerSubmit,
    BulkAnswerSubmit,
    FileUploadUrlRequest,
    FileUploadUrlResponse,
    KBSearchRequest,
    MessageResponse,
    ResponseOut,
)

router = APIRouter(prefix="/responses", tags=["responses"])


# ─────────────────────────────────────────────────────────────────────────────
# Submit a single answer
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/{assignment_id}/answer", response_model=ResponseOut, status_code=status.HTTP_201_CREATED)
def submit_answer(
    assignment_id: str,
    body: AnswerSubmit,
    current_user: CurrentUser,
    bq: BQDep,
    settings: SettingsDep,
):
    a = bq.get_assignment(assignment_id)
    if not a:
        raise HTTPException(status_code=404, detail="Assignment not found")
    if a["user_id"] != current_user.user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    if a["status"] == "submitted":
        raise HTTPException(status_code=400, detail="Assignment already submitted — cannot modify answers")

    # Validate question belongs to questionnaire
    questions = bq.list_questions(a["questionnaire_id"])
    q_map = {q["question_id"]: q for q in questions}
    if body.question_id not in q_map:
        raise HTTPException(status_code=400, detail="Question not found in this questionnaire")

    question = q_map[body.question_id]
    _validate_answer(body, question)

    response_data = {
        "assignment_id": assignment_id,
        "questionnaire_id": a["questionnaire_id"],
        "question_id": body.question_id,
        "user_id": current_user.user_id,
        "question_type": question["question_type"],
        "answer_text": body.answer_text,
        "answer_boolean": body.answer_boolean,
        "answer_number": body.answer_number,
        "answer_choices": body.answer_choices,
        "answer_date": body.answer_date.isoformat() if body.answer_date else None,
        "file_uploads": [f.model_dump() for f in body.file_uploads],
        "ai_hint_used": body.ai_hint_used,
        "channel": body.channel.value,
        "is_draft": body.is_draft,
    }

    r_id = bq.upsert_response(assignment_id, body.question_id, response_data)

    # Update completion percentage
    if not body.is_draft:
        _refresh_completion(assignment_id, a["questionnaire_id"], bq)
        _publish_answer_event(settings, assignment_id, a["questionnaire_id"], body.question_id, current_user.user_id)

    bq.log_event(
        "ANSWER_SUBMITTED",
        user_id=current_user.user_id,
        resource_id=r_id,
        details={"question_id": body.question_id, "is_draft": body.is_draft},
    )
    row = bq._run(f"SELECT * FROM `{bq.project}.{bq.dataset}.responses` WHERE response_id = '{r_id}'")
    return ResponseOut(**row[0])


def _validate_answer(body: AnswerSubmit, question: dict) -> None:
    """Light validation of answer against question type."""
    qt = question["question_type"]
    if qt == "true_false" and body.answer_boolean is None:
        raise HTTPException(status_code=422, detail="true_false question requires answer_boolean")
    if qt == "rating" and body.answer_number is None:
        raise HTTPException(status_code=422, detail="rating question requires answer_number")
    if qt in ("multiple_choice", "multi_select") and not body.answer_choices:
        raise HTTPException(status_code=422, detail=f"{qt} question requires answer_choices")
    if qt == "file_upload" and not body.file_uploads and not body.is_draft:
        raise HTTPException(status_code=422, detail="file_upload question requires at least one file")
    if qt == "number" and body.answer_number is None:
        raise HTTPException(status_code=422, detail="number question requires answer_number")
    if qt == "date" and body.answer_date is None:
        raise HTTPException(status_code=422, detail="date question requires answer_date")


def _refresh_completion(assignment_id: str, questionnaire_id: str, bq) -> None:
    questions = bq.list_questions(questionnaire_id)
    answered = set(bq.get_answered_question_ids(assignment_id))
    total = len(questions)
    if total == 0:
        return
    pct = len(answered) / total * 100
    new_status = "submitted" if pct >= 100 else "in_progress"
    bq.update_assignment_completion(assignment_id, pct, new_status)


def _publish_answer_event(settings, assignment_id, questionnaire_id, question_id, user_id) -> None:
    if not settings.questionnaire_events_topic:
        return
    import json
    from google.cloud import pubsub_v1
    try:
        pub = pubsub_v1.PublisherClient()
        payload = json.dumps({
            "event_type": "ANSWER_SUBMITTED",
            "assignment_id": assignment_id,
            "questionnaire_id": questionnaire_id,
            "question_id": question_id,
            "user_id": user_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }).encode()
        pub.publish(settings.questionnaire_events_topic, payload)
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# Bulk submit
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/bulk", response_model=List[ResponseOut])
def bulk_submit(body: BulkAnswerSubmit, current_user: CurrentUser, bq: BQDep, settings: SettingsDep):
    results = []
    for answer in body.answers:
        # Delegate to single answer endpoint logic
        a = bq.get_assignment(body.assignment_id)
        if not a:
            raise HTTPException(status_code=404, detail="Assignment not found")
        questions = bq.list_questions(a["questionnaire_id"])
        q_map = {q["question_id"]: q for q in questions}
        if answer.question_id not in q_map:
            continue
        question = q_map[answer.question_id]
        response_data = {
            "assignment_id": body.assignment_id,
            "questionnaire_id": a["questionnaire_id"],
            "question_id": answer.question_id,
            "user_id": current_user.user_id,
            "question_type": question["question_type"],
            "answer_text": answer.answer_text,
            "answer_boolean": answer.answer_boolean,
            "answer_number": answer.answer_number,
            "answer_choices": answer.answer_choices,
            "answer_date": answer.answer_date.isoformat() if answer.answer_date else None,
            "file_uploads": [f.model_dump() for f in answer.file_uploads],
            "ai_hint_used": answer.ai_hint_used,
            "channel": answer.channel.value,
            "is_draft": answer.is_draft,
        }
        r_id = bq.upsert_response(body.assignment_id, answer.question_id, response_data)
        row = bq._run(f"SELECT * FROM `{bq.project}.{bq.dataset}.responses` WHERE response_id = '{r_id}'")
        results.append(ResponseOut(**row[0]))

    if results:
        _refresh_completion(body.assignment_id, a["questionnaire_id"], bq)
    return results


# ─────────────────────────────────────────────────────────────────────────────
# Get all responses for an assignment
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/{assignment_id}", response_model=List[ResponseOut])
def get_responses(assignment_id: str, current_user: CurrentUser, bq: BQDep):
    a = bq.get_assignment(assignment_id)
    if not a:
        raise HTTPException(status_code=404, detail="Assignment not found")
    from shared.models import UserRole
    if current_user.role == UserRole.RESPONDENT and a["user_id"] != current_user.user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    rows = bq.get_responses(assignment_id)
    return [ResponseOut(**r) for r in rows]


# ─────────────────────────────────────────────────────────────────────────────
# Evidence file upload — signed URL
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/upload-url", response_model=FileUploadUrlResponse)
def get_evidence_upload_url(
    body: FileUploadUrlRequest,
    current_user: CurrentUser,
    settings: SettingsDep,
):
    file_id = str(uuid.uuid4())
    gcs_path = f"evidence/{current_user.user_id}/{body.assignment_id}/{body.question_id}/{file_id}/{body.file_name}"

    gcs_client = gcs.Client(project=settings.project_id)
    bucket = gcs_client.bucket(settings.evidence_bucket)
    blob = bucket.blob(gcs_path)
    expiry = timedelta(minutes=settings.signed_url_expiry_minutes)

    upload_url = blob.generate_signed_url(
        version="v4",
        expiration=expiry,
        method="PUT",
        content_type=body.content_type,
    )
    return FileUploadUrlResponse(
        file_id=file_id,
        upload_url=upload_url,
        expires_at=datetime.now(timezone.utc) + expiry,
    )


# ─────────────────────────────────────────────────────────────────────────────
# KB Hint — get AI-generated hint for a question from the knowledge base
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/{assignment_id}/hint/{question_id}")
def get_kb_hint(
    assignment_id: str,
    question_id: str,
    current_user: CurrentUser,
    bq: BQDep,
    vertex: VertexDep,
):
    """Return a Gemini-generated hint from the KB for the given question."""
    a = bq.get_assignment(assignment_id)
    if not a:
        raise HTTPException(status_code=404, detail="Assignment not found")
    if a["user_id"] != current_user.user_id:
        raise HTTPException(status_code=403, detail="Access denied")

    questions = bq.list_questions(a["questionnaire_id"])
    question = next((q for q in questions if q["question_id"] == question_id), None)
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")

    # Semantic search for relevant chunks
    neighbors = vertex.search_similar_chunks(question["question_text"], top_k=5)
    if not neighbors:
        return {"hint": "No relevant information found in the knowledge base."}

    chunk_ids = [n[0] for n in neighbors]
    ids_str = ", ".join(f"'{c}'" for c in chunk_ids)
    chunks = bq._run(
        f"SELECT content FROM `{bq.project}.{bq.dataset}.document_chunks` WHERE chunk_id IN ({ids_str})"
    )
    context = [r["content"] for r in chunks]

    kb_name = "Knowledge Base"
    q_data = bq.get_questionnaire(a["questionnaire_id"])
    if q_data and q_data.get("kb_id"):
        kb = bq.get_knowledge_base(q_data["kb_id"])
        if kb:
            kb_name = kb.get("name", kb_name)

    hint = vertex.answer_from_kb(question["question_text"], context, kb_name=kb_name)
    return {"hint": hint, "source_chunk_count": len(context)}
