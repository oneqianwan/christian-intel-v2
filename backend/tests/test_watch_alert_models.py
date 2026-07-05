from __future__ import annotations

import importlib
import os
import sqlite3
import sys

from pathlib import Path

import pytest


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

TEST_DB_PATH = BACKEND_DIR / "data" / "watch_alert_phase41_test.db"
MODULES_TO_PURGE = [
    "config",
    "models.watch_alert",
    "models.database",
    "services.insight_models",
    "services.insight_engine",
    "services.pipeline_orchestrator",
]


def _purge_modules() -> None:
    for module_name in MODULES_TO_PURGE:
        sys.modules.pop(module_name, None)


def _bootstrap_runtime():
    TEST_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()

    os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH.as_posix()}"
    _purge_modules()

    config = importlib.import_module("config")
    database = importlib.import_module("models.database")
    database.Base.metadata.create_all(bind=database.engine)

    return config, database


def _schema_sql_for(table_names: list[str]) -> dict[str, str]:
    conn = sqlite3.connect(TEST_DB_PATH)
    try:
        rows = conn.execute(
            """
            SELECT name, sql
            FROM sqlite_master
            WHERE type IN ('table', 'index')
              AND name IN ({placeholders})
            ORDER BY name
            """.format(placeholders=",".join("?" for _ in table_names)),
            table_names,
        ).fetchall()
        return {name: (sql or "") for name, sql in rows}
    finally:
        conn.close()


@pytest.fixture()
def runtime():
    config, database = _bootstrap_runtime()
    session = database.SessionLocal()
    try:
        yield {
            "config": config,
            "database": database,
            "session": session,
        }
    finally:
        session.close()
        database.engine.dispose()
        _purge_modules()
        if TEST_DB_PATH.exists():
            TEST_DB_PATH.unlink()


def _make_watch_target(database, **overrides):
    payload = {
        "user_id": "user-1",
        "entity_id": "entity-1",
        "entity_type": "organization",
        "status": "active",
        "frequency": "daily",
    }
    payload.update(overrides)
    return database.WatchTarget(**payload)


def _make_signal(database, watch_target_id: str, **overrides):
    payload = {
        "watch_target_id": watch_target_id,
        "entity_id": "entity-1",
        "signal_type": "new_intelligence",
        "title": "signal-title",
        "summary": "signal-summary",
        "severity": "low",
        "dedup_key": "dedup-1",
    }
    payload.update(overrides)
    return database.Signal(**payload)


def _make_alert(database, watch_target_id: str, signal_id: str, **overrides):
    payload = {
        "user_id": "user-1",
        "watch_target_id": watch_target_id,
        "signal_id": signal_id,
        "title": "alert-title",
        "summary": "alert-summary",
        "severity": "low",
        "status": "unread",
    }
    payload.update(overrides)
    return database.Alert(**payload)


def test_01_tables_created(runtime):
    expected = {
        "watch_targets",
        "watch_runs",
        "signals",
        "alert_rules",
        "alerts",
    }
    schema = _schema_sql_for(
        [
            "watch_targets",
            "watch_runs",
            "signals",
            "alert_rules",
            "alerts",
        ]
    )
    assert expected == set(schema)


def test_02_watch_target_active_unique_constraint(runtime):
    db = runtime["session"]
    database = runtime["database"]

    db.add(_make_watch_target(database))
    db.commit()

    db.add(_make_watch_target(database))
    with pytest.raises(Exception):
        db.commit()
    db.rollback()


def test_03_soft_delete_allows_refollow(runtime):
    db = runtime["session"]
    database = runtime["database"]

    target = _make_watch_target(database)
    db.add(target)
    db.commit()

    target.deleted_at = database.datetime.utcnow()
    db.commit()

    db.add(_make_watch_target(database))
    db.commit()

    assert db.query(database.WatchTarget).count() == 2


def test_04_multi_user_isolation(runtime):
    db = runtime["session"]
    database = runtime["database"]

    db.add(_make_watch_target(database, user_id="user-1"))
    db.add(_make_watch_target(database, user_id="user-2"))
    db.commit()

    assert db.query(database.WatchTarget).count() == 2


def test_05_signal_dedup(runtime):
    db = runtime["session"]
    database = runtime["database"]

    target = _make_watch_target(database)
    db.add(target)
    db.commit()

    db.add(_make_signal(database, target.id, dedup_key="same-key"))
    db.commit()

    db.add(_make_signal(database, target.id, dedup_key="same-key"))
    with pytest.raises(Exception):
        db.commit()
    db.rollback()


def test_06_alert_dedup(runtime):
    db = runtime["session"]
    database = runtime["database"]

    target = _make_watch_target(database)
    db.add(target)
    db.commit()

    signal = _make_signal(database, target.id, dedup_key="signal-key")
    db.add(signal)
    db.commit()

    db.add(_make_alert(database, target.id, signal.id, user_id="user-1"))
    db.commit()

    db.add(_make_alert(database, target.id, signal.id, user_id="user-1"))
    with pytest.raises(Exception):
        db.commit()
    db.rollback()


def test_07_alert_rule_user_rule_unique(runtime):
    db = runtime["session"]
    database = runtime["database"]

    db.add(database.AlertRule(user_id="user-1", signal_type="new_news", minimum_severity="low"))
    db.commit()

    db.add(database.AlertRule(user_id="user-1", signal_type="new_news", minimum_severity="medium"))
    with pytest.raises(Exception):
        db.commit()
    db.rollback()


def test_08_alert_rule_system_default_unique(runtime):
    db = runtime["session"]
    database = runtime["database"]

    db.add(database.AlertRule(user_id=None, signal_type="new_video", minimum_severity="low"))
    db.commit()

    db.add(database.AlertRule(user_id=None, signal_type="new_video", minimum_severity="medium"))
    with pytest.raises(Exception):
        db.commit()
    db.rollback()


@pytest.mark.parametrize(
    ("factory_name", "field_name", "field_value"),
    [
        ("WatchTarget", "status", "unknown"),
        ("WatchTarget", "frequency", "hourly"),
        ("WatchRun", "status", "done"),
        ("Signal", "signal_type", "random"),
        ("Signal", "severity", "urgent"),
        ("Alert", "status", "deleted"),
        ("Alert", "severity", "urgent"),
    ],
)
def test_09_invalid_status_rejected(runtime, factory_name, field_name, field_value):
    db = runtime["session"]
    database = runtime["database"]

    target = _make_watch_target(database)
    db.add(target)
    db.commit()

    signal = _make_signal(database, target.id, dedup_key="valid-signal")
    db.add(signal)
    db.commit()

    if factory_name == "WatchTarget":
        record = _make_watch_target(database, **{field_name: field_value, "entity_id": "entity-invalid"})
    elif factory_name == "WatchRun":
        record = database.WatchRun(watch_target_id=target.id, status=field_value)
    elif factory_name == "Signal":
        payload = {
            "watch_target_id": target.id,
            "entity_id": "entity-invalid",
            "signal_type": "new_intelligence",
            "title": "bad-signal",
            "summary": "bad-signal",
            "severity": "low",
            "dedup_key": f"dedup-{field_name}-{field_value}",
        }
        payload[field_name] = field_value
        record = database.Signal(**payload)
    else:
        payload = {
            "user_id": "user-invalid",
            "watch_target_id": target.id,
            "signal_id": signal.id,
            "title": "bad-alert",
            "summary": "bad-alert",
            "severity": "low",
            "status": "unread",
        }
        payload[field_name] = field_value
        record = database.Alert(**payload)

    db.add(record)
    with pytest.raises(Exception):
        db.commit()
    db.rollback()


def test_10_internal_relationships(runtime):
    db = runtime["session"]
    database = runtime["database"]

    target = _make_watch_target(database)
    db.add(target)
    db.commit()

    watch_run = database.WatchRun(watch_target_id=target.id, status="success")
    signal = _make_signal(database, target.id, dedup_key="rel-signal")
    db.add(watch_run)
    db.add(signal)
    db.commit()

    alert = _make_alert(database, target.id, signal.id, user_id="user-rel")
    db.add(alert)
    db.commit()

    db.expire_all()
    loaded = db.query(database.WatchTarget).filter_by(id=target.id).one()
    assert len(loaded.watch_runs) == 1
    assert len(loaded.signals) == 1
    assert len(loaded.alerts) == 1
    assert loaded.signals[0].alerts[0].id == alert.id


def test_11_entity_tables_are_safe(runtime):
    db = runtime["session"]
    database = runtime["database"]

    entity = database.KnowledgeEntity(
        id="entity-safe",
        entity_type="organization",
        name="Entity Safe",
    )
    organization = database.OrganizationProfile(
        id="org-safe",
        name="Org Safe",
        country="PH",
    )
    db.add(entity)
    db.add(organization)
    db.commit()

    target = _make_watch_target(database, entity_id=entity.id)
    db.add(target)
    db.commit()

    target.deleted_at = database.datetime.utcnow()
    db.commit()
    assert db.query(database.KnowledgeEntity).filter_by(id=entity.id).count() == 1
    assert db.query(database.OrganizationProfile).filter_by(id=organization.id).count() == 1

    removable_target = _make_watch_target(database, user_id="user-2", entity_id=entity.id)
    db.add(removable_target)
    db.commit()
    db.delete(removable_target)
    db.commit()

    assert db.query(database.KnowledgeEntity).filter_by(id=entity.id).count() == 1
    assert db.query(database.OrganizationProfile).filter_by(id=organization.id).count() == 1


def test_12_feature_flag_default_false(runtime):
    config = runtime["config"]
    assert config.settings.WATCH_ALERT_V1_ENABLED is False
    assert config.settings.feature_flag("WATCH_ALERT_V1_ENABLED") is False


def test_13_regression_imports(runtime):
    database = runtime["database"]
    config = runtime["config"]

    assert config.settings.DATABASE_URL.endswith("watch_alert_phase41_test.db")
    database.Base.metadata.create_all(bind=database.engine)

    insight_models = importlib.import_module("services.insight_models")
    insight_engine = importlib.import_module("services.insight_engine")
    pipeline_orchestrator = importlib.import_module("services.pipeline_orchestrator")

    assert insight_models is not None
    assert insight_engine is not None
    assert pipeline_orchestrator is not None
