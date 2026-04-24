##############################################################################
# backend/notifications/main.py
# Cloud Run service: Pub/Sub push consumer → sends emails via SendGrid
##############################################################################
from __future__ import annotations

import base64
import json
import logging
import os
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional

import google.cloud.logging
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from shared.config import get_settings
from shared.models import HealthResponse

try:
    google.cloud.logging.Client().setup_logging()
except Exception:
    logging.basicConfig(level=logging.INFO)

logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting KB Notifications Service — env=%s", settings.environment)
    yield


app = FastAPI(
    title="KB Notifications Service",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
)


# ─────────────────────────────────────────────────────────────────────────────
# Email sending via SendGrid
# ─────────────────────────────────────────────────────────────────────────────

def _send_email(to: str, subject: str, html_body: str) -> bool:
    """Send an email via SendGrid. Returns True on success."""
    api_key = settings.sendgrid_api_key
    if not api_key:
        logger.warning("SENDGRID_API_KEY not set — skipping email to %s", to)
        return False

    try:
        import sendgrid  # noqa: PLC0415
        from sendgrid.helpers.mail import Mail  # noqa: PLC0415

        message = Mail(
            from_email=settings.from_email,
            to_emails=to,
            subject=subject,
            html_content=html_body,
        )
        sg = sendgrid.SendGridAPIClient(api_key=api_key)
        response = sg.send(message)
        logger.info("Email sent to %s — status %d", to, response.status_code)
        return response.status_code in (200, 202)
    except Exception as exc:
        logger.error("Failed to send email to %s: %s", to, exc)
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Event handlers
# ─────────────────────────────────────────────────────────────────────────────

def _handle_questionnaire_assigned(payload: Dict[str, Any]) -> None:
    """Send assignment notification email."""
    email = payload.get("user_email")
    name  = payload.get("user_name") or "there"
    title = payload.get("questionnaire_title", "questionnaire")
    due   = payload.get("due_date")

    if not email:
        return

    due_line = f"<p><strong>Due by:</strong> {due}</p>" if due else ""
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:auto">
      <h2 style="color:#DA291C">New Questionnaire Assigned</h2>
      <p>Hi {name},</p>
      <p>You have been assigned a new questionnaire on the Knowledge Base Platform:</p>
      <p style="font-size:1.1em;font-weight:bold;color:#27251F">{title}</p>
      {due_line}
      <p>Please log in to the platform to complete it.</p>
      <hr style="border:none;border-top:1px solid #eee">
      <p style="font-size:0.8em;color:#888">KB Questionnaire Platform</p>
    </div>
    """
    _send_email(email, f"New questionnaire assigned: {title}", html)


def _handle_assignment_completed(payload: Dict[str, Any]) -> None:
    """Notify admins that a user submitted their questionnaire."""
    # This event is informational — logged, optionally email an admin list
    logger.info(
        "Assignment completed: user=%s questionnaire=%s completion=%.1f%%",
        payload.get("user_email"),
        payload.get("questionnaire_id"),
        payload.get("completion_pct", 0),
    )
    # If you want to email a fixed admin address, set ADMIN_NOTIFY_EMAIL env var
    admin_email = os.environ.get("ADMIN_NOTIFY_EMAIL")
    if admin_email:
        user   = payload.get("user_email", "A user")
        q_id   = payload.get("questionnaire_id", "?")
        pct    = payload.get("completion_pct", 100)
        html   = f"""
        <div style="font-family:Arial,sans-serif;max-width:600px;margin:auto">
          <h2>Questionnaire Submitted</h2>
          <p><strong>{user}</strong> has submitted questionnaire
             <code>{q_id}</code> with <strong>{pct:.0f}%</strong> completion.</p>
        </div>
        """
        _send_email(admin_email, f"Submission received from {user}", html)


def _handle_reminder(payload: Dict[str, Any]) -> None:
    """Send a reminder email for an incomplete assignment."""
    email = payload.get("user_email")
    name  = payload.get("user_name") or "there"
    title = payload.get("questionnaire_title", "questionnaire")
    due   = payload.get("due_date")
    pct   = payload.get("completion_pct", 0)

    if not email:
        return

    due_line = f"<p><strong>Due by:</strong> {due}</p>" if due else ""
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:auto">
      <h2 style="color:#DA291C">Reminder: Questionnaire Due</h2>
      <p>Hi {name},</p>
      <p>This is a friendly reminder that you have a pending questionnaire:</p>
      <p style="font-size:1.1em;font-weight:bold;color:#27251F">{title}</p>
      {due_line}
      <p>Your current progress: <strong>{pct:.0f}%</strong></p>
      <p>Please log in to the platform to complete it as soon as possible.</p>
      <hr style="border:none;border-top:1px solid #eee">
      <p style="font-size:0.8em;color:#888">KB Questionnaire Platform</p>
    </div>
    """
    _send_email(email, f"Reminder: Please complete '{title}'", html)


# ─────────────────────────────────────────────────────────────────────────────
# Event router
# ─────────────────────────────────────────────────────────────────────────────

EVENT_HANDLERS = {
    "QUESTIONNAIRE_ASSIGNED": _handle_questionnaire_assigned,
    "ASSIGNMENT_COMPLETED":   _handle_assignment_completed,
    "QUESTIONNAIRE_REMINDER": _handle_reminder,
}


# ─────────────────────────────────────────────────────────────────────────────
# Pub/Sub push endpoint
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/notify", status_code=status.HTTP_200_OK)
async def handle_notification(request: Request):
    """
    Receives Pub/Sub push messages from the notifications topic.
    Always returns HTTP 200 to prevent Pub/Sub retry storms.
    """
    try:
        body         = await request.json()
        envelope     = body.get("message", {})
        data_b64     = envelope.get("data", "")
        if not data_b64:
            return JSONResponse({"status": "ack_empty"})

        payload: Dict[str, Any] = json.loads(
            base64.b64decode(data_b64).decode("utf-8")
        )
        event_type = payload.get("event_type", "UNKNOWN")
        logger.info("Received notification event: %s", event_type)

        handler = EVENT_HANDLERS.get(event_type)
        if handler:
            handler(payload)
        else:
            logger.warning("No handler for event type: %s", event_type)

        return JSONResponse({"status": "ok", "event_type": event_type})

    except Exception as exc:
        logger.exception("Notification processing error: %s", exc)
        return JSONResponse({"status": "error", "detail": str(exc)})


@app.get("/health", response_model=HealthResponse)
def health():
    return HealthResponse(service="kb-notifications", environment=settings.environment)
