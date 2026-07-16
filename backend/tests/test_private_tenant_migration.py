from __future__ import annotations

import sqlite3
import subprocess
import sys

from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
PRIVATE_MIGRATE_SCRIPT = BACKEND_DIR / "scripts" / "migrate_tenant_private_v1.py"


def _run_private_migration(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PRIVATE_MIGRATE_SCRIPT), *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )


def _create_legacy_private_db(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE users (
                id VARCHAR PRIMARY KEY,
                public_id VARCHAR,
                email VARCHAR,
                email_normalized VARCHAR,
                password_hash VARCHAR,
                display_name VARCHAR,
                role VARCHAR,
                status VARCHAR,
                default_tenant_id VARCHAR,
                email_verified_at TIMESTAMP NULL,
                last_login_at TIMESTAMP NULL,
                created_at TIMESTAMP,
                updated_at TIMESTAMP,
                deleted_at TIMESTAMP NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE tenants (
                id VARCHAR PRIMARY KEY,
                public_id VARCHAR,
                name VARCHAR,
                slug VARCHAR,
                status VARCHAR,
                created_at TIMESTAMP,
                updated_at TIMESTAMP,
                deleted_at TIMESTAMP NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE tenant_memberships (
                id VARCHAR PRIMARY KEY,
                public_id VARCHAR,
                tenant_id VARCHAR,
                user_id VARCHAR,
                role VARCHAR,
                status VARCHAR,
                created_by_user_id VARCHAR NULL,
                created_at TIMESTAMP,
                updated_at TIMESTAMP,
                deleted_at TIMESTAMP NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE account_tokens (
                id VARCHAR PRIMARY KEY,
                public_id VARCHAR,
                user_id VARCHAR,
                created_by_user_id VARCHAR NULL,
                token_hash VARCHAR,
                purpose VARCHAR,
                status VARCHAR,
                created_at TIMESTAMP,
                expires_at TIMESTAMP,
                used_at TIMESTAMP NULL,
                revoked_at TIMESTAMP NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE conversations (
                id VARCHAR PRIMARY KEY,
                title VARCHAR,
                owner_user_id VARCHAR NULL,
                is_pinned BOOLEAN,
                pinned_at TIMESTAMP NULL,
                created_at TIMESTAMP,
                updated_at TIMESTAMP
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE messages (
                id VARCHAR PRIMARY KEY,
                conversation_id VARCHAR,
                role VARCHAR,
                content TEXT,
                entities_mentioned JSON NULL,
                sources JSON NULL,
                delivery_type VARCHAR,
                status VARCHAR,
                created_at TIMESTAMP
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE bookmarks (
                id VARCHAR PRIMARY KEY,
                user_id VARCHAR,
                intelligence_item_id VARCHAR NULL,
                note TEXT NULL,
                tags JSON NULL,
                created_at TIMESTAMP
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE user_feedbacks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id VARCHAR,
                user_id VARCHAR NULL,
                feedback_type VARCHAR,
                content TEXT NULL,
                related_entity VARCHAR NULL,
                related_investor VARCHAR NULL,
                created_at TIMESTAMP
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE watch_targets (
                id VARCHAR PRIMARY KEY,
                user_id VARCHAR,
                owner_user_id VARCHAR NULL,
                entity_id VARCHAR,
                entity_type VARCHAR,
                status VARCHAR,
                frequency VARCHAR,
                last_checked_at TIMESTAMP NULL,
                next_check_at TIMESTAMP NULL,
                last_success_at TIMESTAMP NULL,
                last_error_at TIMESTAMP NULL,
                consecutive_failures INTEGER,
                created_at TIMESTAMP,
                updated_at TIMESTAMP,
                deleted_at TIMESTAMP NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE signals (
                id VARCHAR PRIMARY KEY,
                watch_target_id VARCHAR,
                owner_user_id VARCHAR NULL,
                entity_id VARCHAR,
                signal_type VARCHAR,
                title VARCHAR,
                summary TEXT NULL,
                severity VARCHAR,
                evidence_id VARCHAR NULL,
                source_url VARCHAR NULL,
                old_value_json JSON NULL,
                new_value_json JSON NULL,
                detected_at TIMESTAMP,
                dedup_key VARCHAR,
                metadata_json JSON NULL,
                created_at TIMESTAMP
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE alert_rules (
                id VARCHAR PRIMARY KEY,
                user_id VARCHAR NULL,
                signal_type VARCHAR,
                minimum_severity VARCHAR,
                is_enabled BOOLEAN,
                configuration_json JSON NULL,
                created_at TIMESTAMP,
                updated_at TIMESTAMP
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE alerts (
                id VARCHAR PRIMARY KEY,
                user_id VARCHAR,
                owner_user_id VARCHAR NULL,
                watch_target_id VARCHAR,
                signal_id VARCHAR,
                title VARCHAR,
                summary TEXT NULL,
                severity VARCHAR,
                status VARCHAR,
                source_url VARCHAR NULL,
                created_at TIMESTAMP,
                read_at TIMESTAMP NULL,
                dismissed_at TIMESTAMP NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE request_traces (
                id VARCHAR PRIMARY KEY,
                request_id VARCHAR,
                event_type VARCHAR,
                event_data JSON NULL,
                created_at TIMESTAMP
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE user_profiles (
                id VARCHAR PRIMARY KEY,
                session_id VARCHAR,
                name VARCHAR NULL,
                org VARCHAR NULL,
                role VARCHAR NULL,
                project_description TEXT NULL,
                focus_area VARCHAR NULL,
                project_stage VARCHAR NULL,
                focus_region VARCHAR NULL,
                country VARCHAR NULL,
                region VARCHAR NULL,
                preference VARCHAR NULL,
                preferred_investor_type VARCHAR NULL,
                profile_json JSON NULL,
                source VARCHAR NULL,
                confidence FLOAT NULL,
                updated_at TIMESTAMP,
                created_at TIMESTAMP
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_id VARCHAR NULL,
                mission_id VARCHAR NULL,
                title VARCHAR,
                description TEXT NULL,
                priority VARCHAR NULL,
                status VARCHAR NULL,
                created_at TIMESTAMP,
                updated_at TIMESTAMP
            )
            """
        )

        cur.execute(
            "INSERT INTO tenants (id, public_id, name, slug, status, created_at, updated_at, deleted_at) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, NULL)",
            ("tenant-1", "tenant-public-1", "Tenant One", "tenant-one", "active"),
        )
        cur.execute(
            "INSERT INTO users (id, public_id, email, email_normalized, password_hash, display_name, role, status, default_tenant_id, created_at, updated_at, deleted_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, NULL)",
            ("user-1", "user-public-1", "user@example.com", "user@example.com", "hash", "User One", "viewer", "active", "tenant-1"),
        )
        cur.execute(
            "INSERT INTO tenant_memberships (id, public_id, tenant_id, user_id, role, status, created_by_user_id, created_at, updated_at, deleted_at) VALUES (?, ?, ?, ?, ?, ?, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, NULL)",
            ("membership-1", "membership-public-1", "tenant-1", "user-1", "viewer", "active"),
        )
        cur.execute(
            "INSERT INTO account_tokens (id, public_id, user_id, created_by_user_id, token_hash, purpose, status, created_at, expires_at, used_at, revoked_at) VALUES (?, ?, ?, NULL, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, NULL, NULL)",
            ("token-1", "token-public-1", "user-1", "hash-token-1", "setup_password", "active"),
        )

        cur.execute(
            "INSERT INTO conversations (id, title, owner_user_id, is_pinned, pinned_at, created_at, updated_at) VALUES (?, ?, ?, 0, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
            ("conv-1", "Conversation One", "user-1"),
        )
        cur.execute(
            "INSERT INTO messages (id, conversation_id, role, content, delivery_type, status, created_at) VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)",
            ("msg-1", "conv-1", "user", "hello", "text", "completed"),
        )
        cur.execute(
            "INSERT INTO bookmarks (id, user_id, intelligence_item_id, note, created_at) VALUES (?, ?, NULL, ?, CURRENT_TIMESTAMP)",
            ("bookmark-1", "user-1", "note"),
        )
        cur.execute(
            "INSERT INTO user_feedbacks (session_id, user_id, feedback_type, content, created_at) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)",
            ("user:user-1", "user-1", "match_useful", "good"),
        )
        cur.execute(
            "INSERT INTO watch_targets (id, user_id, owner_user_id, entity_id, entity_type, status, frequency, consecutive_failures, created_at, updated_at, deleted_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, NULL)",
            ("watch-1", "user-1", "user-1", "org-1", "organization", "active", "daily", 0),
        )
        cur.execute(
            "INSERT INTO signals (id, watch_target_id, owner_user_id, entity_id, signal_type, title, severity, dedup_key, created_at, detected_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
            ("signal-1", "watch-1", "user-1", "org-1", "new_intelligence", "Signal One", "medium", "dedup-1"),
        )
        cur.execute(
            "INSERT INTO alert_rules (id, user_id, signal_type, minimum_severity, is_enabled, created_at, updated_at) VALUES (?, ?, ?, ?, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
            ("rule-1", "user-1", "new_intelligence", "low"),
        )
        cur.execute(
            "INSERT INTO alerts (id, user_id, owner_user_id, watch_target_id, signal_id, title, severity, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)",
            ("alert-1", "user-1", "user-1", "watch-1", "signal-1", "Alert One", "medium", "unread"),
        )
        cur.execute(
            "INSERT INTO request_traces (id, request_id, event_type, event_data, created_at) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)",
            ("trace-1", "req-1", "route_decided", '{"conversation_id":"conv-1"}'),
        )
        cur.execute(
            "INSERT INTO request_traces (id, request_id, event_type, event_data, created_at) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)",
            ("trace-2", "req-2", "route_decided", '{"note":"unknown"}'),
        )
        cur.execute(
            "INSERT INTO user_profiles (id, session_id, name, source, confidence, updated_at, created_at) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
            ("profile-1", "conv-1", "Known Profile", "conversation", 1.0),
        )
        cur.execute(
            "INSERT INTO user_profiles (id, session_id, name, source, confidence, updated_at, created_at) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
            ("profile-2", "unknown-session", "Unknown Profile", "conversation", 1.0),
        )
        cur.execute(
            "INSERT INTO tasks (entity_id, mission_id, title, description, priority, status, created_at, updated_at) VALUES (?, NULL, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
            ("org-1", "Task One", "Legacy task", "medium", "pending"),
        )
        conn.commit()
    finally:
        conn.close()


def test_private_migration_runs_on_fresh_database(tmp_path: Path):
    db_path = tmp_path / "private_fresh.db"
    proc = _run_private_migration(["--database", str(db_path), "--apply", "--verify"], cwd=BACKEND_DIR)
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "VERIFY_PRIVATE_OK=true" in proc.stdout

    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.cursor()
        conversation_columns = {row[1] for row in cur.execute("PRAGMA table_info(conversations)")}
        message_columns = {row[1] for row in cur.execute("PRAGMA table_info(messages)")}
        watch_target_columns = {row[1] for row in cur.execute("PRAGMA table_info(watch_targets)")}
        assert "tenant_id" in conversation_columns
        assert "tenant_id" in message_columns
        assert "tenant_id" in watch_target_columns
    finally:
        conn.close()


def test_private_migration_adds_columns_and_backfills_existing_database(tmp_path: Path):
    db_path = tmp_path / "private_existing.db"
    _create_legacy_private_db(db_path)

    proc = _run_private_migration(["--database", str(db_path), "--apply", "--verify"], cwd=BACKEND_DIR)
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "VERIFY_PRIVATE_OK=true" in proc.stdout

    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.cursor()
        assert cur.execute("SELECT tenant_id FROM conversations WHERE id = 'conv-1'").fetchone() == ("tenant-1",)
        assert cur.execute("SELECT tenant_id FROM messages WHERE id = 'msg-1'").fetchone() == ("tenant-1",)
        assert cur.execute("SELECT tenant_id FROM bookmarks WHERE id = 'bookmark-1'").fetchone() == ("tenant-1",)
        assert cur.execute("SELECT tenant_id FROM user_feedbacks WHERE user_id = 'user-1'").fetchone() == ("tenant-1",)
        assert cur.execute("SELECT tenant_id FROM watch_targets WHERE id = 'watch-1'").fetchone() == ("tenant-1",)
        assert cur.execute("SELECT tenant_id FROM signals WHERE id = 'signal-1'").fetchone() == ("tenant-1",)
        assert cur.execute("SELECT tenant_id FROM alert_rules WHERE id = 'rule-1'").fetchone() == ("tenant-1",)
        assert cur.execute("SELECT tenant_id FROM alerts WHERE id = 'alert-1'").fetchone() == ("tenant-1",)
        assert cur.execute("SELECT tenant_id FROM request_traces WHERE id = 'trace-1'").fetchone() == ("tenant-1",)
        assert cur.execute("SELECT tenant_id FROM request_traces WHERE id = 'trace-2'").fetchone() == (None,)
        assert cur.execute("SELECT tenant_id FROM user_profiles WHERE id = 'profile-1'").fetchone() == ("tenant-1",)
        assert cur.execute("SELECT tenant_id FROM user_profiles WHERE id = 'profile-2'").fetchone() == (None,)
        assert cur.execute("SELECT tenant_id FROM tasks WHERE id = 1").fetchone() == (None,)
        assert cur.execute("SELECT COUNT(*) FROM account_tokens").fetchone()[0] == 1
        assert cur.execute("SELECT COUNT(*) FROM tenants").fetchone()[0] >= 1
        assert cur.execute("SELECT COUNT(*) FROM tenants WHERE id = 'tenant-1'").fetchone()[0] == 1
        assert cur.execute("SELECT COUNT(*) FROM tenant_memberships").fetchone()[0] >= 1
        assert cur.execute("SELECT COUNT(*) FROM tenant_memberships WHERE tenant_id = 'tenant-1' AND user_id = 'user-1'").fetchone()[0] == 1
    finally:
        conn.close()


def test_private_migration_is_idempotent(tmp_path: Path):
    db_path = tmp_path / "private_idempotent.db"
    _create_legacy_private_db(db_path)

    proc1 = _run_private_migration(["--database", str(db_path), "--apply", "--verify"], cwd=BACKEND_DIR)
    proc2 = _run_private_migration(["--database", str(db_path), "--apply", "--verify"], cwd=BACKEND_DIR)
    assert proc1.returncode == 0, proc1.stderr + proc1.stdout
    assert proc2.returncode == 0, proc2.stderr + proc2.stdout

    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.cursor()
        assert cur.execute("SELECT COUNT(*) FROM conversations").fetchone()[0] == 1
        assert cur.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 1
        assert cur.execute("SELECT COUNT(*) FROM account_tokens").fetchone()[0] == 1
        indexes = {row[1] for row in cur.execute("PRAGMA index_list('conversations')")}
        assert "ix_conversations_tenant_id" in indexes
    finally:
        conn.close()
