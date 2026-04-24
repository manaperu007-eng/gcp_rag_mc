##############################################################################
# backend/api/routers/assignments.py
# Assign questionnaires to users, list assignments, submit completed work
##############################################################################
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException, status
from google.cloud import pubsub_v1

from api.core.dependencies import AdminReviewer, BQDep, CurrentUser, SettingsDep
from shared.models import AssignmentOut, AssignUsersRequest, MessageResponse

router = APIRouter(prefix="/assignments", tags=["assignments"])


def _publish_event(topic: str, event_type: str, payload: dict, project_id: str) -> None:
    """Fire-and-forget Pub/Sub event."""
    if not topic:
        return
    try:
        publisher = pubsub_v1.PublisherClient()
        data = json.dumps({"event_type": event_type, **payload}).encode()
        publisher.publish(topic, data)
    except Exception:
        pass  # Non-critical — do not fail the request


# ─────────────────────────────────────────────────────────────────────────────
# Admin: Assign users to a questionnaire
# ─────────────────────────────────────────────────────────────────────────────

@router.post("", response_model=List[AssignmentOut], status_code=status.HTTP_201_CREATED)
def assign_users(
    body: AssignUsersRequest,
    current_user: CurrentUser,
    bq: BQDep,
    settings: SettingsDep,
    _: None = AdminReviewer,
):
    q = bq.get_questionnaire(body.questionnaire_id)
    if not q:
        raise HTTPException(status_code=404, detail="Questionnaire not found")
    if q["status"] != "published":
        raise HTTPException(status_code=400, detail="Can only assign published questionnaires")

    created: List[AssignmentOut] = []
    for user_id in body.user_ids:
        user = bq.get_user(user_id)
        if not user:
            continue  # Skip missing users

        # Skip if already assigned
        existing = bq.get_user_assignment(user_id, body.questionnaire_id)
        if existing:
            continue

        a_data = {
            "questionnaire_id": body.questionnaire_id,
            "user_id": user_id,
            "user_email": user.get("email"),
            "user_name": user.get("display_name"),
            "region": user.get("region"),
            "country": user.get("country"),
            "city": user.get("city"),
            "department": user.get("department"),
            "due_date": body.due_date.isoformat() if body.due_date else None,
        }
        a_id = bq.create_assignment(a_data)

        if body.send_notification:
            _publish_event(
                settings.notifications_topic,
                "QUESTIONNAIRE_ASSIGNED",
                {
                    "user_email": user.get("email"),
                    "user_name": user.get("display_name"),
                    "questionnaire_title": q.get("title"),
                    "due_date": body.due_date.isoformat() if body.due_date else None,
                    "assignment_id": a_id,
                },
                settings.project_id,
            )

        created.append(AssignmentOut(**bq.get_assignment(a_id)))

    bq.log_event(
        "USERS_ASSIGNED",
        user_id=current_user.user_id,
        resource_id=body.questionnaire_id,
        details={"count": len(created)},
    )
    return created


# ─────────────────────────────────────────────────────────────────────────────
# User: List my assignments
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/my", response_model=List[AssignmentOut])
def my_assignments(current_user: CurrentUser, bq: BQDep):
    rows = bq.list_user_assignments(current_user.user_id)
    return [AssignmentOut(**r) for r in rows]


@router.get("/{assignment_id}", response_model=AssignmentOut)
def get_assignment(assignment_id: str, current_user: CurrentUser, bq: BQDep):
    a = bq.get_assignment(assignment_id)
    if not a:
        raise HTTPException(status_code=404, detail="Assignment not found")

    from shared.models import UserRole
    if current_user.role == UserRole.RESPONDENT and a["user_id"] != current_user.user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    return AssignmentOut(**a)


# ─────────────────────────────────────────────────────────────────────────────
# User: Get next unanswered question for this assignment
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/{assignment_id}/next-question")
def next_question(assignment_id: str, current_user: CurrentUser, bq: BQDep):
    """Returns the next unanswered question for the respondent."""
    a = bq.get_assignment(assignment_id)
    if not a:
        raise HTTPException(status_code=404, detail="Assignment not found")
    if a["user_id"] != current_user.user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    if a["status"] == "submitted":
        return {"complete": True, "next_question": None}

    answered_ids = set(bq.get_answered_question_ids(assignment_id))
    questions = bq.list_questions(a["questionnaire_id"])
    unanswered = [q for q in questions if q["question_id"] not in answered_ids]

    if not unanswered:
        return {"complete": True, "next_question": None}

    from shared.models import QuestionOut
    return {"complete": False, "next_question": QuestionOut(**unanswered[0])}


# ─────────────────────────────────────────────────────────────────────────────
# User: Submit the completed assignment
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/{assignment_id}/submit", response_model=AssignmentOut)
def submit_assignment(
    assignment_id: str,
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
        raise HTTPException(status_code=400, detail="Already submitted")

    # Calculate final completion
    questions = bq.list_questions(a["questionnaire_id"])
    answered_ids = set(bq.get_answered_question_ids(assignment_id))
    required_ids = {q["question_id"] for q in questions if q.get("is_required")}
    unanswered_required = required_ids - answered_ids

    if unanswered_required:
        raise HTTPException(
            status_code=400,
            detail=f"{len(unanswered_required)} required question(s) are still unanswered",
        )

    total = len(questions)
    completion_pct = (len(answered_ids) / total * 100) if total else 100.0
    bq.update_assignment_completion(assignment_id, completion_pct, "submitted")

    # Publish completion event
    _publish_event(
        settings.questionnaire_events_topic,
        "ASSIGNMENT_SUBMITTED",
        {"assignment_id": assignment_id, "questionnaire_id": a["questionnaire_id"], "user_id": a["user_id"]},
        settings.project_id,
    )

    # Notify admins
    _publish_event(
        settings.notifications_topic,
        "ASSIGNMENT_COMPLETED",
        {
            "user_email": current_user.email,
            "user_name": current_user.display_name,
            "questionnaire_id": a["questionnaire_id"],
            "completion_pct": completion_pct,
        },
        settings.project_id,
    )

    bq.log_event(
        "ASSIGNMENT_SUBMITTED",
        user_id=current_user.user_id,
        resource_id=assignment_id,
        details={"completion_pct": completion_pct},
    )
    return AssignmentOut(**bq.get_assignment(assignment_id))
