from __future__ import annotations

import uuid

from datetime import datetime

from sqlalchemy.orm import Session

from models.watch_alert import WatchRun, WatchTarget
from services.signal_service import create_signals_for_changes, list_signals_for_watch_target
from services.watch_change_detector import detect_watch_changes
from services.watch_snapshot_builder import build_watch_snapshot
from services.watch_target_service import WatchTargetEntityNotFoundError, WatchTargetNotFoundError, get_owned_watch_target


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


def _running_watch_run_exists(db: Session, watch_target_id: str) -> bool:
    return (
        db.query(WatchRun.id)
        .filter(
            WatchRun.watch_target_id == watch_target_id,
            WatchRun.status == "running",
        )
        .first()
        is not None
    )


def _mark_run_failed(db: Session, watch_run: WatchRun, watch_target: WatchTarget, error_code: str, error_message: str) -> None:
    finished_at = datetime.utcnow()
    watch_run.status = "failed"
    watch_run.finished_at = finished_at
    watch_run.error_code = error_code
    watch_run.error_message = error_message
    watch_target.last_checked_at = finished_at
    watch_target.last_error_at = finished_at
    watch_target.consecutive_failures = (watch_target.consecutive_failures or 0) + 1
    db.commit()


def run_watch_target(db: Session, watch_target_id: str, user_id: str) -> WatchRun:
    watch_target = get_owned_watch_target(db, watch_target_id, user_id)
    if watch_target.status == "disabled":
        raise WatchTargetDisabledError()
    if _running_watch_run_exists(db, watch_target.id):
        raise WatchRunAlreadyRunningError()

    started_at = datetime.utcnow()
    watch_run = WatchRun(
        id=str(uuid.uuid4()),
        watch_target_id=watch_target.id,
        status="running",
        started_at=started_at,
        items_found=0,
        signals_created=0,
        alerts_created=0,
        metadata_json={},
    )
    db.add(watch_run)
    db.commit()
    db.refresh(watch_run)

    try:
        current_snapshot = build_watch_snapshot(db, watch_target)
        previous_run = _latest_successful_run(db, watch_target.id)
        previous_snapshot = None
        if previous_run and isinstance(previous_run.metadata_json, dict):
            previous_snapshot = {
                key: value
                for key, value in previous_run.metadata_json.items()
                if key != "run_summary"
            }

        changes = detect_watch_changes(previous_snapshot, current_snapshot)
        signals_created = 0 if previous_snapshot is None else create_signals_for_changes(db, watch_target, current_snapshot, changes)
        finished_at = datetime.utcnow()

        items_found = (
            len(current_snapshot.get("intelligence_ids") or [])
            + len(current_snapshot.get("news_urls") or [])
            + len(current_snapshot.get("video_urls") or [])
            + len(current_snapshot.get("relation_keys") or [])
        )

        watch_run.status = "success"
        watch_run.finished_at = finished_at
        watch_run.items_found = items_found
        watch_run.signals_created = signals_created
        watch_run.alerts_created = 0
        watch_run.error_code = None
        watch_run.error_message = None
        watch_run.metadata_json = {
            **current_snapshot,
            "run_summary": {
                "items_found": items_found,
                "signals_created": signals_created,
                "baseline_created": previous_snapshot is None,
            },
        }

        watch_target.last_checked_at = finished_at
        watch_target.last_success_at = finished_at
        watch_target.consecutive_failures = 0
        db.commit()
        db.refresh(watch_run)
        return watch_run
    except LookupError as exc:
        db.refresh(watch_target)
        db.refresh(watch_run)
        _mark_run_failed(db, watch_run, watch_target, "WATCH_TARGET_ENTITY_NOT_FOUND", str(exc))
        raise WatchTargetEntityNotFoundError() from exc
    except Exception as exc:
        db.refresh(watch_target)
        db.refresh(watch_run)
        _mark_run_failed(db, watch_run, watch_target, "WATCH_RUN_FAILED", str(exc))
        raise WatchRunError() from exc


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
