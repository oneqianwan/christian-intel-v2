from __future__ import annotations

import importlib
import os
import sys
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

MODULES_TO_PURGE = [
    "config",
    "main",
    "models",
    "models.database",
    "models.auth",
    "models.watch_alert",
    "routers.health",
    "services.runtime_metrics",
    "services.monitoring_events",
    "services.production_readiness",
]


def _purge_modules() -> None:
    for module_name in MODULES_TO_PURGE:
        sys.modules.pop(module_name, None)


@pytest.fixture()
def monitoring_runtime(tmp_path: Path):
    test_db_path = tmp_path / f"monitoring_runtime_{uuid.uuid4().hex}.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{test_db_path.as_posix()}"
    _purge_modules()

    database = importlib.import_module("models.database")
    importlib.import_module("models.auth")
    importlib.import_module("models.watch_alert")
    monitoring_events = importlib.import_module("services.monitoring_events")
    main = importlib.import_module("main")
    monitoring_events.reset_monitoring_for_tests()

    client_ctx = TestClient(main.app)
    client = client_ctx.__enter__()
    try:
        yield {
            "client": client,
            "database": database,
            "monitoring_events": monitoring_events,
        }
    finally:
        client_ctx.__exit__(None, None, None)
        database.engine.dispose()
        _purge_modules()
        if test_db_path.exists():
            test_db_path.unlink()


def test_runtime_health_endpoint_returns_local_checks_and_counters(monitoring_runtime):
    response = monitoring_runtime["client"].get("/api/health/runtime")
    assert response.status_code == 200

    payload = response.json()
    assert payload["status"] in {"ok", "degraded"}
    assert payload["checks"]["database_config_ok"] is True
    assert payload["checks"]["account_token_storage_ok"] is True
    assert payload["checks"]["production_authentication_ready"] is True
    assert payload["checks"]["tenant_isolation_ready"] is True
    assert payload["checks"]["rate_limit_runtime_guardrails_present"] is True
    assert payload["monitoring"]["counters"]["rate_limit_trips"] == 0
    assert payload["monitoring"]["counters"]["auth_failures"] == 0
    assert payload["monitoring"]["counters"]["tenant_isolation_denials"] == 0
    assert payload["monitoring"]["counters"]["background_job_failures"] == 0
    assert payload["monitoring"]["counters"]["monitoring_events_total"] == 0
    assert payload["monitoring"]["counters"]["alert_events_total"] == 0


def test_ready_endpoint_reports_monitoring_ready_but_public_saas_still_blocked(monitoring_runtime):
    response = monitoring_runtime["client"].get("/api/ready")
    assert response.status_code == 200

    payload = response.json()
    monitoring = payload["monitoring_alerting_readiness"]
    blockers = set(payload["public_saas_blockers"])

    assert payload["status"] == "ready"
    assert monitoring["monitoring_alerting_readiness"] == "ready"
    assert monitoring["runtime_health_endpoint_ready"] == "yes"
    assert monitoring["readiness_endpoint_ready"] == "yes"
    assert monitoring["metrics_snapshot_ready"] == "yes"
    assert monitoring["internal_monitoring_event_sink_ready"] == "yes"
    assert payload["public_saas_ready"] is False
    assert "monitoring_alerting_not_fully_validated" not in blockers
    assert "billing_not_implemented" in blockers
    assert "rate_limit_not_fully_validated" in blockers
    assert "backup_recovery_not_fully_validated" in blockers
    assert "deployment_health_checks_not_fully_validated" in blockers
