from __future__ import annotations

import importlib
import os
import sys

from datetime import datetime
from pathlib import Path

import pytest

from fastapi import HTTPException
from fastapi.testclient import TestClient


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

TEST_DB_PATH = BACKEND_DIR / "data" / "watch_alert_phase44_api_test.db"
MODULES_TO_PURGE = [
    "config",
    "main",
    "models.watch_alert",
    "models.database",
    "routers.alerts",
    "routers.watch_targets",
    "schemas.watch_alert",
    "services.alert_service",
]


def _purge_modules() -> None:
    for module_name in MODULES_TO_PURGE:
        sys.modules.pop(module_name, None)


def _set_flags(runtime, *, v1: bool = True, notifications: bool = True) -> None:
    runtime["config"].settings.WATCH_ALERT_V1_ENABLED = v1
    runtime["config"].settings.WATCH_ALERT_NOTIFICATIONS_ENABLED = notifications


@pytest.fixture(scope="module")
def runtime():
    TEST_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()

    os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH.as_posix()}"
    _purge_modules()

    config = importlib.import_module("config")
    database = importlib.import_module("models.database")
    alerts_router = importlib.import_module("routers.alerts")
    main = importlib.import_module("main")

    _set_flags({"config": config}, v1=True, notifications=True)

    client_ctx = TestClient(main.app)
    client = client_ctx.__enter__()

    yield {
        "config": config,
        "database": database,
        "router_module": alerts_router,
        "app": main.app,
        "client": client,
    }

    client_ctx.__exit__(None, None, None)
    database.engine.dispose()
    _purge_modules()
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()


@pytest.fixture(autouse=True)
def reset_state(runtime):
    _set_flags(runtime)
    database = runtime["database"]
    app = runtime["app"]
    router_module = runtime["router_module"]

    current_user = {"value": "user-1"}

    def override_get_current_user_id():
        if not current_user["value"]:
            raise HTTPException(
                status_code=401,
                detail={"error_code": "AUTH_REQUIRED", "message": "Authentication required"},
            )
        return current_user["value"]

    app.dependency_overrides[router_module.get_current_user_id] = override_get_current_user_id

    session = database.SessionLocal()
    try:
        session.query(database.Alert).delete()
        session.query(database.AlertRule).delete()
        session.query(database.Signal).delete()
        session.query(database.WatchRun).delete()
        session.query(database.WatchTarget).delete()
        session.query(database.KnowledgeEntity).delete()
        session.query(database.OrganizationProfile).delete()
        session.commit()
    finally:
        session.close()

    yield current_user

    app.dependency_overrides.clear()


def _session(runtime):
    return runtime["database"].SessionLocal()


def _create_org(runtime, org_id: str):
    database = runtime["database"]
    session = _session(runtime)
    try:
        session.add(
            database.OrganizationProfile(
                id=org_id,
                name=org_id,
                country="PH",
            )
        )
        session.commit()
    finally:
        session.close()


def _create_watch_target(runtime, *, user_id: str, entity_id: str):
    database = runtime["database"]
    session = _session(runtime)
    try:
        watch_target = database.WatchTarget(
            user_id=user_id,
            entity_id=entity_id,
            entity_type="organization",
            status="active",
            frequency="daily",
        )
        session.add(watch_target)
        session.commit()
        session.refresh(watch_target)
        return watch_target.id
    finally:
        session.close()


def _create_signal(runtime, *, watch_target_id: str, entity_id: str, signal_type: str = "new_news", severity: str = "low"):
    database = runtime["database"]
    session = _session(runtime)
    try:
        signal = database.Signal(
            watch_target_id=watch_target_id,
            entity_id=entity_id,
            signal_type=signal_type,
            title=f"{signal_type}-{severity}",
            summary=f"{signal_type}-{severity}",
            severity=severity,
            source_url="https://example.com/source",
            dedup_key=f"{watch_target_id}|{signal_type}|{severity}|{entity_id}",
        )
        session.add(signal)
        session.commit()
        session.refresh(signal)
        return signal.id
    finally:
        session.close()


def _create_alert(
    runtime,
    *,
    user_id: str,
    entity_id: str,
    signal_type: str = "new_news",
    severity: str = "low",
    status: str = "unread",
    watch_target_id: str | None = None,
):
    _create_org(runtime, entity_id)
    target_id = watch_target_id or _create_watch_target(runtime, user_id=user_id, entity_id=entity_id)
    signal_id = _create_signal(runtime, watch_target_id=target_id, entity_id=entity_id, signal_type=signal_type, severity=severity)
    database = runtime["database"]
    session = _session(runtime)
    try:
        alert = database.Alert(
            user_id=user_id,
            watch_target_id=target_id,
            signal_id=signal_id,
            title=f"alert-{signal_type}-{severity}",
            summary=f"summary-{signal_type}-{severity}",
            severity=severity,
            status=status,
            source_url="https://example.com/source",
            read_at=datetime.utcnow() if status == "read" else None,
            dismissed_at=datetime.utcnow() if status == "dismissed" else None,
        )
        session.add(alert)
        session.commit()
        session.refresh(alert)
        return alert.id, target_id
    finally:
        session.close()


def test_01_notification_flag_disabled_returns_503(runtime):
    _set_flags(runtime, notifications=False)
    response = runtime["client"].get("/api/alerts")
    assert response.status_code == 503
    assert response.json()["detail"]["error_code"] == "WATCH_ALERT_NOTIFICATIONS_DISABLED"


def test_02_v1_flag_disabled_returns_503(runtime):
    _set_flags(runtime, v1=False)
    response = runtime["client"].get("/api/alerts")
    assert response.status_code == 503
    assert response.json()["detail"]["error_code"] == "WATCH_ALERT_NOTIFICATIONS_DISABLED"


def test_03_unauthenticated_returns_401(runtime, reset_state):
    reset_state["value"] = None
    response = runtime["client"].get("/api/alerts")
    assert response.status_code == 401
    assert response.json()["detail"]["error_code"] == "AUTH_REQUIRED"


def test_04_user_can_only_view_owned_alerts(runtime):
    _create_alert(runtime, user_id="user-1", entity_id="org-owned")
    _create_alert(runtime, user_id="user-2", entity_id="org-other")

    response = runtime["client"].get("/api/alerts")
    body = response.json()
    assert response.status_code == 200
    assert body["total"] == 1
    assert all(item["watch_target_id"] for item in body["items"])


def test_05_alert_list_pagination_correct(runtime):
    _create_alert(runtime, user_id="user-1", entity_id="org-page-1", severity="low")
    _create_alert(runtime, user_id="user-1", entity_id="org-page-2", severity="medium")
    _create_alert(runtime, user_id="user-1", entity_id="org-page-3", severity="high")

    response = runtime["client"].get("/api/alerts", params={"page": 1, "page_size": 2})
    body = response.json()
    assert response.status_code == 200
    assert body["page"] == 1
    assert body["page_size"] == 2
    assert body["total"] == 3
    assert len(body["items"]) == 2


def test_06_status_filter_correct(runtime):
    _create_alert(runtime, user_id="user-1", entity_id="org-unread", status="unread")
    _create_alert(runtime, user_id="user-1", entity_id="org-read", status="read")
    _create_alert(runtime, user_id="user-1", entity_id="org-dismissed", status="dismissed")

    response = runtime["client"].get("/api/alerts", params={"status": "read"})
    body = response.json()
    assert response.status_code == 200
    assert body["total"] == 1
    assert body["items"][0]["status"] == "read"


def test_07_severity_filter_correct(runtime):
    _create_alert(runtime, user_id="user-1", entity_id="org-low", severity="low")
    _create_alert(runtime, user_id="user-1", entity_id="org-high", severity="high")

    response = runtime["client"].get("/api/alerts", params={"severity": "high"})
    body = response.json()
    assert response.status_code == 200
    assert body["total"] == 1
    assert body["items"][0]["severity"] == "high"


def test_08_watch_target_filter_correct(runtime):
    alert_id_1, target_id_1 = _create_alert(runtime, user_id="user-1", entity_id="org-target-1")
    _create_alert(runtime, user_id="user-1", entity_id="org-target-2")

    response = runtime["client"].get("/api/alerts", params={"watch_target_id": target_id_1})
    body = response.json()
    assert response.status_code == 200
    assert body["total"] == 1
    assert body["items"][0]["id"] == alert_id_1


def test_09_unread_count_only_counts_current_user(runtime):
    _create_alert(runtime, user_id="user-1", entity_id="org-unread-1", status="unread")
    _create_alert(runtime, user_id="user-1", entity_id="org-read-1", status="read")
    _create_alert(runtime, user_id="user-2", entity_id="org-unread-2", status="unread")

    response = runtime["client"].get("/api/alerts/unread-count")
    assert response.status_code == 200
    assert response.json()["unread_count"] == 1


def test_10_unread_alert_can_mark_read(runtime):
    alert_id, _ = _create_alert(runtime, user_id="user-1", entity_id="org-readable", status="unread")

    response = runtime["client"].patch(f"/api/alerts/{alert_id}/read")
    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "read"
    assert body["read_at"] is not None


def test_11_repeat_read_is_idempotent(runtime):
    alert_id, _ = _create_alert(runtime, user_id="user-1", entity_id="org-already-read", status="read")

    response = runtime["client"].patch(f"/api/alerts/{alert_id}/read")
    assert response.status_code == 200
    assert response.json()["status"] == "read"


def test_12_dismissed_alert_cannot_mark_read(runtime):
    alert_id, _ = _create_alert(runtime, user_id="user-1", entity_id="org-dismissed-read", status="dismissed")

    response = runtime["client"].patch(f"/api/alerts/{alert_id}/read")
    assert response.status_code == 409
    assert response.json()["detail"]["error_code"] == "ALERT_DISMISSED"


def test_13_alert_can_dismiss(runtime):
    alert_id, _ = _create_alert(runtime, user_id="user-1", entity_id="org-dismiss", status="unread")

    response = runtime["client"].patch(f"/api/alerts/{alert_id}/dismiss")
    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "dismissed"
    assert body["dismissed_at"] is not None


def test_14_repeat_dismiss_is_idempotent(runtime):
    alert_id, _ = _create_alert(runtime, user_id="user-1", entity_id="org-dismissed-again", status="dismissed")

    response = runtime["client"].patch(f"/api/alerts/{alert_id}/dismiss")
    assert response.status_code == 200
    assert response.json()["status"] == "dismissed"


def test_15_read_all_only_updates_current_user_unread_and_keeps_dismissed(runtime):
    _create_alert(runtime, user_id="user-1", entity_id="org-read-all-1", status="unread")
    _create_alert(runtime, user_id="user-1", entity_id="org-read-all-2", status="unread")
    dismissed_alert_id, _ = _create_alert(runtime, user_id="user-1", entity_id="org-read-all-3", status="dismissed")
    _create_alert(runtime, user_id="user-2", entity_id="org-read-all-4", status="unread")

    response = runtime["client"].post("/api/alerts/read-all")
    assert response.status_code == 200
    assert response.json()["updated_count"] == 2

    session = _session(runtime)
    try:
        dismissed = session.query(runtime["database"].Alert).filter_by(id=dismissed_alert_id).one()
        user2_unread = session.query(runtime["database"].Alert).filter_by(user_id="user-2", status="unread").count()
        user1_unread = session.query(runtime["database"].Alert).filter_by(user_id="user-1", status="unread").count()
    finally:
        session.close()

    assert dismissed.status == "dismissed"
    assert user2_unread == 1
    assert user1_unread == 0


def test_16_other_user_modification_returns_404(runtime, reset_state):
    alert_id, _ = _create_alert(runtime, user_id="user-1", entity_id="org-other-user")
    reset_state["value"] = "user-2"

    response = runtime["client"].patch(f"/api/alerts/{alert_id}/read")
    assert response.status_code == 404
    assert response.json()["detail"]["error_code"] == "ALERT_NOT_FOUND"


def test_17_api_response_does_not_include_user_id(runtime):
    _create_alert(runtime, user_id="user-1", entity_id="org-response")

    response = runtime["client"].get("/api/alerts")
    assert response.status_code == 200
    assert "user_id" not in response.json()["items"][0]
