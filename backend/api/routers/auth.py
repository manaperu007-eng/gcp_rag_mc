##############################################################################
# backend/api/routers/auth.py
# Auth endpoints: register, login, refresh, me
##############################################################################
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from api.core.dependencies import BQDep, CurrentUser, SettingsDep
from api.core.security import create_access_token, hash_password, verify_password
from shared.models import TokenResponse, UserCreate, UserOut, UserRole

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: str
    password: str


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(body: UserCreate, bq: BQDep, settings: SettingsDep):
    """Register a new user. First user gets admin role."""
    if bq.get_user_by_email(body.email):
        raise HTTPException(status_code=400, detail="Email already registered")

    all_users = bq.list_users()
    role = UserRole.ADMIN if not all_users else UserRole.RESPONDENT

    hashed_pw = hash_password(body.password) if body.password else None
    user_dict = body.model_dump()
    user_dict["role"] = role
    user_dict["password_hash"] = hashed_pw
    user_dict.pop("password", None)

    user_id = bq.create_user(user_dict)
    bq.log_event("USER_REGISTERED", user_email=body.email, resource_id=user_id)
    return UserOut(**bq.get_user(user_id))


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, bq: BQDep, settings: SettingsDep):
    """Authenticate and return a JWT."""
    user = bq.get_user_by_email(body.email)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not verify_password(body.password, user.get("password_hash", "")):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not user.get("is_active"):
        raise HTTPException(status_code=403, detail="Account is deactivated")

    # Update last login
    bq.client.query(
        f"UPDATE `{settings.project_id}.{settings.bq_dataset}.users` "
        f"SET last_login_at = CURRENT_TIMESTAMP() WHERE user_id = '{user['user_id']}'"
    ).result()

    token = create_access_token({"sub": user["user_id"], "role": user["role"]}, settings)
    user_out = UserOut(**user)
    bq.log_event("USER_LOGIN", user_id=user["user_id"], user_email=body.email)
    return TokenResponse(
        access_token=token,
        expires_in=settings.jwt_expiry_minutes * 60,
        user=user_out,
    )


@router.get("/me", response_model=UserOut)
def me(current_user: CurrentUser):
    """Return the currently authenticated user profile."""
    return current_user


@router.post("/refresh", response_model=TokenResponse)
def refresh(current_user: CurrentUser, settings: SettingsDep, bq: BQDep):
    """Issue a fresh token for the current user."""
    token = create_access_token(
        {"sub": current_user.user_id, "role": current_user.role}, settings
    )
    return TokenResponse(
        access_token=token,
        expires_in=settings.jwt_expiry_minutes * 60,
        user=current_user,
    )
