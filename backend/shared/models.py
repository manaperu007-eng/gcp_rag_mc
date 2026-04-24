##############################################################################
# backend/shared/models.py
# Pydantic models shared across all services
##############################################################################
from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field, field_validator


# ─────────────────────────────────────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────────────────────────────────────

class DocumentStatus(str, Enum):
    PENDING    = "pending"
    PROCESSING = "processing"
    READY      = "ready"
    FAILED     = "failed"

class FileType(str, Enum):
    PDF  = "pdf"
    DOCX = "docx"
    XLSX = "xlsx"
    DOC  = "doc"
    XLS  = "xls"

class QuestionnaireStatus(str, Enum):
    DRAFT     = "draft"
    PUBLISHED = "published"
    ARCHIVED  = "archived"

class QuestionType(str, Enum):
    FREE_TEXT       = "free_text"
    FILE_UPLOAD     = "file_upload"
    TRUE_FALSE      = "true_false"
    RATING          = "rating"
    MULTIPLE_CHOICE = "multiple_choice"
    MULTI_SELECT    = "multi_select"
    DATE            = "date"
    NUMBER          = "number"

class AssignmentStatus(str, Enum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    SUBMITTED   = "submitted"
    REVIEWED    = "reviewed"

class UserRole(str, Enum):
    ADMIN      = "admin"
    REVIEWER   = "reviewer"
    RESPONDENT = "respondent"

class Channel(str, Enum):
    WEB  = "web"
    CHAT = "chat"


# ─────────────────────────────────────────────────────────────────────────────
# User Models
# ─────────────────────────────────────────────────────────────────────────────

class UserBase(BaseModel):
    email: str
    display_name: Optional[str] = None
    role: UserRole = UserRole.RESPONDENT
    region: Optional[str] = None
    country: Optional[str] = None
    city: Optional[str] = None
    department: Optional[str] = None

class UserCreate(UserBase):
    password: Optional[str] = None  # None for SSO users

class UserOut(UserBase):
    user_id: str
    is_active: bool
    created_at: datetime
    last_login_at: Optional[datetime] = None

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


# ─────────────────────────────────────────────────────────────────────────────
# Document Models
# ─────────────────────────────────────────────────────────────────────────────

class DocumentBase(BaseModel):
    title: Optional[str] = None
    author: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    category: Optional[str] = None
    kb_ids: List[str] = Field(default_factory=list)

class DocumentCreate(DocumentBase):
    file_name: str
    file_type: FileType

class DocumentOut(DocumentBase):
    document_id: str
    file_name: str
    file_type: FileType
    gcs_uri: str
    processed_uri: Optional[str] = None
    language: Optional[str] = None
    page_count: Optional[int] = None
    word_count: Optional[int] = None
    status: DocumentStatus
    error_message: Optional[str] = None
    chunk_count: Optional[int] = None
    ingested_at: datetime
    processed_at: Optional[datetime] = None
    uploaded_by: Optional[str] = None

class DocumentUploadRequest(BaseModel):
    file_name: str
    file_type: FileType
    title: Optional[str] = None
    category: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    kb_ids: List[str] = Field(default_factory=list)

class DocumentUploadResponse(BaseModel):
    document_id: str
    upload_url: str          # Signed GCS URL for direct upload
    upload_headers: Dict[str, str] = Field(default_factory=dict)
    expires_at: datetime


# ─────────────────────────────────────────────────────────────────────────────
# Knowledge Base Models
# ─────────────────────────────────────────────────────────────────────────────

class KnowledgeBaseCreate(BaseModel):
    name: str
    description: Optional[str] = None

class KnowledgeBaseOut(BaseModel):
    kb_id: str
    name: str
    description: Optional[str] = None
    document_count: int = 0
    created_by: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    is_active: bool = True


# ─────────────────────────────────────────────────────────────────────────────
# Question Models
# ─────────────────────────────────────────────────────────────────────────────

class QuestionOptions(BaseModel):
    choices: List[str] = Field(default_factory=list)
    min_rating: Optional[int] = None
    max_rating: Optional[int] = None
    rating_labels: List[str] = Field(default_factory=list)
    allowed_file_types: List[str] = Field(default_factory=list)
    max_file_size_mb: Optional[int] = None

class QuestionCreate(BaseModel):
    question_text: str
    question_type: QuestionType
    is_required: bool = True
    order_index: int
    section: Optional[str] = None
    help_text: Optional[str] = None
    options: Optional[QuestionOptions] = None
    parent_question_id: Optional[str] = None
    kb_context: Optional[str] = None

class QuestionOut(QuestionCreate):
    question_id: str
    questionnaire_id: str
    ai_generated: bool = False
    source_chunk_ids: List[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: Optional[datetime] = None


# ─────────────────────────────────────────────────────────────────────────────
# Questionnaire Models
# ─────────────────────────────────────────────────────────────────────────────

class QuestionnaireCreate(BaseModel):
    title: str
    description: Optional[str] = None
    kb_id: Optional[str] = None
    passing_score: Optional[float] = None
    time_limit_mins: Optional[int] = None
    due_date: Optional[datetime] = None
    geographic_scope: Optional[str] = None    # global | region | country | city
    allowed_regions: List[str] = Field(default_factory=list)

class QuestionnaireOut(QuestionnaireCreate):
    questionnaire_id: str
    version: int = 1
    status: QuestionnaireStatus
    total_questions: Optional[int] = None
    created_by: Optional[str] = None
    created_at: datetime
    published_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

class QuestionnaireWithQuestions(QuestionnaireOut):
    questions: List[QuestionOut] = Field(default_factory=list)

class GenerateQuestionsRequest(BaseModel):
    kb_id: str
    topic: Optional[str] = None
    num_questions: int = Field(10, ge=1, le=100)
    question_types: List[QuestionType] = Field(
        default_factory=lambda: [
            QuestionType.FREE_TEXT,
            QuestionType.TRUE_FALSE,
            QuestionType.MULTIPLE_CHOICE,
            QuestionType.RATING,
        ]
    )
    difficulty: Optional[str] = "medium"  # easy | medium | hard


# ─────────────────────────────────────────────────────────────────────────────
# Assignment Models
# ─────────────────────────────────────────────────────────────────────────────

class AssignUsersRequest(BaseModel):
    questionnaire_id: str
    user_ids: List[str]
    due_date: Optional[datetime] = None
    send_notification: bool = True

class AssignmentOut(BaseModel):
    assignment_id: str
    questionnaire_id: str
    user_id: str
    user_email: Optional[str] = None
    user_name: Optional[str] = None
    region: Optional[str] = None
    country: Optional[str] = None
    city: Optional[str] = None
    department: Optional[str] = None
    status: AssignmentStatus
    completion_pct: float = 0.0
    score: Optional[float] = None
    assigned_at: datetime
    started_at: Optional[datetime] = None
    submitted_at: Optional[datetime] = None
    due_date: Optional[datetime] = None


# ─────────────────────────────────────────────────────────────────────────────
# Response / Answer Models
# ─────────────────────────────────────────────────────────────────────────────

class FileUploadInfo(BaseModel):
    file_id: str
    file_name: str
    gcs_uri: str
    file_size_bytes: Optional[int] = None
    content_type: Optional[str] = None

class AnswerSubmit(BaseModel):
    question_id: str
    answer_text: Optional[str] = None
    answer_boolean: Optional[bool] = None
    answer_number: Optional[float] = None
    answer_choices: List[str] = Field(default_factory=list)
    answer_date: Optional[date] = None
    file_uploads: List[FileUploadInfo] = Field(default_factory=list)
    is_draft: bool = False
    ai_hint_used: bool = False
    channel: Channel = Channel.WEB

class BulkAnswerSubmit(BaseModel):
    assignment_id: str
    answers: List[AnswerSubmit]

class ResponseOut(BaseModel):
    response_id: str
    assignment_id: str
    questionnaire_id: str
    question_id: str
    user_id: str
    question_type: QuestionType
    answer_text: Optional[str] = None
    answer_boolean: Optional[bool] = None
    answer_number: Optional[float] = None
    answer_choices: List[str] = Field(default_factory=list)
    answer_date: Optional[date] = None
    file_uploads: List[FileUploadInfo] = Field(default_factory=list)
    ai_hint_used: bool = False
    channel: Channel = Channel.WEB
    responded_at: datetime
    updated_at: Optional[datetime] = None
    is_draft: bool = False

class FileUploadUrlRequest(BaseModel):
    question_id: str
    assignment_id: str
    file_name: str
    content_type: str

class FileUploadUrlResponse(BaseModel):
    file_id: str
    upload_url: str
    expires_at: datetime


# ─────────────────────────────────────────────────────────────────────────────
# Chat Models
# ─────────────────────────────────────────────────────────────────────────────

class ChatMessage(BaseModel):
    role: str          # "user" | "assistant"
    content: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class ChatSessionCreate(BaseModel):
    questionnaire_id: str

class ChatSessionOut(BaseModel):
    session_id: str
    questionnaire_id: str
    user_id: str
    messages: List[ChatMessage] = Field(default_factory=list)
    current_question_id: Optional[str] = None
    created_at: datetime
    last_active: datetime

class ChatTurnRequest(BaseModel):
    session_id: str
    message: str

class ChatTurnResponse(BaseModel):
    session_id: str
    assistant_message: str
    question_answered: Optional[str] = None   # question_id if an answer was captured
    next_question_id: Optional[str] = None
    is_complete: bool = False


# ─────────────────────────────────────────────────────────────────────────────
# Admin / Reporting Models
# ─────────────────────────────────────────────────────────────────────────────

class CompletionReport(BaseModel):
    questionnaire_title: str
    questionnaire_status: str
    region: Optional[str] = None
    country: Optional[str] = None
    city: Optional[str] = None
    department: Optional[str] = None
    total_assigned: int
    total_submitted: int
    total_not_started: int
    total_in_progress: int
    completion_rate_pct: float
    avg_completion_pct: float
    avg_score: Optional[float] = None
    first_assigned: Optional[datetime] = None
    last_submitted: Optional[datetime] = None

class ReportFilters(BaseModel):
    questionnaire_id: Optional[str] = None
    region: Optional[str] = None
    country: Optional[str] = None
    city: Optional[str] = None
    department: Optional[str] = None
    status: Optional[AssignmentStatus] = None
    from_date: Optional[datetime] = None
    to_date: Optional[datetime] = None

class OverdueAssignment(BaseModel):
    assignment_id: str
    user_id: str
    user_email: Optional[str] = None
    user_name: Optional[str] = None
    region: Optional[str] = None
    country: Optional[str] = None
    department: Optional[str] = None
    questionnaire_title: str
    due_date: datetime
    status: AssignmentStatus
    completion_pct: float
    days_overdue: int


# ─────────────────────────────────────────────────────────────────────────────
# Pagination / Common
# ─────────────────────────────────────────────────────────────────────────────

class PaginatedResponse(BaseModel):
    items: List[Any]
    total: int
    page: int
    page_size: int
    has_next: bool

class HealthResponse(BaseModel):
    status: str = "ok"
    service: str
    environment: str
    version: str = "1.0.0"

class MessageResponse(BaseModel):
    message: str
    detail: Optional[Any] = None

class KBSearchRequest(BaseModel):
    query: str
    kb_id: Optional[str] = None
    top_k: int = Field(5, ge=1, le=20)

class KBSearchResult(BaseModel):
    chunk_id: str
    document_id: str
    document_title: Optional[str] = None
    content: str
    page_number: Optional[int] = None
    section_title: Optional[str] = None
    score: float
