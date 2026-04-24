##############################################################################
# backend/api/routers/chat.py
# Conversational questionnaire interface powered by Gemini
##############################################################################
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, status
from google.cloud import firestore

from api.core.dependencies import BQDep, CurrentUser, SettingsDep, VertexDep
from shared.models import (
    ChatMessage,
    ChatSessionCreate,
    ChatSessionOut,
    ChatTurnRequest,
    ChatTurnResponse,
    MessageResponse,
)

router = APIRouter(prefix="/chat", tags=["chat"])
logger = logging.getLogger(__name__)

_FS_COLLECTION = "chat_sessions"


# ─────────────────────────────────────────────────────────────────────────────
# Firestore session helpers
# ─────────────────────────────────────────────────────────────────────────────

def _get_fs_client(settings) -> firestore.Client:
    return firestore.Client(
        project=settings.project_id,
        database=settings.firestore_db,
    )


def _session_ref(client: firestore.Client, session_id: str):
    return client.collection(_FS_COLLECTION).document(session_id)


def _save_session(client: firestore.Client, session: Dict[str, Any]) -> None:
    """Upsert the session document in Firestore."""
    ref = _session_ref(client, session["session_id"])
    ref.set(session)


def _load_session(client: firestore.Client, session_id: str) -> Optional[Dict[str, Any]]:
    """Load a session document from Firestore; returns None if not found."""
    doc = _session_ref(client, session_id).get()
    return doc.to_dict() if doc.exists else None


# ─────────────────────────────────────────────────────────────────────────────
# Create chat session
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/sessions",
    response_model=ChatSessionOut,
    status_code=status.HTTP_201_CREATED,
)
def create_session(
    body: ChatSessionCreate,
    current_user: CurrentUser,
    bq: BQDep,
    settings: SettingsDep,
):
    """
    Start a new chat session for a questionnaire.
    The user must have an active assignment for the questionnaire.
    """
    # Verify the user has an assignment
    assignment = bq.get_user_assignment(current_user.user_id, body.questionnaire_id)
    if not assignment:
        raise HTTPException(
            status_code=403,
            detail="You are not assigned to this questionnaire",
        )
    if assignment.get("status") == "submitted":
        raise HTTPException(
            status_code=400,
            detail="This assignment has already been submitted",
        )

    # Find the first unanswered question
    answered_ids = set(bq.get_answered_question_ids(assignment["assignment_id"]))
    questions = bq.list_questions(body.questionnaire_id)
    unanswered = [q for q in questions if q["question_id"] not in answered_ids]
    first_question_id = unanswered[0]["question_id"] if unanswered else None

    now = datetime.now(timezone.utc).isoformat()
    session_id = str(uuid.uuid4())
    session: Dict[str, Any] = {
        "session_id": session_id,
        "questionnaire_id": body.questionnaire_id,
        "assignment_id": assignment["assignment_id"],
        "user_id": current_user.user_id,
        "messages": [],
        "current_question_id": first_question_id,
        "created_at": now,
        "last_active": now,
    }

    # Welcome message with current question
    if first_question_id:
        q = next(q for q in questions if q["question_id"] == first_question_id)
        welcome = _build_question_prompt(q, questions)
        session["messages"].append({
            "role": "assistant",
            "content": welcome,
            "timestamp": now,
        })

    fs = _get_fs_client(settings)
    _save_session(fs, session)

    bq.log_event(
        "CHAT_SESSION_CREATED",
        user_id=current_user.user_id,
        resource_id=session_id,
        details={"questionnaire_id": body.questionnaire_id},
    )

    return _to_session_out(session)


# ─────────────────────────────────────────────────────────────────────────────
# Get session state
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/sessions/{session_id}", response_model=ChatSessionOut)
def get_session(session_id: str, current_user: CurrentUser, settings: SettingsDep):
    fs = _get_fs_client(settings)
    session = _load_session(fs, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session["user_id"] != current_user.user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    return _to_session_out(session)


# ─────────────────────────────────────────────────────────────────────────────
# Send a chat message
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/sessions/{session_id}/turn", response_model=ChatTurnResponse)
def chat_turn(
    session_id: str,
    body: ChatTurnRequest,
    current_user: CurrentUser,
    bq: BQDep,
    vertex: VertexDep,
    settings: SettingsDep,
):
    """
    Process one conversational turn:
      1. Append user message.
      2. If there is a current question, try to interpret the message as an answer.
      3. If captured, save the answer and advance to the next question.
      4. Generate and return the assistant reply.
    """
    fs = _get_fs_client(settings)
    session = _load_session(fs, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session["user_id"] != current_user.user_id:
        raise HTTPException(status_code=403, detail="Access denied")

    now = datetime.now(timezone.utc).isoformat()
    session["messages"].append({"role": "user", "content": body.message, "timestamp": now})

    questions = bq.list_questions(session["questionnaire_id"])
    q_map = {q["question_id"]: q for q in questions}
    current_qid = session.get("current_question_id")

    question_answered_id: Optional[str] = None
    next_question_id: Optional[str] = None
    is_complete = False
    assistant_reply: str

    if not current_qid:
        # No more questions
        is_complete = True
        assistant_reply = (
            "You have answered all questions in this questionnaire. "
            "Please submit your assignment when you're ready."
        )
    else:
        current_q = q_map.get(current_qid)
        if not current_q:
            raise HTTPException(status_code=500, detail="Session state error: question not found")

        # Try to interpret the user message as an answer
        interpretation = vertex.interpret_chat_answer(
            question_text=current_q["question_text"],
            question_type=current_q["question_type"],
            options=current_q.get("options"),
            user_message=body.message,
        )

        if interpretation.get("captured") and interpretation.get("confidence") != "low":
            # Save the captured answer
            _save_chat_answer(bq, session, current_q, interpretation, settings)
            question_answered_id = current_qid

            # Advance to the next unanswered question
            answered_ids = set(bq.get_answered_question_ids(session["assignment_id"]))
            unanswered = [q for q in questions if q["question_id"] not in answered_ids]

            if unanswered:
                next_qid = unanswered[0]["question_id"]
                session["current_question_id"] = next_qid
                next_question_id = next_qid
                assistant_reply = (
                    f"✓ Got it! Moving on.\n\n"
                    + _build_question_prompt(unanswered[0], questions)
                )
            else:
                session["current_question_id"] = None
                is_complete = True
                assistant_reply = (
                    "🎉 You've answered all the questions! "
                    "When you're ready, click **Submit** to finalise your submission."
                )
        else:
            # Ask for clarification
            clarification = interpretation.get(
                "clarification_needed",
                "I didn't quite understand. Could you rephrase your answer?",
            )
            assistant_reply = clarification

    session["messages"].append(
        {"role": "assistant", "content": assistant_reply, "timestamp": now}
    )
    session["last_active"] = now
    _save_session(fs, session)

    return ChatTurnResponse(
        session_id=session_id,
        assistant_message=assistant_reply,
        question_answered=question_answered_id,
        next_question_id=next_question_id,
        is_complete=is_complete,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Delete / end session
# ─────────────────────────────────────────────────────────────────────────────

@router.delete("/sessions/{session_id}", response_model=MessageResponse)
def delete_session(session_id: str, current_user: CurrentUser, settings: SettingsDep):
    fs = _get_fs_client(settings)
    session = _load_session(fs, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session["user_id"] != current_user.user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    _session_ref(fs, session_id).delete()
    return MessageResponse(message="Session ended")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _build_question_prompt(question: Dict[str, Any], all_questions: List[Dict[str, Any]]) -> str:
    """Build a human-friendly prompt for a question."""
    total = len(all_questions)
    position = next(
        (i + 1 for i, q in enumerate(all_questions) if q["question_id"] == question["question_id"]),
        "?",
    )
    lines: List[str] = [f"**Question {position} of {total}**"]

    section = question.get("section")
    if section:
        lines.append(f"*Section: {section}*")

    lines.append(f"\n{question['question_text']}")

    help_text = question.get("help_text")
    if help_text:
        lines.append(f"_{help_text}_")

    options = question.get("options") or {}
    qt = question.get("question_type", "free_text")

    if qt in ("multiple_choice", "multi_select") and options.get("choices"):
        choices_str = "\n".join(f"  • {c}" for c in options["choices"])
        label = "Choose one" if qt == "multiple_choice" else "Choose all that apply"
        lines.append(f"\n{label}:\n{choices_str}")

    elif qt == "true_false":
        lines.append("\nPlease answer **True** or **False**.")

    elif qt == "rating":
        min_r = options.get("min_rating", 1)
        max_r = options.get("max_rating", 5)
        labels = options.get("rating_labels", [])
        scale = f"{min_r}–{max_r}"
        if labels:
            scale += f" ({labels[0]} → {labels[-1]})"
        lines.append(f"\nRating scale: {scale}")

    elif qt == "date":
        lines.append("\nPlease provide a date (e.g. 2024-06-15).")

    elif qt == "number":
        lines.append("\nPlease provide a numeric value.")

    elif qt == "file_upload":
        allowed = options.get("allowed_file_types", [])
        msg = "Please upload a file."
        if allowed:
            msg += f" Accepted types: {', '.join(allowed)}."
        lines.append(f"\n{msg}")

    if question.get("is_required"):
        lines.append("\n*(Required)*")

    return "\n".join(lines)


def _save_chat_answer(
    bq,
    session: Dict[str, Any],
    question: Dict[str, Any],
    interpretation: Dict[str, Any],
    settings,
) -> None:
    """Persist an interpreted chat answer to BigQuery via upsert."""
    from shared.models import Channel  # noqa: PLC0415

    response_data = {
        "assignment_id": session["assignment_id"],
        "questionnaire_id": session["questionnaire_id"],
        "question_id": question["question_id"],
        "user_id": session["user_id"],
        "question_type": question["question_type"],
        "answer_text": interpretation.get("answer_text"),
        "answer_boolean": interpretation.get("answer_boolean"),
        "answer_number": interpretation.get("answer_number"),
        "answer_choices": interpretation.get("answer_choices", []),
        "answer_date": None,
        "file_uploads": [],
        "ai_hint_used": False,
        "channel": Channel.CHAT.value,
        "is_draft": False,
    }
    bq.upsert_response(session["assignment_id"], question["question_id"], response_data)


def _to_session_out(session: Dict[str, Any]) -> ChatSessionOut:
    """Convert a raw Firestore session dict to a ChatSessionOut model."""
    messages = [
        ChatMessage(
            role=m["role"],
            content=m["content"],
            timestamp=datetime.fromisoformat(m["timestamp"]),
        )
        for m in session.get("messages", [])
    ]
    return ChatSessionOut(
        session_id=session["session_id"],
        questionnaire_id=session["questionnaire_id"],
        user_id=session["user_id"],
        messages=messages,
        current_question_id=session.get("current_question_id"),
        created_at=datetime.fromisoformat(session["created_at"]),
        last_active=datetime.fromisoformat(session["last_active"]),
    )
