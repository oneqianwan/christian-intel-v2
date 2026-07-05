from __future__ import annotations

import json

from datetime import datetime

from rq import get_current_job

from models.database import SessionLocal
from models.watch_alert import WatchRun
from queue_client import get_collection_queue
from services.watch_runner import run_watch_target


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


def _mark_failed_without_target(db, watch_run_id: str | None, rq_job_id: str | None, error_message: str) -> WatchRun | None:
    if not watch_run_id:
        return None

    watch_run = db.query(WatchRun).filter(WatchRun.id == watch_run_id).first()
    if not watch_run:
        return None

    finished_at = datetime.utcnow()
    metadata = dict(watch_run.metadata_json or {}) if isinstance(watch_run.metadata_json, dict) else {}
    metadata["trigger"] = "automatic"
    metadata["rq_job_id"] = rq_job_id
    watch_run.status = "failed"
    watch_run.started_at = watch_run.started_at or finished_at
    watch_run.finished_at = finished_at
    watch_run.error_code = "WATCH_TARGET_NOT_FOUND"
    watch_run.error_message = error_message[:300]
    watch_run.job_run_id = rq_job_id
    watch_run.metadata_json = metadata
    db.commit()
    db.refresh(watch_run)
    return watch_run


def execute_watch_target_job(
    watch_target_id: str,
    watch_run_id: str,
    scheduled_at: str | None = None,
    retry_number: int = 0,
):
    job = get_current_job()
    rq_job_id = getattr(job, "id", None)
    db = SessionLocal()
    try:
        try:
            watch_run = run_watch_target(
                db,
                watch_target_id,
                trigger="automatic",
                watch_run_id=watch_run_id,
                scheduled_at=_parse_datetime(scheduled_at),
                retry_number=retry_number,
                rq_job_id=rq_job_id,
                queue=get_collection_queue(),
            )
        except Exception as exc:
            watch_run = _mark_failed_without_target(db, watch_run_id, rq_job_id, str(exc))

        payload = {
            "watch_target_id": watch_target_id,
            "watch_run_id": getattr(watch_run, "id", watch_run_id),
            "rq_job_id": rq_job_id,
            "retry_number": retry_number,
            "status": getattr(watch_run, "status", "failed"),
        }
        print(json.dumps(payload, ensure_ascii=False))
        return payload
    finally:
        db.close()
