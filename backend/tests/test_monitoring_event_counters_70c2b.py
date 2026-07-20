from __future__ import annotations

import importlib
import os
import sys
import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

MODULES_TO_PURGE = [
    "config",
    "models",
    "models.database",
    "models.auth",
    "models.watch_alert",
    "services.auth_service",
    "services.rate_limiter",
    "services.monitoring_events",
    "dependencies.rate_limit",
    "routers.diagnostics",
    "workers.watch_tasks",
]


def _purge_modules() -> None:
    for module_name in MODULES_TO_PURGE:
        sys.modules.pop(module_name, None)


@pytest.fixture()
def monitoring_modules(tmp_path: Path):
    test_db_path = tmp_path / f"monitoring_events_{uuid.uuid4().hex}.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{test_db_path.as_posix()}"
    _purge_modules()

    database = importlib.import_module("models.database")
    auth_models = importlib.import_module("models.auth")
    importlib.import_module("models.watch_alert")
    auth_service = importlib.import_module("services.auth_service")
    monitoring_events = importlib.import_module("services.monitoring_events")
    rate_limit_module = importlib.import_module("dependencies.rate_limit")
    rate_limiter_module = importlib.import_module("services.rate_limiter")
    diagnostics_module = importlib.import_module("routers.diagnostics")
    watch_tasks = importlib.import_module("workers.watch_tasks")
    database.init_db()
    monitoring_events.reset_monitoring_for_tests()
    monitoring_events.set_monitoring_time_for_tests(1000)

    try:
        yield {
            "database": database,
            "auth_models": auth_models,
            "auth_service": auth_service,
            "monitoring_events": monitoring_events,
            "rate_limit_module": rate_limit_module,
            "rate_limiter_module": rate_limiter_module,
            "diagnostics_module": diagnostics_module,
            "watch_tasks": watch_tasks,
        }
    finally:
        database.engine.dispose()
        _purge_modules()
        if test_db_path.exists():
            test_db_path.unlink()


def test_monitoring_counters_cover_rate_limit_auth_tenant_and_background_paths(monitoring_modules, monkeypatch):
    limiter = monitoring_modules["rate_limiter_module"].InMemoryRateLimiter(
        rules={
            "test": monitoring_modules["rate_limiter_module"].RateLimitRule(
                name="test",
                limit=1,
                window_seconds=60,
                key_parts=("ip", "route"),
            )
        }
    )
    limiter.set_time_for_tests(1000)
    monkeypatch.setattr(monitoring_modules["rate_limit_module"], "get_rate_limiter", lambda: limiter)

    app = FastAPI()

    @app.get("/limited")
    def limited(request: Request):
        monitoring_modules["rate_limit_module"].enforce_rate_limit_for_request(request, rule_name="test")
        return {"ok": True}

    client = TestClient(app)
    assert client.get("/limited").status_code == 200
    assert client.get("/limited").status_code == 429

    db = monitoring_modules["database"].SessionLocal()
    try:
        with pytest.raises(monitoring_modules["auth_service"].AuthError):
            monitoring_modules["auth_service"].authenticate_user(
                db,
                email="unknown@example.com",
                password="pw",
                client_fingerprint="client-1",
            )
    finally:
        db.close()

    with pytest.raises(Exception):
        monitoring_modules["diagnostics_module"]._raise_api_error(403, "TENANT_REQUIRED", "Tenant required")

    db = monitoring_modules["database"].SessionLocal()
    try:
        watch_run = monitoring_modules["database"].WatchRun(
            id="run-monitoring",
            watch_target_id="missing-target",
            status="running",
            metadata_json={},
        )
        db.add(watch_run)
        db.commit()
        monitoring_modules["watch_tasks"]._mark_failed_without_target(
            db,
            watch_run_id="run-monitoring",
            rq_job_id="rq-monitoring",
            error_message="boom",
        )
    finally:
        db.close()

    snapshot = monitoring_modules["monitoring_events"].monitoring_snapshot()
    assert snapshot["counters"]["rate_limit_trips"] == 1
    assert snapshot["counters"]["auth_failures"] == 1
    assert snapshot["counters"]["tenant_isolation_denials"] == 1
    assert snapshot["counters"]["background_job_failures"] >= 1
    assert snapshot["counters"]["monitoring_events_total"] >= 4
    assert snapshot["counters"]["alert_events_total"] >= 3
    assert snapshot["total_events"] >= 4
    assert snapshot["total_alerts"] >= 3


def test_monitoring_reset_for_tests_clears_counters_and_events(monitoring_modules):
    monitoring_modules["monitoring_events"].record_monitoring_event(
        event_type="manual-test",
        severity="warning",
        message="manual",
        alert=True,
    )
    before = monitoring_modules["monitoring_events"].monitoring_snapshot()
    assert before["counters"]["monitoring_events_total"] >= 1

    monitoring_modules["monitoring_events"].reset_monitoring_for_tests()
    after = monitoring_modules["monitoring_events"].monitoring_snapshot()
    assert after["counters"]["rate_limit_trips"] == 0
    assert after["counters"]["auth_failures"] == 0
    assert after["counters"]["tenant_isolation_denials"] == 0
    assert after["counters"]["background_job_failures"] == 0
    assert after["counters"]["monitoring_events_total"] == 0
    assert after["counters"]["alert_events_total"] == 0
    assert after["events"] == []
    assert after["alerts"] == []
