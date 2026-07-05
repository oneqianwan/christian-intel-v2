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

TEST_DB_PATH = BACKEND_DIR / "data" / "watch_alert_phase43a_signals_test.db"
MODULES_TO_PURGE = [
    "config",
    "main",
    "models.watch_alert",
    "models.database",
    "routers.watch_targets",
    "services.watch_target_service",
    "services.watch_runner",
    "services.watch_snapshot_builder",
    "services.watch_change_detector",
    "services.signal_service",
    "schemas.watch_alert",
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
        session.query(database.RelationEdge).delete()
        session.query(database.IntelligenceItem).delete()
        session.query(database.Source).delete()
        session.query(database.KnowledgeEntity).delete()
        session.query(database.OrganizationProfile).delete()
        session.commit()
    finally:
        session.close()

    yield current_user

    app.dependency_overrides.clear()


def _session(runtime):
    return runtime["database"].SessionLocal()


def _create_source(runtime):
    database = runtime["database"]
    session = _session(runtime)
    try:
        existing = session.query(database.Source).filter_by(id="source-1").first()
        if existing:
            return
        session.add(
            database.Source(
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


def _create_org(runtime, org_id: str, name: str):
    database = runtime["database"]
    session = _session(runtime)
    try:
        session.add(
            database.OrganizationProfile(
                id=org_id,
                name=name,
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


def _create_watch_target(runtime, user_id: str, entity_id: str):
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


def _add_intelligence(runtime, item_id: str, entity_name: str, category: str, url: str):
    database = runtime["database"]
    _create_source(runtime)
    session = _session(runtime)
    try:
        session.add(
            database.IntelligenceItem(
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


def _run_watch(runtime, watch_target_id: str):
    return runtime["client"].post(f"/api/watch-targets/{watch_target_id}/run")


def test_23_signals_api_only_returns_current_user_data(runtime, reset_state):
    _create_org(runtime, "org-owner", "Org Owner")
    watch_target_id = _create_watch_target(runtime, "user-1", "org-owner")
    assert _run_watch(runtime, watch_target_id).status_code == 200
    _add_intelligence(runtime, "sig-1", "Org Owner", "news", "https://news.example.com/1")
    assert _run_watch(runtime, watch_target_id).status_code == 200

    response = runtime["client"].get(f"/api/watch-targets/{watch_target_id}/signals")
    assert response.status_code == 200
    assert response.json()["total"] == 1

    reset_state["value"] = "user-2"
    other_response = runtime["client"].get(f"/api/watch-targets/{watch_target_id}/signals")
    assert other_response.status_code == 404
    assert other_response.json()["detail"]["error_code"] == "WATCH_TARGET_NOT_FOUND"


def test_24_signal_type_filter_works(runtime):
    _create_org(runtime, "org-filter", "Org Filter")
    watch_target_id = _create_watch_target(runtime, "user-1", "org-filter")
    assert _run_watch(runtime, watch_target_id).status_code == 200
    _add_intelligence(runtime, "sig-news", "Org Filter", "news", "https://news.example.com/news")
    _add_intelligence(runtime, "sig-video", "Org Filter", "video", "https://youtube.com/watch?v=2")
    assert _run_watch(runtime, watch_target_id).status_code == 200

    response = runtime["client"].get(
        f"/api/watch-targets/{watch_target_id}/signals",
        params={"signal_type": "new_news"},
    )
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["signal_type"] == "new_news"


def test_25_severity_filter_works(runtime):
    _create_org(runtime, "org-severity", "Org Severity")
    watch_target_id = _create_watch_target(runtime, "user-1", "org-severity")
    assert _run_watch(runtime, watch_target_id).status_code == 200
    session = _session(runtime)
    try:
        org = session.query(runtime["database"].OrganizationProfile).filter_by(id="org-severity").one()
        org.people_score = 5
        session.commit()
    finally:
        session.close()
    assert _run_watch(runtime, watch_target_id).status_code == 200

    response = runtime["client"].get(
        f"/api/watch-targets/{watch_target_id}/signals",
        params={"severity": "high"},
    )
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["severity"] == "high"


def test_26_signals_pagination_works(runtime):
    _create_org(runtime, "org-pagination", "Org Pagination")
    watch_target_id = _create_watch_target(runtime, "user-1", "org-pagination")
    assert _run_watch(runtime, watch_target_id).status_code == 200
    _add_intelligence(runtime, "sig-page-1", "Org Pagination", "news", "https://news.example.com/a")
    _add_intelligence(runtime, "sig-page-2", "Org Pagination", "video", "https://youtube.com/watch?v=3")
    _add_intelligence(runtime, "sig-page-3", "Org Pagination", "brief", "https://example.com/brief")
    assert _run_watch(runtime, watch_target_id).status_code == 200

    response = runtime["client"].get(
        f"/api/watch-targets/{watch_target_id}/signals",
        params={"page": 1, "page_size": 2},
    )
    body = response.json()
    assert response.status_code == 200
    assert body["page"] == 1
    assert body["page_size"] == 2
    assert body["total"] == 3
    assert len(body["items"]) == 2
