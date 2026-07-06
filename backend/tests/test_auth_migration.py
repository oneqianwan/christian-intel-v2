from __future__ import annotations

import importlib
import os
import sqlite3
import subprocess
import sys

from pathlib import Path

import pytest


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

SCRIPTS_DIR = BACKEND_DIR / "scripts"
MIGRATE_SCRIPT = SCRIPTS_DIR / "migrate_auth_v1.py"


def _run_migration(args: list[str], *, cwd: Path, env: dict | None = None) -> subprocess.CompletedProcess:
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    return subprocess.run(
        [sys.executable, str(MIGRATE_SCRIPT), *args],
        cwd=str(cwd),
        env=full_env,
        capture_output=True,
        text=True,
    )


def test_refuse_without_database_arg():
    proc = subprocess.run(
        [sys.executable, str(MIGRATE_SCRIPT)],
        cwd=str(BACKEND_DIR),
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0


def test_empty_db_apply_and_verify(tmp_path: Path):
    db_path = tmp_path / "auth_empty.db"
    if db_path.exists():
        db_path.unlink()

    proc = _run_migration(["--database", str(db_path), "--apply", "--verify"], cwd=BACKEND_DIR)
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "VERIFY_OK=true" in proc.stdout

    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.cursor()
        tables = {row[0] for row in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "users" in tables
        assert "auth_sessions" in tables
    finally:
        conn.close()


def _create_existing_db(db_path: Path) -> None:
    if db_path.exists():
        db_path.unlink()

    os.environ["DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"

    for module_name in ("config", "models.database", "models.watch_alert"):
        sys.modules.pop(module_name, None)

    database = importlib.import_module("models.database")
    importlib.import_module("models.watch_alert")

    database.Base.metadata.create_all(bind=database.engine)

    db = database.SessionLocal()
    try:
        conv = database.Conversation(id="c1", title="t1")
        db.add(conv)
        db.commit()
    finally:
        db.close()
        database.engine.dispose()
        for module_name in ("config", "models.database", "models.watch_alert"):
            sys.modules.pop(module_name, None)


def test_existing_db_additive_and_idempotent(tmp_path: Path):
    db_path = tmp_path / "auth_existing.db"
    _create_existing_db(db_path)

    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.cursor()
        before_tables = {row[0] for row in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        before_conv_count = cur.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
    finally:
        conn.close()

    proc1 = _run_migration(["--database", str(db_path), "--apply", "--verify"], cwd=BACKEND_DIR)
    assert proc1.returncode == 0, proc1.stderr + proc1.stdout
    assert "VERIFY_OK=true" in proc1.stdout

    proc2 = _run_migration(["--database", str(db_path), "--apply", "--verify"], cwd=BACKEND_DIR)
    assert proc2.returncode == 0, proc2.stderr + proc2.stdout
    assert "VERIFY_OK=true" in proc2.stdout

    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.cursor()
        after_tables = {row[0] for row in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        after_conv_count = cur.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
    finally:
        conn.close()

    assert before_tables.issubset(after_tables)
    assert "users" in after_tables
    assert "auth_sessions" in after_tables
    assert before_conv_count == after_conv_count

