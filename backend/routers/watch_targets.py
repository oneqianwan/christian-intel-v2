from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from config import settings
from dependencies.watch_alert_auth import get_watch_alert_current_user_id as get_current_user_id
from models.database import get_db
from schemas.watch_alert import (
    ApiErrorResponse,
    SignalListResponse,
    SignalResponse,
    SignalSeverity,
    SignalType,
    WatchEntityType,
    WatchRunResponse,
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
from services.watch_runner import (
    WatchRunAlreadyRunningError,
    WatchRunError,
    WatchTargetDisabledError,
    list_watch_target_signals,
    run_watch_target,
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


@router.post("/{watch_target_id}/run", response_model=WatchRunResponse)
def run_watch_target_route(
    watch_target_id: str,
    _: None = Depends(require_watch_alert_enabled),
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    try:
        watch_run = run_watch_target(db, watch_target_id, user_id)
    except (
        WatchTargetNotFoundError,
        WatchTargetDisabledError,
        WatchRunAlreadyRunningError,
        WatchTargetEntityNotFoundError,
        WatchRunError,
    ) as exc:
        _translate_service_error(exc)
    return WatchRunResponse(
        run_id=watch_run.id,
        watch_target_id=watch_run.watch_target_id,
        status=watch_run.status,
        items_found=watch_run.items_found,
        signals_created=watch_run.signals_created,
        started_at=watch_run.started_at,
        finished_at=watch_run.finished_at,
    )


@router.get("/{watch_target_id}/signals", response_model=SignalListResponse)
def list_watch_target_signals_route(
    watch_target_id: str,
    _: None = Depends(require_watch_alert_enabled),
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
    signal_type: SignalType | None = Query(default=None),
    severity: SignalSeverity | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    try:
        items, total = list_watch_target_signals(
            db,
            watch_target_id,
            user_id,
            signal_type=signal_type,
            severity=severity,
            page=page,
            page_size=page_size,
        )
    except WatchTargetNotFoundError as exc:
        _translate_service_error(exc)

    return SignalListResponse(
        items=[SignalResponse.model_validate(item) for item in items],
        page=page,
        page_size=page_size,
        total=total,
    )
