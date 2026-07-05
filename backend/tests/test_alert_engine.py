from __future__ import annotations

import importlib
import os
import sys

from pathlib import Path

import pytest


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

TEST_DB_PATH = BACKEND_DIR / "data" / "watch_alert_phase44_engine_test.db"
MODULES_TO_PURGE = [
    "config",
    "models.watch_alert",
    "models.database",
    "schemas.watch_alert",
    "services.signal_service",
    "services.alert_rule_service",
    "services.alert_engine",
    "services.watch_target_service",
    "services.watch_change_detector",
    "services.watch_snapshot_builder",
    "services.watch_runner",
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
    signal_service = importlib.import_module("services.signal_service")
    alert_rule_service = importlib.import_module("services.alert_rule_service")
    alert_engine = importlib.import_module("services.alert_engine")
    watch_target_service = importlib.import_module("services.watch_target_service")
    watch_runner = importlib.import_module("services.watch_runner")
    database.init_db()

    yield {
        "config": config,
        "database": database,
        "signal_service": signal_service,
        "alert_rule_service": alert_rule_service,
        "alert_engine": alert_engine,
        "watch_target_service": watch_target_service,
        "watch_runner": watch_runner,
    }

    database.engine.dispose()
    _purge_modules()
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()


@pytest.fixture(autouse=True)
def reset_state(runtime):
    _set_flags(runtime)

    session = runtime["database"].SessionLocal()
    try:
        session.query(runtime["database"].Alert).delete()
        session.query(runtime["database"].AlertRule).delete()
        session.query(runtime["database"].Signal).delete()
        session.query(runtime["database"].WatchRun).delete()
        session.query(runtime["database"].WatchTarget).delete()
        session.query(runtime["database"].RelationEdge).delete()
        session.query(runtime["database"].IntelligenceItem).delete()
        session.query(runtime["database"].Source).delete()
        session.query(runtime["database"].KnowledgeEntity).delete()
        session.query(runtime["database"].OrganizationProfile).delete()
        session.commit()
    finally:
        session.close()

    yield


def _session(runtime):
    return runtime["database"].SessionLocal()


def _create_source(runtime):
    database = runtime["database"]
    session = _session(runtime)
    try:
        if session.query(database.Source).filter_by(id="source-1").first():
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


def _create_watch_target(runtime, *, user_id: str, entity_id: str, frequency: str = "daily") -> str:
    database = runtime["database"]
    session = _session(runtime)
    try:
        watch_target = database.WatchTarget(
            user_id=user_id,
            entity_id=entity_id,
            entity_type="organization",
            status="active",
            frequency=frequency,
        )
        session.add(watch_target)
        session.commit()
        session.refresh(watch_target)
        return watch_target.id
    finally:
        session.close()


def _create_signal(
    runtime,
    *,
    watch_target_id: str,
    entity_id: str,
    signal_type: str,
    severity: str,
    title: str | None = None,
    summary: str | None = None,
    source_url: str | None = "https://example.com/item",
):
    database = runtime["database"]
    session = _session(runtime)
    try:
        signal = database.Signal(
            watch_target_id=watch_target_id,
            entity_id=entity_id,
            signal_type=signal_type,
            title=title or signal_type,
            summary=summary or f"{signal_type} summary",
            severity=severity,
            source_url=source_url,
            dedup_key=f"{watch_target_id}|{signal_type}|{severity}|{title or signal_type}",
        )
        session.add(signal)
        session.commit()
        session.refresh(signal)
        return signal.id
    finally:
        session.close()


def _create_user_rule(runtime, *, user_id: str, signal_type: str, minimum_severity: str, is_enabled: bool = True):
    database = runtime["database"]
    session = _session(runtime)
    try:
        session.add(
            database.AlertRule(
                user_id=user_id,
                signal_type=signal_type,
                minimum_severity=minimum_severity,
                is_enabled=is_enabled,
                configuration_json={},
            )
        )
        session.commit()
    finally:
        session.close()


def _add_intelligence(runtime, *, item_id: str, entity_name: str, category: str, url: str):
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


def _run_watch(runtime, watch_target_id: str, *, user_id: str = "user-1"):
    session = _session(runtime)
    try:
        watch_run = runtime["watch_runner"].run_watch_target(session, watch_target_id, user_id)
        session.expunge(watch_run)
        return watch_run
    finally:
        session.close()


def test_01_notification_flag_disabled_does_not_generate_alert(runtime):
    _set_flags(runtime, notifications=False)
    _create_org(runtime, "org-flag-off")
    watch_target_id = _create_watch_target(runtime, user_id="user-1", entity_id="org-flag-off")
    signal_id = _create_signal(
        runtime,
        watch_target_id=watch_target_id,
        entity_id="org-flag-off",
        signal_type="new_news",
        severity="low",
    )

    session = _session(runtime)
    try:
        alert = runtime["alert_engine"].process_signal(session, signal_id)
        session.commit()
        alert_count = session.query(runtime["database"].Alert).count()
    finally:
        session.close()

    assert alert is None
    assert alert_count == 0


def test_05_default_rules_are_idempotent(runtime):
    session = _session(runtime)
    try:
        first = runtime["alert_rule_service"].ensure_default_alert_rules(session)
        second = runtime["alert_rule_service"].ensure_default_alert_rules(session)
        session.commit()
        total = session.query(runtime["database"].AlertRule).filter(runtime["database"].AlertRule.user_id.is_(None)).count()
    finally:
        session.close()

    assert len(first) == 8
    assert len(second) == 8
    assert total == 8


def test_07_user_rule_overrides_system_rule(runtime):
    _create_org(runtime, "org-user-rule")
    watch_target_id = _create_watch_target(runtime, user_id="user-1", entity_id="org-user-rule")
    signal_id = _create_signal(
        runtime,
        watch_target_id=watch_target_id,
        entity_id="org-user-rule",
        signal_type="new_news",
        severity="low",
    )
    _create_user_rule(runtime, user_id="user-1", signal_type="new_news", minimum_severity="critical")

    session = _session(runtime)
    try:
        alert = runtime["alert_engine"].process_signal(session, signal_id)
        session.commit()
    finally:
        session.close()

    assert alert is None


def test_08_disabled_rule_does_not_generate_alert(runtime):
    _create_org(runtime, "org-disabled-rule")
    watch_target_id = _create_watch_target(runtime, user_id="user-1", entity_id="org-disabled-rule")
    signal_id = _create_signal(
        runtime,
        watch_target_id=watch_target_id,
        entity_id="org-disabled-rule",
        signal_type="new_news",
        severity="low",
    )
    _create_user_rule(runtime, user_id="user-1", signal_type="new_news", minimum_severity="low", is_enabled=False)

    session = _session(runtime)
    try:
        alert = runtime["alert_engine"].process_signal(session, signal_id)
        session.commit()
    finally:
        session.close()

    assert alert is None


def test_09_to_14_rule_thresholds_and_signal_types(runtime):
    _create_org(runtime, "org-thresholds")
    watch_target_id = _create_watch_target(runtime, user_id="user-1", entity_id="org-thresholds")
    signal_ids = [
        _create_signal(
            runtime,
            watch_target_id=watch_target_id,
            entity_id="org-thresholds",
            signal_type="score_change",
            severity="low",
            title="below-threshold",
        ),
        _create_signal(
            runtime,
            watch_target_id=watch_target_id,
            entity_id="org-thresholds",
            signal_type="score_change",
            severity="medium",
            title="equal-threshold",
        ),
        _create_signal(
            runtime,
            watch_target_id=watch_target_id,
            entity_id="org-thresholds",
            signal_type="leadership_change",
            severity="critical",
            title="above-threshold",
        ),
        _create_signal(
            runtime,
            watch_target_id=watch_target_id,
            entity_id="org-thresholds",
            signal_type="leadership_change",
            severity="high",
            title="leadership-high",
        ),
        _create_signal(
            runtime,
            watch_target_id=watch_target_id,
            entity_id="org-thresholds",
            signal_type="score_change",
            severity="medium",
            title="score-medium",
        ),
        _create_signal(
            runtime,
            watch_target_id=watch_target_id,
            entity_id="org-thresholds",
            signal_type="new_news",
            severity="low",
            title="news-low",
        ),
    ]

    session = _session(runtime)
    try:
        results = [runtime["alert_engine"].process_signal(session, signal_id) for signal_id in signal_ids]
        session.commit()
    finally:
        session.close()

    assert results[0] is None
    assert results[1] is not None
    assert results[2] is not None
    assert results[3] is not None
    assert results[4] is not None
    assert results[5] is not None


def test_15_same_signal_is_not_duplicated(runtime):
    _create_org(runtime, "org-dedup")
    watch_target_id = _create_watch_target(runtime, user_id="user-1", entity_id="org-dedup")
    signal_id = _create_signal(
        runtime,
        watch_target_id=watch_target_id,
        entity_id="org-dedup",
        signal_type="new_news",
        severity="low",
    )

    session = _session(runtime)
    try:
        first = runtime["alert_engine"].process_signal(session, signal_id)
        second = runtime["alert_engine"].process_signal(session, signal_id)
        session.commit()
        count = session.query(runtime["database"].Alert).count()
    finally:
        session.close()

    assert first is not None
    assert second is None
    assert count == 1


def test_16_alert_user_id_comes_from_watch_target(runtime):
    _create_org(runtime, "org-user")
    watch_target_id = _create_watch_target(runtime, user_id="owner-1", entity_id="org-user")
    signal_id = _create_signal(
        runtime,
        watch_target_id=watch_target_id,
        entity_id="org-user",
        signal_type="new_news",
        severity="low",
    )

    session = _session(runtime)
    try:
        alert = runtime["alert_engine"].process_signal(session, signal_id)
        alert_user_id = alert.user_id if alert is not None else None
        session.commit()
    finally:
        session.close()

    assert alert is not None
    assert alert_user_id == "owner-1"


def test_17_alert_source_url_is_empty_or_real_url(runtime):
    _create_org(runtime, "org-source")
    watch_target_id = _create_watch_target(runtime, user_id="user-1", entity_id="org-source")
    valid_signal_id = _create_signal(
        runtime,
        watch_target_id=watch_target_id,
        entity_id="org-source",
        signal_type="new_news",
        severity="low",
        title="valid-url",
        source_url="https://news.example.com/1",
    )
    invalid_signal_id = _create_signal(
        runtime,
        watch_target_id=watch_target_id,
        entity_id="org-source",
        signal_type="new_video",
        severity="low",
        title="invalid-url",
        source_url="notaurl",
    )

    session = _session(runtime)
    try:
        valid_alert = runtime["alert_engine"].process_signal(session, valid_signal_id)
        invalid_alert = runtime["alert_engine"].process_signal(session, invalid_signal_id)
        valid_source_url = valid_alert.source_url if valid_alert is not None else None
        invalid_source_url = invalid_alert.source_url if invalid_alert is not None else None
        session.commit()
    finally:
        session.close()

    assert valid_alert is not None
    assert valid_source_url == "https://news.example.com/1"
    assert invalid_alert is not None
    assert invalid_source_url is None


def test_18_first_baseline_does_not_generate_alert(runtime):
    _create_org(runtime, "org-baseline")
    watch_target_id = _create_watch_target(runtime, user_id="user-1", entity_id="org-baseline")

    watch_run = _run_watch(runtime, watch_target_id)

    session = _session(runtime)
    try:
        alert_count = session.query(runtime["database"].Alert).count()
    finally:
        session.close()

    assert watch_run.signals_created == 0
    assert watch_run.alerts_created == 0
    assert alert_count == 0


def test_19_20_38_followup_changes_update_alert_counts_without_duplicates(runtime):
    _create_org(runtime, "org-followup")
    watch_target_id = _create_watch_target(runtime, user_id="user-1", entity_id="org-followup")
    _run_watch(runtime, watch_target_id)

    _add_intelligence(
        runtime,
        item_id="intel-1",
        entity_name="org-followup",
        category="news",
        url="https://news.example.com/followup",
    )
    changed_run = _run_watch(runtime, watch_target_id)
    unchanged_run = _run_watch(runtime, watch_target_id)

    session = _session(runtime)
    try:
        alert_count = session.query(runtime["database"].Alert).count()
        signal_count = session.query(runtime["database"].Signal).count()
    finally:
        session.close()

    assert changed_run.alerts_created == 1
    assert unchanged_run.signals_created == 0
    assert unchanged_run.alerts_created == 0
    assert signal_count == 1
    assert alert_count == 1


def test_21_alert_engine_exception_does_not_leave_running_watch_run(monkeypatch, runtime):
    _create_org(runtime, "org-engine-fail")
    watch_target_id = _create_watch_target(runtime, user_id="user-1", entity_id="org-engine-fail")
    _run_watch(runtime, watch_target_id)

    _add_intelligence(
        runtime,
        item_id="intel-fail",
        entity_name="org-engine-fail",
        category="news",
        url="https://news.example.com/fail",
    )
    monkeypatch.setattr(runtime["watch_runner"], "process_signals", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("alert engine failed")))

    watch_run = _run_watch(runtime, watch_target_id)

    session = _session(runtime)
    try:
        running_count = session.query(runtime["database"].WatchRun).filter_by(watch_target_id=watch_target_id, status="running").count()
        signal_count = session.query(runtime["database"].Signal).filter_by(watch_target_id=watch_target_id).count()
        alert_count = session.query(runtime["database"].Alert).count()
    finally:
        session.close()

    assert watch_run.status == "success"
    assert watch_run.alerts_created == 0
    assert running_count == 0
    assert signal_count == 1
    assert alert_count == 0


def test_37_soft_deleted_watch_target_keeps_historical_alerts(runtime):
    _create_org(runtime, "org-soft-delete")
    watch_target_id = _create_watch_target(runtime, user_id="user-1", entity_id="org-soft-delete")
    signal_id = _create_signal(
        runtime,
        watch_target_id=watch_target_id,
        entity_id="org-soft-delete",
        signal_type="new_news",
        severity="low",
    )

    session = _session(runtime)
    try:
        runtime["alert_engine"].process_signal(session, signal_id)
        session.commit()
    finally:
        session.close()

    session = _session(runtime)
    try:
        runtime["watch_target_service"].soft_delete_watch_target(session, watch_target_id, "user-1")
        alert_count = session.query(runtime["database"].Alert).filter_by(watch_target_id=watch_target_id).count()
    finally:
        session.close()

    assert alert_count == 1
