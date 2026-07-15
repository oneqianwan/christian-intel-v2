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
    settings.AUTH_COOKIE_SECURE = False
    settings.AUTH_COOKIE_SAMESITE = "lax"
    settings.CHAT_USER_OWNERSHIP_ENABLED = True
    settings.WATCH_ALERT_USER_OWNERSHIP_ENABLED = True
    settings.BOOKMARKS_USER_OWNERSHIP_ENABLED = True
    settings.FEEDBACK_USER_OWNERSHIP_ENABLED = True
    settings.ALLOW_PUBLIC_CORE_APIS = False
    settings.ALLOW_LEGACY_SESSION_ID = False
    settings.ALLOW_ANONYMOUS_FEEDBACK = False


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
            display_name=email.split("@", 1)[0],
            role="viewer",
            status=status,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    finally:
        db.close()


def _create_session_token(runtime, *, user) -> str:
    database = runtime["database"]
    auth_service = runtime["auth_service"]
    db = database.SessionLocal()
    try:
        _, token = auth_service.create_auth_session(db, user=user)
        return token
    finally:
        db.close()


def test_cookie_session_has_http_only_samesite_and_expiry(runtime):
    client = runtime["client"]
    _set_production_auth_defaults(runtime)
    _create_user(runtime, email="cookie@example.com", password="Password123456!")

    response = client.post("/api/auth/login", json={"email": "cookie@example.com", "password": "Password123456!"})

    assert response.status_code == 200
    set_cookie = response.headers.get("set-cookie") or ""
    assert "HttpOnly" in set_cookie
    assert f"Path={runtime['config'].settings.AUTH_COOKIE_PATH}" in set_cookie
    assert f"Max-Age={runtime['config'].settings.AUTH_SESSION_TTL_SECONDS}" in set_cookie
    assert "SameSite=" in set_cookie


def test_production_cookie_secure_policy_is_supported(runtime):
    client = runtime["client"]
    settings = runtime["config"].settings
    _set_production_auth_defaults(runtime)
    settings.APP_ENV = "production"
    settings.DEPLOYMENT_ENV = "production"
    settings.AUTH_COOKIE_SECURE = True
    settings.AUTH_COOKIE_SAMESITE = "lax"
    _create_user(runtime, email="secure-cookie@example.com", password="Password123456!")

    response = client.post("/api/auth/login", json={"email": "secure-cookie@example.com", "password": "Password123456!"})

    assert response.status_code == 200
    set_cookie = response.headers.get("set-cookie") or ""
    assert "Secure" in set_cookie
    assert "SameSite=lax" in set_cookie or "SameSite=Lax" in set_cookie


def test_disabled_user_session_is_rejected_without_secret_leak(runtime):
    client = runtime["client"]
    _set_production_auth_defaults(runtime)
    user = _create_user(runtime, email="disabled@example.com", password="Password123456!", status="disabled")
    raw_token = _create_session_token(runtime, user=user)

    client.cookies.set(runtime["config"].settings.AUTH_COOKIE_NAME, raw_token, path=runtime["config"].settings.AUTH_COOKIE_PATH)
    response = client.get("/api/auth/me")

    assert response.status_code == 403
    assert _error_code(response) == "ACCOUNT_DISABLED"
    serialized = str(response.json()).lower()
    assert raw_token.lower() not in serialized
    assert "password" not in serialized
    assert "secret" not in serialized


def test_password_hash_remains_argon2id(runtime):
    auth_service = runtime["auth_service"]
    user = _create_user(runtime, email="argon2@example.com", password="Password123456!")

    assert user.password_hash.startswith("$argon2id$")
    assert auth_service.verify_password(user.password_hash, "Password123456!") is True


def test_login_failure_limit_and_brute_force_protection_remain_enabled(runtime):
    client = runtime["client"]
    _set_production_auth_defaults(runtime)

    for _ in range(3):
        response = client.post("/api/auth/login", json={"email": "unknown@example.com", "password": "wrong-password"})
        assert response.status_code == 401
        assert _error_code(response) == "INVALID_CREDENTIALS"

    limited = client.post("/api/auth/login", json={"email": "unknown@example.com", "password": "wrong-password"})
    assert limited.status_code == 429
    assert _error_code(limited) == "LOGIN_RATE_LIMITED"
    assert "Retry-After" in limited.headers


def test_login_response_does_not_print_password_or_session_token(runtime):
    client = runtime["client"]
    _set_production_auth_defaults(runtime)
    _create_user(runtime, email="no-print@example.com", password="Password123456!")

    response = client.post("/api/auth/login", json={"email": "no-print@example.com", "password": "Password123456!"})

    assert response.status_code == 200
    payload_text = str(response.json()).lower()
    set_cookie = response.headers.get("set-cookie") or ""
    raw_token = set_cookie.split(";", 1)[0].split("=", 1)[1]
    assert "password" not in payload_text
    assert "token_hash" not in payload_text
    assert raw_token not in payload_text
