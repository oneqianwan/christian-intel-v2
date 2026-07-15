from __future__ import annotations

import pytest

from production_auth_testkit import reset_runtime_state, runtime


@pytest.fixture(autouse=True)
def _reset_runtime(runtime):
    reset_runtime_state(runtime)
    yield


def _error_code(response) -> str | None:
    payload = response.json()
    detail = payload.get("detail")
    if isinstance(detail, dict):
        return detail.get("error_code")
    return payload.get("error_code")


def _set_production_auth_defaults(runtime) -> None:
    settings = runtime["config"].settings
    settings.APP_ENV = "production"
    settings.DEPLOYMENT_ENV = "production"
    settings.AUTH_V1_ENABLED = True
    settings.AUTH_COOKIE_REQUIRED = True
    settings.CHAT_USER_OWNERSHIP_ENABLED = True
    settings.WATCH_ALERT_USER_OWNERSHIP_ENABLED = True
    settings.ALLOW_PUBLIC_CORE_APIS = False
    settings.ALLOW_LEGACY_SESSION_ID = False


def _create_user(runtime, *, email: str, password: str, role: str = "viewer", status: str = "active"):
    database = runtime["database"]
    auth_models = runtime["auth_models"]
    auth_service = runtime["auth_service"]
    db = database.SessionLocal()
    try:
        user = auth_models.User(
            email=email,
            email_normalized=auth_service.normalize_email(email),
            password_hash=auth_service.hash_password(password),
            display_name=email.split("@", 1)[0],
            role=role,
            status=status,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    finally:
        db.close()


def _login(client, *, email: str, password: str) -> None:
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text


def _create_session_token(runtime, *, user) -> str:
    database = runtime["database"]
    auth_service = runtime["auth_service"]
    db = database.SessionLocal()
    try:
        _, token = auth_service.create_auth_session(db, user=user)
        return token
    finally:
        db.close()


def test_auth_disabled_admin_and_chat_apis_fail_closed(runtime):
    client = runtime["client"]
    _set_production_auth_defaults(runtime)
    runtime["config"].settings.AUTH_V1_ENABLED = False

    admin_response = client.get("/api/admin/users")
    chat_response = client.post("/api/chat/simple", json={"message": "hello"})
    conversations_response = client.get("/api/conversations")

    assert admin_response.status_code == 503
    assert _error_code(admin_response) == "AUTH_DISABLED"
    assert chat_response.status_code == 503
    assert _error_code(chat_response) == "AUTH_DISABLED"
    assert conversations_response.status_code == 503
    assert _error_code(conversations_response) == "AUTH_DISABLED"
    assert "token" not in str(admin_response.json()).lower()


def test_disabled_user_session_is_blocked(runtime):
    client = runtime["client"]
    _set_production_auth_defaults(runtime)
    disabled_user = _create_user(runtime, email="disabled-session@example.com", password="Password123456!", status="disabled")
    token = _create_session_token(runtime, user=disabled_user)

    client.cookies.set(runtime["config"].settings.AUTH_COOKIE_NAME, token, path=runtime["config"].settings.AUTH_COOKIE_PATH)
    response = client.get("/api/conversations")

    assert response.status_code == 403
    assert _error_code(response) == "ACCOUNT_DISABLED"


def test_logout_invalidates_follow_up_access(runtime):
    client = runtime["client"]
    _set_production_auth_defaults(runtime)
    _create_user(runtime, email="logout@example.com", password="Password123456!")

    _login(client, email="logout@example.com", password="Password123456!")
    logout_response = client.post("/api/auth/logout")
    follow_up = client.get("/api/conversations")

    assert logout_response.status_code == 200
    assert follow_up.status_code == 401
    assert _error_code(follow_up) == "AUTH_REQUIRED"


def test_logout_all_revokes_existing_session(runtime):
    client = runtime["client"]
    _set_production_auth_defaults(runtime)
    user = _create_user(runtime, email="logoutall@example.com", password="Password123456!")
    token = _create_session_token(runtime, user=user)

    client.cookies.set(runtime["config"].settings.AUTH_COOKIE_NAME, token, path=runtime["config"].settings.AUTH_COOKIE_PATH)
    logout_all_response = client.post("/api/auth/logout-all")

    client.cookies.clear()
    client.cookies.set(runtime["config"].settings.AUTH_COOKIE_NAME, token, path=runtime["config"].settings.AUTH_COOKIE_PATH)
    blocked = client.get("/api/conversations")

    assert logout_all_response.status_code == 200
    assert blocked.status_code == 401
    assert _error_code(blocked) == "SESSION_REVOKED"
