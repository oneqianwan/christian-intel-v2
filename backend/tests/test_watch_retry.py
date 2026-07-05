from __future__ import annotations

import importlib
import os
import sys

from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

TEST_DB_PATH = BACKEND_DIR / "data" / "watch_alert_phase43b_retry_test.db"
MODULES_TO_PURGE = [
    "config",
    "models.watch_alert",
    "models.database",
    "schemas.watch_alert",
    "services.watch_target_service",
    "services.watch_scheduler",
    "services.watch_runner",
    "services.watch_snapshot_builder",
    "workers.watch_tasks",
]


class FakeJob:
    def __init__(self, func, args, kwargs):
        self.func = func
        self.args = args
        self.kwargs = kwargs
        self.id = kwargs["job_id"]
        self.meta = kwargs.get("meta", {})


class FakeQueue:
    def __init__(self):
        self.jobs = {}

    def fetch_job(self, job_id):
        return self.jobs.get(job_id)

    def enqueue(self, func, *args, **kwargs):
        job = FakeJob(func, args, kwargs)
        self.jobs[job.id] = job
        return job


def _purge_modules() -> None:
    for module_name in MODULES_TO_PURGE:
        sys.modules.pop(module_name, None)


def _set_flags(runtime, *, v1: bool, scheduler: bool) -> None:
    runtime["config"].settings.WATCH_ALERT_V1_ENABLED = v1
    runtime["config"].settings.WATCH_ALERT_SCHEDULER_ENABLED = scheduler


def _set_now(monkeypatch, runtime, current_time: datetime) -> None:
    monkeypatch.setattr(runtime["watch_target_service"], "utcnow", lambda: current_time)
    monkeypatch.setattr(runtime["watch_scheduler"], "utcnow", lambda: current_time)
    monkeypatch.setattr(runtime["watch_runner"], "utcnow", lambda: current_time)


@pytest.fixture(scope="module")
def runtime():
    TEST_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()

    os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH.as_posix()}"
    _purge_modules()

    config = importlib.import_module("config")
    database = importlib.import_module("models.database")
    schemas = importlib.import_module("schemas.watch_alert")
    watch_target_service = importlib.import_module("services.watch_target_service")
    watch_scheduler = importlib.import_module("services.watch_scheduler")
    watch_runner = importlib.import_module("services.watch_runner")
    watch_tasks = importlib.import_module("workers.watch_tasks")
    database.init_db()

    yield {
        "config": config,
        "database": database,
        "schemas": schemas,
        "watch_target_service": watch_target_service,
        "watch_scheduler": watch_scheduler,
        "watch_runner": watch_runner,
        "watch_tasks": watch_tasks,
    }

    database.engine.dispose()
    _purge_modules()
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()


@pytest.fixture(autouse=True)
def reset_state(runtime):
    database = runtime["database"]
    _set_flags(runtime, v1=True, scheduler=True)

    session = database.SessionLocal()
    try:
        session.query(database.Alert).delete()
        session.query(database.Signal).delete()
        session.query(database.WatchRun).delete()
        session.query(database.WatchTarget).delete()
        session.query(database.RelationEdge).delete()
        session.query(database.IntelligenceItem).delete()
        session.query(database.Source).delete()
        session.query(database.KnowledgeEntity).delete()
        session.query(database.OrganizationProfile).delete()
        session.commit()
    finally:
        session.close()

    yield


def _session(runtime):
    return runtime["database"].SessionLocal()


def _create_org(runtime, org_id: str, *, name: str | None = None):
    database = runtime["database"]
    session = _session(runtime)
    try:
        session.add(
            database.OrganizationProfile(
                id=org_id,
                name=name or org_id,
                country="PH",
                leader_name="Leader One",
                official_website="https://example.org",
                people_score=10,
                digital_score=20,
                intel_score=30,
            )
        )
        session.commit()
    finally:
        session.close()


def _create_due_watch_target(runtime, *, entity_id: str, frequency: str, now: datetime, consecutive_failures: int = 0) -> str:
    database = runtime["database"]
    session = _session(runtime)
    try:
        watch_target = database.WatchTarget(
            user_id="user-1",
            entity_id=entity_id,
            entity_type="organization",
            status="active",
            frequency=frequency,
            next_check_at=now,
            consecutive_failures=consecutive_failures,
        )
        session.add(watch_target)
        session.commit()
        session.refresh(watch_target)
        return watch_target.id
    finally:
        session.close()


def _enqueue_due_job(runtime, *, queue: FakeQueue, now: datetime, frequency: str = "daily", entity_id: str = "org-auto", consecutive_failures: int = 0):
    _create_org(runtime, entity_id, name=entity_id)
    target_id = _create_due_watch_target(
        runtime,
        entity_id=entity_id,
        frequency=frequency,
        now=now,
        consecutive_failures=consecutive_failures,
    )
    session = _session(runtime)
    try:
        runtime["watch_scheduler"].enqueue_due_watch_targets(session, queue=queue, now=now)
    finally:
        session.close()
    assert len(queue.jobs) == 1
    return target_id, next(iter(queue.jobs.values()))


def _execute_job(runtime, monkeypatch, queue: FakeQueue, job: FakeJob):
    monkeypatch.setattr(runtime["watch_tasks"], "get_current_job", lambda: SimpleNamespace(id=job.id))
    monkeypatch.setattr(runtime["watch_tasks"], "get_collection_queue", lambda: queue)
    return runtime["watch_tasks"].execute_watch_target_job(*job.args)


def test_14_worker_reuses_watch_runner(monkeypatch, runtime):
    captured = {}

    def fake_run_watch_target(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return SimpleNamespace(id="run-1", status="success")

    monkeypatch.setattr(runtime["watch_tasks"], "run_watch_target", fake_run_watch_target)
    monkeypatch.setattr(runtime["watch_tasks"], "get_current_job", lambda: SimpleNamespace(id="job-1"))
    monkeypatch.setattr(runtime["watch_tasks"], "get_collection_queue", lambda: FakeQueue())

    payload = runtime["watch_tasks"].execute_watch_target_job("target-1", "run-1", "2026-01-01T10:00:00", 0)

    assert payload["status"] == "success"
    assert captured["args"][1] == "target-1"
    assert captured["kwargs"]["trigger"] == "automatic"
    assert captured["kwargs"]["watch_run_id"] == "run-1"


def test_15_auto_run_success_generates_watch_run(monkeypatch, runtime):
    now = datetime(2026, 1, 1, 10, 0, 0)
    queue = FakeQueue()
    _set_now(monkeypatch, runtime, now)
    target_id, job = _enqueue_due_job(runtime, queue=queue, now=now, entity_id="org-auto-success")

    payload = _execute_job(runtime, monkeypatch, queue, job)

    session = _session(runtime)
    try:
        watch_run = session.query(runtime["database"].WatchRun).filter_by(watch_target_id=target_id).one()
    finally:
        session.close()

    assert payload["status"] == "success"
    assert watch_run.status == "success"
    assert watch_run.metadata_json["snapshot_version"] == 1
    assert watch_run.metadata_json["run_summary"]["trigger"] == "automatic"


def test_16_auto_success_calculates_daily_next_cycle(monkeypatch, runtime):
    now = datetime(2026, 1, 1, 10, 0, 0)
    queue = FakeQueue()
    _set_now(monkeypatch, runtime, now)
    target_id, job = _enqueue_due_job(runtime, queue=queue, now=now, frequency="daily", entity_id="org-daily-next")

    _execute_job(runtime, monkeypatch, queue, job)

    session = _session(runtime)
    try:
        target = session.query(runtime["database"].WatchTarget).filter_by(id=target_id).one()
    finally:
        session.close()

    assert target.next_check_at == now + timedelta(days=1)


def test_17_auto_success_calculates_weekly_next_cycle(monkeypatch, runtime):
    now = datetime(2026, 1, 1, 10, 0, 0)
    queue = FakeQueue()
    _set_now(monkeypatch, runtime, now)
    target_id, job = _enqueue_due_job(runtime, queue=queue, now=now, frequency="weekly", entity_id="org-weekly-next")

    _execute_job(runtime, monkeypatch, queue, job)

    session = _session(runtime)
    try:
        target = session.query(runtime["database"].WatchTarget).filter_by(id=target_id).one()
    finally:
        session.close()

    assert target.next_check_at == now + timedelta(days=7)


def test_18_execution_delay_does_not_cause_permanent_drift(monkeypatch, runtime):
    scheduled_at = datetime(2026, 1, 1, 10, 0, 0)
    executed_at = datetime(2026, 1, 3, 13, 0, 0)
    queue = FakeQueue()
    _set_now(monkeypatch, runtime, scheduled_at)
    target_id, job = _enqueue_due_job(runtime, queue=queue, now=scheduled_at, frequency="daily", entity_id="org-drift")

    _set_now(monkeypatch, runtime, executed_at)
    _execute_job(runtime, monkeypatch, queue, job)

    session = _session(runtime)
    try:
        target = session.query(runtime["database"].WatchTarget).filter_by(id=target_id).one()
    finally:
        session.close()

    assert target.next_check_at == datetime(2026, 1, 4, 10, 0, 0)


def test_22_first_retry_schedules_five_minutes(monkeypatch, runtime):
    now = datetime(2026, 1, 1, 10, 0, 0)
    queue = FakeQueue()
    _set_now(monkeypatch, runtime, now)
    target_id, job = _enqueue_due_job(runtime, queue=queue, now=now, entity_id="org-retry-1")
    monkeypatch.setattr(runtime["watch_runner"], "build_watch_snapshot", lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError("network timeout")))

    _execute_job(runtime, monkeypatch, queue, job)

    session = _session(runtime)
    try:
        target = session.query(runtime["database"].WatchTarget).filter_by(id=target_id).one()
        watch_run = session.query(runtime["database"].WatchRun).filter_by(watch_target_id=target_id).one()
    finally:
        session.close()

    assert watch_run.status == "pending"
    assert target.next_check_at == now + timedelta(minutes=5)
    assert runtime["watch_scheduler"].build_retry_job_id(target_id, watch_run.id, 1) in queue.jobs


def test_23_second_retry_schedules_ten_minutes(monkeypatch, runtime):
    now = datetime(2026, 1, 1, 10, 0, 0)
    second_attempt = now + timedelta(minutes=5)
    queue = FakeQueue()
    _set_now(monkeypatch, runtime, now)
    target_id, job = _enqueue_due_job(runtime, queue=queue, now=now, entity_id="org-retry-2")
    monkeypatch.setattr(runtime["watch_runner"], "build_watch_snapshot", lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError("network timeout")))
    _execute_job(runtime, monkeypatch, queue, job)

    retry_job = queue.fetch_job(next(job_id for job_id in queue.jobs if ":retry:" in job_id))
    _set_now(monkeypatch, runtime, second_attempt)
    _execute_job(runtime, monkeypatch, queue, retry_job)

    session = _session(runtime)
    try:
        target = session.query(runtime["database"].WatchTarget).filter_by(id=target_id).one()
        watch_run = session.query(runtime["database"].WatchRun).filter_by(watch_target_id=target_id).one()
    finally:
        session.close()

    assert watch_run.status == "pending"
    assert target.next_check_at == second_attempt + timedelta(minutes=10)
    assert runtime["watch_scheduler"].build_retry_job_id(target_id, watch_run.id, 2) in queue.jobs


def test_24_third_retry_schedules_twenty_minutes(monkeypatch, runtime):
    start = datetime(2026, 1, 1, 10, 0, 0)
    queue = FakeQueue()
    _set_now(monkeypatch, runtime, start)
    target_id, job = _enqueue_due_job(runtime, queue=queue, now=start, entity_id="org-retry-3")
    monkeypatch.setattr(runtime["watch_runner"], "build_watch_snapshot", lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError("network timeout")))
    _execute_job(runtime, monkeypatch, queue, job)

    retry_jobs = [queue.jobs[job_id] for job_id in queue.jobs if ":retry:" in job_id]
    _set_now(monkeypatch, runtime, start + timedelta(minutes=5))
    _execute_job(runtime, monkeypatch, queue, retry_jobs[-1])

    retry_jobs = [queue.jobs[job_id] for job_id in queue.jobs if ":retry:" in job_id]
    _set_now(monkeypatch, runtime, start + timedelta(minutes=15))
    _execute_job(runtime, monkeypatch, queue, retry_jobs[-1])

    session = _session(runtime)
    try:
        target = session.query(runtime["database"].WatchTarget).filter_by(id=target_id).one()
        watch_run = session.query(runtime["database"].WatchRun).filter_by(watch_target_id=target_id).one()
    finally:
        session.close()

    assert watch_run.status == "pending"
    assert target.next_check_at == start + timedelta(minutes=35)
    assert runtime["watch_scheduler"].build_retry_job_id(target_id, watch_run.id, 3) in queue.jobs


def test_25_retry_stops_after_max_attempts(monkeypatch, runtime):
    now = datetime(2026, 1, 1, 10, 0, 0)
    _create_org(runtime, "org-max-retries")
    target_id = _create_due_watch_target(runtime, entity_id="org-max-retries", frequency="daily", now=now)
    queue = FakeQueue()
    session = _session(runtime)
    try:
        watch_run = runtime["watch_scheduler"].create_pending_watch_run(
            session,
            session.query(runtime["database"].WatchTarget).filter_by(id=target_id).one(),
            scheduled_at=now,
            rq_job_id="watch-target:seed",
        )
    finally:
        session.close()

    monkeypatch.setattr(runtime["watch_runner"], "build_watch_snapshot", lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError("network timeout")))
    _set_now(monkeypatch, runtime, now)
    session = _session(runtime)
    try:
        final_run = runtime["watch_runner"].run_watch_target(
            session,
            target_id,
            trigger="automatic",
            watch_run_id=watch_run.id,
            scheduled_at=now,
            retry_number=3,
            rq_job_id="retry-job-3",
            queue=queue,
        )
    finally:
        session.close()

    session = _session(runtime)
    try:
        target = session.query(runtime["database"].WatchTarget).filter_by(id=target_id).one()
    finally:
        session.close()

    assert final_run.status == "failed"
    assert not any(job_id.endswith(":4") for job_id in queue.jobs)
    assert target.next_check_at == now + timedelta(days=1)


def test_26_non_retryable_error_does_not_schedule_retry(monkeypatch, runtime):
    now = datetime(2026, 1, 1, 10, 0, 0)
    queue = FakeQueue()
    _set_now(monkeypatch, runtime, now)
    target_id, job = _enqueue_due_job(runtime, queue=queue, now=now, entity_id="org-non-retryable")
    monkeypatch.setattr(runtime["watch_runner"], "build_watch_snapshot", lambda *args, **kwargs: (_ for _ in ()).throw(LookupError("WATCH_TARGET_ENTITY_NOT_FOUND")))

    _execute_job(runtime, monkeypatch, queue, job)

    session = _session(runtime)
    try:
        target = session.query(runtime["database"].WatchTarget).filter_by(id=target_id).one()
        watch_run = session.query(runtime["database"].WatchRun).filter_by(watch_target_id=target_id).one()
    finally:
        session.close()

    assert watch_run.status == "failed"
    assert watch_run.error_code == "WATCH_TARGET_ENTITY_NOT_FOUND"
    assert len([job_id for job_id in queue.jobs if ":retry:" in job_id]) == 0
    assert target.consecutive_failures == 1


def test_27_duplicate_task_does_not_increase_failures(monkeypatch, runtime):
    now = datetime(2026, 1, 1, 10, 0, 0)
    _create_org(runtime, "org-duplicate-skip")
    target_id = _create_due_watch_target(runtime, entity_id="org-duplicate-skip", frequency="daily", now=now, consecutive_failures=2)
    session = _session(runtime)
    try:
        target = session.query(runtime["database"].WatchTarget).filter_by(id=target_id).one()
        pending_run = runtime["watch_scheduler"].create_pending_watch_run(session, target, scheduled_at=now, rq_job_id="job-seed")
        pending_run_id = pending_run.id
        session.add(runtime["database"].WatchRun(id="run-other", watch_target_id=target_id, status="running"))
        session.commit()
    finally:
        session.close()

    _set_now(monkeypatch, runtime, now)
    session = _session(runtime)
    try:
        skipped = runtime["watch_runner"].run_watch_target(
            session,
            target_id,
            trigger="automatic",
            watch_run_id=pending_run_id,
            scheduled_at=now,
            retry_number=0,
            rq_job_id="job-run",
            queue=FakeQueue(),
        )
    finally:
        session.close()

    session = _session(runtime)
    try:
        target = session.query(runtime["database"].WatchTarget).filter_by(id=target_id).one()
    finally:
        session.close()

    assert skipped.status == "skipped"
    assert target.consecutive_failures == 2


def test_28_success_clears_consecutive_failures(monkeypatch, runtime):
    now = datetime(2026, 1, 1, 10, 0, 0)
    queue = FakeQueue()
    _set_now(monkeypatch, runtime, now)
    target_id, job = _enqueue_due_job(runtime, queue=queue, now=now, entity_id="org-clear-failures", consecutive_failures=2)

    _execute_job(runtime, monkeypatch, queue, job)

    session = _session(runtime)
    try:
        target = session.query(runtime["database"].WatchTarget).filter_by(id=target_id).one()
    finally:
        session.close()

    assert target.consecutive_failures == 0


def test_29_failure_increases_consecutive_failures(monkeypatch, runtime):
    now = datetime(2026, 1, 1, 10, 0, 0)
    queue = FakeQueue()
    _set_now(monkeypatch, runtime, now)
    target_id, job = _enqueue_due_job(runtime, queue=queue, now=now, entity_id="org-fail-increment")
    monkeypatch.setattr(runtime["watch_runner"], "build_watch_snapshot", lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("bad config")))

    _execute_job(runtime, monkeypatch, queue, job)

    session = _session(runtime)
    try:
        target = session.query(runtime["database"].WatchTarget).filter_by(id=target_id).one()
    finally:
        session.close()

    assert target.consecutive_failures == 1


def test_30_and_31_five_consecutive_failures_auto_pause(monkeypatch, runtime):
    now = datetime(2026, 1, 1, 10, 0, 0)
    queue = FakeQueue()
    _set_now(monkeypatch, runtime, now)
    target_id, job = _enqueue_due_job(runtime, queue=queue, now=now, entity_id="org-auto-pause", consecutive_failures=4)
    monkeypatch.setattr(runtime["watch_runner"], "build_watch_snapshot", lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("bad config")))

    _execute_job(runtime, monkeypatch, queue, job)

    session = _session(runtime)
    try:
        target = session.query(runtime["database"].WatchTarget).filter_by(id=target_id).one()
        watch_run = session.query(runtime["database"].WatchRun).filter_by(watch_target_id=target_id).one()
    finally:
        session.close()

    assert target.status == "paused"
    assert target.next_check_at is None
    assert watch_run.error_code == runtime["watch_scheduler"].WATCH_TARGET_AUTO_PAUSED


def test_33_worker_exception_does_not_leave_running_watch_run(monkeypatch, runtime):
    now = datetime(2026, 1, 1, 10, 0, 0)
    queue = FakeQueue()
    _set_now(monkeypatch, runtime, now)
    target_id, job = _enqueue_due_job(runtime, queue=queue, now=now, entity_id="org-no-running-left")
    monkeypatch.setattr(runtime["watch_runner"], "build_watch_snapshot", lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("bad config")))

    _execute_job(runtime, monkeypatch, queue, job)

    session = _session(runtime)
    try:
        running_count = session.query(runtime["database"].WatchRun).filter_by(watch_target_id=target_id, status="running").count()
    finally:
        session.close()

    assert running_count == 0
