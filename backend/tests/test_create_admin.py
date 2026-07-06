from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path

import pytest


BACKEND_DIR = Path(__file__).resolve().parents[1]
TEST_DB_PATH = BACKEND_DIR / "data" / "create_admin_test.db"
SCRIPT_PATH = BACKEND_DIR / "scripts" / "create_admin.py"


@pytest.fixture(autouse=True)
def _reset_db_file():
    TEST_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()
    yield
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()


def _run_create_admin(
    *, email: str, display_name: str, password: str | None, confirm: str | None = None
) -> tuple[int, str]:
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH.as_posix()}"
    env["AUTH_CORS_ALLOW_ORIGINS"] = "http://127.0.0.1:4173"
    env["AUTH_PASSWORD_TIME_COST"] = "1"
    env["AUTH_PASSWORD_MEMORY_COST_KIB"] = "8192"
    env["AUTH_PASSWORD_PARALLELISM"] = "1"
    env["AUTH_PASSWORD_HASH_LEN"] = "16"
    env["AUTH_PASSWORD_SALT_LEN"] = "16"
    env["AUTH_PASSWORD_MIN_LENGTH"] = "12"
    env["AUTH_PASSWORD_MAX_LENGTH"] = "128"
    env.pop("CIO_BOOTSTRAP_ADMIN_PASSWORD", None)
    env.pop("CIO_BOOTSTRAP_ADMIN_PASSWORD_CONFIRM", None)
    if password is not None:
        env["CIO_BOOTSTRAP_ADMIN_PASSWORD"] = password
    if confirm is not None:
        env["CIO_BOOTSTRAP_ADMIN_PASSWORD_CONFIRM"] = confirm

    cmd = [
        sys.executable,
        str(SCRIPT_PATH),
        "--email",
        email,
        "--display-name",
        display_name,
        "--database",
        str(TEST_DB_PATH),
    ]
    result = subprocess.run(cmd, text=True, capture_output=True, env=env)
    output = (result.stdout or "") + (result.stderr or "")
    return int(result.returncode), output


def _init_db() -> None:
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH.as_posix()}"
    cmd = [
        sys.executable,
        "-c",
        "import os,sys; from pathlib import Path; "
        f"sys.path.insert(0, r\"{str(BACKEND_DIR)}\"); "
        "from models.database import init_db; import models.auth; init_db()",
    ]
    subprocess.run(cmd, text=True, capture_output=True, env=env, check=True)


def _query_one(sql: str, params: tuple = ()) -> tuple | None:
    if not TEST_DB_PATH.exists():
        return None
    conn = sqlite3.connect(str(TEST_DB_PATH))
    try:
        cur = conn.execute(sql, params)
        return cur.fetchone()
    finally:
        conn.close()


def _query_all(sql: str, params: tuple = ()) -> list[tuple]:
    if not TEST_DB_PATH.exists():
        return []
    conn = sqlite3.connect(str(TEST_DB_PATH))
    try:
        cur = conn.execute(sql, params)
        return list(cur.fetchall())
    finally:
        conn.close()


def test_create_first_super_admin_success():
    code, output = _run_create_admin(
        email="Admin@Example.com",
        display_name="Root",
        password="CorrectHorseBatteryStaple!",
        confirm="CorrectHorseBatteryStaple!",
    )
    assert code == 0
    assert "CREATED_SUPER_ADMIN" in output
    assert "CorrectHorseBatteryStaple!" not in output
    assert "$argon2" not in output

    row = _query_one("SELECT role, status, email_normalized, password_hash FROM users")
    assert row is not None
    role, status, email_normalized, password_hash = row
    assert role == "super_admin"
    assert status == "active"
    assert email_normalized == "admin@example.com"
    assert str(password_hash).startswith("$argon2id$")
    assert _query_one("SELECT COUNT(*) FROM auth_sessions")[0] == 0


def test_existing_super_admin_refuses_second_creation():
    _run_create_admin(
        email="admin@example.com",
        display_name="Root",
        password="CorrectHorseBatteryStaple!",
        confirm="CorrectHorseBatteryStaple!",
    )
    code, output = _run_create_admin(
        email="admin2@example.com",
        display_name="Root2",
        password="AnotherCorrectHorseBatteryStaple!",
        confirm="AnotherCorrectHorseBatteryStaple!",
    )
    assert code == 1
    assert "SUPER_ADMIN_ALREADY_EXISTS" in output


def test_existing_user_email_not_elevated():
    _init_db()
    conn = sqlite3.connect(str(TEST_DB_PATH))
    try:
        now = datetime.utcnow().isoformat()
        conn.execute(
            "INSERT INTO users (id, public_id, email, email_normalized, password_hash, display_name, role, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(uuid.uuid4()),
                str(uuid.uuid4()),
                "viewer@example.com",
                "viewer@example.com",
                "not-a-real-hash",
                "Viewer",
                "viewer",
                "active",
                now,
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    code, output = _run_create_admin(
        email="viewer@example.com",
        display_name="Root",
        password="CorrectHorseBatteryStaple!",
        confirm="CorrectHorseBatteryStaple!",
    )
    assert code == 1
    assert "USER_EMAIL_EXISTS" in output

    roles = [row[0] for row in _query_all("SELECT role FROM users")]
    assert roles == ["viewer"]


def test_password_confirmation_mismatch_fails_and_creates_no_user():
    code, output = _run_create_admin(
        email="admin@example.com",
        display_name="Root",
        password="pw1",
        confirm="pw2",
    )
    assert code == 1
    assert "PASSWORD_CONFIRMATION_MISMATCH" in output
    assert not TEST_DB_PATH.exists()


def test_password_too_short_fails():
    code, output = _run_create_admin(
        email="admin@example.com",
        display_name="Root",
        password="short",
        confirm="short",
    )
    assert code == 1
    assert "PASSWORD_TOO_SHORT" in output


def test_invalid_email_fails():
    code, output = _run_create_admin(
        email="not-an-email",
        display_name="Root",
        password="CorrectHorseBatteryStaple!",
        confirm="CorrectHorseBatteryStaple!",
    )
    assert code == 1
    assert "INVALID_EMAIL" in output


def test_no_password_argument_supported():
    env = os.environ.copy()
    env["CIO_BOOTSTRAP_ADMIN_PASSWORD"] = "CorrectHorseBatteryStaple!"
    env["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH.as_posix()}"
    cmd = [
        sys.executable,
        str(SCRIPT_PATH),
        "--email",
        "admin@example.com",
        "--display-name",
        "Root",
        "--database",
        str(TEST_DB_PATH),
        "--password",
        "pw",
    ]
    result = subprocess.run(cmd, text=True, capture_output=True, env=env)
    out = (result.stdout or "") + (result.stderr or "")
    assert result.returncode != 0
    assert "--password" in out
