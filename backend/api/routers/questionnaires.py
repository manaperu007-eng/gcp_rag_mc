##############################################################################
# backend/api/routers/questionnaires.py
# Questionnaires: CRUD + AI question generation + publish
##############################################################################
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, status

from api.core.dependencies import (
    AdminOnly,
    AdminReviewer,
    BQDep,
    CurrentUser,
    VertexDep,
)
from shared.models import (
    GenerateQuestionsRequest,
    MessageResponse,
    QuestionCreate,
    QuestionnaireCreate,
    QuestionnaireOut,
    QuestionnaireWithQuestions,
    QuestionOut,
    QuestionnaireStatus,
)

router = APIRouter(prefix="/questionnaires", tags=["questionnaires"])


# ─────────────────────────────────────────────────────────────────────────────
# Questionnaire CRUD
# ─────────────────────────────────────────────────────────────────────────────

@router.post("", response_model=QuestionnaireOut, status_code=status.HTTP_201_CREATED)
def create_questionnaire(
    body: QuestionnaireCreate,
    current_user: CurrentUser,
    bq: BQDep,
    _: None = AdminReviewer,
):
    data = body.model_dump()
    data["created_by"] = current_user.email
    q_id = bq.create_questionnaire(data)
    bq.log_event("QUESTIONNAIRE_CREATED", user_id=current_user.user_id, resource_id=q_id)
    return QuestionnaireOut(**bq.get_questionnaire(q_id))


@router.get("", response_model=List[QuestionnaireOut])
def list_questionnaires(
    current_user: CurrentUser,
    bq: BQDep,
    q_status: Optional[str] = Query(None, alias="status"),
):
    # Respondents only see published questionnaires assigned to them
    from shared.models import UserRole
    if current_user.role == UserRole.RESPONDENT:
        q_status = "published"
    rows = bq.list_questionnaires(status=q_status)
    return [QuestionnaireOut(**r) for r in rows]


@router.get("/{questionnaire_id}", response_model=QuestionnaireWithQuestions)
def get_questionnaire(questionnaire_id: str, current_user: CurrentUser, bq: BQDep):
    q = bq.get_questionnaire(questionnaire_id)
    if not q:
        raise HTTPException(status_code=404, detail="Questionnaire not found")
    questions = bq.list_questions(questionnaire_id)
    return QuestionnaireWithQuestions(
        **q,
        questions=[QuestionOut(**qn) for qn in questions],
    )


@router.put("/{questionnaire_id}", response_model=QuestionnaireOut)
def update_questionnaire(
    questionnaire_id: str,
    body: QuestionnaireCreate,
    current_user: CurrentUser,
    bq: BQDep,
    _: None = AdminReviewer,
):
    q = bq.get_questionnaire(questionnaire_id)
    if not q:
        raise HTTPException(status_code=404, detail="Questionnaire not found")
    if q["status"] == "published":
        raise HTTPException(status_code=400, detail="Cannot edit a published questionnaire")

    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    set_clauses = ", ".join(
        f"{k} = '{v}'" if isinstance(v, str) else f"{k} = {v}"
        for k, v in updates.items()
    )
    bq.client.query(
        f"UPDATE `{bq.project}.{bq.dataset}.questionnaires` "
        f"SET {set_clauses}, updated_at = CURRENT_TIMESTAMP() "
        f"WHERE questionnaire_id = '{questionnaire_id}'"
    ).result()
    bq.log_event("QUESTIONNAIRE_UPDATED", user_id=current_user.user_id, resource_id=questionnaire_id)
    return QuestionnaireOut(**bq.get_questionnaire(questionnaire_id))


@router.post("/{questionnaire_id}/publish", response_model=QuestionnaireOut)
def publish_questionnaire(
    questionnaire_id: str,
    current_user: CurrentUser,
    bq: BQDep,
    _: None = AdminReviewer,
):
    q = bq.get_questionnaire(questionnaire_id)
    if not q:
        raise HTTPException(status_code=404, detail="Questionnaire not found")
    if q["status"] == "published":
        raise HTTPException(status_code=400, detail="Already published")

    questions = bq.list_questions(questionnaire_id)
    if not questions:
        raise HTTPException(status_code=400, detail="Cannot publish questionnaire with no questions")

    bq.publish_questionnaire(questionnaire_id)
    bq.log_event("QUESTIONNAIRE_PUBLISHED", user_id=current_user.user_id, resource_id=questionnaire_id)
    return QuestionnaireOut(**bq.get_questionnaire(questionnaire_id))


@router.delete("/{questionnaire_id}", response_model=MessageResponse)
def delete_questionnaire(
    questionnaire_id: str,
    current_user: CurrentUser,
    bq: BQDep,
    _: None = AdminOnly,
):
    q = bq.get_questionnaire(questionnaire_id)
    if not q:
        raise HTTPException(status_code=404, detail="Questionnaire not found")
    bq.client.query(
        f"UPDATE `{bq.project}.{bq.dataset}.questionnaires` "
        f"SET status = 'archived' WHERE questionnaire_id = '{questionnaire_id}'"
    ).result()
    bq.log_event("QUESTIONNAIRE_ARCHIVED", user_id=current_user.user_id, resource_id=questionnaire_id)
    return MessageResponse(message="Questionnaire archived")


# ─────────────────────────────────────────────────────────────────────────────
# Questions CRUD
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/{questionnaire_id}/questions", response_model=List[QuestionOut])
def list_questions(questionnaire_id: str, current_user: CurrentUser, bq: BQDep):
    return [QuestionOut(**q) for q in bq.list_questions(questionnaire_id)]


@router.post(
    "/{questionnaire_id}/questions",
    response_model=QuestionOut,
    status_code=status.HTTP_201_CREATED,
)
def add_question(
    questionnaire_id: str,
    body: QuestionCreate,
    current_user: CurrentUser,
    bq: BQDep,
    _: None = AdminReviewer,
):
    q = bq.get_questionnaire(questionnaire_id)
    if not q:
        raise HTTPException(status_code=404, detail="Questionnaire not found")
    if q["status"] == "published":
        raise HTTPException(status_code=400, detail="Cannot add questions to a published questionnaire")

    data = body.model_dump()
    data["questionnaire_id"] = questionnaire_id
    data["ai_generated"] = False
    q_id = bq.create_question(data)
    bq.log_event("QUESTION_ADDED", user_id=current_user.user_id, resource_id=q_id)
    rows = bq._run(
        f"SELECT * FROM `{bq.project}.{bq.dataset}.questions` WHERE question_id = '{q_id}'"
    )
    return QuestionOut(**rows[0])


@router.delete("/{questionnaire_id}/questions/{question_id}", response_model=MessageResponse)
def delete_question(
    questionnaire_id: str,
    question_id: str,
    current_user: CurrentUser,
    bq: BQDep,
    _: None = AdminReviewer,
):
    bq.client.query(
        f"DELETE FROM `{bq.project}.{bq.dataset}.questions` "
        f"WHERE question_id = '{question_id}' AND questionnaire_id = '{questionnaire_id}'"
    ).result()
    bq.log_event("QUESTION_DELETED", user_id=current_user.user_id, resource_id=question_id)
    return MessageResponse(message="Question deleted")


# ─────────────────────────────────────────────────────────────────────────────
# AI Question Generation
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/{questionnaire_id}/generate-questions",
    response_model=List[QuestionOut],
    status_code=status.HTTP_201_CREATED,
)
def generate_questions(
    questionnaire_id: str,
    body: GenerateQuestionsRequest,
    current_user: CurrentUser,
    bq: BQDep,
    vertex: VertexDep,
    _: None = AdminReviewer,
):
    """
    Use Vertex AI Gemini to generate questions from the KB and
    automatically add them to the questionnaire.
    """
    q = bq.get_questionnaire(questionnaire_id)
    if not q:
        raise HTTPException(status_code=404, detail="Questionnaire not found")
    if q["status"] == "published":
        raise HTTPException(status_code=400, detail="Cannot modify a published questionnaire")

    # Fetch representative KB chunks
    kb = bq.get_knowledge_base(body.kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")

    rows = bq._run(
        f"""SELECT content FROM `{bq.project}.{bq.dataset}.document_chunks` dc
            JOIN `{bq.project}.{bq.dataset}.documents` d ON dc.document_id = d.document_id
            WHERE '{body.kb_id}' IN UNNEST(d.kb_ids)
            ORDER BY RAND() LIMIT 30"""
    )
    if not rows:
        raise HTTPException(status_code=400, detail="No document chunks found in this knowledge base")

    chunks = [r["content"] for r in rows]
    qt_values = [qt.value for qt in body.question_types]

    try:
        generated = vertex.generate_questions_from_chunks(
            chunks=chunks,
            topic=body.topic,
            num_questions=body.num_questions,
            question_types=qt_values,
            difficulty=body.difficulty,
        )
    except ValueError as e:
        raise HTTPException(status_code=502, detail=f"AI generation failed: {e}")

    # Get current max order_index
    existing = bq.list_questions(questionnaire_id)
    start_index = max((q["order_index"] for q in existing), default=-1) + 1

    created: List[QuestionOut] = []
    for i, gen_q in enumerate(generated):
        # Fetch chunk IDs used (approximate — based on semantic similarity)
        neighbor_ids = vertex.search_similar_chunks(gen_q.get("question_text", ""), top_k=3)
        source_chunk_ids = [n[0] for n in neighbor_ids]

        data = {
            "questionnaire_id": questionnaire_id,
            "question_text": gen_q.get("question_text", ""),
            "question_type": gen_q.get("question_type", "free_text"),
            "is_required": gen_q.get("is_required", True),
            "order_index": start_index + i,
            "section": gen_q.get("section"),
            "help_text": gen_q.get("help_text"),
            "options": gen_q.get("options", {}),
            "ai_generated": True,
            "source_chunk_ids": source_chunk_ids,
        }
        q_id = bq.create_question(data)
        row = bq._run(
            f"SELECT * FROM `{bq.project}.{bq.dataset}.questions` WHERE question_id = '{q_id}'"
        )
        created.append(QuestionOut(**row[0]))

    # Update total_questions count
    bq.client.query(
        f"UPDATE `{bq.project}.{bq.dataset}.questionnaires` "
        f"SET total_questions = (SELECT COUNT(*) FROM `{bq.project}.{bq.dataset}.questions` "
        f"WHERE questionnaire_id = '{questionnaire_id}'), "
        f"updated_at = CURRENT_TIMESTAMP() "
        f"WHERE questionnaire_id = '{questionnaire_id}'"
    ).result()

    bq.log_event(
        "QUESTIONS_AI_GENERATED",
        user_id=current_user.user_id,
        resource_id=questionnaire_id,
        details={"count": len(created), "kb_id": body.kb_id},
    )
    return created
