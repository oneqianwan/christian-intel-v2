from __future__ import annotations

import importlib
import os
import sqlite3
import sys

from pathlib import Path

from sqlalchemy import text

from test_auth_migration import _run_migration
from test_production_readiness_startup_checks import startup_runtime


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def test_fresh_db_bootstrap_and_migration_cover_tenant_tables(tmp_path: Path):
    db_path = tmp_path / "tenant_core.db"
    proc = _run_migration(["--database", str(db_path), "--apply", "--verify"], cwd=BACKEND_DIR)
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "VERIFY_OK=true" in proc.stdout

    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.cursor()
        tables = {row[0] for row in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "tenants" in tables
        assert "tenant_memberships" in tables

        user_columns = {row[1] for row in cur.execute("PRAGMA table_info(users)")}
        tenant_columns = {row[1] for row in cur.execute("PRAGMA table_info(tenants)")}
        membership_columns = {row[1] for row in cur.execute("PRAGMA table_info(tenant_memberships)")}
        assert "default_tenant_id" in user_columns
        assert {"public_id", "slug", "status", "deleted_at"}.issubset(tenant_columns)
        assert {"tenant_id", "user_id", "role", "status", "created_by_user_id", "deleted_at"}.issubset(
            membership_columns
        )

        default_tenant = cur.execute("SELECT slug FROM tenants WHERE slug = 'default'").fetchone()
        assert default_tenant == ("default",)
        membership_count = cur.execute("SELECT COUNT(*) FROM tenant_memberships").fetchone()[0]
        assert membership_count >= 0
    finally:
        conn.close()


def test_existing_users_are_backfilled_with_default_tenant_and_membership(tmp_path: Path):
    db_path = tmp_path / "tenant_backfill.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"
    for module_name in ("config", "models.database", "models.auth", "models.watch_alert"):
        sys.modules.pop(module_name, None)

    database = importlib.import_module("models.database")
    auth_models = importlib.import_module("models.auth")
    importlib.import_module("models.watch_alert")
    database.Base.metadata.create_all(bind=database.engine, tables=[auth_models.User.__table__])
    db = database.SessionLocal()
    try:
        user = auth_models.User(
            email="legacy@example.com",
            email_normalized="legacy@example.com",
            password_hash="hash",
            display_name="Legacy",
            role="viewer",
            status="active",
        )
        db.add(user)
        db.commit()
    finally:
        db.close()
        database.engine.dispose()
        for module_name in ("config", "models.database", "models.auth", "models.watch_alert"):
            sys.modules.pop(module_name, None)

    proc = _run_migration(["--database", str(db_path), "--apply", "--verify"], cwd=BACKEND_DIR)
    assert proc.returncode == 0, proc.stderr + proc.stdout

    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.cursor()
        default_tenant_id = cur.execute(
            "SELECT default_tenant_id FROM users WHERE email_normalized = 'legacy@example.com'"
        ).fetchone()
        assert default_tenant_id is not None
        assert default_tenant_id[0]
        membership = cur.execute(
            "SELECT tm.role, tm.status FROM tenant_memberships tm "
            "JOIN users u ON u.id = tm.user_id "
            "WHERE u.email_normalized = 'legacy@example.com'"
        ).fetchone()
        assert membership == ("viewer", "active")
    finally:
        conn.close()


def test_readiness_detects_missing_tenant_tables(startup_runtime):
    database = startup_runtime["database"]
    checker = startup_runtime["readiness_module"].ProductionReadinessChecker()
    report = checker.build_report()

    assert report["tenant_readiness"]["tenant_core_models_ready"] is True
    assert report["tenant_readiness"]["tenant_membership_ready"] is True
    assert report["tenant_readiness"]["tenant_user_default_tenant_ready"] is True
    assert report["tenant_readiness"]["tenant_isolation_readiness"] == "partial"
    assert report["commercial_readiness"]["public_saas_ready"] is False
    assert report["environment"]["account_token_storage_ok"] is True

    with database.engine.begin() as conn:
        conn.execute(text("DROP TABLE tenant_memberships"))

    missing_report = checker.build_report()
    assert missing_report["tenant_readiness"]["tenant_core_models_ready"] is False
    assert missing_report["tenant_readiness"]["tenant_membership_ready"] is False
    assert missing_report["tenant_readiness"]["tenant_isolation_readiness"] == "blocked"
