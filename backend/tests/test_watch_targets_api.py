from __future__ import annotations

import importlib
import os
import sys

from pathlib import Path

import pytest

from fastapi import HTTPException
from fastapi.testclient import TestClient


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

TEST_DB_PATH = BACKEND_DIR / "data" / "watch_alert_phase42_test.db"
MODULES_TO_PURGE = [
    "config",
    "main",
    "models.watch_alert",
    "models.database",
    "routers.watch_targets",
    "services.watch_target_service",
    "schemas.watch_alert",
    "services.insight_models",
    "services.insight_engine",
    "services.pipeline_orchestrator",
    "routers.chat",
]


def _purge_modules() -> None:
    for module_name in MODULES_TO_PURGE:
        sys.modules.pop(module_name, None)


def _set_watch_flag(config, enabled: bool) -> None:
    config.settings.WATCH_ALERT_V1_ENABLED = enabled
    config.settings.FEATURE_FLAGS.WATCH_ALERT_V1_ENABLED = enabled


@pytest.fixture(scope="module")
def runtime():
    TEST_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()

    os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH.as_posix()}"
    _purge_modules()

    config = importlib.import_module("config")
    database = importlib.import_module("models.database")
    watch_targets_router = importlib.import_module("routers.watch_targets")
    main = importlib.import_module("main")

    _set_watch_flag(config, True)

    client_ctx = TestClient(main.app)
    client = client_ctx.__enter__()

    yield {
        "config": config,
        "database": database,
        "router_module": watch_targets_router,
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
    database = runtime["database"]
    app = runtime["app"]
    router_module = runtime["router_module"]
    config = runtime["config"]

    _set_watch_flag(config, True)

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


def _create_org(runtime, org_id: str, name: str | None = None):
    database = runtime["database"]
    session = _session(runtime)
    try:
        session.add(
            database.OrganizationProfile(
                id=org_id,
                name=name or org_id,
                country="PH",
            )
        )
        session.commit()
    finally:
        session.close()


def _create_entity(runtime, entity_id: str, entity_type: str = "organization", name: str | None = None):
    database = runtime["database"]
    session = _session(runtime)
    try:
        session.add(
            database.KnowledgeEntity(
                id=entity_id,
                entity_type=entity_type,
                name=name or entity_id,
            )
        )
        session.commit()
    finally:
        session.close()


def _create_watch_target_via_db(runtime, user_id: str, entity_id: str, entity_type: str = "organization"):
    database = runtime["database"]
    session = _session(runtime)
    try:
        watch_target = database.WatchTarget(
            user_id=user_id,
            entity_id=entity_id,
            entity_type=entity_type,
            status="active",
            frequency="daily",
        )
        session.add(watch_target)
        session.commit()
        session.refresh(watch_target)
        return watch_target.id
    finally:
        session.close()


def test_01_feature_flag_disabled_returns_503_and_no_write(runtime):
    client = runtime["client"]
    config = runtime["config"]
    database = runtime["database"]
    _create_org(runtime, "org-flag")
    _set_watch_flag(config, False)

    session = _session(runtime)
    try:
        before = session.query(database.WatchTarget).count()
    finally:
        session.close()

    response = client.post(
        "/api/watch-targets",
        json={"entity_id": "org-flag", "entity_type": "organization", "frequency": "daily"},
    )

    assert response.status_code == 503
    assert response.json()["detail"]["error_code"] == "WATCH_ALERT_V1_DISABLED"

    session = _session(runtime)
    try:
        after = session.query(database.WatchTarget).count()
    finally:
        session.close()

    assert before == after == 0


def test_02_unauthenticated_returns_401(runtime, reset_state):
    client = runtime["client"]
    _create_org(runtime, "org-auth")
    reset_state["value"] = None

    response = client.post(
        "/api/watch-targets",
        json={"entity_id": "org-auth", "entity_type": "organization", "frequency": "daily"},
    )

    assert response.status_code == 401
    assert response.json()["detail"]["error_code"] == "AUTH_REQUIRED"


def test_03_user_can_create_watch_target(runtime):
    client = runtime["client"]
    _create_org(runtime, "org-create")

    response = client.post(
        "/api/watch-targets",
        json={"entity_id": "org-create", "entity_type": "organization", "frequency": "weekly"},
    )

    assert response.status_code == 201
    assert response.json()["entity_id"] == "org-create"


def test_04_create_defaults_status_active(runtime):
    client = runtime["client"]
    _create_org(runtime, "org-default-status")

    response = client.post(
        "/api/watch-targets",
        json={"entity_id": "org-default-status", "entity_type": "organization"},
    )

    assert response.status_code == 201
    assert response.json()["status"] == "active"


def test_05_create_defaults_frequency_daily(runtime):
    client = runtime["client"]
    _create_org(runtime, "org-default-frequency")

    response = client.post(
        "/api/watch-targets",
        json={"entity_id": "org-default-frequency", "entity_type": "organization"},
    )

    assert response.status_code == 201
    assert response.json()["frequency"] == "daily"


def test_06_same_user_duplicate_follow_returns_409(runtime):
    client = runtime["client"]
    _create_org(runtime, "org-dup")

    payload = {"entity_id": "org-dup", "entity_type": "organization", "frequency": "daily"}
    assert client.post("/api/watch-targets", json=payload).status_code == 201
    response = client.post("/api/watch-targets", json=payload)

    assert response.status_code == 409
    assert response.json()["detail"]["error_code"] == "WATCH_TARGET_EXISTS"


def test_07_different_users_can_follow_same_entity(runtime, reset_state):
    client = runtime["client"]
    _create_org(runtime, "org-shared")

    response_user1 = client.post(
        "/api/watch-targets",
        json={"entity_id": "org-shared", "entity_type": "organization", "frequency": "daily"},
    )
    assert response_user1.status_code == 201

    reset_state["value"] = "user-2"
    response_user2 = client.post(
        "/api/watch-targets",
        json={"entity_id": "org-shared", "entity_type": "organization", "frequency": "daily"},
    )
    assert response_user2.status_code == 201


def test_08_list_only_returns_current_user_targets(runtime, reset_state):
    client = runtime["client"]
    _create_org(runtime, "org-own")
    _create_org(runtime, "org-other")

    assert client.post(
        "/api/watch-targets",
        json={"entity_id": "org-own", "entity_type": "organization", "frequency": "daily"},
    ).status_code == 201

    reset_state["value"] = "user-2"
    assert client.post(
        "/api/watch-targets",
        json={"entity_id": "org-other", "entity_type": "organization", "frequency": "daily"},
    ).status_code == 201

    reset_state["value"] = "user-1"
    response = client.get("/api/watch-targets")
    body = response.json()

    assert response.status_code == 200
    assert body["total"] == 1
    assert body["items"][0]["entity_id"] == "org-own"


def test_09_status_filter_works(runtime):
    client = runtime["client"]
    _create_org(runtime, "org-active")
    _create_org(runtime, "org-paused")

    first = client.post("/api/watch-targets", json={"entity_id": "org-active", "entity_type": "organization"})
    second = client.post("/api/watch-targets", json={"entity_id": "org-paused", "entity_type": "organization"})
    assert first.status_code == second.status_code == 201

    paused_id = second.json()["id"]
    patched = client.patch(f"/api/watch-targets/{paused_id}", json={"status": "paused"})
    assert patched.status_code == 200

    response = client.get("/api/watch-targets", params={"status": "paused"})
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["entity_id"] == "org-paused"


def test_10_entity_type_filter_works(runtime):
    client = runtime["client"]
    _create_org(runtime, "org-filter")
    _create_entity(runtime, "entity-filter", entity_type="company")

    assert client.post(
        "/api/watch-targets",
        json={"entity_id": "org-filter", "entity_type": "organization"},
    ).status_code == 201
    assert client.post(
        "/api/watch-targets",
        json={"entity_id": "entity-filter", "entity_type": "knowledge_entity"},
    ).status_code == 201

    response = client.get("/api/watch-targets", params={"entity_type": "organization"})
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["entity_type"] == "organization"


def test_11_pagination_works(runtime):
    client = runtime["client"]
    for idx in range(25):
        _create_org(runtime, f"org-page-{idx}")
        response = client.post(
            "/api/watch-targets",
            json={"entity_id": f"org-page-{idx}", "entity_type": "organization"},
        )
        assert response.status_code == 201

    response = client.get("/api/watch-targets", params={"page": 2, "page_size": 10})
    body = response.json()

    assert response.status_code == 200
    assert body["page"] == 2
    assert body["page_size"] == 10
    assert body["total"] == 25
    assert len(body["items"]) == 10


def test_12_page_size_over_100_rejected(runtime):
    client = runtime["client"]
    response = client.get("/api/watch-targets", params={"page_size": 101})
    assert response.status_code == 422


def test_13_user_can_pause_watch_target(runtime):
    client = runtime["client"]
    _create_org(runtime, "org-pause")
    created = client.post("/api/watch-targets", json={"entity_id": "org-pause", "entity_type": "organization"})
    watch_target_id = created.json()["id"]

    response = client.patch(f"/api/watch-targets/{watch_target_id}", json={"status": "paused"})
    assert response.status_code == 200
    assert response.json()["status"] == "paused"


def test_14_user_can_restore_active(runtime):
    client = runtime["client"]
    _create_org(runtime, "org-reactivate")
    created = client.post("/api/watch-targets", json={"entity_id": "org-reactivate", "entity_type": "organization"})
    watch_target_id = created.json()["id"]
    assert client.patch(f"/api/watch-targets/{watch_target_id}", json={"status": "paused"}).status_code == 200

    response = client.patch(f"/api/watch-targets/{watch_target_id}", json={"status": "active"})
    assert response.status_code == 200
    assert response.json()["status"] == "active"


def test_15_user_can_update_frequency(runtime):
    client = runtime["client"]
    _create_org(runtime, "org-frequency-update")
    created = client.post(
        "/api/watch-targets",
        json={"entity_id": "org-frequency-update", "entity_type": "organization", "frequency": "daily"},
    )
    watch_target_id = created.json()["id"]

    response = client.patch(f"/api/watch-targets/{watch_target_id}", json={"frequency": "manual"})
    assert response.status_code == 200
    assert response.json()["frequency"] == "manual"


def test_16_invalid_status_returns_422(runtime):
    client = runtime["client"]
    _create_org(runtime, "org-invalid-status")
    created = client.post("/api/watch-targets", json={"entity_id": "org-invalid-status", "entity_type": "organization"})
    watch_target_id = created.json()["id"]

    response = client.patch(f"/api/watch-targets/{watch_target_id}", json={"status": "unknown"})
    assert response.status_code == 422


def test_17_invalid_frequency_returns_422(runtime):
    client = runtime["client"]
    _create_org(runtime, "org-invalid-frequency")

    response = client.post(
        "/api/watch-targets",
        json={"entity_id": "org-invalid-frequency", "entity_type": "organization", "frequency": "hourly"},
    )
    assert response.status_code == 422


def test_18_user_cannot_modify_other_users_record(runtime, reset_state):
    client = runtime["client"]
    _create_org(runtime, "org-owned")
    created = client.post("/api/watch-targets", json={"entity_id": "org-owned", "entity_type": "organization"})
    watch_target_id = created.json()["id"]

    reset_state["value"] = "user-2"
    response = client.patch(f"/api/watch-targets/{watch_target_id}", json={"status": "paused"})
    assert response.status_code == 404
    assert response.json()["detail"]["error_code"] == "WATCH_TARGET_NOT_FOUND"


def test_19_delete_performs_soft_delete(runtime):
    client = runtime["client"]
    database = runtime["database"]
    _create_org(runtime, "org-delete")
    created = client.post("/api/watch-targets", json={"entity_id": "org-delete", "entity_type": "organization"})
    watch_target_id = created.json()["id"]

    response = client.delete(f"/api/watch-targets/{watch_target_id}")
    assert response.status_code == 204

    session = _session(runtime)
    try:
        watch_target = session.query(database.WatchTarget).filter_by(id=watch_target_id).one()
        assert watch_target.deleted_at is not None
        assert watch_target.status == "disabled"
    finally:
        session.close()


def test_20_soft_deleted_records_are_hidden_from_list(runtime):
    client = runtime["client"]
    _create_org(runtime, "org-hidden")
    created = client.post("/api/watch-targets", json={"entity_id": "org-hidden", "entity_type": "organization"})
    watch_target_id = created.json()["id"]
    assert client.delete(f"/api/watch-targets/{watch_target_id}").status_code == 204

    response = client.get("/api/watch-targets")
    assert response.status_code == 200
    assert response.json()["total"] == 0


def test_21_refollow_after_soft_delete_is_allowed(runtime):
    client = runtime["client"]
    _create_org(runtime, "org-refollow")
    payload = {"entity_id": "org-refollow", "entity_type": "organization"}
    created = client.post("/api/watch-targets", json=payload)
    watch_target_id = created.json()["id"]
    assert client.delete(f"/api/watch-targets/{watch_target_id}").status_code == 204

    response = client.post("/api/watch-targets", json=payload)
    assert response.status_code == 201


def test_22_delete_does_not_affect_entity_tables(runtime):
    client = runtime["client"]
    database = runtime["database"]
    _create_org(runtime, "org-safe-delete")
    _create_entity(runtime, "entity-safe-delete", entity_type="organization")
    created = client.post("/api/watch-targets", json={"entity_id": "org-safe-delete", "entity_type": "organization"})
    watch_target_id = created.json()["id"]

    session = _session(runtime)
    try:
        org_before = session.query(database.OrganizationProfile).count()
        entity_before = session.query(database.KnowledgeEntity).count()
    finally:
        session.close()

    assert client.delete(f"/api/watch-targets/{watch_target_id}").status_code == 204

    session = _session(runtime)
    try:
        assert session.query(database.OrganizationProfile).count() == org_before
        assert session.query(database.KnowledgeEntity).count() == entity_before
    finally:
        session.close()


def test_23_response_does_not_expose_user_id_or_deleted_at(runtime):
    client = runtime["client"]
    _create_org(runtime, "org-response")

    created = client.post("/api/watch-targets", json={"entity_id": "org-response", "entity_type": "organization"})
    body = created.json()

    assert created.status_code == 201
    assert "user_id" not in body
    assert "deleted_at" not in body

    listed = client.get("/api/watch-targets").json()["items"][0]
    assert "user_id" not in listed
    assert "deleted_at" not in listed


def test_24_watch_targets_router_registered(runtime):
    client = runtime["client"]
    openapi = client.get("/openapi.json")
    assert openapi.status_code == 200
    assert "/api/watch-targets" in openapi.json()["paths"]


def test_25_import_regression_for_insight_database_chat(runtime):
    database_module = importlib.import_module("models.database")
    insight_models_module = importlib.import_module("services.insight_models")
    insight_engine_module = importlib.import_module("services.insight_engine")
    chat_router_module = importlib.import_module("routers.chat")

    assert database_module is not None
    assert insight_models_module is not None
    assert insight_engine_module is not None
    assert chat_router_module is not None
