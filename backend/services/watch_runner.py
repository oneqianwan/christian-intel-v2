from __future__ import annotations

import uuid

from datetime import datetime, timedelta

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from models.watch_alert import WatchRun, WatchTarget
from services.signal_service import create_signals_for_changes, list_signals_for_watch_target
from services.watch_change_detector import detect_watch_changes
from services.watch_scheduler import (
    WATCH_RUN_DUPLICATE,
    WATCH_TARGET_AUTO_PAUSED,
    build_retry_job_id,
    max_consecutive_failures,
    max_retries,
    retry_base_seconds,
)
from services.watch_snapshot_builder import build_watch_snapshot
from services.watch_target_service import (
    WatchTargetEntityNotFoundError,
    WatchTargetNotFoundError,
    advance_next_check_at,
    get_owned_watch_target,
)


class WatchRunError(Exception):
    status_code = 400
    error_code = "WATCH_RUN_FAILED"
    message = "Watch run failed"

    def __init__(self, message: str | None = None):
        if message:
            self.message = message
        super().__init__(self.message)


class WatchTargetDisabledError(WatchRunError):
    status_code = 409
    error_code = "WATCH_TARGET_DISABLED"
    message = "Watch target is disabled"


class WatchRunAlreadyRunningError(WatchRunError):
    status_code = 409
    error_code = "WATCH_RUN_ALREADY_RUNNING"
    message = "Watch target already has a running watch run"


def utcnow() -> datetime:
    return datetime.utcnow()


def _isoformat(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _latest_successful_run(db: Session, watch_target_id: str) -> WatchRun | None:
    return (
        db.query(WatchRun)
        .filter(
            WatchRun.watch_target_id == watch_target_id,
            WatchRun.status == "success",
        )
        .order_by(WatchRun.finished_at.desc().nullslast(), WatchRun.created_at.desc())
        .first()
    )


def _running_watch_run_exists(db: Session, watch_target_id: str, *, exclude_run_id: str | None = None) -> bool:
    query = db.query(WatchRun.id).filter(
        WatchRun.watch_target_id == watch_target_id,
        WatchRun.status == "running",
    )
    if exclude_run_id:
        query = query.filter(WatchRun.id != exclude_run_id)
    return query.first() is not None


def _base_metadata(watch_run: WatchRun) -> dict:
    return dict(watch_run.metadata_json or {}) if isinstance(watch_run.metadata_json, dict) else {}


def _scheduled_at_from_metadata(watch_run: WatchRun) -> datetime | None:
    metadata = _base_metadata(watch_run)
    raw = metadata.get("original_scheduled_at") or metadata.get("scheduled_at")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _manual_watch_run_metadata() -> dict:
    return {"trigger": "manual"}


def _automatic_watch_run_metadata(
    *,
    scheduled_at: datetime | None,
    rq_job_id: str | None,
    retry_number: int,
    watch_run: WatchRun | None = None,
) -> dict:
    existing = _base_metadata(watch_run) if watch_run else {}
    original_scheduled_at = existing.get("original_scheduled_at") or _isoformat(scheduled_at)
    return {
        **existing,
        "trigger": "automatic",
        "scheduled_at": _isoformat(scheduled_at),
        "original_scheduled_at": original_scheduled_at,
        "rq_job_id": rq_job_id,
        "retry_number": retry_number,
    }


def _build_previous_snapshot(previous_run: WatchRun | None) -> dict | None:
    if previous_run and isinstance(previous_run.metadata_json, dict):
        return {
            key: value
            for key, value in previous_run.metadata_json.items()
            if key != "run_summary"
        }
    return None


def _load_auto_watch_target(db: Session, watch_target_id: str) -> WatchTarget:
    watch_target = (
        db.query(WatchTarget)
        .filter(
            WatchTarget.id == watch_target_id,
            WatchTarget.deleted_at.is_(None),
        )
        .first()
    )
    if not watch_target:
        raise WatchTargetNotFoundError()
    return watch_target


def _create_running_watch_run(db: Session, watch_target: WatchTarget, *, metadata_json: dict) -> WatchRun:
    watch_run = WatchRun(
        id=str(uuid.uuid4()),
        watch_target_id=watch_target.id,
        status="running",
        started_at=utcnow(),
        items_found=0,
        signals_created=0,
        alerts_created=0,
        metadata_json=metadata_json,
    )
    db.add(watch_run)
    db.commit()
    db.refresh(watch_run)
    return watch_run


def _claim_pending_auto_run(
    db: Session,
    watch_target: WatchTarget,
    *,
    watch_run_id: str | None,
    scheduled_at: datetime | None,
    rq_job_id: str | None,
    retry_number: int,
) -> WatchRun:
    if watch_run_id:
        watch_run = (
            db.query(WatchRun)
            .filter(
                WatchRun.id == watch_run_id,
                WatchRun.watch_target_id == watch_target.id,
            )
            .first()
        )
    else:
        watch_run = None

    if not watch_run:
        watch_run = WatchRun(
            id=watch_run_id or str(uuid.uuid4()),
            watch_target_id=watch_target.id,
            status="pending",
            metadata_json={},
        )
        db.add(watch_run)
        db.commit()
        db.refresh(watch_run)

    watch_run.job_run_id = rq_job_id
    watch_run.status = "running"
    watch_run.started_at = watch_run.started_at or utcnow()
    watch_run.metadata_json = _automatic_watch_run_metadata(
        scheduled_at=scheduled_at,
        rq_job_id=rq_job_id,
        retry_number=retry_number,
        watch_run=watch_run,
    )
    db.commit()
    db.refresh(watch_run)
    return watch_run


def _collect_execution_result(db: Session, watch_target: WatchTarget) -> tuple[dict, int, int, bool]:
    current_snapshot = build_watch_snapshot(db, watch_target)
    previous_run = _latest_successful_run(db, watch_target.id)
    previous_snapshot = _build_previous_snapshot(previous_run)
    changes = detect_watch_changes(previous_snapshot, current_snapshot)
    signals_created = 0 if previous_snapshot is None else create_signals_for_changes(db, watch_target, current_snapshot, changes)
    items_found = (
        len(current_snapshot.get("intelligence_ids") or [])
        + len(current_snapshot.get("news_urls") or [])
        + len(current_snapshot.get("video_urls") or [])
        + len(current_snapshot.get("relation_keys") or [])
    )
    return current_snapshot, items_found, signals_created, previous_snapshot is None


def _mark_run_success(
    db: Session,
    watch_run: WatchRun,
    watch_target: WatchTarget,
    *,
    current_snapshot: dict,
    items_found: int,
    signals_created: int,
    baseline_created: bool,
    next_check_at: datetime | None,
    extra_summary: dict | None = None,
) -> WatchRun:
    finished_at = utcnow()
    run_summary = {
        "items_found": items_found,
        "signals_created": signals_created,
        "baseline_created": baseline_created,
    }
    if extra_summary:
        run_summary.update(extra_summary)

    watch_run.status = "success"
    watch_run.finished_at = finished_at
    watch_run.items_found = items_found
    watch_run.signals_created = signals_created
    watch_run.alerts_created = 0
    watch_run.error_code = None
    watch_run.error_message = None
    watch_run.metadata_json = {
        **current_snapshot,
        "run_summary": run_summary,
    }

    watch_target.last_checked_at = finished_at
    watch_target.last_success_at = finished_at
    watch_target.consecutive_failures = 0
    if next_check_at is not None or watch_target.frequency == "manual":
        watch_target.next_check_at = next_check_at

    db.commit()
    db.refresh(watch_run)
    return watch_run


def _mark_manual_run_failed(db: Session, watch_run: WatchRun, watch_target: WatchTarget, error_code: str, error_message: str) -> None:
    finished_at = utcnow()
    watch_run.status = "failed"
    watch_run.finished_at = finished_at
    watch_run.error_code = error_code
    watch_run.error_message = error_message
    watch_target.last_checked_at = finished_at
    watch_target.last_error_at = finished_at
    watch_target.consecutive_failures = (watch_target.consecutive_failures or 0) + 1
    db.commit()


def _mark_run_skipped(
    db: Session,
    watch_run: WatchRun,
    *,
    reason: str,
    rq_job_id: str | None,
) -> WatchRun:
    current_time = utcnow()
    metadata = _automatic_watch_run_metadata(
        scheduled_at=_scheduled_at_from_metadata(watch_run),
        rq_job_id=rq_job_id,
        retry_number=int((_base_metadata(watch_run).get("retry_number") or 0)),
        watch_run=watch_run,
    )
    metadata["duplicate_reason"] = reason
    watch_run.status = "skipped"
    watch_run.started_at = watch_run.started_at or current_time
    watch_run.finished_at = current_time
    watch_run.error_code = WATCH_RUN_DUPLICATE
    watch_run.error_message = reason
    watch_run.job_run_id = rq_job_id
    watch_run.metadata_json = metadata
    db.commit()
    db.refresh(watch_run)
    return watch_run


def _classify_error(exc: Exception) -> tuple[str, str]:
    if isinstance(exc, WatchTargetEntityNotFoundError):
        return exc.error_code, exc.message
    if isinstance(exc, WatchTargetDisabledError):
        return exc.error_code, exc.message
    if isinstance(exc, WatchTargetNotFoundError):
        return exc.error_code, exc.message
    if isinstance(exc, WatchRunAlreadyRunningError):
        return exc.error_code, exc.message
    if isinstance(exc, WatchRunError):
        return exc.error_code, str(exc)
    if isinstance(exc, LookupError):
        return "WATCH_TARGET_ENTITY_NOT_FOUND", str(exc)
    return "WATCH_RUN_FAILED", str(exc)[:300]


def _is_retryable_error(exc: Exception, error_code: str) -> bool:
    if error_code in {
        "WATCH_TARGET_ENTITY_NOT_FOUND",
        "WATCH_TARGET_DISABLED",
        "WATCH_TARGET_NOT_FOUND",
        "WATCH_RUN_DUPLICATE",
    }:
        return False

    if isinstance(exc, (TimeoutError, ConnectionError, OperationalError)):
        return True

    lowered = str(exc).lower()
    retryable_markers = [
        "timeout",
        "temporarily",
        "temporary",
        "database is locked",
        "connection reset",
        "connection aborted",
        "connection refused",
        "worker temporary",
    ]
    return any(marker in lowered for marker in retryable_markers)


def _retry_delay_seconds(retry_number: int) -> int:
    return retry_base_seconds() * (2 ** max(retry_number - 1, 0))


def _enqueue_retry_job(
    *,
    queue,
    watch_target_id: str,
    watch_run_id: str,
    retry_number: int,
) -> str | None:
    if queue is None:
        return None

    retry_job_id = build_retry_job_id(watch_target_id, watch_run_id, retry_number)
    fetch_job = getattr(queue, "fetch_job", None)
    if callable(fetch_job) and fetch_job(retry_job_id) is not None:
        return retry_job_id

    from workers.watch_tasks import execute_watch_target_job

    queue.enqueue(
        execute_watch_target_job,
        watch_target_id,
        watch_run_id,
        None,
        retry_number,
        job_id=retry_job_id,
        job_timeout=300,
        result_ttl=3600,
        meta={
            "watch_target_id": watch_target_id,
            "watch_run_id": watch_run_id,
            "retry_number": retry_number,
        },
    )
    return retry_job_id


def _mark_auto_run_for_retry(
    db: Session,
    watch_run: WatchRun,
    watch_target: WatchTarget,
    *,
    error_code: str,
    error_message: str,
    next_retry_at: datetime,
    retry_number: int,
    rq_job_id: str | None,
    retry_job_id: str | None,
) -> WatchRun:
    current_time = utcnow()
    metadata = _automatic_watch_run_metadata(
        scheduled_at=_scheduled_at_from_metadata(watch_run),
        rq_job_id=rq_job_id,
        retry_number=retry_number,
        watch_run=watch_run,
    )
    metadata["retry"] = {
        "status": "scheduled",
        "next_retry_at": _isoformat(next_retry_at),
        "next_retry_number": retry_number,
        "retry_job_id": retry_job_id,
        "last_error_code": error_code,
    }
    watch_run.status = "pending"
    watch_run.error_code = error_code
    watch_run.error_message = error_message
    watch_run.metadata_json = metadata
    watch_target.last_checked_at = current_time
    watch_target.last_error_at = current_time
    watch_target.consecutive_failures = (watch_target.consecutive_failures or 0) + 1
    watch_target.next_check_at = next_retry_at
    db.commit()
    db.refresh(watch_run)
    return watch_run


def _mark_auto_run_failed(
    db: Session,
    watch_run: WatchRun,
    watch_target: WatchTarget,
    *,
    error_code: str,
    error_message: str,
    scheduled_at: datetime | None,
    rq_job_id: str | None,
) -> WatchRun:
    current_time = utcnow()
    watch_target.last_checked_at = current_time
    watch_target.last_error_at = current_time
    watch_target.consecutive_failures = (watch_target.consecutive_failures or 0) + 1

    metadata = _automatic_watch_run_metadata(
        scheduled_at=scheduled_at,
        rq_job_id=rq_job_id,
        retry_number=int((_base_metadata(watch_run).get("retry_number") or 0)),
        watch_run=watch_run,
    )
    metadata["retry"] = {
        "status": "stopped",
        "last_error_code": error_code,
    }

    final_error_code = error_code
    final_error_message = error_message
    if watch_target.consecutive_failures >= max_consecutive_failures():
        watch_target.status = "paused"
        watch_target.next_check_at = None
        final_error_code = WATCH_TARGET_AUTO_PAUSED
        final_error_message = f"Watch target auto-paused after {watch_target.consecutive_failures} consecutive failures"
        metadata["auto_paused"] = True
    else:
        watch_target.next_check_at = advance_next_check_at(
            frequency=watch_target.frequency,
            scheduled_at=scheduled_at,
            now=current_time,
        )

    watch_run.status = "failed"
    watch_run.finished_at = current_time
    watch_run.error_code = final_error_code
    watch_run.error_message = final_error_message
    watch_run.metadata_json = metadata
    db.commit()
    db.refresh(watch_run)
    return watch_run


def _mark_failed_without_target(
    db: Session,
    *,
    watch_run_id: str | None,
    rq_job_id: str | None,
    error_code: str,
    error_message: str,
) -> WatchRun:
    watch_run = db.query(WatchRun).filter(WatchRun.id == watch_run_id).first()
    if not watch_run:
        raise WatchTargetNotFoundError()

    current_time = utcnow()
    metadata = _base_metadata(watch_run)
    metadata["trigger"] = "automatic"
    metadata["rq_job_id"] = rq_job_id
    watch_run.status = "failed"
    watch_run.started_at = watch_run.started_at or current_time
    watch_run.finished_at = current_time
    watch_run.error_code = error_code
    watch_run.error_message = error_message[:300]
    watch_run.job_run_id = rq_job_id
    watch_run.metadata_json = metadata
    db.commit()
    db.refresh(watch_run)
    return watch_run


def _run_manual_watch_target(db: Session, watch_target_id: str, user_id: str) -> WatchRun:
    watch_target = get_owned_watch_target(db, watch_target_id, user_id)
    if watch_target.status == "disabled":
        raise WatchTargetDisabledError()
    if _running_watch_run_exists(db, watch_target.id):
        raise WatchRunAlreadyRunningError()

    watch_run = _create_running_watch_run(
        db,
        watch_target,
        metadata_json=_manual_watch_run_metadata(),
    )

    try:
        current_snapshot, items_found, signals_created, baseline_created = _collect_execution_result(db, watch_target)
        return _mark_run_success(
            db,
            watch_run,
            watch_target,
            current_snapshot=current_snapshot,
            items_found=items_found,
            signals_created=signals_created,
            baseline_created=baseline_created,
            next_check_at=watch_target.next_check_at,
        )
    except LookupError as exc:
        _mark_manual_run_failed(db, watch_run, watch_target, "WATCH_TARGET_ENTITY_NOT_FOUND", str(exc))
        raise WatchTargetEntityNotFoundError() from exc
    except Exception as exc:
        _mark_manual_run_failed(db, watch_run, watch_target, "WATCH_RUN_FAILED", str(exc))
        raise WatchRunError() from exc


def _run_automatic_watch_target(
    db: Session,
    watch_target_id: str,
    *,
    watch_run_id: str | None,
    scheduled_at: datetime | None,
    retry_number: int,
    rq_job_id: str | None,
    queue,
) -> WatchRun:
    try:
        watch_target = _load_auto_watch_target(db, watch_target_id)
    except WatchTargetNotFoundError as exc:
        return _mark_failed_without_target(
            db,
            watch_run_id=watch_run_id,
            rq_job_id=rq_job_id,
            error_code=exc.error_code,
            error_message=exc.message,
        )

    watch_run = _claim_pending_auto_run(
        db,
        watch_target,
        watch_run_id=watch_run_id,
        scheduled_at=scheduled_at,
        rq_job_id=rq_job_id,
        retry_number=retry_number,
    )
    scheduled_at = scheduled_at or _scheduled_at_from_metadata(watch_run) or watch_target.next_check_at
    current_time = utcnow()

    if watch_target.status != "active" or watch_target.next_check_at is None or watch_target.next_check_at > current_time:
        return _mark_run_skipped(
            db,
            watch_run,
            reason="target_not_due",
            rq_job_id=rq_job_id,
        )

    if _running_watch_run_exists(db, watch_target.id, exclude_run_id=watch_run.id):
        return _mark_run_skipped(
            db,
            watch_run,
            reason="duplicate_running_watch_run",
            rq_job_id=rq_job_id,
        )

    try:
        current_snapshot, items_found, signals_created, baseline_created = _collect_execution_result(db, watch_target)
        next_check_at = advance_next_check_at(
            frequency=watch_target.frequency,
            scheduled_at=scheduled_at,
            now=utcnow(),
        )
        return _mark_run_success(
            db,
            watch_run,
            watch_target,
            current_snapshot=current_snapshot,
            items_found=items_found,
            signals_created=signals_created,
            baseline_created=baseline_created,
            next_check_at=next_check_at,
            extra_summary={
                "trigger": "automatic",
                "scheduled_at": _isoformat(scheduled_at),
                "retry_number": retry_number,
                "rq_job_id": rq_job_id,
            },
        )
    except Exception as exc:
        error_code, error_message = _classify_error(exc)
        if _is_retryable_error(exc, error_code) and retry_number < max_retries():
            next_retry_number = retry_number + 1
            next_retry_at = utcnow() + timedelta(seconds=_retry_delay_seconds(next_retry_number))
            try:
                retry_job_id = _enqueue_retry_job(
                    queue=queue,
                    watch_target_id=watch_target.id,
                    watch_run_id=watch_run.id,
                    retry_number=next_retry_number,
                )
            except Exception as retry_exc:
                return _mark_auto_run_failed(
                    db,
                    watch_run,
                    watch_target,
                    error_code="WATCH_RUN_FAILED",
                    error_message=str(retry_exc),
                    scheduled_at=scheduled_at,
                    rq_job_id=rq_job_id,
                )
            return _mark_auto_run_for_retry(
                db,
                watch_run,
                watch_target,
                error_code=error_code,
                error_message=error_message,
                next_retry_at=next_retry_at,
                retry_number=next_retry_number,
                rq_job_id=rq_job_id,
                retry_job_id=retry_job_id,
            )

        return _mark_auto_run_failed(
            db,
            watch_run,
            watch_target,
            error_code=error_code,
            error_message=error_message,
            scheduled_at=scheduled_at,
            rq_job_id=rq_job_id,
        )


def run_watch_target(
    db: Session,
    watch_target_id: str,
    user_id: str | None = None,
    *,
    trigger: str = "manual",
    watch_run_id: str | None = None,
    scheduled_at: datetime | None = None,
    retry_number: int = 0,
    rq_job_id: str | None = None,
    queue=None,
) -> WatchRun:
    if trigger == "manual":
        if not user_id:
            raise WatchTargetNotFoundError()
        return _run_manual_watch_target(db, watch_target_id, user_id)
    if trigger == "automatic":
        return _run_automatic_watch_target(
            db,
            watch_target_id,
            watch_run_id=watch_run_id,
            scheduled_at=scheduled_at,
            retry_number=retry_number,
            rq_job_id=rq_job_id,
            queue=queue,
        )
    raise ValueError(f"unsupported watch trigger: {trigger}")


def list_watch_target_signals(
    db: Session,
    watch_target_id: str,
    user_id: str,
    *,
    signal_type: str | None,
    severity: str | None,
    page: int,
    page_size: int,
):
    watch_target = get_owned_watch_target(db, watch_target_id, user_id)
    return list_signals_for_watch_target(
        db,
        watch_target.id,
        signal_type=signal_type,
        severity=severity,
        page=page,
        page_size=page_size,
    )
