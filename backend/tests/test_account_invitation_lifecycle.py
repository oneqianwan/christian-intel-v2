from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from account_lifecycle_testkit import create_user, error_code, login, runtime, set_production_auth_defaults
from production_auth_testkit import reset_runtime_state


@pytest.fixture(autouse=True)
def _reset_runtime(runtime):
    reset_runtime_state(runtime)
    set_production_auth_defaults(runtime)
    yield


def _invite_user(runtime, *, email: str = "invitee@example.com") -> tuple[dict, str]:
    client = runtime["client"]
    create_user(runtime, email="admin@example.com", password="Password123456!", role="admin")
    login(client, email="admin@example.com", password="Password123456!")
    response = client.post(
        "/api/admin/users",
        json={
            "email": email,
            "display_name": "Invitee",
            "role": "viewer",
            "status": "pending",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    return payload, payload["setup_token"]


def test_setup_password_valid_token_activates_user_and_allows_login(runtime):
    client = runtime["client"]
    database = runtime["database"]
    auth_models = runtime["auth_models"]

    payload, setup_token = _invite_user(runtime)

    response = client.post(
        "/api/auth/setup-password",
        json={
            "token": setup_token,
            "new_password": "NewPassword123456!",
            "confirm_password": "NewPassword123456!",
        },
    )

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert response.json()["login_allowed"] is True
    assert setup_token not in str(response.json())

    db = database.SessionLocal()
    try:
        user = db.query(auth_models.User).filter(auth_models.User.public_id == payload["user"]["public_id"]).one()
        token = db.query(auth_models.AccountToken).filter(auth_models.AccountToken.user_id == user.id).one()
        assert user.status == "active"
        assert user.password_hash.startswith("$argon2id$")
        assert token.status == "used"
        assert token.used_at is not None
    finally:
        db.close()

    login_response = client.post(
        "/api/auth/login",
        json={"email": payload["user"]["email"], "password": "NewPassword123456!"},
    )
    assert login_response.status_code == 200


def test_setup_password_expired_token_is_blocked(runtime):
    client = runtime["client"]
    database = runtime["database"]
    auth_models = runtime["auth_models"]

    payload, setup_token = _invite_user(runtime, email="expired@example.com")

    db = database.SessionLocal()
    try:
        user = db.query(auth_models.User).filter(auth_models.User.public_id == payload["user"]["public_id"]).one()
        token = db.query(auth_models.AccountToken).filter(auth_models.AccountToken.user_id == user.id).one()
        token.expires_at = datetime.utcnow() - timedelta(seconds=5)
        db.add(token)
        db.commit()
    finally:
        db.close()

    response = client.post(
        "/api/auth/setup-password",
        json={
            "token": setup_token,
            "new_password": "NewPassword123456!",
            "confirm_password": "NewPassword123456!",
        },
    )

    assert response.status_code == 400
    assert error_code(response) == "TOKEN_EXPIRED"


def test_setup_password_used_token_cannot_be_reused(runtime):
    client = runtime["client"]

    payload, setup_token = _invite_user(runtime, email="used@example.com")

    first = client.post(
        "/api/auth/setup-password",
        json={
            "token": setup_token,
            "new_password": "NewPassword123456!",
            "confirm_password": "NewPassword123456!",
        },
    )
    assert first.status_code == 200

    second = client.post(
        "/api/auth/setup-password",
        json={
            "token": setup_token,
            "new_password": "AnotherPassword123456!",
            "confirm_password": "AnotherPassword123456!",
        },
    )
    assert second.status_code == 400
    assert error_code(second) == "TOKEN_INVALID"

    blocked_login = client.post(
        "/api/auth/login",
        json={"email": payload["user"]["email"], "password": "AnotherPassword123456!"},
    )
    assert blocked_login.status_code == 401
    assert error_code(blocked_login) == "INVALID_CREDENTIALS"


def test_setup_password_invalid_token_does_not_leak_user_identity(runtime):
    client = runtime["client"]

    _invite_user(runtime, email="unknown@example.com")
    response = client.post(
        "/api/auth/setup-password",
        json={
            "token": "not-a-real-token",
            "new_password": "NewPassword123456!",
            "confirm_password": "NewPassword123456!",
        },
    )

    assert response.status_code == 400
    assert error_code(response) == "TOKEN_INVALID"
    serialized = str(response.json()).lower()
    assert "unknown@example.com" not in serialized
    assert "token_hash" not in serialized


def test_setup_password_weak_password_is_blocked_and_user_cannot_login(runtime):
    client = runtime["client"]

    payload, setup_token = _invite_user(runtime, email="weak@example.com")
    response = client.post(
        "/api/auth/setup-password",
        json={
            "token": setup_token,
            "new_password": "short",
            "confirm_password": "short",
        },
    )

    assert response.status_code == 422
    assert error_code(response) == "PASSWORD_TOO_SHORT"

    login_response = client.post(
        "/api/auth/login",
        json={"email": payload["user"]["email"], "password": "short"},
    )
    assert login_response.status_code == 403
    assert error_code(login_response) == "ACCOUNT_PENDING"
