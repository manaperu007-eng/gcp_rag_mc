##############################################################################
# backend/api/core/dependencies.py
# FastAPI dependency injection: DB clients, current user, role guards
##############################################################################
from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Optional

from fastapi import Depends, Header, HTTPException, status
from jose import JWTError

from api.core.security import decode_token
from shared.bigquery_client import BigQueryClient
from shared.config import Settings, get_settings
from shared.models import UserOut, UserRole
from shared.vertex_client import VertexAIClient


# ── Settings ──────────────────────────────────────────────────────────────

def settings_dep() -> Settings:
    return get_settings()

SettingsDep = Annotated[Settings, Depends(settings_dep)]


# ── Shared clients (singleton per process) ────────────────────────────────

@lru_cache
def _bq_client_singleton(project_id: str, dataset: str) -> BigQueryClient:
    s = get_settings()
    return BigQueryClient(s)

@lru_cache
def _vertex_client_singleton(project_id: str) -> VertexAIClient:
    return VertexAIClient(get_settings())


def get_bq(settings: SettingsDep) -> BigQueryClient:
    return _bq_client_singleton(settings.project_id, settings.bq_dataset)

def get_vertex(settings: SettingsDep) -> VertexAIClient:
    return _vertex_client_singleton(settings.project_id)

BQDep     = Annotated[BigQueryClient, Depends(get_bq)]
VertexDep = Annotated[VertexAIClient, Depends(get_vertex)]


# ── Auth ──────────────────────────────────────────────────────────────────

def _extract_token(authorization: Optional[str] = Header(default=None)) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return authorization.split(" ", 1)[1]


def get_current_user(
    token: Annotated[str, Depends(_extract_token)],
    settings: SettingsDep,
    bq: BQDep,
) -> UserOut:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_token(token, settings)
        user_id: str = payload.get("sub")
        if not user_id:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user_data = bq.get_user(user_id)
    if not user_data or not user_data.get("is_active"):
        raise credentials_exception

    return UserOut(**user_data)


CurrentUser = Annotated[UserOut, Depends(get_current_user)]


def require_role(*roles: UserRole):
    """Dependency factory that enforces one of the given roles."""
    def _guard(current_user: CurrentUser) -> UserOut:
        if current_user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access requires role: {[r.value for r in roles]}",
            )
        return current_user
    return Depends(_guard)


AdminOnly     = require_role(UserRole.ADMIN)
AdminReviewer = require_role(UserRole.ADMIN, UserRole.REVIEWER)
