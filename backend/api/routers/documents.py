##############################################################################
# backend/api/routers/documents.py
# Document management: upload initiation, status, KB management
##############################################################################
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, status
from google.cloud import storage as gcs

from api.core.dependencies import (
    AdminOnly,
    AdminReviewer,
    BQDep,
    CurrentUser,
    SettingsDep,
)
from shared.models import (
    DocumentOut,
    DocumentUploadRequest,
    DocumentUploadResponse,
    KnowledgeBaseCreate,
    KnowledgeBaseOut,
    MessageResponse,
)

router = APIRouter(prefix="/documents", tags=["documents"])


# ─────────────────────────────────────────────────────────────────────────────
# Document Upload
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/upload-url", response_model=DocumentUploadResponse)
def get_upload_url(
    body: DocumentUploadRequest,
    current_user: CurrentUser,
    bq: BQDep,
    settings: SettingsDep,
    _admin: None = AdminReviewer,
):
    """
    Generate a signed GCS URL for direct client-side upload.
    After the client uploads the file, the GCS notification triggers ingestion.
    """
    doc_id = str(uuid.uuid4())
    gcs_path = f"uploads/{current_user.user_id}/{doc_id}/{body.file_name}"
    bucket_name = settings.document_bucket

    # Create the document record first (status=pending)
    bq.insert_document({
        "document_id": doc_id,
        "file_name": body.file_name,
        "file_type": body.file_type,
        "gcs_uri": f"gs://{bucket_name}/{gcs_path}",
        "title": body.title,
        "category": body.category,
        "tags": body.tags,
        "kb_ids": body.kb_ids,
        "status": "pending",
        "uploaded_by": current_user.email,
        "ingested_at": datetime.now(timezone.utc).isoformat(),
    })

    # Generate signed URL
    gcs_client = gcs.Client(project=settings.project_id)
    bucket = gcs_client.bucket(bucket_name)
    blob = bucket.blob(gcs_path)

    expiry = timedelta(minutes=settings.signed_url_expiry_minutes)
    upload_url = blob.generate_signed_url(
        version="v4",
        expiration=expiry,
        method="PUT",
        content_type=_mime_type(body.file_type),
    )

    bq.log_event(
        "DOCUMENT_UPLOAD_INITIATED",
        user_id=current_user.user_id,
        user_email=current_user.email,
        resource_type="document",
        resource_id=doc_id,
        details={"file_name": body.file_name, "file_type": body.file_type},
    )

    return DocumentUploadResponse(
        document_id=doc_id,
        upload_url=upload_url,
        upload_headers={"Content-Type": _mime_type(body.file_type)},
        expires_at=datetime.now(timezone.utc) + expiry,
    )


def _mime_type(file_type: str) -> str:
    return {
        "pdf":  "application/pdf",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "doc":  "application/msword",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "xls":  "application/vnd.ms-excel",
    }.get(file_type.lower(), "application/octet-stream")


# ─────────────────────────────────────────────────────────────────────────────
# Document CRUD
# ─────────────────────────────────────────────────────────────────────────────

@router.get("", response_model=List[DocumentOut])
def list_documents(
    current_user: CurrentUser,
    bq: BQDep,
    kb_id: Optional[str] = Query(None),
    doc_status: Optional[str] = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    rows = bq.list_documents(kb_id=kb_id, status=doc_status, limit=limit, offset=offset)
    return [DocumentOut(**r) for r in rows]


@router.get("/{document_id}", response_model=DocumentOut)
def get_document(document_id: str, current_user: CurrentUser, bq: BQDep):
    doc = bq.get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return DocumentOut(**doc)


@router.delete("/{document_id}", response_model=MessageResponse)
def delete_document(
    document_id: str,
    current_user: CurrentUser,
    bq: BQDep,
    settings: SettingsDep,
    _admin: None = AdminOnly,
):
    doc = bq.get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Soft delete via status
    bq.update_document_status(document_id, "deleted")
    bq.log_event(
        "DOCUMENT_DELETED",
        user_id=current_user.user_id,
        resource_type="document",
        resource_id=document_id,
    )
    return MessageResponse(message=f"Document {document_id} deleted")


# ─────────────────────────────────────────────────────────────────────────────
# Knowledge Base CRUD
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/knowledge-bases", response_model=List[KnowledgeBaseOut], tags=["knowledge-bases"])
def list_knowledge_bases(current_user: CurrentUser, bq: BQDep):
    return [KnowledgeBaseOut(**r) for r in bq.list_knowledge_bases()]


@router.post(
    "/knowledge-bases",
    response_model=KnowledgeBaseOut,
    status_code=status.HTTP_201_CREATED,
    tags=["knowledge-bases"],
)
def create_knowledge_base(
    body: KnowledgeBaseCreate,
    current_user: CurrentUser,
    bq: BQDep,
    _admin: None = AdminReviewer,
):
    kb_dict = body.model_dump()
    kb_dict["created_by"] = current_user.email
    kb_id = bq.create_knowledge_base(kb_dict)
    bq.log_event("KB_CREATED", user_id=current_user.user_id, resource_id=kb_id)
    return KnowledgeBaseOut(**bq.get_knowledge_base(kb_id))


@router.get("/knowledge-bases/{kb_id}", response_model=KnowledgeBaseOut, tags=["knowledge-bases"])
def get_knowledge_base(kb_id: str, current_user: CurrentUser, bq: BQDep):
    kb = bq.get_knowledge_base(kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    return KnowledgeBaseOut(**kb)


# ─────────────────────────────────────────────────────────────────────────────
# KB Semantic Search
# ─────────────────────────────────────────────────────────────────────────────

from shared.models import KBSearchRequest, KBSearchResult
from shared.vertex_client import VertexAIClient
from api.core.dependencies import VertexDep


@router.post("/knowledge-bases/search", response_model=List[KBSearchResult], tags=["knowledge-bases"])
def search_kb(body: KBSearchRequest, current_user: CurrentUser, bq: BQDep, vertex: VertexDep):
    """Semantic search over the knowledge base using Vector Search."""
    neighbors = vertex.search_similar_chunks(body.query, top_k=body.top_k)
    if not neighbors:
        return []

    chunk_ids = [n[0] for n in neighbors]
    score_map = {n[0]: n[1] for n in neighbors}

    # Fetch chunk details from BQ
    ids_str = ", ".join(f"'{c}'" for c in chunk_ids)
    rows = bq._run(
        f"""SELECT dc.*, d.title AS document_title
            FROM `{bq.project}.{bq.dataset}.document_chunks` dc
            JOIN `{bq.project}.{bq.dataset}.documents` d ON dc.document_id = d.document_id
            WHERE dc.chunk_id IN ({ids_str})
            {'AND dc.document_id IN (SELECT document_id FROM `' + bq.project + '.' + bq.dataset + '.documents` WHERE @kb IN UNNEST(kb_ids))' if body.kb_id else ''}
        """,
    )

    results = [
        KBSearchResult(
            chunk_id=r["chunk_id"],
            document_id=r["document_id"],
            document_title=r.get("document_title"),
            content=r["content"],
            page_number=r.get("page_number"),
            section_title=r.get("section_title"),
            score=score_map.get(r["chunk_id"], 0.0),
        )
        for r in rows
    ]
    results.sort(key=lambda x: x.score, reverse=True)
    return results
