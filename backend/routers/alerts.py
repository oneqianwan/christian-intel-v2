from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from config import settings
from dependencies.tenant_context import TenantRequestContext, require_tenant_member
from models.database import get_db
from schemas.watch_alert import (
    AlertListResponse,
    AlertReadAllResponse,
    AlertResponse,
    AlertSeverity,
    AlertStatus,
    AlertUnreadCountResponse,
    ApiErrorResponse,
)
from services.alert_service import (
    AlertDismissedError,
    AlertNotFoundError,
    AlertServiceError,
    dismiss_alert,
    get_owned_alert,
    get_unread_count,
    list_alerts,
    mark_alert_read,
    mark_all_read,
)

router = APIRouter(prefix="/alerts", tags=["alerts"])


def _raise_api_error(status_code: int, error_code: str, message: str) -> None:
    raise HTTPException(status_code=status_code, detail=ApiErrorResponse(error_code=error_code, message=message).model_dump())


def require_alert_notifications_enabled() -> None:
    if settings.feature_flag("WATCH_ALERT_V1_ENABLED") and settings.feature_flag("WATCH_ALERT_NOTIFICATIONS_ENABLED"):
        return
    _raise_api_error(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "WATCH_ALERT_NOTIFICATIONS_DISABLED",
        "Watch alert notifications are disabled",
    )


def _translate_service_error(exc: AlertServiceError) -> None:
    _raise_api_error(exc.status_code, exc.error_code, exc.message)


@router.get("", response_model=AlertListResponse)
def list_alerts_route(
    _: None = Depends(require_alert_notifications_enabled),
    context: TenantRequestContext = Depends(require_tenant_member),
    db: Session = Depends(get_db),
    status_filter: AlertStatus | None = Query(default=None, alias="status"),
    severity: AlertSeverity | None = Query(default=None),
    watch_target_id: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    items, total = list_alerts(
        db,
        str(context.user.id),
        current_user=context.user,
        current_tenant=str(context.tenant.id),
        status=status_filter,
        severity=severity,
        watch_target_id=watch_target_id,
        page=page,
        page_size=page_size,
    )
    return AlertListResponse(
        items=[AlertResponse.model_validate(item) for item in items],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/unread-count", response_model=AlertUnreadCountResponse)
def get_unread_count_route(
    _: None = Depends(require_alert_notifications_enabled),
    context: TenantRequestContext = Depends(require_tenant_member),
    db: Session = Depends(get_db),
):
    return AlertUnreadCountResponse(
        unread_count=get_unread_count(
            db,
            str(context.user.id),
            current_user=context.user,
            current_tenant=str(context.tenant.id),
        )
    )


@router.patch("/{alert_id}/read", response_model=AlertResponse)
def mark_alert_read_route(
    alert_id: str,
    _: None = Depends(require_alert_notifications_enabled),
    context: TenantRequestContext = Depends(require_tenant_member),
    db: Session = Depends(get_db),
):
    try:
        alert = mark_alert_read(
            db,
            alert_id,
            str(context.user.id),
            current_user=context.user,
            current_tenant=str(context.tenant.id),
        )
    except (AlertNotFoundError, AlertDismissedError) as exc:
        _translate_service_error(exc)
    return AlertResponse.model_validate(alert)


@router.patch("/{alert_id}/dismiss", response_model=AlertResponse)
def dismiss_alert_route(
    alert_id: str,
    _: None = Depends(require_alert_notifications_enabled),
    context: TenantRequestContext = Depends(require_tenant_member),
    db: Session = Depends(get_db),
):
    try:
        alert = dismiss_alert(
            db,
            alert_id,
            str(context.user.id),
            current_user=context.user,
            current_tenant=str(context.tenant.id),
        )
    except AlertNotFoundError as exc:
        _translate_service_error(exc)
    return AlertResponse.model_validate(alert)


@router.delete("/{alert_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_alert_route(
    alert_id: str,
    _: None = Depends(require_alert_notifications_enabled),
    context: TenantRequestContext = Depends(require_tenant_member),
    db: Session = Depends(get_db),
):
    try:
        dismiss_alert(
            db,
            alert_id,
            str(context.user.id),
            current_user=context.user,
            current_tenant=str(context.tenant.id),
        )
    except AlertNotFoundError as exc:
        _translate_service_error(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/read-all", response_model=AlertReadAllResponse)
def mark_all_read_route(
    _: None = Depends(require_alert_notifications_enabled),
    context: TenantRequestContext = Depends(require_tenant_member),
    db: Session = Depends(get_db),
):
    return AlertReadAllResponse(
        updated_count=mark_all_read(
            db,
            str(context.user.id),
            current_user=context.user,
            current_tenant=str(context.tenant.id),
        )
    )


@router.get("/{alert_id}", response_model=AlertResponse)
def get_alert_route(
    alert_id: str,
    _: None = Depends(require_alert_notifications_enabled),
    context: TenantRequestContext = Depends(require_tenant_member),
    db: Session = Depends(get_db),
):
    try:
        alert = get_owned_alert(
            db,
            alert_id,
            str(context.user.id),
            current_user=context.user,
            current_tenant=str(context.tenant.id),
        )
    except AlertNotFoundError as exc:
        _translate_service_error(exc)
    return AlertResponse.model_validate(alert)
