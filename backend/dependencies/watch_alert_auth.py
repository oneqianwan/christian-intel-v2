from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from config import settings
from dependencies.auth import resolve_user_for_request
from models.database import get_db
from schemas.watch_alert import ApiErrorResponse


def _raise_api_error(status_code: int, error_code: str, message: str) -> None:
    raise HTTPException(
        status_code=status_code,
        detail=ApiErrorResponse(error_code=error_code, message=message).model_dump(),
    )


def watch_alert_user_ownership_enabled() -> bool:
    return bool(settings.feature_flag("WATCH_ALERT_USER_OWNERSHIP_ENABLED"))


def _legacy_session_bypass_enabled() -> bool:
    return bool(settings.legacy_session_id_enabled()) and not watch_alert_user_ownership_enabled()


def get_watch_alert_current_user_id(
    request: Request,
    db: Session = Depends(get_db),
    x_session_id: Annotated[str | None, Header(alias="x-session-id")] = None,
) -> str:
    if not _legacy_session_bypass_enabled():
        user = resolve_user_for_request(request=request, db=db, touch_last_seen=True)
        return str(user.id)

    user_id = str(x_session_id or "").strip()
    if not user_id:
        _raise_api_error(
            status.HTTP_401_UNAUTHORIZED,
            "AUTH_REQUIRED",
            "Authentication required",
        )
    return user_id
