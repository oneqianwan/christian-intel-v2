from __future__ import annotations

import hashlib

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

import config
from dependencies.auth import require_authenticated_user, require_authenticated_user_no_touch
from models.auth import User
from models.database import get_db
from models.schemas import (
    AuthUserResponse,
    ChangePasswordRequest,
    ChangePasswordResponse,
    LoginRequest,
    LoginResponse,
    LogoutAllResponse,
    LogoutResponse,
)
from schemas.watch_alert import ApiErrorResponse
from services.auth_service import (
    AuthError,
    authenticate_user,
    change_user_password,
    create_auth_session,
    revoke_all_user_sessions,
    revoke_auth_session,
    resolve_auth_session,
)


router = APIRouter(prefix="/auth", tags=["auth"])


def _api_error_payload(error_code: str, message: str) -> dict:
    return {"detail": ApiErrorResponse(error_code=error_code, message=message).model_dump()}


def _raise_api_error(status_code: int, error_code: str, message: str) -> None:
    raise HTTPException(
        status_code=status_code,
        detail=ApiErrorResponse(error_code=error_code, message=message).model_dump(),
    )


def _cookie_kwargs() -> dict:
    return {
        "httponly": True,
        "secure": bool(config.settings.AUTH_COOKIE_SECURE),
        "samesite": str(config.settings.AUTH_COOKIE_SAMESITE),
        "path": str(config.settings.AUTH_COOKIE_PATH),
        "max_age": int(config.settings.AUTH_SESSION_TTL_SECONDS),
    }


def _delete_cookie(response: Response) -> None:
    response.delete_cookie(
        key=str(config.settings.AUTH_COOKIE_NAME),
        path=str(config.settings.AUTH_COOKIE_PATH),
        samesite=str(config.settings.AUTH_COOKIE_SAMESITE),
        secure=bool(config.settings.AUTH_COOKIE_SECURE),
    )


def _client_fingerprint(request: Request) -> str:
    host = getattr(getattr(request, "client", None), "host", None) or "unknown"
    return hashlib.sha256(str(host).encode("utf-8")).hexdigest()


@router.post("/login", response_model=LoginResponse)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    if not bool(config.settings.AUTH_V1_ENABLED):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=ApiErrorResponse(error_code="AUTH_DISABLED", message="Auth is disabled").model_dump(),
        )

    try:
        user = authenticate_user(
            db,
            email=payload.email,
            password=payload.password,
            client_fingerprint=_client_fingerprint(request),
        )
    except AuthError as exc:
        headers = {}
        if exc.retry_after_seconds is not None:
            headers["Retry-After"] = str(int(exc.retry_after_seconds))
        raise HTTPException(
            status_code=int(exc.status_code),
            detail=ApiErrorResponse(error_code=exc.error_code, message=exc.message).model_dump(),
            headers=headers or None,
        )

    _, raw_token = create_auth_session(db, user=user)
    response.set_cookie(key=str(config.settings.AUTH_COOKIE_NAME), value=raw_token, **_cookie_kwargs())

    return LoginResponse(
        user=AuthUserResponse(
            public_id=str(user.public_id),
            email=str(user.email),
            display_name=str(user.display_name),
            role=str(user.role),
            status=str(user.status),
        )
    )


@router.post("/logout", response_model=LogoutResponse)
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    if not bool(config.settings.AUTH_V1_ENABLED):
        resp = JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=_api_error_payload("AUTH_DISABLED", "Auth is disabled"),
        )
        _delete_cookie(resp)
        return resp

    raw_token = str(request.cookies.get(str(config.settings.AUTH_COOKIE_NAME)) or "").strip()
    if raw_token:
        try:
            session = resolve_auth_session(db, raw_token=raw_token)
            revoke_auth_session(db, session=session)
        except AuthError:
            pass
        except Exception:
            pass

    _delete_cookie(response)
    return LogoutResponse(success=True)


@router.get("/me", response_model=LoginResponse)
def me(user: User = Depends(require_authenticated_user)):
    return LoginResponse(
        user=AuthUserResponse(
            public_id=str(user.public_id),
            email=str(user.email),
            display_name=str(user.display_name),
            role=str(user.role),
            status=str(user.status),
        )
    )


@router.post("/change-password", response_model=ChangePasswordResponse)
def change_password(
    payload: ChangePasswordRequest,
    response: Response,
    user: User = Depends(require_authenticated_user_no_touch),
    db: Session = Depends(get_db),
):
    if payload.new_password != payload.confirm_password:
        _raise_api_error(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "PASSWORD_CONFIRMATION_MISMATCH",
            "Password confirmation mismatch",
        )

    try:
        change_user_password(
            db,
            user=user,
            current_password=payload.current_password,
            new_password=payload.new_password,
        )
        db.commit()
    except AuthError as exc:
        db.rollback()
        raise HTTPException(
            status_code=int(exc.status_code),
            detail=ApiErrorResponse(error_code=exc.error_code, message=exc.message).model_dump(),
        )
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ApiErrorResponse(error_code="INTERNAL_ERROR", message="Internal error").model_dump(),
        )

    _delete_cookie(response)
    return ChangePasswordResponse(success=True, reauthentication_required=True)


@router.post("/logout-all", response_model=LogoutAllResponse)
def logout_all(
    response: Response,
    user: User = Depends(require_authenticated_user_no_touch),
    db: Session = Depends(get_db),
):
    try:
        revoked_count = revoke_all_user_sessions(db, user_id=user.id)
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ApiErrorResponse(error_code="INTERNAL_ERROR", message="Internal error").model_dump(),
        )

    _delete_cookie(response)
    return LogoutAllResponse(success=True, revoked_count=int(revoked_count))
