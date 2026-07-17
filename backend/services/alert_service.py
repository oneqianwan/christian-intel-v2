from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from models.watch_alert import Alert
from services import tenant_scope, tenant_service
from services.watch_alert_ownership import ownership_enabled


class AlertServiceError(Exception):
    status_code = 400
    error_code = "ALERT_SERVICE_ERROR"
    message = "Alert request failed"

    def __init__(self, message: str | None = None):
        if message:
            self.message = message
        super().__init__(self.message)


class AlertNotFoundError(AlertServiceError):
    status_code = 404
    error_code = "ALERT_NOT_FOUND"
    message = "Alert not found"


class AlertDismissedError(AlertServiceError):
    status_code = 409
    error_code = "ALERT_DISMISSED"
    message = "Dismissed alert cannot be marked as read"


def utcnow() -> datetime:
    return datetime.utcnow()


def _is_super_admin(current_user) -> bool:
    if isinstance(current_user, bool):
        return bool(current_user)
    return tenant_service.is_platform_super_admin(current_user)


def apply_alert_access_scope(
    query,
    *,
    user_id: str,
    current_user=None,
    current_tenant=None,
):
    if current_tenant is not None:
        current_tenant_id = tenant_scope.ensure_tenant_id_for_create({}, current_tenant).get("tenant_id")
        query = tenant_scope.filter_by_tenant(query, Alert, current_tenant_id)

    if _is_super_admin(current_user) and current_tenant is not None:
        return query

    if ownership_enabled():
        return query.filter(Alert.owner_user_id == user_id)
    return query.filter(Alert.user_id == user_id)


def get_owned_alert(
    db: Session,
    alert_id: str,
    user_id: str,
    *,
    current_user=None,
    current_tenant=None,
) -> Alert:
    alert = apply_alert_access_scope(
        db.query(Alert),
        user_id=user_id,
        current_user=current_user,
        current_tenant=current_tenant,
    ).filter(Alert.id == alert_id).first()
    if not alert:
        raise AlertNotFoundError()
    if current_tenant is not None:
        tenant_scope.require_record_tenant(alert, current_tenant)
    return alert


def list_alerts(
    db: Session,
    user_id: str,
    *,
    current_user=None,
    current_tenant=None,
    status: str | None,
    severity: str | None,
    watch_target_id: str | None,
    page: int,
    page_size: int,
) -> tuple[list[Alert], int]:
    query = apply_alert_access_scope(
        db.query(Alert),
        user_id=user_id,
        current_user=current_user,
        current_tenant=current_tenant,
    )
    if status:
        query = query.filter(Alert.status == status)
    if severity:
        query = query.filter(Alert.severity == severity)
    if watch_target_id:
        query = query.filter(Alert.watch_target_id == watch_target_id)

    total = query.count()
    items = (
        query.order_by(Alert.created_at.desc(), Alert.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return items, total


def get_unread_count(db: Session, user_id: str, *, current_user=None, current_tenant=None) -> int:
    query = apply_alert_access_scope(
        db.query(Alert).filter(Alert.status == "unread"),
        user_id=user_id,
        current_user=current_user,
        current_tenant=current_tenant,
    )
    return query.count()


def mark_alert_read(db: Session, alert_id: str, user_id: str, *, current_user=None, current_tenant=None) -> Alert:
    alert = get_owned_alert(
        db,
        alert_id,
        user_id,
        current_user=current_user,
        current_tenant=current_tenant,
    )
    if alert.status == "dismissed":
        raise AlertDismissedError()
    if alert.status == "read":
        return alert

    alert.status = "read"
    alert.read_at = utcnow()
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(alert)
    return alert


def dismiss_alert(db: Session, alert_id: str, user_id: str, *, current_user=None, current_tenant=None) -> Alert:
    alert = get_owned_alert(
        db,
        alert_id,
        user_id,
        current_user=current_user,
        current_tenant=current_tenant,
    )
    if alert.status == "dismissed":
        return alert

    alert.status = "dismissed"
    alert.dismissed_at = utcnow()
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(alert)
    return alert


def mark_all_read(db: Session, user_id: str, *, current_user=None, current_tenant=None) -> int:
    current_time = utcnow()
    try:
        query = apply_alert_access_scope(
            db.query(Alert).filter(Alert.status == "unread"),
            user_id=user_id,
            current_user=current_user,
            current_tenant=current_tenant,
        )
        updated_count = query.update(
            {
                Alert.status: "read",
                Alert.read_at: current_time,
            },
            synchronize_session=False,
        )
        db.commit()
        return int(updated_count or 0)
    except Exception:
        db.rollback()
        raise
