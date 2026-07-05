from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from models.watch_alert import Alert


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


def get_owned_alert(db: Session, alert_id: str, user_id: str) -> Alert:
    alert = (
        db.query(Alert)
        .filter(
            Alert.id == alert_id,
            Alert.user_id == user_id,
        )
        .first()
    )
    if not alert:
        raise AlertNotFoundError()
    return alert


def list_alerts(
    db: Session,
    user_id: str,
    *,
    status: str | None,
    severity: str | None,
    watch_target_id: str | None,
    page: int,
    page_size: int,
) -> tuple[list[Alert], int]:
    query = db.query(Alert).filter(Alert.user_id == user_id)
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


def get_unread_count(db: Session, user_id: str) -> int:
    return (
        db.query(Alert)
        .filter(
            Alert.user_id == user_id,
            Alert.status == "unread",
        )
        .count()
    )


def mark_alert_read(db: Session, alert_id: str, user_id: str) -> Alert:
    alert = get_owned_alert(db, alert_id, user_id)
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


def dismiss_alert(db: Session, alert_id: str, user_id: str) -> Alert:
    alert = get_owned_alert(db, alert_id, user_id)
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


def mark_all_read(db: Session, user_id: str) -> int:
    current_time = utcnow()
    try:
        updated_count = (
            db.query(Alert)
            .filter(
                Alert.user_id == user_id,
                Alert.status == "unread",
            )
            .update(
                {
                    Alert.status: "read",
                    Alert.read_at: current_time,
                },
                synchronize_session=False,
            )
        )
        db.commit()
        return int(updated_count or 0)
    except Exception:
        db.rollback()
        raise
