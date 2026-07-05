from __future__ import annotations

import json
import uuid

from datetime import datetime
from time import perf_counter
from typing import Any

from sqlalchemy import exists
from sqlalchemy.orm import Session

from config import settings
from models.watch_alert import WatchRun, WatchTarget
from queue_client import get_collection_queue


WATCH_RUN_DUPLICATE = "WATCH_RUN_DUPLICATE"
WATCH_TARGET_AUTO_PAUSED = "WATCH_TARGET_AUTO_PAUSED"


def utcnow() -> datetime:
    return datetime.utcnow()


def _isoformat(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def scheduler_enabled() -> bool:
    return settings.feature_flag("WATCH_ALERT_V1_ENABLED") and settings.feature_flag("WATCH_ALERT_SCHEDULER_ENABLED")


def scheduler_interval_seconds() -> int:
    return max(1, int(settings.WATCH_ALERT_SCHEDULER_INTERVAL_SECONDS or 300))


def max_retries() -> int:
    return max(0, int(settings.WATCH_ALERT_MAX_RETRIES or 0))


def retry_base_seconds() -> int:
    return max(1, int(settings.WATCH_ALERT_RETRY_BASE_SECONDS or 300))


def max_consecutive_failures() -> int:
    return max(1, int(settings.WATCH_ALERT_MAX_CONSECUTIVE_FAILURES or 5))


def due_scan_limit(limit: int | None = None) -> int:
    raw_limit = 100 if limit is None else int(limit)
    return max(1, min(raw_limit, 100))


def build_scheduled_job_id(watch_target_id: str, scheduled_at: datetime) -> str:
    normalized = scheduled_at.replace(microsecond=0).strftime("%Y%m%dT%H%M%S")
    return f"watch-target:{watch_target_id}:{normalized}"


def build_retry_job_id(watch_target_id: str, watch_run_id: str, retry_number: int) -> str:
    return f"watch-target:{watch_target_id}:retry:{watch_run_id}:{int(retry_number)}"


def _job_exists(queue: Any, job_id: str) -> bool:
    fetch_job = getattr(queue, "fetch_job", None)
    if callable(fetch_job):
        return fetch_job(job_id) is not None
    return False


def get_watch_queue():
    return get_collection_queue()


def scan_due_watch_targets(db: Session, now: datetime | None = None, limit: int = 100) -> list[WatchTarget]:
    if not scheduler_enabled():
        return []

    current_time = now or utcnow()
    running_exists = exists().where(
        WatchRun.watch_target_id == WatchTarget.id,
        WatchRun.status == "running",
    )

    query = (
        db.query(WatchTarget)
        .filter(
            WatchTarget.deleted_at.is_(None),
            WatchTarget.status == "active",
            WatchTarget.frequency.in_(("daily", "weekly")),
            WatchTarget.next_check_at.is_not(None),
            WatchTarget.next_check_at <= current_time,
            WatchTarget.consecutive_failures < max_consecutive_failures(),
            ~running_exists,
        )
        .order_by(WatchTarget.next_check_at.asc())
        .limit(due_scan_limit(limit))
    )
    return query.all()


def _build_watch_run_metadata(
    *,
    trigger: str,
    scheduled_at: datetime | None,
    rq_job_id: str | None,
    retry_number: int,
    original_scheduled_at: datetime | None = None,
    duplicate_reason: str | None = None,
) -> dict[str, Any]:
    return {
        "trigger": trigger,
        "scheduled_at": _isoformat(scheduled_at),
        "original_scheduled_at": _isoformat(original_scheduled_at or scheduled_at),
        "rq_job_id": rq_job_id,
        "retry_number": retry_number,
        "duplicate_reason": duplicate_reason,
    }


def create_pending_watch_run(
    db: Session,
    watch_target: WatchTarget,
    *,
    scheduled_at: datetime,
    rq_job_id: str,
    retry_number: int = 0,
    now: datetime | None = None,
) -> WatchRun:
    created_at = now or utcnow()
    watch_run = WatchRun(
        id=str(uuid.uuid4()),
        watch_target_id=watch_target.id,
        job_run_id=rq_job_id,
        status="pending",
        metadata_json=_build_watch_run_metadata(
            trigger="automatic",
            scheduled_at=scheduled_at,
            rq_job_id=rq_job_id,
            retry_number=retry_number,
        ),
        created_at=created_at,
    )
    db.add(watch_run)
    db.commit()
    db.refresh(watch_run)
    return watch_run


def create_skipped_watch_run(
    db: Session,
    watch_target: WatchTarget,
    *,
    scheduled_at: datetime | None,
    reason: str,
    rq_job_id: str | None = None,
    now: datetime | None = None,
) -> WatchRun:
    current_time = now or utcnow()
    watch_run = WatchRun(
        id=str(uuid.uuid4()),
        watch_target_id=watch_target.id,
        job_run_id=rq_job_id,
        status="skipped",
        started_at=current_time,
        finished_at=current_time,
        error_code=WATCH_RUN_DUPLICATE,
        error_message=reason,
        metadata_json=_build_watch_run_metadata(
            trigger="automatic",
            scheduled_at=scheduled_at,
            rq_job_id=rq_job_id,
            retry_number=0,
            duplicate_reason=reason,
        ),
    )
    db.add(watch_run)
    db.commit()
    db.refresh(watch_run)
    return watch_run


def enqueue_due_watch_targets(
    db: Session,
    *,
    queue: Any | None = None,
    now: datetime | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    scan_started_at = now or utcnow()
    started_perf = perf_counter()
    stats = {
        "scan_started_at": _isoformat(scan_started_at),
        "due_count": 0,
        "enqueued_count": 0,
        "duplicate_count": 0,
        "skipped_count": 0,
        "failed_count": 0,
        "scan_finished_at": None,
        "duration_ms": 0,
    }

    if not scheduler_enabled():
        finished_at = utcnow()
        stats["scan_finished_at"] = _isoformat(finished_at)
        stats["duration_ms"] = int((perf_counter() - started_perf) * 1000)
        return stats

    work_queue = queue or get_watch_queue()
    due_targets = scan_due_watch_targets(db, now=scan_started_at, limit=limit)
    stats["due_count"] = len(due_targets)

    from workers.watch_tasks import execute_watch_target_job

    for watch_target in due_targets:
        scheduled_at = watch_target.next_check_at
        if scheduled_at is None:
            stats["skipped_count"] += 1
            continue

        job_id = build_scheduled_job_id(watch_target.id, scheduled_at)

        if watch_target.deleted_at is not None or watch_target.status != "active":
            create_skipped_watch_run(
                db,
                watch_target,
                scheduled_at=scheduled_at,
                rq_job_id=job_id,
                reason="target_not_active",
                now=scan_started_at,
            )
            stats["skipped_count"] += 1
            continue

        if watch_target.next_check_at is None or watch_target.next_check_at > scan_started_at:
            create_skipped_watch_run(
                db,
                watch_target,
                scheduled_at=scheduled_at,
                rq_job_id=job_id,
                reason="target_not_due",
                now=scan_started_at,
            )
            stats["skipped_count"] += 1
            continue

        running_exists = (
            db.query(WatchRun.id)
            .filter(
                WatchRun.watch_target_id == watch_target.id,
                WatchRun.status == "running",
            )
            .first()
            is not None
        )
        if running_exists or _job_exists(work_queue, job_id):
            create_skipped_watch_run(
                db,
                watch_target,
                scheduled_at=scheduled_at,
                rq_job_id=job_id,
                reason="duplicate_job",
                now=scan_started_at,
            )
            stats["duplicate_count"] += 1
            continue

        watch_run = create_pending_watch_run(
            db,
            watch_target,
            scheduled_at=scheduled_at,
            rq_job_id=job_id,
            now=scan_started_at,
        )
        try:
            work_queue.enqueue(
                execute_watch_target_job,
                watch_target.id,
                watch_run.id,
                _isoformat(scheduled_at),
                0,
                job_id=job_id,
                job_timeout=300,
                result_ttl=3600,
                meta={
                    "watch_target_id": watch_target.id,
                    "watch_run_id": watch_run.id,
                    "retry_number": 0,
                    "scheduled_at": _isoformat(scheduled_at),
                },
            )
            stats["enqueued_count"] += 1
        except Exception as exc:
            watch_run.status = "failed"
            watch_run.finished_at = utcnow()
            watch_run.error_code = "WATCH_RUN_FAILED"
            watch_run.error_message = str(exc)[:300]
            db.commit()
            stats["failed_count"] += 1

    finished_at = utcnow()
    stats["scan_finished_at"] = _isoformat(finished_at)
    stats["duration_ms"] = int((perf_counter() - started_perf) * 1000)
    return stats


def run_watch_scheduler_once(
    db: Session,
    *,
    queue: Any | None = None,
    now: datetime | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    stats = enqueue_due_watch_targets(
        db,
        queue=queue,
        now=now,
        limit=limit,
    )
    print(json.dumps(stats, ensure_ascii=False))
    return stats
