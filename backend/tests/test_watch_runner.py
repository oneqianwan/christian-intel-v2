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

TEST_DB_PATH = BACKEND_DIR / "data" / "watch_alert_phase43a_test.db"
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


def _create_source(runtime, source_id: str = "source-1"):
    database = runtime["database"]
    session = _session(runtime)
    try:
        existing = session.query(database.Source).filter_by(id=source_id).first()
        if existing:
            return
        session.add(
            database.Source(
                id=source_id,
                name=f"Source {source_id}",
                url=f"https://example.com/{source_id}",
                type="website",
                country="PH",
            )
        )
        session.commit()
    finally:
        session.close()


def _create_org(runtime, org_id: str, **overrides):
    database = runtime["database"]
    session = _session(runtime)
    try:
        defaults = {
            "id": org_id,
            "name": overrides.pop("name", org_id),
            "country": overrides.pop("country", "PH"),
            "leader_name": overrides.pop("leader_name", "Leader One"),
            "official_website": overrides.pop("official_website", "https://example.org"),
            "contact_email": overrides.pop("contact_email", None),
            "phone_public": overrides.pop("phone_public", None),
            "people_score": overrides.pop("people_score", 10),
            "digital_score": overrides.pop("digital_score", 20),
            "intel_score": overrides.pop("intel_score", 30),
        }
        defaults.update(overrides)
        session.add(database.OrganizationProfile(**defaults))
        session.commit()
    finally:
        session.close()


def _create_entity(runtime, entity_id: str, **overrides):
    database = runtime["database"]
    session = _session(runtime)
    try:
        defaults = {
            "id": entity_id,
            "entity_type": overrides.pop("entity_type", "organization"),
            "name": overrides.pop("name", entity_id),
            "source_url": overrides.pop("source_url", "https://entity.example.com"),
        }
        defaults.update(overrides)
        session.add(database.KnowledgeEntity(**defaults))
        session.commit()
    finally:
        session.close()


def _create_watch_target(runtime, user_id: str, entity_id: str, **overrides) -> str:
    database = runtime["database"]
    session = _session(runtime)
    try:
        watch_target = database.WatchTarget(
            user_id=user_id,
            entity_id=entity_id,
            entity_type=overrides.pop("entity_type", "organization"),
            status=overrides.pop("status", "active"),
            frequency=overrides.pop("frequency", "daily"),
            **overrides,
        )
        session.add(watch_target)
        session.commit()
        session.refresh(watch_target)
        return watch_target.id
    finally:
        session.close()


def _add_intelligence(runtime, item_id: str, entity_name: str, category: str, source_url: str | None):
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
                source_url=source_url,
            )
        )
        session.commit()
    finally:
        session.close()


def _add_relation(runtime, entity_id: str, relation_key: str):
    database = runtime["database"]
    session = _session(runtime)
    try:
        source_id, relation_type, target_id = relation_key.split("|")
        session.add(
            database.RelationEdge(
                source_id=source_id,
                target_id=target_id,
                relation_type=relation_type,
                source_item="manual",
            )
        )
        session.commit()
    finally:
        session.close()


def _run_watch(runtime, watch_target_id: str):
    return runtime["client"].post(f"/api/watch-targets/{watch_target_id}/run")


def _latest_watch_run(runtime):
    database = runtime["database"]
    session = _session(runtime)
    try:
        return session.query(database.WatchRun).order_by(database.WatchRun.created_at.desc()).first()
    finally:
        session.close()


def _all_signals(runtime):
    database = runtime["database"]
    session = _session(runtime)
    try:
        return session.query(database.Signal).order_by(database.Signal.created_at.asc()).all()
    finally:
        session.close()


def test_01_feature_flag_disabled_returns_503(runtime):
    _create_org(runtime, "org-flag")
    watch_target_id = _create_watch_target(runtime, "user-1", "org-flag")
    _set_watch_flag(runtime["config"], False)

    response = _run_watch(runtime, watch_target_id)
    assert response.status_code == 503
    assert response.json()["detail"]["error_code"] == "WATCH_ALERT_V1_DISABLED"


def test_02_unauthenticated_returns_401(runtime, reset_state):
    _create_org(runtime, "org-auth")
    watch_target_id = _create_watch_target(runtime, "user-1", "org-auth")
    reset_state["value"] = None

    response = _run_watch(runtime, watch_target_id)
    assert response.status_code == 401
    assert response.json()["detail"]["error_code"] == "AUTH_REQUIRED"


def test_03_cannot_run_other_users_target(runtime, reset_state):
    _create_org(runtime, "org-owner")
    watch_target_id = _create_watch_target(runtime, "user-1", "org-owner")
    reset_state["value"] = "user-2"

    response = _run_watch(runtime, watch_target_id)
    assert response.status_code == 404
    assert response.json()["detail"]["error_code"] == "WATCH_TARGET_NOT_FOUND"


def test_04_disabled_target_cannot_run(runtime):
    _create_org(runtime, "org-disabled")
    watch_target_id = _create_watch_target(runtime, "user-1", "org-disabled", status="disabled")

    response = _run_watch(runtime, watch_target_id)
    assert response.status_code == 409
    assert response.json()["detail"]["error_code"] == "WATCH_TARGET_DISABLED"


def test_05_first_run_creates_baseline_snapshot(runtime):
    _create_org(runtime, "org-baseline", name="Victory Philippines")
    watch_target_id = _create_watch_target(runtime, "user-1", "org-baseline", frequency="manual")

    response = _run_watch(runtime, watch_target_id)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"

    database = runtime["database"]
    session = _session(runtime)
    try:
        run = session.query(database.WatchRun).filter_by(id=body["run_id"]).one()
        assert run.metadata_json["snapshot_version"] == 1
        assert list(run.metadata_json["fields"].keys()) == [
            "name",
            "leader_name",
            "official_website",
            "email",
            "phone",
            "people_score",
            "digital_score",
            "intel_score",
            "composite_score",
        ]
        assert run.metadata_json["run_summary"]["baseline_created"] is True
    finally:
        session.close()


def test_06_first_run_signals_created_zero(runtime):
    _create_org(runtime, "org-first-run")
    watch_target_id = _create_watch_target(runtime, "user-1", "org-first-run")

    response = _run_watch(runtime, watch_target_id)
    assert response.status_code == 200
    assert response.json()["signals_created"] == 0


def test_07_second_run_without_change_creates_no_signal(runtime):
    _create_org(runtime, "org-no-change")
    watch_target_id = _create_watch_target(runtime, "user-1", "org-no-change")
    assert _run_watch(runtime, watch_target_id).status_code == 200

    response = _run_watch(runtime, watch_target_id)
    assert response.status_code == 200
    assert response.json()["signals_created"] == 0
    assert len(_all_signals(runtime)) == 0


def test_08_leader_change_generates_signal(runtime):
    _create_org(runtime, "org-leader", name="Org Leader")
    watch_target_id = _create_watch_target(runtime, "user-1", "org-leader")
    assert _run_watch(runtime, watch_target_id).status_code == 200

    session = _session(runtime)
    try:
        org = session.query(runtime["database"].OrganizationProfile).filter_by(id="org-leader").one()
        org.leader_name = "Leader Two"
        session.commit()
    finally:
        session.close()

    response = _run_watch(runtime, watch_target_id)
    assert response.status_code == 200
    signal = _all_signals(runtime)[0]
    assert signal.signal_type == "leadership_change"
    assert signal.severity == "high"


def test_09_email_change_generates_contact_signal(runtime):
    _create_org(runtime, "org-email", name="Org Email", contact_email=None)
    watch_target_id = _create_watch_target(runtime, "user-1", "org-email")
    assert _run_watch(runtime, watch_target_id).status_code == 200

    session = _session(runtime)
    try:
        org = session.query(runtime["database"].OrganizationProfile).filter_by(id="org-email").one()
        org.contact_email = "hello@example.org"
        session.commit()
    finally:
        session.close()

    assert _run_watch(runtime, watch_target_id).status_code == 200
    signal = _all_signals(runtime)[0]
    assert signal.signal_type == "contact_change"
    assert signal.new_value_json["field"] == "email"


def test_10_website_change_generates_contact_signal(runtime):
    _create_org(runtime, "org-web", official_website="https://example.org/a")
    watch_target_id = _create_watch_target(runtime, "user-1", "org-web")
    assert _run_watch(runtime, watch_target_id).status_code == 200

    session = _session(runtime)
    try:
        org = session.query(runtime["database"].OrganizationProfile).filter_by(id="org-web").one()
        org.official_website = " https://example.org/b/ "
        session.commit()
    finally:
        session.close()

    assert _run_watch(runtime, watch_target_id).status_code == 200
    signal = _all_signals(runtime)[0]
    assert signal.signal_type == "contact_change"
    assert signal.new_value_json["field"] == "official_website"
    assert signal.source_url == "https://example.org/b"


def test_11_people_score_drop_generates_high_score_signal(runtime):
    _create_org(runtime, "org-people-score", people_score=64)
    watch_target_id = _create_watch_target(runtime, "user-1", "org-people-score")
    assert _run_watch(runtime, watch_target_id).status_code == 200

    session = _session(runtime)
    try:
        org = session.query(runtime["database"].OrganizationProfile).filter_by(id="org-people-score").one()
        org.people_score = 40
        session.commit()
    finally:
        session.close()

    assert _run_watch(runtime, watch_target_id).status_code == 200
    signal = _all_signals(runtime)[0]
    assert signal.signal_type == "score_change"
    assert signal.severity == "high"
    assert signal.new_value_json["field"] == "people_score"


def test_12_digital_score_rise_generates_medium_score_signal(runtime):
    _create_org(runtime, "org-digital-score", digital_score=10)
    watch_target_id = _create_watch_target(runtime, "user-1", "org-digital-score")
    assert _run_watch(runtime, watch_target_id).status_code == 200

    session = _session(runtime)
    try:
        org = session.query(runtime["database"].OrganizationProfile).filter_by(id="org-digital-score").one()
        org.digital_score = 35
        session.commit()
    finally:
        session.close()

    assert _run_watch(runtime, watch_target_id).status_code == 200
    signal = _all_signals(runtime)[0]
    assert signal.signal_type == "score_change"
    assert signal.severity == "medium"
    assert signal.new_value_json["field"] == "digital_score"


def test_13_new_intelligence_generates_signal(runtime):
    _create_org(runtime, "org-intel", name="Org Intel")
    watch_target_id = _create_watch_target(runtime, "user-1", "org-intel")
    assert _run_watch(runtime, watch_target_id).status_code == 200
    _add_intelligence(runtime, "intel-1", "Org Intel", "brief", None)

    assert _run_watch(runtime, watch_target_id).status_code == 200
    signal = _all_signals(runtime)[0]
    assert signal.signal_type == "new_intelligence"
    assert signal.evidence_id == "intel-1"


def test_14_new_news_generates_signal(runtime):
    _create_org(runtime, "org-news", name="Org News")
    watch_target_id = _create_watch_target(runtime, "user-1", "org-news")
    assert _run_watch(runtime, watch_target_id).status_code == 200
    _add_intelligence(runtime, "news-1", "Org News", "news", "https://news.example.com/1")

    assert _run_watch(runtime, watch_target_id).status_code == 200
    signal = _all_signals(runtime)[0]
    assert signal.signal_type == "new_news"
    assert signal.source_url == "https://news.example.com/1"


def test_15_new_video_generates_signal(runtime):
    _create_org(runtime, "org-video", name="Org Video")
    watch_target_id = _create_watch_target(runtime, "user-1", "org-video")
    assert _run_watch(runtime, watch_target_id).status_code == 200
    _add_intelligence(runtime, "video-1", "Org Video", "video", "https://youtube.com/watch?v=1")

    assert _run_watch(runtime, watch_target_id).status_code == 200
    signal = _all_signals(runtime)[0]
    assert signal.signal_type == "new_video"
    assert signal.source_url == "https://youtube.com/watch?v=1"


def test_16_new_relation_generates_signal(runtime):
    _create_org(runtime, "org-relation")
    watch_target_id = _create_watch_target(runtime, "user-1", "org-relation")
    assert _run_watch(runtime, watch_target_id).status_code == 200
    _add_relation(runtime, "org-relation", "org-relation|partnered_with|target-1")

    assert _run_watch(runtime, watch_target_id).status_code == 200
    signal = _all_signals(runtime)[0]
    assert signal.signal_type == "relation_change"


def test_17_same_change_does_not_duplicate_signal(runtime):
    _create_org(runtime, "org-dedup", name="Org Dedup")
    watch_target_id = _create_watch_target(runtime, "user-1", "org-dedup")
    assert _run_watch(runtime, watch_target_id).status_code == 200
    _add_intelligence(runtime, "intel-dedup", "Org Dedup", "brief", None)
    assert _run_watch(runtime, watch_target_id).status_code == 200
    assert len(_all_signals(runtime)) == 1

    response = _run_watch(runtime, watch_target_id)
    assert response.status_code == 200
    assert response.json()["signals_created"] == 0
    assert len(_all_signals(runtime)) == 1


def test_18_existing_running_run_returns_409(runtime):
    _create_org(runtime, "org-running")
    watch_target_id = _create_watch_target(runtime, "user-1", "org-running")
    database = runtime["database"]
    session = _session(runtime)
    try:
        session.add(database.WatchRun(id="run-existing", watch_target_id=watch_target_id, status="running"))
        session.commit()
    finally:
        session.close()

    response = _run_watch(runtime, watch_target_id)
    assert response.status_code == 409
    assert response.json()["detail"]["error_code"] == "WATCH_RUN_ALREADY_RUNNING"


def test_19_missing_entity_marks_watch_run_failed(runtime):
    watch_target_id = _create_watch_target(runtime, "user-1", "missing-org")

    response = _run_watch(runtime, watch_target_id)
    assert response.status_code == 404
    assert response.json()["detail"]["error_code"] == "WATCH_TARGET_ENTITY_NOT_FOUND"

    run = _latest_watch_run(runtime)
    assert run.status == "failed"
    assert run.error_code == "WATCH_TARGET_ENTITY_NOT_FOUND"


def test_20_failure_does_not_leave_running_state(runtime):
    watch_target_id = _create_watch_target(runtime, "user-1", "missing-running")
    _run_watch(runtime, watch_target_id)

    database = runtime["database"]
    session = _session(runtime)
    try:
        assert session.query(database.WatchRun).filter_by(watch_target_id=watch_target_id, status="running").count() == 0
    finally:
        session.close()


def test_21_success_updates_watch_target_timestamps_and_resets_failures(runtime):
    _create_org(runtime, "org-success")
    watch_target_id = _create_watch_target(runtime, "user-1", "org-success", consecutive_failures=3)

    response = _run_watch(runtime, watch_target_id)
    assert response.status_code == 200

    database = runtime["database"]
    session = _session(runtime)
    try:
        target = session.query(database.WatchTarget).filter_by(id=watch_target_id).one()
        assert target.last_checked_at is not None
        assert target.last_success_at is not None
        assert target.consecutive_failures == 0
    finally:
        session.close()


def test_22_failure_increments_consecutive_failures(runtime):
    watch_target_id = _create_watch_target(runtime, "user-1", "missing-failure", consecutive_failures=1)

    response = _run_watch(runtime, watch_target_id)
    assert response.status_code == 404

    database = runtime["database"]
    session = _session(runtime)
    try:
        target = session.query(database.WatchTarget).filter_by(id=watch_target_id).one()
        assert target.consecutive_failures == 2
        assert target.last_error_at is not None
    finally:
        session.close()


def test_27_signal_source_url_is_none_or_http(runtime):
    _create_org(runtime, "org-source-url", name="Org Source Url", official_website="https://example.org/root")
    watch_target_id = _create_watch_target(runtime, "user-1", "org-source-url")
    assert _run_watch(runtime, watch_target_id).status_code == 200
    _add_intelligence(runtime, "news-source", "Org Source Url", "news", "https://news.example.com/item")
    session = _session(runtime)
    try:
        org = session.query(runtime["database"].OrganizationProfile).filter_by(id="org-source-url").one()
        org.leader_name = "Leader Next"
        session.commit()
    finally:
        session.close()
    assert _run_watch(runtime, watch_target_id).status_code == 200

    for signal in _all_signals(runtime):
        assert signal.source_url is None or signal.source_url.startswith(("http://", "https://"))


def test_28_signal_old_new_json_are_correct(runtime):
    _create_org(runtime, "org-json", people_score=10)
    watch_target_id = _create_watch_target(runtime, "user-1", "org-json")
    assert _run_watch(runtime, watch_target_id).status_code == 200
    session = _session(runtime)
    try:
        org = session.query(runtime["database"].OrganizationProfile).filter_by(id="org-json").one()
        org.people_score = 15
        session.commit()
    finally:
        session.close()

    assert _run_watch(runtime, watch_target_id).status_code == 200
    signal = _all_signals(runtime)[0]
    assert signal.old_value_json == {"value": 10, "field": "people_score"}
    assert signal.new_value_json == {"value": 15, "field": "people_score"}


def test_29_soft_delete_watch_target_keeps_historical_signals(runtime):
    _create_org(runtime, "org-history", name="Org History")
    watch_target_id = _create_watch_target(runtime, "user-1", "org-history")
    assert _run_watch(runtime, watch_target_id).status_code == 200
    _add_intelligence(runtime, "intel-history", "Org History", "brief", None)
    assert _run_watch(runtime, watch_target_id).status_code == 200

    assert runtime["client"].delete(f"/api/watch-targets/{watch_target_id}").status_code == 204

    database = runtime["database"]
    session = _session(runtime)
    try:
        assert session.query(database.Signal).filter_by(watch_target_id=watch_target_id).count() == 1
    finally:
        session.close()


def test_30_regression_imports_pass(runtime):
    database_module = importlib.import_module("models.database")
    chat_router_module = importlib.import_module("routers.chat")
    insight_models_module = importlib.import_module("services.insight_models")
    insight_engine_module = importlib.import_module("services.insight_engine")
    pipeline_orchestrator_module = importlib.import_module("services.pipeline_orchestrator")

    assert database_module is not None
    assert chat_router_module is not None
    assert insight_models_module is not None
    assert insight_engine_module is not None
    assert pipeline_orchestrator_module is not None


def test_manual_frequency_watch_target_can_run(runtime):
    _create_org(runtime, "org-manual")
    watch_target_id = _create_watch_target(runtime, "user-1", "org-manual", frequency="manual")
    response = _run_watch(runtime, watch_target_id)
    assert response.status_code == 200
    assert response.json()["status"] == "success"
