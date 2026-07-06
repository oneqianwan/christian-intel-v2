from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from config import settings
from models.auth import AuthSession, User
from models.database import get_db
from schemas.watch_alert import ApiErrorResponse
from services.auth_service import hash_session_token, touch_session_last_seen


def _raise_api_error(status_code: int, error_code: str, message: str) -> None:
    raise HTTPException(
        status_code=status_code,
        detail=ApiErrorResponse(error_code=error_code, message=message).model_dump(),
    )


def require_auth_enabled() -> None:
    if not bool(settings.AUTH_V1_ENABLED):
        _raise_api_error(status.HTTP_503_SERVICE_UNAVAILABLE, "AUTH_DISABLED", "Auth is disabled")


def _get_cookie_token(request: Request) -> str:
    cookie_name = str(settings.AUTH_COOKIE_NAME or "").strip()
    return str(request.cookies.get(cookie_name) or "")


@dataclass(frozen=True)
class AuthContext:
    user: User
    session: AuthSession


def get_current_auth_context(
    request: Request,
    _: None = Depends(require_auth_enabled),
    db: Session = Depends(get_db),
) -> AuthContext:
    raw_token = _get_cookie_token(request).strip()
    if not raw_token:
        _raise_api_error(status.HTTP_401_UNAUTHORIZED, "AUTH_REQUIRED", "Authentication required")

    token_hash = hash_session_token(raw_token)
    session: AuthSession | None = db.query(AuthSession).filter(AuthSession.token_hash == token_hash).first()
    if session is None:
        _raise_api_error(status.HTTP_401_UNAUTHORIZED, "INVALID_SESSION", "Invalid session")

    if str(session.status) == "revoked" or session.revoked_at is not None:
        _raise_api_error(status.HTTP_401_UNAUTHORIZED, "SESSION_REVOKED", "Session revoked")

    if session.expires_at is not None and session.expires_at <= datetime.utcnow():
        _raise_api_error(status.HTTP_401_UNAUTHORIZED, "SESSION_EXPIRED", "Session expired")

    user: User | None = db.query(User).filter(User.id == session.user_id).first()
    if user is None:
        _raise_api_error(status.HTTP_401_UNAUTHORIZED, "INVALID_SESSION", "Invalid session")

    if user.deleted_at is not None:
        _raise_api_error(status.HTTP_403_FORBIDDEN, "ACCOUNT_DISABLED", "Account disabled")

    status_value = str(user.status or "").strip().lower()
    if status_value == "disabled":
        _raise_api_error(status.HTTP_403_FORBIDDEN, "ACCOUNT_DISABLED", "Account disabled")
    if status_value == "pending":
        _raise_api_error(status.HTTP_403_FORBIDDEN, "ACCOUNT_PENDING", "Account pending")

    touch_session_last_seen(db, session=session)
    return AuthContext(user=user, session=session)


def get_current_auth_session(context: AuthContext = Depends(get_current_auth_context)) -> AuthSession:
    return context.session


def get_current_user(context: AuthContext = Depends(get_current_auth_context)) -> User:
    return context.user


def require_authenticated_user(user: User = Depends(get_current_user)) -> User:
    return user
