from __future__ import annotations

from datetime import datetime, timedelta

import os
import subprocess
import sys
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from test_auth_api import runtime


@pytest.fixture(autouse=True)
def reset_db(runtime):
    database = runtime["database"]
    auth_models = runtime["auth_models"]
    client = runtime["client"]
    auth_service = runtime["auth_service"]

    db = database.SessionLocal()
    try:
        db.query(auth_models.AuthSession).delete()
        db.query(auth_models.User).delete()
        db.commit()
    finally:
        db.close()

    client.cookies.clear()
    limiter = getattr(auth_service, "_default_rate_limiter", None)
    if limiter is not None:
        lock = getattr(limiter, "_lock", None)
        attempts = getattr(limiter, "_attempts", None)
        if lock is not None and attempts is not None:
            with lock:
                attempts.clear()


def _error_code(response) -> str | None:
    payload = response.json()
    detail = payload.get("detail")
    if isinstance(detail, dict):
        return detail.get("error_code")
    return payload.get("error_code")


def _set_auth_enabled(enabled: bool) -> None:
    import config as config_module

    config_module.settings.AUTH_V1_ENABLED = bool(enabled)


def _probe_auth_disabled(*, endpoint: str) -> tuple[int, str | None]:
    backend_dir = Path(__file__).resolve().parents[1]
    db_path = backend_dir / "data" / "auth_disabled_probe.db"
    if db_path.exists():
        db_path.unlink()

    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"
    env["AUTH_V1_ENABLED"] = "false"
    env["AUTH_CORS_ALLOW_ORIGINS"] = "http://127.0.0.1:4173"
    env["AUTH_PASSWORD_TIME_COST"] = "1"
    env["AUTH_PASSWORD_MEMORY_COST_KIB"] = "8192"
    env["AUTH_PASSWORD_PARALLELISM"] = "1"
    env["AUTH_PASSWORD_HASH_LEN"] = "16"
    env["AUTH_PASSWORD_SALT_LEN"] = "16"

    code = f"""
import json
import sys
from pathlib import Path
from fastapi.testclient import TestClient

backend_dir = Path(r\"{str(backend_dir)}\")
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

mods = [
    'config',
    'main',
    'models.database',
    'models.auth',
    'models.schemas',
    'routers.auth',
    'dependencies.auth',
    'services.auth_service',
]
for m in mods:
    sys.modules.pop(m, None)

import main

client_ctx = TestClient(main.app)
client = client_ctx.__enter__()
try:
    endpoint = {endpoint!r}
    if endpoint.endswith('/change-password'):
        r = client.post(
            endpoint,
            json={{
                'current_password': 'x',
                'new_password': 'NewPassword123!',
                'confirm_password': 'NewPassword123!',
            }},
        )
    else:
        r = client.post(endpoint)
    payload = r.json()
    detail = payload.get('detail')
    err = detail.get('error_code') if isinstance(detail, dict) else payload.get('error_code')
    print(json.dumps({{'status_code': r.status_code, 'error_code': err}}))
finally:
    client_ctx.__exit__(None, None, None)
""".strip()

    result = subprocess.run([sys.executable, "-c", code], text=True, capture_output=True, env=env)
    lines = (result.stdout or "").splitlines()
    parsed: dict = {}
    for line in reversed(lines):
        try:
            candidate = json.loads(line.strip())
        except Exception:
            continue
        if isinstance(candidate, dict) and "status_code" in candidate:
            parsed = candidate
            break
    return int(parsed.get("status_code") or 0), parsed.get("error_code")


def _create_user(runtime, *, email: str, password: str, status: str = "active"):
    database = runtime["database"]
    auth_models = runtime["auth_models"]
    auth_service = runtime["auth_service"]
    db = database.SessionLocal()
    try:
        user = auth_models.User(
            email=email,
            email_normalized=auth_service.normalize_email(email),
            password_hash=auth_service.hash_password(password),
            display_name="User",
            role="viewer",
            status=status,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    finally:
        db.close()


def _login_and_get_token(client: TestClient, *, email: str, password: str) -> str:
    resp = client.post("/api/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200
    set_cookie = resp.headers.get("set-cookie") or ""
    return set_cookie.split(";", 1)[0].split("=", 1)[1]


def test_change_password_success_revokes_all_sessions_and_requires_reauth(runtime):
    config = runtime["config"]
    client = runtime["client"]
    database = runtime["database"]
    auth_models = runtime["auth_models"]
    auth_service = runtime["auth_service"]

    _set_auth_enabled(True)
    user = _create_user(runtime, email="user@example.com", password="OldPassword123!")

    token1 = _login_and_get_token(client, email="user@example.com", password="OldPassword123!")

    db = database.SessionLocal()
    try:
        _, token2 = auth_service.create_auth_session(db, user=user)
        expired_token = auth_service.generate_session_token()
        expired_hash = auth_service.hash_session_token(expired_token)
        expired_session = auth_models.AuthSession(
            user_id=user.id,
            token_hash=expired_hash,
            status="expired",
            created_at=datetime.utcnow(),
            expires_at=datetime.utcnow() - timedelta(seconds=10),
        )
        db.add(expired_session)
        db.commit()
    finally:
        db.close()

    resp = client.post(
        "/api/auth/change-password",
        json={
            "current_password": "OldPassword123!",
            "new_password": "NewPassword123!",
            "confirm_password": "NewPassword123!",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert resp.json()["reauthentication_required"] is True
    cleared_cookie = resp.headers.get("set-cookie") or ""
    assert f"{config.settings.AUTH_COOKIE_NAME}=" in cleared_cookie
    assert "Max-Age=0" in cleared_cookie or "expires=" in cleared_cookie.lower()

    client.cookies.clear()
    me_after = client.get("/api/auth/me")
    assert me_after.status_code == 401
    assert _error_code(me_after) == "AUTH_REQUIRED"

    client.cookies.set(config.settings.AUTH_COOKIE_NAME, token1, path=config.settings.AUTH_COOKIE_PATH)
    me_old = client.get("/api/auth/me")
    assert me_old.status_code == 401
    assert _error_code(me_old) == "SESSION_REVOKED"

    client.cookies.set(config.settings.AUTH_COOKIE_NAME, token2, path=config.settings.AUTH_COOKIE_PATH)
    me_old2 = client.get("/api/auth/me")
    assert me_old2.status_code == 401
    assert _error_code(me_old2) == "SESSION_REVOKED"

    client.cookies.set(config.settings.AUTH_COOKIE_NAME, expired_token, path=config.settings.AUTH_COOKIE_PATH)
    me_expired = client.get("/api/auth/me")
    assert me_expired.status_code == 401
    assert _error_code(me_expired) == "SESSION_EXPIRED"

    old_login = client.post("/api/auth/login", json={"email": "user@example.com", "password": "OldPassword123!"})
    assert old_login.status_code == 401
    assert _error_code(old_login) == "INVALID_CREDENTIALS"

    new_login = client.post("/api/auth/login", json={"email": "user@example.com", "password": "NewPassword123!"})
    assert new_login.status_code == 200

    db = database.SessionLocal()
    try:
        sessions = db.query(auth_models.AuthSession).filter(auth_models.AuthSession.user_id == user.id).all()
        statuses = {s.status for s in sessions}
        assert "revoked" in statuses
        assert "expired" in statuses
    finally:
        db.close()


def test_change_password_wrong_current_password_does_not_revoke_sessions(runtime):
    config = runtime["config"]
    client = runtime["client"]
    database = runtime["database"]
    auth_models = runtime["auth_models"]

    _set_auth_enabled(True)
    user = _create_user(runtime, email="user@example.com", password="OldPassword123!")
    token = _login_and_get_token(client, email="user@example.com", password="OldPassword123!")

    resp = client.post(
        "/api/auth/change-password",
        json={
            "current_password": "wrong",
            "new_password": "NewPassword123!",
            "confirm_password": "NewPassword123!",
        },
    )
    assert resp.status_code == 401
    assert _error_code(resp) == "CURRENT_PASSWORD_INVALID"
    assert "set-cookie" not in {k.lower(): v for k, v in resp.headers.items()}

    client.cookies.set(config.settings.AUTH_COOKIE_NAME, token, path=config.settings.AUTH_COOKIE_PATH)
    me = client.get("/api/auth/me")
    assert me.status_code == 200

    db = database.SessionLocal()
    try:
        sessions = db.query(auth_models.AuthSession).filter(auth_models.AuthSession.user_id == user.id).all()
        assert sessions
        assert all(s.status == "active" for s in sessions)
    finally:
        db.close()


def test_logout_all_revokes_only_current_user_sessions(runtime):
    config = runtime["config"]
    database = runtime["database"]
    auth_models = runtime["auth_models"]
    auth_service = runtime["auth_service"]

    _set_auth_enabled(True)
    user_a = _create_user(runtime, email="a@example.com", password="Password123456!")
    user_b = _create_user(runtime, email="b@example.com", password="Password123456!")

    client_a = runtime["client"]
    token_a1 = _login_and_get_token(client_a, email="a@example.com", password="Password123456!")
    token_b = _login_and_get_token(client_a, email="b@example.com", password="Password123456!")

    client_b_ctx = TestClient(runtime["main"].app)
    client_b = client_b_ctx.__enter__()
    try:
        client_b.cookies.set(config.settings.AUTH_COOKIE_NAME, token_b, path=config.settings.AUTH_COOKIE_PATH)
        me_b = client_b.get("/api/auth/me")
        assert me_b.status_code == 200
    finally:
        client_b_ctx.__exit__(None, None, None)

    db = database.SessionLocal()
    try:
        _, token_a2 = auth_service.create_auth_session(db, user=user_a)
        expired_token = auth_service.generate_session_token()
        expired_hash = auth_service.hash_session_token(expired_token)
        expired_session = auth_models.AuthSession(
            user_id=user_a.id,
            token_hash=expired_hash,
            status="expired",
            created_at=datetime.utcnow(),
            expires_at=datetime.utcnow() - timedelta(seconds=10),
        )
        db.add(expired_session)
        db.commit()
    finally:
        db.close()

    client_a.cookies.set(config.settings.AUTH_COOKIE_NAME, token_a1, path=config.settings.AUTH_COOKIE_PATH)
    resp = client_a.post("/api/auth/logout-all")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["success"] is True
    assert payload["revoked_count"] == 2
    cleared_cookie = resp.headers.get("set-cookie") or ""
    assert f"{config.settings.AUTH_COOKIE_NAME}=" in cleared_cookie

    client_a.cookies.clear()
    me_after = client_a.get("/api/auth/me")
    assert me_after.status_code == 401
    assert _error_code(me_after) == "AUTH_REQUIRED"

    client_a.cookies.set(config.settings.AUTH_COOKIE_NAME, token_a1, path=config.settings.AUTH_COOKIE_PATH)
    me_revoked = client_a.get("/api/auth/me")
    assert me_revoked.status_code == 401
    assert _error_code(me_revoked) == "SESSION_REVOKED"

    client_a.cookies.set(config.settings.AUTH_COOKIE_NAME, token_a2, path=config.settings.AUTH_COOKIE_PATH)
    me_revoked2 = client_a.get("/api/auth/me")
    assert me_revoked2.status_code == 401
    assert _error_code(me_revoked2) == "SESSION_REVOKED"

    client_a.cookies.set(config.settings.AUTH_COOKIE_NAME, expired_token, path=config.settings.AUTH_COOKIE_PATH)
    me_expired = client_a.get("/api/auth/me")
    assert me_expired.status_code == 401
    assert _error_code(me_expired) == "SESSION_EXPIRED"

    db = database.SessionLocal()
    try:
        sessions_a = db.query(auth_models.AuthSession).filter(auth_models.AuthSession.user_id == user_a.id).all()
        assert {s.status for s in sessions_a} == {"revoked", "expired"}

        sessions_b = db.query(auth_models.AuthSession).filter(auth_models.AuthSession.user_id == user_b.id).all()
        assert sessions_b
        assert all(s.status == "active" for s in sessions_b)
    finally:
        db.close()


def test_flag_disabled_change_password_returns_503(runtime):
    status_code, error_code = _probe_auth_disabled(endpoint="/api/auth/change-password")
    assert status_code == 503
    assert error_code == "AUTH_DISABLED"


def test_flag_disabled_logout_all_returns_503(runtime):
    status_code, error_code = _probe_auth_disabled(endpoint="/api/auth/logout-all")
    assert status_code == 503
    assert error_code == "AUTH_DISABLED"
