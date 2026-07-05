from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from models.database import KnowledgeEntity, OrganizationProfile, WatchTarget
from schemas.watch_alert import WatchTargetCreate, WatchTargetUpdate


class WatchTargetServiceError(Exception):
    status_code = 400
    error_code = "WATCH_TARGET_ERROR"
    message = "Watch target request failed"

    def __init__(self, message: str | None = None):
        if message:
            self.message = message
        super().__init__(self.message)


class WatchTargetExistsError(WatchTargetServiceError):
    status_code = 409
    error_code = "WATCH_TARGET_EXISTS"
    message = "Watch target already exists"


class WatchTargetNotFoundError(WatchTargetServiceError):
    status_code = 404
    error_code = "WATCH_TARGET_NOT_FOUND"
    message = "Watch target not found"


class WatchTargetEntityNotFoundError(WatchTargetServiceError):
    status_code = 404
    error_code = "WATCH_TARGET_ENTITY_NOT_FOUND"
    message = "Target entity not found"


def utcnow() -> datetime:
    return datetime.utcnow()


def _schedule_interval(frequency: str) -> timedelta | None:
    if frequency == "daily":
        return timedelta(days=1)
    if frequency == "weekly":
        return timedelta(days=7)
    return None


def compute_next_check_at(frequency: str, *, now: datetime | None = None) -> datetime | None:
    base_time = now or utcnow()
    interval = _schedule_interval(frequency)
    if interval is None:
        return None
    return base_time + interval


def compute_next_check_at_for_state(
    *,
    status: str,
    frequency: str,
    now: datetime | None = None,
) -> datetime | None:
    if status != "active":
        return None
    return compute_next_check_at(frequency, now=now)


def advance_next_check_at(
    *,
    frequency: str,
    scheduled_at: datetime | None,
    now: datetime | None = None,
) -> datetime | None:
    if frequency == "manual" or scheduled_at is None:
        return None

    interval = _schedule_interval(frequency)
    if interval is None:
        return None

    current_time = now or utcnow()
    candidate = scheduled_at + interval
    while candidate <= current_time:
        candidate += interval
    return candidate


def _entity_exists(db: Session, entity_id: str, entity_type: Literal["organization", "knowledge_entity"]) -> bool:
    if entity_type == "organization":
        org_exists = (
            db.query(OrganizationProfile.id)
            .filter(OrganizationProfile.id == entity_id)
            .first()
            is not None
        )
        if org_exists:
            return True
        entity_exists = (
            db.query(KnowledgeEntity.id)
            .filter(KnowledgeEntity.id == entity_id, KnowledgeEntity.entity_type == "organization")
            .first()
            is not None
        )
        return entity_exists

    return (
        db.query(KnowledgeEntity.id)
        .filter(KnowledgeEntity.id == entity_id)
        .first()
        is not None
    )


def get_owned_watch_target(db: Session, watch_target_id: str, user_id: str) -> WatchTarget:
    watch_target = (
        db.query(WatchTarget)
        .filter(
            WatchTarget.id == watch_target_id,
            WatchTarget.user_id == user_id,
            WatchTarget.deleted_at.is_(None),
        )
        .first()
    )
    if not watch_target:
        raise WatchTargetNotFoundError()
    return watch_target


def create_watch_target(db: Session, user_id: str, payload: WatchTargetCreate) -> WatchTarget:
    if not _entity_exists(db, payload.entity_id, payload.entity_type):
        raise WatchTargetEntityNotFoundError()

    existing = (
        db.query(WatchTarget)
        .filter(
            WatchTarget.user_id == user_id,
            WatchTarget.entity_id == payload.entity_id,
            WatchTarget.entity_type == payload.entity_type,
            WatchTarget.deleted_at.is_(None),
        )
        .first()
    )
    if existing:
        raise WatchTargetExistsError()

    watch_target = WatchTarget(
        user_id=user_id,
        entity_id=payload.entity_id,
        entity_type=payload.entity_type,
        status="active",
        frequency=payload.frequency,
        next_check_at=compute_next_check_at_for_state(
            status="active",
            frequency=payload.frequency,
        ),
    )
    db.add(watch_target)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise WatchTargetExistsError() from exc
    db.refresh(watch_target)
    return watch_target


def list_watch_targets(
    db: Session,
    user_id: str,
    *,
    status: str | None,
    entity_type: str | None,
    page: int,
    page_size: int,
) -> tuple[list[WatchTarget], int]:
    query = (
        db.query(WatchTarget)
        .filter(
            WatchTarget.user_id == user_id,
            WatchTarget.deleted_at.is_(None),
        )
    )
    if status:
        query = query.filter(WatchTarget.status == status)
    if entity_type:
        query = query.filter(WatchTarget.entity_type == entity_type)

    total = query.count()
    items = (
        query.order_by(WatchTarget.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return items, total


def update_watch_target(db: Session, watch_target_id: str, user_id: str, payload: WatchTargetUpdate) -> WatchTarget:
    watch_target = get_owned_watch_target(db, watch_target_id, user_id)
    next_status = payload.status if payload.status is not None else watch_target.status
    next_frequency = payload.frequency if payload.frequency is not None else watch_target.frequency

    if payload.status is not None:
        watch_target.status = payload.status
    if payload.frequency is not None:
        watch_target.frequency = payload.frequency

    if payload.status is not None or payload.frequency is not None:
        watch_target.next_check_at = compute_next_check_at_for_state(
            status=next_status,
            frequency=next_frequency,
        )

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(watch_target)
    return watch_target


def soft_delete_watch_target(db: Session, watch_target_id: str, user_id: str) -> None:
    watch_target = get_owned_watch_target(db, watch_target_id, user_id)
    watch_target.deleted_at = utcnow()
    watch_target.status = "disabled"
    watch_target.next_check_at = None
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
