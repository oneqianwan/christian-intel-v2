from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from account_lifecycle_testkit import create_user, error_code, login, runtime, set_production_auth_defaults, set_test_mode
from production_auth_testkit import reset_runtime_state


@pytest.fixture(autouse=True)
def _reset_runtime(runtime):
    reset_runtime_state(runtime)
    set_production_auth_defaults(runtime)
    yield


def _request_reset(client, *, email: str):
    return client.post("/api/auth/password-reset/request", json={"email": email})


def test_password_reset_request_prevents_email_enumeration(runtime):
    client = runtime["client"]

    create_user(runtime, email="user@example.com", password="Password123456!", role="viewer", status="active")

    existing = _request_reset(client, email="user@example.com")
    missing = _request_reset(client, email="missing@example.com")

    assert existing.status_code == 200
    assert missing.status_code == 200
    assert existing.json() == missing.json()
    assert existing.json()["message"] == "If the account exists, reset instructions have been generated."


def test_disabled_user_cannot_reset_back_to_active(runtime):
    client = runtime["client"]
    database = runtime["database"]
    auth_models = runtime["auth_models"]

    create_user(runtime, email="disabled@example.com", password="Password123456!", role="viewer", status="disabled")
    set_test_mode(runtime)

    response = _request_reset(client, email="disabled@example.com")

    assert response.status_code == 200
    assert response.json()["reset_token"] is None

    db = database.SessionLocal()
    try:
        user = db.query(auth_models.User).filter(auth_models.User.email_normalized == "disabled@example.com").one()
        tokens = db.query(auth_models.AccountToken).filter(auth_models.AccountToken.user_id == user.id).all()
        assert user.status == "disabled"
        assert tokens == []
    finally:
        db.close()


def test_password_reset_token_hash_is_stored_and_plaintext_is_not(runtime):
    client = runtime["client"]
    database = runtime["database"]
    auth_models = runtime["auth_models"]

    create_user(runtime, email="user@example.com", password="Password123456!", role="viewer", status="active")
    set_test_mode(runtime)

    response = _request_reset(client, email="user@example.com")

    assert response.status_code == 200
    raw_token = response.json()["reset_token"]
    assert raw_token
    assert "Password123456!" not in str(response.json())

    db = database.SessionLocal()
    try:
        user = db.query(auth_models.User).filter(auth_models.User.email_normalized == "user@example.com").one()
        token = (
            db.query(auth_models.AccountToken)
            .filter(
                auth_models.AccountToken.user_id == user.id,
                auth_models.AccountToken.purpose == "password_reset",
            )
            .one()
        )
        assert token.expires_at is not None
        assert token.token_hash
        assert raw_token not in token.token_hash
    finally:
        db.close()


def test_password_reset_expiry_and_one_time_use_are_enforced(runtime):
    client = runtime["client"]
    database = runtime["database"]
    auth_models = runtime["auth_models"]

    create_user(runtime, email="user@example.com", password="Password123456!", role="viewer", status="active")
    set_test_mode(runtime)
    response = _request_reset(client, email="user@example.com")
    raw_token = response.json()["reset_token"]

    db = database.SessionLocal()
    try:
        token = db.query(auth_models.AccountToken).filter(auth_models.AccountToken.purpose == "password_reset").one()
        token.expires_at = datetime.utcnow() - timedelta(seconds=5)
        db.add(token)
        db.commit()
    finally:
        db.close()

    expired = client.post(
        "/api/auth/password-reset/confirm",
        json={
            "token": raw_token,
            "new_password": "NewPassword123456!",
            "confirm_password": "NewPassword123456!",
        },
    )
    assert expired.status_code == 400
    assert error_code(expired) == "TOKEN_EXPIRED"

    reset_again = _request_reset(client, email="user@example.com")
    next_token = reset_again.json()["reset_token"]
    confirmed = client.post(
        "/api/auth/password-reset/confirm",
        json={
            "token": next_token,
            "new_password": "NewPassword123456!",
            "confirm_password": "NewPassword123456!",
        },
    )
    assert confirmed.status_code == 200

    reused = client.post(
        "/api/auth/password-reset/confirm",
        json={
            "token": next_token,
            "new_password": "AnotherPassword123456!",
            "confirm_password": "AnotherPassword123456!",
        },
    )
    assert reused.status_code == 400
    assert error_code(reused) == "TOKEN_INVALID"


def test_password_reset_changes_password_and_invalidates_old_session(runtime):
    client = runtime["client"]

    create_user(runtime, email="user@example.com", password="Password123456!", role="viewer", status="active")
    login_response = login(client, email="user@example.com", password="Password123456!")
    old_session_token = login_response.headers.get("set-cookie", "").split(";", 1)[0].split("=", 1)[1]

    set_test_mode(runtime)
    request_response = _request_reset(client, email="user@example.com")
    raw_token = request_response.json()["reset_token"]

    response = client.post(
        "/api/auth/password-reset/confirm",
        json={
            "token": raw_token,
            "new_password": "NewPassword123456!",
            "confirm_password": "NewPassword123456!",
        },
    )

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert response.json()["reauthentication_required"] is True
    assert raw_token not in str(response.json())

    client.cookies.clear()
    client.cookies.set(
        runtime["config"].settings.AUTH_COOKIE_NAME,
        old_session_token,
        path=runtime["config"].settings.AUTH_COOKIE_PATH,
    )
    me_old = client.get("/api/auth/me")
    assert me_old.status_code == 401
    assert error_code(me_old) == "SESSION_REVOKED"

    old_password_login = client.post("/api/auth/login", json={"email": "user@example.com", "password": "Password123456!"})
    assert old_password_login.status_code == 401
    assert error_code(old_password_login) == "INVALID_CREDENTIALS"

    new_password_login = client.post("/api/auth/login", json={"email": "user@example.com", "password": "NewPassword123456!"})
    assert new_password_login.status_code == 200
