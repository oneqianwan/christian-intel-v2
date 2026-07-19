from __future__ import annotations

import importlib
import os
import sys

from datetime import datetime, timedelta
from pathlib import Path

import pytest


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

TEST_DB_PATH = BACKEND_DIR / "data" / "watch_alert_phase43b_scheduler_test.db"
MODULES_TO_PURGE = [
    "config",
    "models.auth",
    "models.watch_alert",
    "models.database",
    "services.watch_alert_ownership",
    "schemas.watch_alert",
    "services.watch_target_service",
    "services.watch_scheduler",
    "services.watch_runner",
    "workers.watch_tasks",
    "scripts.run_watch_scheduler",
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
    runtime["config"].settings.WATCH_ALERT_USER_OWNERSHIP_ENABLED = False


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
    scheduler_script = importlib.import_module("scripts.run_watch_scheduler")
    database.init_db()

    _set_flags(
        {
            "config": config,
        },
        v1=True,
        scheduler=True,
    )

    yield {
        "config": config,
        "database": database,
        "schemas": schemas,
        "watch_target_service": watch_target_service,
        "watch_scheduler": watch_scheduler,
        "watch_runner": watch_runner,
        "watch_tasks": watch_tasks,
        "scheduler_script": scheduler_script,
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


def _create_org(runtime, org_id: str, name: str | None = None):
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


def _create_watch_target_direct(
    runtime,
    *,
    user_id: str,
    entity_id: str,
    frequency: str = "daily",
    status: str = "active",
    next_check_at: datetime | None = None,
    consecutive_failures: int = 0,
    deleted_at: datetime | None = None,
):
    database = runtime["database"]
    session = _session(runtime)
    try:
        watch_target = database.WatchTarget(
            tenant_id="tenant-1",
            user_id=user_id,
            entity_id=entity_id,
            entity_type="organization",
            status=status,
            frequency=frequency,
            next_check_at=next_check_at,
            consecutive_failures=consecutive_failures,
            deleted_at=deleted_at,
        )
        session.add(watch_target)
        session.commit()
        session.refresh(watch_target)
        return watch_target.id
    finally:
        session.close()


def test_01_scheduler_flag_disabled_does_not_scan(runtime):
    _create_org(runtime, "org-flag-disabled")
    _create_watch_target_direct(
        runtime,
        user_id="user-1",
        entity_id="org-flag-disabled",
        frequency="daily",
        next_check_at=datetime(2026, 1, 1, 8, 0, 0),
    )
    _set_flags(runtime, v1=True, scheduler=False)

    session = _session(runtime)
    try:
        due = runtime["watch_scheduler"].scan_due_watch_targets(
            session,
            now=datetime(2026, 1, 1, 9, 0, 0),
        )
    finally:
        session.close()

    assert due == []


def test_02_v1_flag_disabled_does_not_scan(runtime):
    _create_org(runtime, "org-v1-disabled")
    _create_watch_target_direct(
        runtime,
        user_id="user-1",
        entity_id="org-v1-disabled",
        frequency="daily",
        next_check_at=datetime(2026, 1, 1, 8, 0, 0),
    )
    _set_flags(runtime, v1=False, scheduler=True)

    session = _session(runtime)
    try:
        due = runtime["watch_scheduler"].scan_due_watch_targets(
            session,
            now=datetime(2026, 1, 1, 9, 0, 0),
        )
    finally:
        session.close()

    assert due == []


def test_03_daily_due_target_is_enqueued(runtime):
    now = datetime(2026, 1, 1, 10, 0, 0)
    queue = FakeQueue()
    _create_org(runtime, "org-daily-due")
    target_id = _create_watch_target_direct(
        runtime,
        user_id="user-1",
        entity_id="org-daily-due",
        frequency="daily",
        next_check_at=now - timedelta(minutes=1),
    )

    session = _session(runtime)
    try:
        stats = runtime["watch_scheduler"].enqueue_due_watch_targets(session, queue=queue, now=now)
        watch_run = session.query(runtime["database"].WatchRun).one()
    finally:
        session.close()

    assert stats["due_count"] == 1
    assert stats["enqueued_count"] == 1
    assert watch_run.status == "pending"
    assert watch_run.watch_target_id == target_id
    assert watch_run.metadata_json["tenant_id"] == "tenant-1"
    assert len(queue.jobs) == 1
    assert next(iter(queue.jobs.values())).meta["tenant_id"] == "tenant-1"


def test_04_weekly_due_target_is_enqueued(runtime):
    now = datetime(2026, 1, 1, 10, 0, 0)
    queue = FakeQueue()
    _create_org(runtime, "org-weekly-due")
    _create_watch_target_direct(
        runtime,
        user_id="user-1",
        entity_id="org-weekly-due",
        frequency="weekly",
        next_check_at=now - timedelta(hours=1),
    )

    session = _session(runtime)
    try:
        stats = runtime["watch_scheduler"].enqueue_due_watch_targets(session, queue=queue, now=now)
    finally:
        session.close()

    assert stats["enqueued_count"] == 1
    assert len(queue.jobs) == 1


def test_05_to_09_non_eligible_targets_are_not_enqueued(runtime):
    now = datetime(2026, 1, 1, 10, 0, 0)
    queue = FakeQueue()
    for suffix in ["manual", "paused", "disabled", "deleted", "future", "valid"]:
        _create_org(runtime, f"org-{suffix}")

    _create_watch_target_direct(runtime, user_id="user-1", entity_id="org-manual", frequency="manual", next_check_at=None)
    _create_watch_target_direct(runtime, user_id="user-1", entity_id="org-paused", status="paused", next_check_at=now - timedelta(minutes=1))
    _create_watch_target_direct(runtime, user_id="user-1", entity_id="org-disabled", status="disabled", next_check_at=now - timedelta(minutes=1))
    _create_watch_target_direct(
        runtime,
        user_id="user-1",
        entity_id="org-deleted",
        next_check_at=now - timedelta(minutes=1),
        deleted_at=now - timedelta(days=1),
    )
    _create_watch_target_direct(runtime, user_id="user-1", entity_id="org-future", next_check_at=now + timedelta(minutes=30))
    valid_target_id = _create_watch_target_direct(runtime, user_id="user-1", entity_id="org-valid", next_check_at=now - timedelta(minutes=5))

    session = _session(runtime)
    try:
        due = runtime["watch_scheduler"].scan_due_watch_targets(session, now=now)
    finally:
        session.close()

    assert [target.id for target in due] == [valid_target_id]


def test_10_existing_running_watch_run_is_not_reenqueued(runtime):
    now = datetime(2026, 1, 1, 10, 0, 0)
    _create_org(runtime, "org-running")
    target_id = _create_watch_target_direct(runtime, user_id="user-1", entity_id="org-running", next_check_at=now - timedelta(minutes=5))

    session = _session(runtime)
    try:
        session.add(runtime["database"].WatchRun(id="run-running", watch_target_id=target_id, status="running"))
        session.commit()
        due = runtime["watch_scheduler"].scan_due_watch_targets(session, now=now)
    finally:
        session.close()

    assert due == []


def test_11_same_job_id_is_not_duplicated(runtime):
    now = datetime(2026, 1, 1, 10, 0, 0)
    queue = FakeQueue()
    _create_org(runtime, "org-dup-job")
    _create_watch_target_direct(runtime, user_id="user-1", entity_id="org-dup-job", next_check_at=now - timedelta(minutes=1))

    session = _session(runtime)
    try:
        first = runtime["watch_scheduler"].enqueue_due_watch_targets(session, queue=queue, now=now)
        second = runtime["watch_scheduler"].enqueue_due_watch_targets(session, queue=queue, now=now)
        skipped_count = session.query(runtime["database"].WatchRun).filter_by(status="skipped").count()
    finally:
        session.close()

    assert first["enqueued_count"] == 1
    assert second["duplicate_count"] == 1
    assert len(queue.jobs) == 1
    assert skipped_count == 1


def test_12_scan_limit_applies(runtime):
    now = datetime(2026, 1, 1, 10, 0, 0)
    for idx in range(3):
        _create_org(runtime, f"org-limit-{idx}")
        _create_watch_target_direct(
            runtime,
            user_id="user-1",
            entity_id=f"org-limit-{idx}",
            next_check_at=now - timedelta(minutes=idx + 1),
        )

    session = _session(runtime)
    try:
        due = runtime["watch_scheduler"].scan_due_watch_targets(session, now=now, limit=2)
    finally:
        session.close()

    assert len(due) == 2


def test_13_due_targets_are_ordered_by_next_check_at(runtime):
    now = datetime(2026, 1, 1, 10, 0, 0)
    expected = []
    for minutes in [30, 20, 10]:
        entity_id = f"org-order-{minutes}"
        _create_org(runtime, entity_id)
        target_id = _create_watch_target_direct(
            runtime,
            user_id="user-1",
            entity_id=entity_id,
            next_check_at=now - timedelta(minutes=minutes),
        )
        expected.append((target_id, now - timedelta(minutes=minutes)))

    session = _session(runtime)
    try:
        due = runtime["watch_scheduler"].scan_due_watch_targets(session, now=now, limit=10)
    finally:
        session.close()

    assert [target.id for target in due] == [item[0] for item in sorted(expected, key=lambda item: item[1])]


def test_19_frequency_change_recalculates_next_check_at(monkeypatch, runtime):
    now = datetime(2026, 1, 1, 10, 0, 0)
    _set_now(monkeypatch, runtime, now)
    _create_org(runtime, "org-frequency-recalc")
    session = _session(runtime)
    try:
        watch_target = runtime["watch_target_service"].create_watch_target(
            session,
            "user-1",
            runtime["schemas"].WatchTargetCreate(
                entity_id="org-frequency-recalc",
                entity_type="organization",
                frequency="daily",
            ),
        )
        updated = runtime["watch_target_service"].update_watch_target(
            session,
            watch_target.id,
            "user-1",
            runtime["schemas"].WatchTargetUpdate(frequency="weekly"),
        )
    finally:
        session.close()

    assert updated.next_check_at == now + timedelta(days=7)


def test_20_paused_or_disabled_sets_next_check_at_null(monkeypatch, runtime):
    now = datetime(2026, 1, 1, 10, 0, 0)
    _set_now(monkeypatch, runtime, now)
    _create_org(runtime, "org-status-null")
    session = _session(runtime)
    try:
        watch_target = runtime["watch_target_service"].create_watch_target(
            session,
            "user-1",
            runtime["schemas"].WatchTargetCreate(
                entity_id="org-status-null",
                entity_type="organization",
                frequency="daily",
            ),
        )
        paused = runtime["watch_target_service"].update_watch_target(
            session,
            watch_target.id,
            "user-1",
            runtime["schemas"].WatchTargetUpdate(status="paused"),
        )
        disabled = runtime["watch_target_service"].update_watch_target(
            session,
            watch_target.id,
            "user-1",
            runtime["schemas"].WatchTargetUpdate(status="disabled"),
        )
    finally:
        session.close()

    assert paused.next_check_at is None
    assert disabled.next_check_at is None


def test_21_restore_active_recalculates_next_check_at(monkeypatch, runtime):
    create_now = datetime(2026, 1, 1, 10, 0, 0)
    resume_now = datetime(2026, 1, 3, 8, 30, 0)
    _create_org(runtime, "org-restore-active")
    session = _session(runtime)
    try:
        _set_now(monkeypatch, runtime, create_now)
        watch_target = runtime["watch_target_service"].create_watch_target(
            session,
            "user-1",
            runtime["schemas"].WatchTargetCreate(
                entity_id="org-restore-active",
                entity_type="organization",
                frequency="daily",
            ),
        )
        runtime["watch_target_service"].update_watch_target(
            session,
            watch_target.id,
            "user-1",
            runtime["schemas"].WatchTargetUpdate(status="paused"),
        )
        _set_now(monkeypatch, runtime, resume_now)
        restored = runtime["watch_target_service"].update_watch_target(
            session,
            watch_target.id,
            "user-1",
            runtime["schemas"].WatchTargetUpdate(status="active"),
        )
    finally:
        session.close()

    assert restored.next_check_at == resume_now + timedelta(days=1)


def test_32_scheduler_runs_single_round_and_exits(monkeypatch, runtime):
    now = datetime(2026, 1, 1, 10, 0, 0)
    queue = FakeQueue()
    _set_now(monkeypatch, runtime, now)
    _create_org(runtime, "org-script")
    _create_watch_target_direct(runtime, user_id="user-1", entity_id="org-script", next_check_at=now - timedelta(minutes=1))

    session = _session(runtime)
    try:
        stats = runtime["watch_scheduler"].run_watch_scheduler_once(session, queue=queue, now=now)
    finally:
        session.close()

    assert stats["enqueued_count"] == 1
    assert stats["scan_finished_at"] is not None


def test_33_null_tenant_target_is_skipped_fail_closed(runtime):
    now = datetime(2026, 1, 1, 10, 0, 0)
    queue = FakeQueue()
    _create_org(runtime, "org-null-tenant")
    database = runtime["database"]
    session = _session(runtime)
    try:
        watch_target = database.WatchTarget(
            tenant_id=None,
            user_id="user-1",
            entity_id="org-null-tenant",
            entity_type="organization",
            status="active",
            frequency="daily",
            next_check_at=now - timedelta(minutes=1),
        )
        session.add(watch_target)
        session.commit()
        session.refresh(watch_target)
        due = runtime["watch_scheduler"].scan_due_watch_targets(session, now=now)
        stats = runtime["watch_scheduler"].enqueue_due_watch_targets(session, queue=queue, now=now)
    finally:
        session.close()

    assert due == []
    assert stats["due_count"] == 0
    assert stats["skipped_count"] == 0
    assert stats["enqueued_count"] == 0
    assert queue.jobs == {}
