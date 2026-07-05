from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from config import settings
from models.database import get_db
from schemas.watch_alert import (
    ApiErrorResponse,
    WatchEntityType,
    WatchTargetCreate,
    WatchTargetListResponse,
    WatchTargetResponse,
    WatchTargetStatus,
    WatchTargetUpdate,
)
from services.watch_target_service import (
    WatchTargetEntityNotFoundError,
    WatchTargetExistsError,
    WatchTargetNotFoundError,
    WatchTargetServiceError,
    create_watch_target,
    list_watch_targets,
    soft_delete_watch_target,
    update_watch_target,
)

router = APIRouter(prefix="/watch-targets", tags=["watch_targets"])


def _raise_api_error(status_code: int, error_code: str, message: str) -> None:
    raise HTTPException(status_code=status_code, detail=ApiErrorResponse(error_code=error_code, message=message).model_dump())


def require_watch_alert_enabled() -> None:
    if not settings.feature_flag("WATCH_ALERT_V1_ENABLED"):
        _raise_api_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "WATCH_ALERT_V1_DISABLED",
            "Watch / Alert V1 is disabled",
        )


def get_current_user_id(
    x_session_id: Annotated[str | None, Header(alias="x-session-id")] = None,
) -> str:
    user_id = (x_session_id or "").strip()
    if not user_id:
        _raise_api_error(
            status.HTTP_401_UNAUTHORIZED,
            "AUTH_REQUIRED",
            "Authentication required",
        )
    return user_id


def _translate_service_error(exc: WatchTargetServiceError) -> None:
    _raise_api_error(exc.status_code, exc.error_code, exc.message)


@router.post(
    "",
    response_model=WatchTargetResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_watch_target_route(
    payload: WatchTargetCreate,
    _: None = Depends(require_watch_alert_enabled),
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    try:
        watch_target = create_watch_target(db, user_id, payload)
    except (WatchTargetExistsError, WatchTargetEntityNotFoundError) as exc:
        _translate_service_error(exc)
    return watch_target


@router.get("", response_model=WatchTargetListResponse)
def list_watch_targets_route(
    _: None = Depends(require_watch_alert_enabled),
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
    status_filter: WatchTargetStatus | None = Query(default=None, alias="status"),
    entity_type: WatchEntityType | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    items, total = list_watch_targets(
        db,
        user_id,
        status=status_filter,
        entity_type=entity_type,
        page=page,
        page_size=page_size,
    )
    return WatchTargetListResponse(
        items=items,
        page=page,
        page_size=page_size,
        total=total,
    )


@router.patch("/{watch_target_id}", response_model=WatchTargetResponse)
def update_watch_target_route(
    watch_target_id: str,
    payload: WatchTargetUpdate,
    _: None = Depends(require_watch_alert_enabled),
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    try:
        watch_target = update_watch_target(db, watch_target_id, user_id, payload)
    except WatchTargetNotFoundError as exc:
        _translate_service_error(exc)
    return watch_target


@router.delete("/{watch_target_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_watch_target_route(
    watch_target_id: str,
    _: None = Depends(require_watch_alert_enabled),
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    try:
        soft_delete_watch_target(db, watch_target_id, user_id)
    except WatchTargetNotFoundError as exc:
        _translate_service_error(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
