from __future__ import annotations

import importlib
import os
import sqlite3
import subprocess
import sys

from pathlib import Path

from sqlalchemy import inspect


BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = BACKEND_DIR.parent
SCRIPT_PATH = BACKEND_DIR / "scripts" / "migrate_legacy_watch_alert_owner.py"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

MODULES_TO_PURGE = [
    "config",
    "models.database",
    "models.auth",
    "models.watch_alert",
    "services.auth_service",
]


def _purge_modules() -> None:
    for module_name in MODULES_TO_PURGE:
        sys.modules.pop(module_name, None)


def _bootstrap_runtime(db_path: Path):
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"
    _purge_modules()
    config = importlib.import_module("config")
    database = importlib.import_module("models.database")
    auth_models = importlib.import_module("models.auth")
    watch_models = importlib.import_module("models.watch_alert")
    auth_service = importlib.import_module("services.auth_service")
    database.init_db()
    return config, database, auth_models, watch_models, auth_service


def _seed_user(database, auth_models, auth_service, *, email: str, password: str, status: str = "active"):
    session = database.SessionLocal()
    try:
        user = auth_models.User(
            email=email,
            email_normalized=email.strip().lower(),
            password_hash=auth_service.hash_password(password),
            display_name=email.split("@", 1)[0],
            role="analyst",
            status=status,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        return user
    finally:
        session.close()


def _seed_legacy_watch_chain(database, watch_models, *, legacy_session_id: str, entity_id: str, owner_user_id: str | None = None):
    session = database.SessionLocal()
    try:
        watch_target = watch_models.WatchTarget(
            user_id=legacy_session_id,
            owner_user_id=owner_user_id,
            entity_id=entity_id,
            entity_type="organization",
            status="active",
            frequency="daily",
        )
        session.add(watch_target)
        session.commit()
        session.refresh(watch_target)

        signal = watch_models.Signal(
            watch_target_id=watch_target.id,
            owner_user_id=owner_user_id,
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

        alert = watch_models.Alert(
            user_id=legacy_session_id,
            owner_user_id=owner_user_id,
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


def _read_owner_state(database, watch_models):
    session = database.SessionLocal()
    try:
        return {
            "watch_targets": [
                (item.id, item.user_id, item.owner_user_id)
                for item in session.query(watch_models.WatchTarget).order_by(watch_models.WatchTarget.id).all()
            ],
            "signals": [
                (item.id, item.watch_target_id, item.owner_user_id)
                for item in session.query(watch_models.Signal).order_by(watch_models.Signal.id).all()
            ],
            "alerts": [
                (item.id, item.user_id, item.watch_target_id, item.owner_user_id)
                for item in session.query(watch_models.Alert).order_by(watch_models.Alert.id).all()
            ],
        }
    finally:
        session.close()


def _run_cli(db_path: Path, *args: str):
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--database",
            str(db_path),
            *args,
        ],
        cwd=str(REPO_DIR),
        capture_output=True,
        text=True,
    )


def test_01_existing_db_upgrade_adds_owner_columns_and_indexes(tmp_path):
    db_path = tmp_path / "watch_alert_owner_upgrade.db"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(
            """
            CREATE TABLE watch_targets (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                status TEXT NOT NULL,
                frequency TEXT NOT NULL,
                last_checked_at TIMESTAMP NULL,
                next_check_at TIMESTAMP NULL,
                last_success_at TIMESTAMP NULL,
                last_error_at TIMESTAMP NULL,
                consecutive_failures INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP NULL,
                updated_at TIMESTAMP NULL,
                deleted_at TIMESTAMP NULL
            );
            CREATE TABLE signals (
                id TEXT PRIMARY KEY,
                watch_target_id TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                signal_type TEXT NOT NULL,
                title TEXT NOT NULL,
                summary TEXT NULL,
                severity TEXT NOT NULL,
                evidence_id TEXT NULL,
                source_url TEXT NULL,
                old_value_json JSON NULL,
                new_value_json JSON NULL,
                detected_at TIMESTAMP NULL,
                dedup_key TEXT NOT NULL,
                metadata_json JSON NULL,
                created_at TIMESTAMP NULL
            );
            CREATE TABLE alerts (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                watch_target_id TEXT NOT NULL,
                signal_id TEXT NOT NULL,
                title TEXT NOT NULL,
                summary TEXT NULL,
                severity TEXT NOT NULL,
                status TEXT NOT NULL,
                source_url TEXT NULL,
                created_at TIMESTAMP NULL,
                read_at TIMESTAMP NULL,
                dismissed_at TIMESTAMP NULL
            );
            INSERT INTO watch_targets (id, user_id, entity_id, entity_type, status, frequency) VALUES
                ('wt-1', 'legacy-a', 'org-a', 'organization', 'active', 'daily');
            INSERT INTO signals (id, watch_target_id, entity_id, signal_type, title, severity, dedup_key) VALUES
                ('sig-1', 'wt-1', 'org-a', 'new_news', 'legacy-signal', 'low', 'wt-1|legacy');
            INSERT INTO alerts (id, user_id, watch_target_id, signal_id, title, severity, status) VALUES
                ('alert-1', 'legacy-a', 'wt-1', 'sig-1', 'legacy-alert', 'low', 'unread');
            """
        )
        conn.commit()
    finally:
        conn.close()

    _, database, _, _, _ = _bootstrap_runtime(db_path)
    inspector = inspect(database.engine)
    watch_columns = {column["name"] for column in inspector.get_columns("watch_targets")}
    signal_columns = {column["name"] for column in inspector.get_columns("signals")}
    alert_columns = {column["name"] for column in inspector.get_columns("alerts")}
    watch_indexes = {item["name"] for item in inspector.get_indexes("watch_targets")}
    signal_indexes = {item["name"] for item in inspector.get_indexes("signals")}
    alert_indexes = {item["name"] for item in inspector.get_indexes("alerts")}
    session = database.SessionLocal()
    try:
        assert session.query(database.WatchTarget).count() == 1
        assert session.query(database.Signal).count() == 1
        assert session.query(database.Alert).count() == 1
    finally:
        session.close()
        database.engine.dispose()

    assert "owner_user_id" in watch_columns
    assert "owner_user_id" in signal_columns
    assert "owner_user_id" in alert_columns
    assert "ix_watch_targets_owner_user_id" in watch_indexes
    assert "ix_signals_owner_user_id_detected_at" in signal_indexes
    assert "ix_alerts_owner_user_id_status_created_at" in alert_indexes


def test_02_default_mode_is_dry_run_and_does_not_write(tmp_path):
    db_path = tmp_path / "watch_alert_owner_migration_dry_run.db"
    _, database, auth_models, watch_models, auth_service = _bootstrap_runtime(db_path)
    _seed_user(database, auth_models, auth_service, email="target@example.com", password="StrongPass123!")
    _seed_legacy_watch_chain(database, watch_models, legacy_session_id="legacy-a", entity_id="org-a")
    before = _read_owner_state(database, watch_models)

    result = _run_cli(
        db_path,
        "--email",
        "target@example.com",
        "--legacy-session-id",
        "legacy-a",
    )

    after = _read_owner_state(database, watch_models)
    database.engine.dispose()

    assert result.returncode == 0, result.stdout + result.stderr
    assert "MODE=dry-run" in result.stdout
    assert "WATCH_TARGETS matched=1 updated=1 skipped=0 conflicts=0" in result.stdout
    assert "SIGNALS matched=1 updated=1 skipped=0 conflicts=0" in result.stdout
    assert "ALERTS matched=1 updated=1 skipped=0 conflicts=0" in result.stdout
    assert before == after


def test_03_apply_migrates_watch_signal_and_alert_owner(tmp_path):
    db_path = tmp_path / "watch_alert_owner_migration_apply.db"
    _, database, auth_models, watch_models, auth_service = _bootstrap_runtime(db_path)
    user = _seed_user(database, auth_models, auth_service, email="target@example.com", password="StrongPass123!")
    _seed_legacy_watch_chain(database, watch_models, legacy_session_id="legacy-a", entity_id="org-a")

    result = _run_cli(
        db_path,
        "--email",
        "target@example.com",
        "--legacy-session-id",
        "legacy-a",
        "--apply",
    )

    state = _read_owner_state(database, watch_models)
    database.engine.dispose()

    assert result.returncode == 0, result.stdout + result.stderr
    assert "MODE=apply" in result.stdout
    assert "CONSISTENCY_CHECK=PASS" in result.stdout
    assert state["watch_targets"][0][2] == str(user.id)
    assert state["signals"][0][2] == str(user.id)
    assert state["alerts"][0][3] == str(user.id)


def test_04_missing_user_fails_safely(tmp_path):
    db_path = tmp_path / "watch_alert_owner_missing_user.db"
    _, database, _, watch_models, _ = _bootstrap_runtime(db_path)
    _seed_legacy_watch_chain(database, watch_models, legacy_session_id="legacy-a", entity_id="org-a")

    result = _run_cli(
        db_path,
        "--email",
        "missing@example.com",
        "--legacy-session-id",
        "legacy-a",
        "--apply",
    )

    state = _read_owner_state(database, watch_models)
    database.engine.dispose()

    assert result.returncode == 1
    assert "ERROR=USER_NOT_FOUND" in result.stdout
    assert state["watch_targets"][0][2] is None


def test_05_disabled_user_is_rejected(tmp_path):
    db_path = tmp_path / "watch_alert_owner_disabled_user.db"
    _, database, auth_models, watch_models, auth_service = _bootstrap_runtime(db_path)
    _seed_user(
        database,
        auth_models,
        auth_service,
        email="disabled@example.com",
        password="StrongPass123!",
        status="disabled",
    )
    _seed_legacy_watch_chain(database, watch_models, legacy_session_id="legacy-a", entity_id="org-a")

    result = _run_cli(
        db_path,
        "--email",
        "disabled@example.com",
        "--legacy-session-id",
        "legacy-a",
        "--apply",
    )
    database.engine.dispose()

    assert result.returncode == 1
    assert "ERROR=USER_NOT_ACTIVE" in result.stdout


def test_06_apply_is_idempotent(tmp_path):
    db_path = tmp_path / "watch_alert_owner_idempotent.db"
    _, database, auth_models, watch_models, auth_service = _bootstrap_runtime(db_path)
    _seed_user(database, auth_models, auth_service, email="target@example.com", password="StrongPass123!")
    _seed_legacy_watch_chain(database, watch_models, legacy_session_id="legacy-a", entity_id="org-a")

    first = _run_cli(
        db_path,
        "--email",
        "target@example.com",
        "--legacy-session-id",
        "legacy-a",
        "--apply",
    )
    second = _run_cli(
        db_path,
        "--email",
        "target@example.com",
        "--legacy-session-id",
        "legacy-a",
        "--apply",
    )
    database.engine.dispose()

    assert first.returncode == 0
    assert second.returncode == 0
    assert "WATCH_TARGETS matched=1 updated=0 skipped=1 conflicts=0" in second.stdout
    assert "SIGNALS matched=1 updated=0 skipped=1 conflicts=0" in second.stdout
    assert "ALERTS matched=1 updated=0 skipped=1 conflicts=0" in second.stdout


def test_07_conflicting_owner_is_reported_and_not_overwritten(tmp_path):
    db_path = tmp_path / "watch_alert_owner_conflict.db"
    _, database, auth_models, watch_models, auth_service = _bootstrap_runtime(db_path)
    target_user = _seed_user(database, auth_models, auth_service, email="target@example.com", password="StrongPass123!")
    other_user = _seed_user(database, auth_models, auth_service, email="other@example.com", password="StrongPass123!")
    _seed_legacy_watch_chain(
        database,
        watch_models,
        legacy_session_id="legacy-a",
        entity_id="org-a",
        owner_user_id=str(other_user.id),
    )

    result = _run_cli(
        db_path,
        "--email",
        "target@example.com",
        "--legacy-session-id",
        "legacy-a",
        "--apply",
    )

    state = _read_owner_state(database, watch_models)
    database.engine.dispose()

    assert result.returncode == 0, result.stdout + result.stderr
    assert "WATCH_TARGETS matched=1 updated=0 skipped=0 conflicts=1" in result.stdout
    assert "SIGNALS matched=1 updated=0 skipped=0 conflicts=1" in result.stdout
    assert "ALERTS matched=1 updated=0 skipped=0 conflicts=1" in result.stdout
    assert state["watch_targets"][0][2] == str(other_user.id)
    assert state["watch_targets"][0][2] != str(target_user.id)


def test_08_apply_merges_legacy_chain_when_target_already_owns_same_entity(tmp_path):
    db_path = tmp_path / "watch_alert_owner_merge_existing_target.db"
    _, database, auth_models, watch_models, auth_service = _bootstrap_runtime(db_path)
    target_user = _seed_user(database, auth_models, auth_service, email="target@example.com", password="StrongPass123!")
    legacy_watch_id, legacy_signal_id, legacy_alert_id = _seed_legacy_watch_chain(
        database,
        watch_models,
        legacy_session_id="legacy-a",
        entity_id="org-a",
    )

    session = database.SessionLocal()
    try:
        existing_watch = watch_models.WatchTarget(
            user_id="current-user-session",
            owner_user_id=str(target_user.id),
            entity_id="org-a",
            entity_type="organization",
            status="active",
            frequency="daily",
        )
        session.add(existing_watch)
        session.commit()
        session.refresh(existing_watch)
        existing_watch_id = str(existing_watch.id)
    finally:
        session.close()

    result = _run_cli(
        db_path,
        "--email",
        "target@example.com",
        "--legacy-session-id",
        "legacy-a",
        "--apply",
    )

    session = database.SessionLocal()
    try:
        migrated_watch = session.query(watch_models.WatchTarget).filter(watch_models.WatchTarget.id == legacy_watch_id).one()
        migrated_signal = session.query(watch_models.Signal).filter(watch_models.Signal.id == legacy_signal_id).one()
        migrated_alert = session.query(watch_models.Alert).filter(watch_models.Alert.id == legacy_alert_id).one()
    finally:
        session.close()
        database.engine.dispose()

    assert result.returncode == 0, result.stdout + result.stderr
    assert "WATCH_TARGETS matched=1 updated=0 skipped=1 conflicts=0" in result.stdout
    assert "SIGNALS matched=1 updated=1 skipped=0 conflicts=0" in result.stdout
    assert "ALERTS matched=1 updated=1 skipped=0 conflicts=0" in result.stdout
    assert "CONSISTENCY_CHECK=PASS" in result.stdout
    assert migrated_watch.owner_user_id == str(target_user.id)
    assert migrated_watch.deleted_at is not None
    assert migrated_signal.owner_user_id == str(target_user.id)
    assert migrated_signal.watch_target_id == existing_watch_id
    assert migrated_alert.owner_user_id == str(target_user.id)
    assert migrated_alert.watch_target_id == existing_watch_id
