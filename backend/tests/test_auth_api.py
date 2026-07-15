from __future__ import annotations

import importlib
import os
import sys

from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

TEST_DB_PATH = BACKEND_DIR / "data" / "auth_api_test.db"
MODULES_TO_PURGE = [
    "config",
    "main",
    "models.database",
    "models.auth",
    "models.schemas",
    "routers.auth",
    "dependencies.auth",
    "services.auth_service",
]

_RUNTIME_CONFIG = None


def _purge_modules() -> None:
    for module_name in MODULES_TO_PURGE:
        sys.modules.pop(module_name, None)


@pytest.fixture(scope="session")
def runtime():
    TEST_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()

    os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH.as_posix()}"
    os.environ["AUTH_CORS_ALLOW_ORIGINS"] = "http://127.0.0.1:4173"
    os.environ["AUTH_PASSWORD_TIME_COST"] = "1"
    os.environ["AUTH_PASSWORD_MEMORY_COST_KIB"] = "8192"
    os.environ["AUTH_PASSWORD_PARALLELISM"] = "1"
    os.environ["AUTH_PASSWORD_HASH_LEN"] = "16"
    os.environ["AUTH_PASSWORD_SALT_LEN"] = "16"
    os.environ["AUTH_LOGIN_MAX_ATTEMPTS"] = "3"
    os.environ["AUTH_LOGIN_WINDOW_SECONDS"] = "60"

    _purge_modules()

    config = importlib.import_module("config")
    database = importlib.import_module("models.database")
    auth_models = importlib.import_module("models.auth")
    auth_service = importlib.import_module("services.auth_service")
    main = importlib.import_module("main")

    client_ctx = TestClient(main.app)
    client = client_ctx.__enter__()

    yield {
        "config": config,
        "database": database,
        "auth_models": auth_models,
        "auth_service": auth_service,
        "main": main,
        "client": client,
    }

    client_ctx.__exit__(None, None, None)
    database.engine.dispose()
    _purge_modules()
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()


@pytest.fixture(autouse=True)
def reset_db(runtime):
    global _RUNTIME_CONFIG
    database = runtime["database"]
    auth_models = runtime["auth_models"]
    client = runtime["client"]
    auth_service = runtime["auth_service"]
    _RUNTIME_CONFIG = runtime["config"]

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
    _reset_auth_settings(runtime)


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


def _error_code(response) -> str | None:
    payload = response.json()
    detail = payload.get("detail")
    if isinstance(detail, dict):
        return detail.get("error_code")
    return payload.get("error_code")


def _set_auth_enabled(enabled: bool) -> None:
    value = bool(enabled)
    if _RUNTIME_CONFIG is not None:
        _RUNTIME_CONFIG.settings.AUTH_V1_ENABLED = value
    config_module = sys.modules.get("config")
    if config_module is not None:
        config_module.settings.AUTH_V1_ENABLED = value
    auth_dependencies = sys.modules.get("dependencies.auth")
    if auth_dependencies is not None:
        auth_dependencies.config.settings.AUTH_V1_ENABLED = value


def _reset_auth_settings(runtime) -> None:
    settings = runtime["config"].settings
    settings.APP_ENV = "production"
    settings.DEPLOYMENT_ENV = "production"
    settings.AUTH_V1_ENABLED = True
    settings.AUTH_COOKIE_REQUIRED = True
    settings.AUTH_COOKIE_SECURE = False
    settings.AUTH_COOKIE_SAMESITE = "lax"
    settings.CHAT_USER_OWNERSHIP_ENABLED = True
    settings.WATCH_ALERT_USER_OWNERSHIP_ENABLED = True
    settings.BOOKMARKS_USER_OWNERSHIP_ENABLED = True
    settings.FEEDBACK_USER_OWNERSHIP_ENABLED = True
    settings.ALLOW_PUBLIC_CORE_APIS = False
    settings.ALLOW_LEGACY_SESSION_ID = False
    settings.ALLOW_ANONYMOUS_FEEDBACK = False
    settings.WATCH_ALERT_V1_ENABLED = True
    settings.WATCH_ALERT_NOTIFICATIONS_ENABLED = True
    settings.WATCH_ALERT_SCHEDULER_ENABLED = True


def test_flag_disabled_login_returns_503(runtime):
    config = runtime["config"]
    client = runtime["client"]

    _set_auth_enabled(False)
    response = client.post("/api/auth/login", json={"email": "a@example.com", "password": "pw"})
    assert response.status_code == 503
    assert _error_code(response) == "AUTH_DISABLED"
    assert "set-cookie" not in {k.lower(): v for k, v in response.headers.items()}


def test_flag_disabled_me_returns_503(runtime):
    config = runtime["config"]
    client = runtime["client"]

    _set_auth_enabled(False)
    response = client.get("/api/auth/me")
    assert response.status_code == 503
    assert _error_code(response) == "AUTH_DISABLED"


def test_login_sets_cookie_and_returns_user(runtime):
    config = runtime["config"]
    client = runtime["client"]
    database = runtime["database"]
    auth_models = runtime["auth_models"]
    auth_service = runtime["auth_service"]

    _set_auth_enabled(True)
    _create_user(runtime, email="user@example.com", password="pw")

    response = client.post("/api/auth/login", json={"email": "user@example.com", "password": "pw"})
    assert response.status_code == 200
    payload = response.json()
    assert "user" in payload
    assert payload["user"]["email"] == "user@example.com"
    assert "password_hash" not in str(payload).lower()
    assert "token_hash" not in str(payload).lower()

    set_cookie = response.headers.get("set-cookie") or ""
    assert f"{config.settings.AUTH_COOKIE_NAME}=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert f"Path={config.settings.AUTH_COOKIE_PATH}" in set_cookie
    assert f"Max-Age={config.settings.AUTH_SESSION_TTL_SECONDS}" in set_cookie
    assert f"SameSite={config.settings.AUTH_COOKIE_SAMESITE.capitalize()}" in set_cookie or f"SameSite={config.settings.AUTH_COOKIE_SAMESITE}" in set_cookie

    raw_token = set_cookie.split(";", 1)[0].split("=", 1)[1]
    assert raw_token
    assert raw_token not in str(payload)

    db = database.SessionLocal()
    try:
        session = db.query(auth_models.AuthSession).one()
        assert session.token_hash == auth_service.hash_session_token(raw_token)
        assert session.token_hash != raw_token
    finally:
        db.close()


def test_flag_disabled_login_does_not_create_session(runtime):
    config = runtime["config"]
    client = runtime["client"]
    database = runtime["database"]
    auth_models = runtime["auth_models"]

    _set_auth_enabled(False)
    _create_user(runtime, email="user@example.com", password="pw")

    resp = client.post("/api/auth/login", json={"email": "user@example.com", "password": "pw"})
    assert resp.status_code == 503
    assert _error_code(resp) == "AUTH_DISABLED"

    db = database.SessionLocal()
    try:
        assert db.query(auth_models.AuthSession).count() == 0
    finally:
        db.close()


def test_invalid_credentials_same_error(runtime):
    config = runtime["config"]
    client = runtime["client"]

    _set_auth_enabled(True)
    _create_user(runtime, email="known@example.com", password="pw")

    resp1 = client.post("/api/auth/login", json={"email": "known@example.com", "password": "wrong"})
    resp2 = client.post("/api/auth/login", json={"email": "unknown@example.com", "password": "pw"})
    assert resp1.status_code == 401
    assert resp2.status_code == 401
    assert _error_code(resp1) == "INVALID_CREDENTIALS"
    assert _error_code(resp2) == "INVALID_CREDENTIALS"


def test_disabled_user_forbidden(runtime):
    config = runtime["config"]
    client = runtime["client"]

    _set_auth_enabled(True)
    _create_user(runtime, email="disabled@example.com", password="pw", status="disabled")

    response = client.post("/api/auth/login", json={"email": "disabled@example.com", "password": "pw"})
    assert response.status_code == 403
    assert _error_code(response) == "ACCOUNT_DISABLED"


def test_pending_user_forbidden(runtime):
    config = runtime["config"]
    client = runtime["client"]

    _set_auth_enabled(True)
    _create_user(runtime, email="pending@example.com", password="pw", status="pending")

    response = client.post("/api/auth/login", json={"email": "pending@example.com", "password": "pw"})
    assert response.status_code == 403
    assert _error_code(response) == "ACCOUNT_PENDING"


def test_empty_password_rejected(runtime):
    config = runtime["config"]
    client = runtime["client"]

    _set_auth_enabled(True)
    response = client.post("/api/auth/login", json={"email": "user@example.com", "password": ""})
    assert response.status_code == 422


def test_oversized_password_rejected(runtime):
    config = runtime["config"]
    client = runtime["client"]

    _set_auth_enabled(True)
    response = client.post("/api/auth/login", json={"email": "user@example.com", "password": "x" * 300})
    assert response.status_code == 422


def test_me_requires_cookie_and_does_not_accept_x_session_id(runtime):
    config = runtime["config"]
    client = runtime["client"]

    _set_auth_enabled(True)
    response = client.get("/api/auth/me", headers={"x-session-id": "session-anything"})
    assert response.status_code == 401
    assert _error_code(response) == "AUTH_REQUIRED"


def test_me_does_not_accept_user_id_query_param(runtime):
    config = runtime["config"]
    client = runtime["client"]

    _set_auth_enabled(True)
    response = client.get("/api/auth/me", params={"user_id": "any"})
    assert response.status_code == 401
    assert _error_code(response) == "AUTH_REQUIRED"


def test_logout_revokes_session_and_clears_cookie(runtime):
    config = runtime["config"]
    client = runtime["client"]
    database = runtime["database"]
    auth_models = runtime["auth_models"]
    auth_service = runtime["auth_service"]

    _set_auth_enabled(True)
    _create_user(runtime, email="user@example.com", password="pw")

    login_resp = client.post("/api/auth/login", json={"email": "user@example.com", "password": "pw"})
    assert login_resp.status_code == 200
    set_cookie = login_resp.headers.get("set-cookie") or ""
    raw_token = set_cookie.split(";", 1)[0].split("=", 1)[1]
    token_hash = auth_service.hash_session_token(raw_token)

    me_resp = client.get("/api/auth/me")
    assert me_resp.status_code == 200

    logout_resp = client.post("/api/auth/logout")
    assert logout_resp.status_code == 200
    assert logout_resp.json()["success"] is True
    cleared_cookie = logout_resp.headers.get("set-cookie") or ""
    assert f"{config.settings.AUTH_COOKIE_NAME}=" in cleared_cookie
    assert "Max-Age=0" in cleared_cookie or "expires=" in cleared_cookie.lower()

    me_after = client.get("/api/auth/me")
    assert me_after.status_code == 401
    assert _error_code(me_after) == "AUTH_REQUIRED"

    client.cookies.set(config.settings.AUTH_COOKIE_NAME, raw_token, path=config.settings.AUTH_COOKIE_PATH)
    me_revoked = client.get("/api/auth/me")
    assert me_revoked.status_code == 401
    assert _error_code(me_revoked) == "SESSION_REVOKED"

    logout_again = client.post("/api/auth/logout")
    assert logout_again.status_code == 200
    assert logout_again.json()["success"] is True

    db = database.SessionLocal()
    try:
        session = db.query(auth_models.AuthSession).filter(auth_models.AuthSession.token_hash == token_hash).one()
        assert session.status == "revoked"
        assert session.revoked_at is not None
    finally:
        db.close()


def test_expired_session_returns_401(runtime):
    config = runtime["config"]
    client = runtime["client"]
    database = runtime["database"]
    auth_models = runtime["auth_models"]
    auth_service = runtime["auth_service"]

    _set_auth_enabled(True)
    user = _create_user(runtime, email="user@example.com", password="pw")
    raw_token = auth_service.generate_session_token()
    token_hash = auth_service.hash_session_token(raw_token)

    db = database.SessionLocal()
    try:
        session = auth_models.AuthSession(
            user_id=user.id,
            token_hash=token_hash,
            status="active",
            created_at=datetime.utcnow(),
            expires_at=datetime.utcnow() - timedelta(seconds=10),
        )
        db.add(session)
        db.commit()
    finally:
        db.close()

    client.cookies.set(config.settings.AUTH_COOKIE_NAME, raw_token, path=config.settings.AUTH_COOKIE_PATH)
    response = client.get("/api/auth/me")
    assert response.status_code == 401
    assert _error_code(response) == "SESSION_EXPIRED"


def test_invalid_session_returns_401(runtime):
    config = runtime["config"]
    client = runtime["client"]

    _set_auth_enabled(True)
    client.cookies.set(config.settings.AUTH_COOKIE_NAME, "not-a-real-token", path=config.settings.AUTH_COOKIE_PATH)
    response = client.get("/api/auth/me")
    assert response.status_code == 401
    assert _error_code(response) == "INVALID_SESSION"


def test_rate_limit_returns_429(runtime):
    config = runtime["config"]
    client = runtime["client"]

    _set_auth_enabled(True)
    config.settings.AUTH_LOGIN_RATE_LIMIT_ENABLED = True

    for _ in range(3):
        resp = client.post("/api/auth/login", json={"email": "unknown@example.com", "password": "pw"})
        assert resp.status_code == 401

    limited = client.post("/api/auth/login", json={"email": "unknown@example.com", "password": "pw"})
    assert limited.status_code == 429
    assert _error_code(limited) == "LOGIN_RATE_LIMITED"
    assert "Retry-After" in limited.headers


def test_cookie_value_is_not_user_id_or_public_id(runtime):
    config = runtime["config"]
    client = runtime["client"]

    _set_auth_enabled(True)
    user = _create_user(runtime, email="user@example.com", password="pw")

    response = client.post("/api/auth/login", json={"email": "user@example.com", "password": "pw"})
    assert response.status_code == 200
    set_cookie = response.headers.get("set-cookie") or ""
    raw_token = set_cookie.split(";", 1)[0].split("=", 1)[1]
    assert raw_token not in {str(user.id), str(user.public_id)}


def test_needs_rehash_upgrades_password_hash_on_login(runtime):
    config = runtime["config"]
    client = runtime["client"]
    database = runtime["database"]
    auth_models = runtime["auth_models"]
    auth_service = runtime["auth_service"]

    _set_auth_enabled(True)
    config.settings.AUTH_PASSWORD_TIME_COST = 1
    user = _create_user(runtime, email="user@example.com", password="pw")

    db = database.SessionLocal()
    try:
        before = db.query(auth_models.User).filter(auth_models.User.id == user.id).one().password_hash
    finally:
        db.close()

    config.settings.AUTH_PASSWORD_TIME_COST = 2

    response = client.post("/api/auth/login", json={"email": "user@example.com", "password": "pw"})
    assert response.status_code == 200

    db = database.SessionLocal()
    try:
        after = db.query(auth_models.User).filter(auth_models.User.id == user.id).one().password_hash
    finally:
        db.close()
    assert before != after
    assert auth_service.verify_password(after, "pw") is True


def test_last_seen_throttled(runtime):
    config = runtime["config"]
    client = runtime["client"]
    database = runtime["database"]
    auth_models = runtime["auth_models"]

    _set_auth_enabled(True)
    config.settings.AUTH_SESSION_LAST_SEEN_UPDATE_SECONDS = 60
    _create_user(runtime, email="user@example.com", password="pw")

    login_resp = client.post("/api/auth/login", json={"email": "user@example.com", "password": "pw"})
    assert login_resp.status_code == 200

    me1 = client.get("/api/auth/me")
    assert me1.status_code == 200

    db = database.SessionLocal()
    try:
        session = db.query(auth_models.AuthSession).one()
        first_last_seen = session.last_seen_at
        assert first_last_seen is not None
    finally:
        db.close()

    me2 = client.get("/api/auth/me")
    assert me2.status_code == 200

    db = database.SessionLocal()
    try:
        session = db.query(auth_models.AuthSession).one()
        assert session.last_seen_at == first_last_seen
    finally:
        db.close()


def test_cors_credentials_headers(runtime):
    config = runtime["config"]
    client = runtime["client"]

    _set_auth_enabled(True)
    allowed_origin = "http://127.0.0.1:4173"
    resp_allowed = client.get("/api/auth/me", headers={"Origin": allowed_origin})
    assert resp_allowed.headers.get("access-control-allow-origin") == allowed_origin
    assert resp_allowed.headers.get("access-control-allow-credentials") == "true"

    resp_denied = client.get("/api/auth/me", headers={"Origin": "http://evil.example"})
    assert resp_denied.headers.get("access-control-allow-origin") is None
