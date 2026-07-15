from __future__ import annotations

import importlib
import os
import sys

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from fastapi.testclient import TestClient


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

TEST_DB_PATH = BACKEND_DIR / "data" / "watch_alert_phase53a_ownership_test.db"
MODULES_TO_PURGE = [
    "config",
    "main",
    "models",
    "models.database",
    "models.auth",
    "models.watch_alert",
    "models.schemas",
    "routers",
    "schemas.watch_alert",
    "routers.auth",
    "routers.alerts",
    "routers.watch_targets",
    "dependencies",
    "dependencies.auth",
    "dependencies.watch_alert_auth",
    "services",
    "services.auth_service",
    "services.alert_engine",
    "services.alert_rule_service",
    "services.alert_service",
    "services.signal_service",
    "services.watch_alert_ownership",
    "services.watch_runner",
    "services.watch_scheduler",
    "services.watch_target_service",
]


def _purge_modules() -> None:
    for module_name in MODULES_TO_PURGE:
        sys.modules.pop(module_name, None)


def _set_flags(
    runtime,
    *,
    ownership: bool = False,
    auth: bool = True,
    v1: bool = True,
    notifications: bool = True,
    scheduler: bool = True,
    legacy_allowed: bool = False,
) -> None:
    config = runtime["config"]
    config.settings.WATCH_ALERT_V1_ENABLED = v1
    config.settings.WATCH_ALERT_NOTIFICATIONS_ENABLED = notifications
    config.settings.WATCH_ALERT_SCHEDULER_ENABLED = scheduler
    config.settings.WATCH_ALERT_USER_OWNERSHIP_ENABLED = ownership
    config.settings.AUTH_V1_ENABLED = auth
    config.settings.AUTH_COOKIE_REQUIRED = False
    config.settings.ALLOW_LEGACY_SESSION_ID = legacy_allowed


@pytest.fixture(scope="module")
def runtime():
    TEST_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()

    os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH.as_posix()}"
    _purge_modules()

    config = importlib.import_module("config")
    database = importlib.import_module("models.database")
    auth_models = importlib.import_module("models.auth")
    auth_service = importlib.import_module("services.auth_service")
    watch_runner = importlib.import_module("services.watch_runner")
    watch_scheduler = importlib.import_module("services.watch_scheduler")
    signal_service = importlib.import_module("services.signal_service")
    main = importlib.import_module("main")

    database.init_db()

    client_ctx = TestClient(main.app)
    client = client_ctx.__enter__()
    yield {
        "config": config,
        "database": database,
        "auth_models": auth_models,
        "auth_service": auth_service,
        "watch_runner": watch_runner,
        "watch_scheduler": watch_scheduler,
        "signal_service": signal_service,
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
    _set_flags(runtime, ownership=True, auth=True, v1=True, notifications=True, scheduler=True, legacy_allowed=False)
    runtime["client"].cookies.clear()
    rate_limiter = getattr(runtime["auth_service"], "_default_rate_limiter", None)
    if rate_limiter is not None and hasattr(rate_limiter, "_attempts"):
        rate_limiter._attempts.clear()

    database = runtime["database"]
    session = database.SessionLocal()
    try:
        session.query(database.Alert).delete()
        session.query(database.AlertRule).delete()
        session.query(database.Signal).delete()
        session.query(database.WatchRun).delete()
        session.query(database.WatchTarget).delete()
        session.query(database.IntelligenceItem).delete()
        session.query(database.Source).delete()
        session.query(database.KnowledgeEntity).delete()
        session.query(database.OrganizationProfile).delete()
        session.query(runtime["auth_models"].AuthSession).delete()
        session.query(runtime["auth_models"].User).delete()
        session.commit()
    finally:
        session.close()
    yield


def _session(runtime):
    return runtime["database"].SessionLocal()


def _create_user(runtime, *, email: str, password: str, role: str = "analyst", status: str = "active"):
    session = _session(runtime)
    try:
        user = runtime["auth_models"].User(
            email=email,
            email_normalized=email.strip().lower(),
            password_hash=runtime["auth_service"].hash_password(password),
            display_name=email.split("@", 1)[0],
            role=role,
            status=status,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        return {"id": str(user.id), "email": user.email, "password": password}
    finally:
        session.close()


def _create_org(runtime, org_id: str, *, name: str | None = None):
    session = _session(runtime)
    try:
        session.add(
            runtime["database"].OrganizationProfile(
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


def _create_source(runtime):
    session = _session(runtime)
    try:
        if session.query(runtime["database"].Source).filter_by(id="source-1").first():
            return
        session.add(
            runtime["database"].Source(
                id="source-1",
                name="Source 1",
                url="https://example.com/source",
                type="website",
                country="PH",
            )
        )
        session.commit()
    finally:
        session.close()


def _add_intelligence(runtime, *, item_id: str, entity_name: str, category: str, url: str):
    _create_source(runtime)
    session = _session(runtime)
    try:
        session.add(
            runtime["database"].IntelligenceItem(
                id=item_id,
                source_id="source-1",
                title=item_id,
                content=item_id,
                entity_name=entity_name,
                entity_type="organization",
                category=category,
                source_url=url,
            )
        )
        session.commit()
    finally:
        session.close()


def _login(client: TestClient, *, email: str, password: str) -> None:
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text


def _create_watch_with_legacy_header(client: TestClient, *, legacy_session_id: str, entity_id: str):
    return client.post(
        "/api/watch-targets",
        headers={"x-session-id": legacy_session_id},
        json={"entity_id": entity_id, "entity_type": "organization", "frequency": "daily"},
    )


def _seed_legacy_watch_chain(runtime, *, legacy_session_id: str, entity_id: str):
    _create_org(runtime, entity_id, name=entity_id)
    session = _session(runtime)
    try:
        watch_target = runtime["database"].WatchTarget(
            user_id=legacy_session_id,
            entity_id=entity_id,
            entity_type="organization",
            status="active",
            frequency="daily",
            next_check_at=datetime.utcnow() - timedelta(minutes=5),
        )
        session.add(watch_target)
        session.commit()
        session.refresh(watch_target)

        signal = runtime["database"].Signal(
            watch_target_id=watch_target.id,
            entity_id=entity_id,
            signal_type="new_news",
            title="legacy-signal",
            summary="legacy-signal",
            severity="low",
            source_url="https://legacy.example.com/news",
            dedup_key=f"{watch_target.id}|legacy-news",
        )
        session.add(signal)
        session.commit()
        session.refresh(signal)

        alert = runtime["database"].Alert(
            user_id=legacy_session_id,
            watch_target_id=watch_target.id,
            signal_id=signal.id,
            title="legacy-alert",
            summary="legacy-alert",
            severity="low",
            status="unread",
            source_url="https://legacy.example.com/news",
        )
        session.add(alert)
        session.commit()
        session.refresh(alert)
        return watch_target.id, signal.id, alert.id
    finally:
        session.close()


def test_01_feature_flag_default_safe(runtime):
    assert runtime["config"].settings.feature_flag("WATCH_ALERT_USER_OWNERSHIP_ENABLED") is True
    assert runtime["config"].settings.ALLOW_LEGACY_SESSION_ID is False


def test_02_flag_false_keeps_x_session_id_legacy_mode(runtime):
    _set_flags(runtime, ownership=False, auth=True, v1=True, notifications=True, scheduler=True, legacy_allowed=True)
    _create_org(runtime, "org-legacy", name="Org Legacy")

    response = _create_watch_with_legacy_header(
        runtime["client"],
        legacy_session_id="legacy-user-a",
        entity_id="org-legacy",
    )

    assert response.status_code == 201
    session = _session(runtime)
    try:
        watch_target = session.query(runtime["database"].WatchTarget).one()
        assert watch_target.user_id == "legacy-user-a"
        assert watch_target.owner_user_id is None
    finally:
        session.close()


def test_03_flag_true_rejects_unauthenticated_and_x_session_id_only(runtime):
    _set_flags(runtime, ownership=True, auth=True)
    _create_org(runtime, "org-auth-required")

    response = _create_watch_with_legacy_header(
        runtime["client"],
        legacy_session_id="legacy-user-a",
        entity_id="org-auth-required",
    )

    assert response.status_code == 401
    assert response.json()["detail"]["error_code"] == "AUTH_REQUIRED"


def test_04_flag_true_auth_disabled_fails_closed(runtime):
    _set_flags(runtime, ownership=True, auth=False)

    response = runtime["client"].get("/api/watch-targets", headers={"x-session-id": "legacy-user-a"})

    assert response.status_code == 503
    assert response.json()["detail"]["error_code"] == "AUTH_DISABLED"


def test_05_flag_true_logged_in_user_creates_watch_with_owner(runtime):
    _set_flags(runtime, ownership=True, auth=True)
    user_a = _create_user(runtime, email="a@example.com", password="StrongPass123!")
    _create_org(runtime, "org-owned", name="Org Owned")

    with TestClient(runtime["app"]) as client:
        _login(client, email=user_a["email"], password=user_a["password"])
        response = client.post(
            "/api/watch-targets",
            json={"entity_id": "org-owned", "entity_type": "organization", "frequency": "daily"},
        )

    assert response.status_code == 201
    watch_target_id = response.json()["id"]
    session = _session(runtime)
    try:
        watch_target = session.query(runtime["database"].WatchTarget).filter_by(id=watch_target_id).one()
        assert str(watch_target.owner_user_id) == user_a["id"]
    finally:
        session.close()


def test_06_dual_users_can_watch_same_entity_and_are_isolated(runtime):
    _set_flags(runtime, ownership=True, auth=True)
    user_a = _create_user(runtime, email="owner-a@example.com", password="StrongPass123!")
    user_b = _create_user(runtime, email="owner-b@example.com", password="StrongPass123!")
    _create_org(runtime, "org-shared", name="Org Shared")

    with TestClient(runtime["app"]) as client_a, TestClient(runtime["app"]) as client_b:
        _login(client_a, email=user_a["email"], password=user_a["password"])
        _login(client_b, email=user_b["email"], password=user_b["password"])

        created_a = client_a.post(
            "/api/watch-targets",
            json={"entity_id": "org-shared", "entity_type": "organization", "frequency": "daily"},
        )
        created_b = client_b.post(
            "/api/watch-targets",
            json={"entity_id": "org-shared", "entity_type": "organization", "frequency": "daily"},
        )

        assert created_a.status_code == 201
        assert created_b.status_code == 201

        list_a = client_a.get("/api/watch-targets")
        list_b = client_b.get("/api/watch-targets")
        assert list_a.json()["total"] == 1
        assert list_b.json()["total"] == 1

        other_watch_id = created_b.json()["id"]
        assert client_a.patch(f"/api/watch-targets/{other_watch_id}", json={"status": "paused"}).status_code == 404
        assert client_a.delete(f"/api/watch-targets/{other_watch_id}").status_code == 404
        assert client_a.post(f"/api/watch-targets/{other_watch_id}/run").status_code == 404


def test_07_cookie_identity_ignores_x_session_id_header(runtime):
    _set_flags(runtime, ownership=True, auth=True)
    user_a = _create_user(runtime, email="cookie-a@example.com", password="StrongPass123!")
    _create_org(runtime, "org-cookie-a", name="Org Cookie A")

    with TestClient(runtime["app"]) as client_a:
        _login(client_a, email=user_a["email"], password=user_a["password"])
        assert client_a.post(
            "/api/watch-targets",
            json={"entity_id": "org-cookie-a", "entity_type": "organization", "frequency": "daily"},
        ).status_code == 201

        _seed_legacy_watch_chain(runtime, legacy_session_id="legacy-header-b", entity_id="org-legacy-hidden")

        response = client_a.get("/api/watch-targets", headers={"x-session-id": "legacy-header-b"})

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["entity_id"] == "org-cookie-a"


def test_08_signal_and_alert_owner_propagate_from_watch_target(runtime):
    _set_flags(runtime, ownership=True, auth=True, notifications=True)
    user_a = _create_user(runtime, email="propagate-a@example.com", password="StrongPass123!")
    _create_org(runtime, "org-propagate", name="Org Propagate")

    with TestClient(runtime["app"]) as client_a:
        _login(client_a, email=user_a["email"], password=user_a["password"])
        created = client_a.post(
            "/api/watch-targets",
            json={"entity_id": "org-propagate", "entity_type": "organization", "frequency": "daily"},
        )
        watch_target_id = created.json()["id"]
        assert client_a.post(f"/api/watch-targets/{watch_target_id}/run").status_code == 200
        _add_intelligence(
            runtime,
            item_id="intel-owner-prop",
            entity_name="Org Propagate",
            category="news",
            url="https://news.example.com/propagate",
        )
        rerun = client_a.post(f"/api/watch-targets/{watch_target_id}/run")

    assert rerun.status_code == 200
    assert rerun.json()["signals_created"] == 1

    session = _session(runtime)
    try:
        signal = session.query(runtime["database"].Signal).one()
        alert = session.query(runtime["database"].Alert).one()
        watch_run = session.query(runtime["database"].WatchRun).order_by(runtime["database"].WatchRun.created_at.desc()).first()
        assert str(signal.owner_user_id) == user_a["id"]
        assert str(alert.owner_user_id) == user_a["id"]
        assert alert.user_id == user_a["id"]
        assert watch_run is not None
        assert watch_run.alerts_created == 1
    finally:
        session.close()


def test_09_cross_user_alert_and_unread_count_are_isolated(runtime):
    _set_flags(runtime, ownership=True, auth=True, notifications=True)
    user_a = _create_user(runtime, email="alerts-a@example.com", password="StrongPass123!")
    user_b = _create_user(runtime, email="alerts-b@example.com", password="StrongPass123!")
    _create_org(runtime, "org-alert-shared", name="Org Alert Shared")

    with TestClient(runtime["app"]) as client_a, TestClient(runtime["app"]) as client_b:
        _login(client_a, email=user_a["email"], password=user_a["password"])
        _login(client_b, email=user_b["email"], password=user_b["password"])

        created_a = client_a.post(
            "/api/watch-targets",
            json={"entity_id": "org-alert-shared", "entity_type": "organization", "frequency": "daily"},
        )
        created_b = client_b.post(
            "/api/watch-targets",
            json={"entity_id": "org-alert-shared", "entity_type": "organization", "frequency": "daily"},
        )
        watch_a = created_a.json()["id"]
        watch_b = created_b.json()["id"]
        assert client_a.post(f"/api/watch-targets/{watch_a}/run").status_code == 200
        assert client_b.post(f"/api/watch-targets/{watch_b}/run").status_code == 200

        _add_intelligence(
            runtime,
            item_id="intel-shared-alert",
            entity_name="Org Alert Shared",
            category="news",
            url="https://news.example.com/shared-alert",
        )
        assert client_a.post(f"/api/watch-targets/{watch_a}/run").status_code == 200
        assert client_b.post(f"/api/watch-targets/{watch_b}/run").status_code == 200

        alerts_a = client_a.get("/api/alerts")
        alerts_b = client_b.get("/api/alerts")
        unread_a = client_a.get("/api/alerts/unread-count")
        unread_b = client_b.get("/api/alerts/unread-count")

        assert alerts_a.json()["total"] == 1
        assert alerts_b.json()["total"] == 1
        assert unread_a.json()["unread_count"] == 1
        assert unread_b.json()["unread_count"] == 1

        other_alert_id = alerts_b.json()["items"][0]["id"]
        assert client_a.patch(f"/api/alerts/{other_alert_id}/read").status_code == 404
        read_all_a = client_a.post("/api/alerts/read-all")
        assert read_all_a.status_code == 200
        assert read_all_a.json()["updated_count"] == 1
        assert client_a.get("/api/alerts/unread-count").json()["unread_count"] == 0
        assert client_b.get("/api/alerts/unread-count").json()["unread_count"] == 1


def test_10_legacy_null_owner_records_are_hidden_in_new_mode(runtime):
    _set_flags(runtime, ownership=True, auth=True)
    user_a = _create_user(runtime, email="hidden-a@example.com", password="StrongPass123!")
    legacy_watch_id, _, _ = _seed_legacy_watch_chain(
        runtime,
        legacy_session_id="legacy-hidden-a",
        entity_id="org-hidden-owner",
    )

    with TestClient(runtime["app"]) as client_a:
        _login(client_a, email=user_a["email"], password=user_a["password"])
        watch_list = client_a.get("/api/watch-targets")
        alerts = client_a.get("/api/alerts")
        signals = client_a.get(
            f"/api/watch-targets/{legacy_watch_id}/signals",
            headers={"x-session-id": "legacy-hidden-a"},
        )

    assert watch_list.status_code == 200
    assert watch_list.json()["total"] == 0
    assert alerts.status_code == 200
    assert alerts.json()["total"] == 0
    assert signals.status_code == 404


def test_11_revoked_session_cannot_access_new_mode(runtime):
    _set_flags(runtime, ownership=True, auth=True)
    user_a = _create_user(runtime, email="revoked-a@example.com", password="StrongPass123!")

    with TestClient(runtime["app"]) as client_a:
        _login(client_a, email=user_a["email"], password=user_a["password"])
        session = _session(runtime)
        try:
            auth_session = session.query(runtime["auth_models"].AuthSession).one()
            auth_session.status = "revoked"
            auth_session.revoked_at = datetime.utcnow()
            session.commit()
        finally:
            session.close()

        response = client_a.get("/api/watch-targets")

    assert response.status_code == 401
    assert response.json()["detail"]["error_code"] == "SESSION_REVOKED"


def test_12_scheduler_hides_null_owner_targets_in_new_mode(runtime):
    _set_flags(runtime, ownership=True, auth=True, scheduler=True)
    _seed_legacy_watch_chain(
        runtime,
        legacy_session_id="legacy-scheduler-a",
        entity_id="org-scheduler-hidden",
    )
    now = datetime.utcnow()

    session = _session(runtime)
    try:
        due_targets = runtime["watch_scheduler"].scan_due_watch_targets(session, now=now)
    finally:
        session.close()

    assert due_targets == []


def test_13_signal_creation_without_owner_is_rejected_in_new_mode(runtime):
    _set_flags(runtime, ownership=True, auth=True)
    _create_org(runtime, "org-no-owner", name="Org No Owner")
    session = _session(runtime)
    try:
        watch_target = runtime["database"].WatchTarget(
            user_id="legacy-without-owner",
            entity_id="org-no-owner",
            entity_type="organization",
            status="active",
            frequency="daily",
        )
        session.add(watch_target)
        session.commit()
        session.refresh(watch_target)

        with pytest.raises(ValueError, match="SIGNAL_OWNER_REQUIRED"):
            runtime["signal_service"].create_signal_records_for_changes(
                session,
                watch_target,
                current_snapshot={"snapshot_version": 1, "fields": {}},
                changes=[
                    {
                        "signal_type": "new_news",
                        "field_name": "official_website",
                        "old_value": None,
                        "new_value": "https://example.com/news",
                    }
                ],
            )
    finally:
        session.close()
