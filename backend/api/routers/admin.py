##############################################################################
# backend/api/routers/admin.py
# Admin: users, reports, filtering, export, send reminders
##############################################################################
from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from google.cloud import storage as gcs

from api.core.dependencies import AdminOnly, AdminReviewer, BQDep, CurrentUser, SettingsDep
from shared.models import (
    AssignmentOut,
    CompletionReport,
    MessageResponse,
    OverdueAssignment,
    ReportFilters,
    UserCreate,
    UserOut,
    UserRole,
)

router = APIRouter(prefix="/admin", tags=["admin"])


# ─────────────────────────────────────────────────────────────────────────────
# User Management
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/users", response_model=List[UserOut])
def list_users(
    current_user: CurrentUser,
    bq: BQDep,
    role: Optional[str] = Query(None),
    _: None = AdminReviewer,
):
    rows = bq.list_users(role=role)
    return [UserOut(**r) for r in rows]


@router.get("/users/{user_id}", response_model=UserOut)
def get_user(user_id: str, current_user: CurrentUser, bq: BQDep, _: None = AdminReviewer):
    user = bq.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return UserOut(**user)


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(body: UserCreate, current_user: CurrentUser, bq: BQDep, _: None = AdminOnly):
    from api.core.security import hash_password
    if bq.get_user_by_email(body.email):
        raise HTTPException(status_code=400, detail="Email already registered")
    user_dict = body.model_dump()
    if body.password:
        user_dict["password_hash"] = hash_password(body.password)
    user_dict.pop("password", None)
    user_id = bq.create_user(user_dict)
    bq.log_event("ADMIN_CREATED_USER", user_id=current_user.user_id, resource_id=user_id)
    return UserOut(**bq.get_user(user_id))


@router.patch("/users/{user_id}/role", response_model=UserOut)
def change_user_role(
    user_id: str,
    role: UserRole,
    current_user: CurrentUser,
    bq: BQDep,
    _: None = AdminOnly,
):
    user = bq.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    bq.client.query(
        f"UPDATE `{bq.project}.{bq.dataset}.users` SET role = '{role.value}' WHERE user_id = '{user_id}'"
    ).result()
    bq.log_event("USER_ROLE_CHANGED", user_id=current_user.user_id, resource_id=user_id, details={"new_role": role.value})
    return UserOut(**bq.get_user(user_id))


@router.delete("/users/{user_id}", response_model=MessageResponse)
def deactivate_user(user_id: str, current_user: CurrentUser, bq: BQDep, _: None = AdminOnly):
    bq.client.query(
        f"UPDATE `{bq.project}.{bq.dataset}.users` SET is_active = FALSE WHERE user_id = '{user_id}'"
    ).result()
    bq.log_event("USER_DEACTIVATED", user_id=current_user.user_id, resource_id=user_id)
    return MessageResponse(message=f"User {user_id} deactivated")


# ─────────────────────────────────────────────────────────────────────────────
# Completion Reports
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/reports/completion", response_model=List[CompletionReport])
def completion_report(
    filters: ReportFilters,
    current_user: CurrentUser,
    bq: BQDep,
    _: None = AdminReviewer,
):
    """
    Returns questionnaire completion rates with optional filters for
    questionnaire_id, region, country, city, department.
    """
    rows = bq.get_completion_report(filters.model_dump(exclude_none=True))
    return [CompletionReport(**r) for r in rows]


@router.get("/reports/overdue", response_model=List[OverdueAssignment])
def overdue_report(
    current_user: CurrentUser,
    bq: BQDep,
    region: Optional[str] = Query(None),
    country: Optional[str] = Query(None),
    department: Optional[str] = Query(None),
    _: None = AdminReviewer,
):
    """Returns all overdue assignments with geographic filtering."""
    filters = {k: v for k, v in {"region": region, "country": country, "department": department}.items() if v}
    rows = bq.get_overdue_assignments(filters)
    return [OverdueAssignment(**r) for r in rows]


@router.get("/reports/response-summary/{questionnaire_id}")
def response_summary(
    questionnaire_id: str,
    current_user: CurrentUser,
    bq: BQDep,
    _: None = AdminReviewer,
):
    """Per-question answer statistics for a questionnaire."""
    rows = bq.get_response_summary(questionnaire_id)
    return rows


# ─────────────────────────────────────────────────────────────────────────────
# Export Reports to CSV
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/reports/export/completion")
def export_completion_csv(
    filters: ReportFilters,
    current_user: CurrentUser,
    bq: BQDep,
    settings: SettingsDep,
    _: None = AdminReviewer,
):
    """Stream a CSV export of the completion report."""
    rows = bq.get_completion_report(filters.model_dump(exclude_none=True))
    if not rows:
        raise HTTPException(status_code=404, detail="No data found")

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=rows[0].keys())
    writer.writeheader()
    writer.writerows(rows)
    output.seek(0)

    filename = f"completion_report_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"

    # Optionally save to GCS
    if settings.reports_bucket:
        try:
            gcs_client = gcs.Client(project=settings.project_id)
            blob = gcs_client.bucket(settings.reports_bucket).blob(f"exports/{current_user.user_id}/{filename}")
            blob.upload_from_string(output.getvalue(), content_type="text/csv")
        except Exception:
            pass
        output.seek(0)

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.post("/reports/export/overdue")
def export_overdue_csv(
    current_user: CurrentUser,
    bq: BQDep,
    region: Optional[str] = Query(None),
    country: Optional[str] = Query(None),
    department: Optional[str] = Query(None),
    _: None = AdminReviewer,
):
    filters = {k: v for k, v in {"region": region, "country": country, "department": department}.items() if v}
    rows = bq.get_overdue_assignments(filters)
    if not rows:
        raise HTTPException(status_code=404, detail="No overdue assignments found")

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=rows[0].keys())
    writer.writeheader()
    writer.writerows(rows)
    output.seek(0)
    filename = f"overdue_report_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ─────────────────────────────────────────────────────────────────────────────
# Send Reminders
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/remind/{questionnaire_id}", response_model=MessageResponse)
def send_reminders(
    questionnaire_id: str,
    current_user: CurrentUser,
    bq: BQDep,
    settings: SettingsDep,
    _: None = AdminReviewer,
):
    """Publish reminder notifications for all incomplete assignments."""
    from google.cloud import pubsub_v1
    import json

    rows = bq._run(
        f"""SELECT ua.*, q.title FROM `{bq.project}.{bq.dataset}.user_assignments` ua
            JOIN `{bq.project}.{bq.dataset}.questionnaires` q ON ua.questionnaire_id = q.questionnaire_id
            WHERE ua.questionnaire_id = '{questionnaire_id}'
              AND ua.status NOT IN ('submitted', 'reviewed')"""
    )

    if not rows:
        return MessageResponse(message="No pending assignments found")

    sent = 0
    if settings.notifications_topic:
        publisher = pubsub_v1.PublisherClient()
        for row in rows:
            payload = json.dumps({
                "event_type": "QUESTIONNAIRE_REMINDER",
                "user_email": row.get("user_email"),
                "user_name": row.get("user_name"),
                "questionnaire_title": row.get("title"),
                "due_date": str(row.get("due_date")),
                "completion_pct": row.get("completion_pct", 0),
            }).encode()
            try:
                publisher.publish(settings.notifications_topic, payload)
                sent += 1
            except Exception:
                pass

    bq.log_event(
        "REMINDERS_SENT",
        user_id=current_user.user_id,
        resource_id=questionnaire_id,
        details={"sent_count": sent},
    )
    return MessageResponse(message=f"Sent {sent} reminder(s)")


# ─────────────────────────────────────────────────────────────────────────────
# Dashboard Stats
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/dashboard/stats")
def dashboard_stats(current_user: CurrentUser, bq: BQDep, _: None = AdminReviewer):
    """High-level platform statistics for the admin dashboard."""
    stats = {}
    for key, query in {
        "total_users": f"SELECT COUNT(*) as c FROM `{bq.project}.{bq.dataset}.users` WHERE is_active = TRUE",
        "total_questionnaires": f"SELECT COUNT(*) as c FROM `{bq.project}.{bq.dataset}.questionnaires` WHERE status = 'published'",
        "total_documents": f"SELECT COUNT(*) as c FROM `{bq.project}.{bq.dataset}.documents` WHERE status = 'ready'",
        "total_assignments": f"SELECT COUNT(*) as c FROM `{bq.project}.{bq.dataset}.user_assignments`",
        "submitted_assignments": f"SELECT COUNT(*) as c FROM `{bq.project}.{bq.dataset}.user_assignments` WHERE status = 'submitted'",
        "overdue_assignments": f"SELECT COUNT(*) as c FROM `{bq.project}.{bq.dataset}.vw_overdue_assignments`",
    }.items():
        try:
            row = bq._run(query)
            stats[key] = row[0]["c"] if row else 0
        except Exception:
            stats[key] = 0

    stats["completion_rate_pct"] = round(
        stats["submitted_assignments"] / max(stats["total_assignments"], 1) * 100, 1
    )
    return stats
