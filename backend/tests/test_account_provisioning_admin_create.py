from __future__ import annotations

import pytest

from account_lifecycle_testkit import create_user, error_code, login, runtime, set_production_auth_defaults
from production_auth_testkit import reset_runtime_state


@pytest.fixture(autouse=True)
def _reset_runtime(runtime):
    reset_runtime_state(runtime)
    set_production_auth_defaults(runtime)
    yield


def _admin_create_payload(*, email: str, role: str = "viewer", status: str = "pending") -> dict:
    return {
        "email": email,
        "display_name": "Provisioned User",
        "role": role,
        "status": status,
    }


def test_unauthenticated_cannot_create_user(runtime):
    client = runtime["client"]

    response = client.post("/api/admin/users", json=_admin_create_payload(email="viewer@example.com"))

    assert response.status_code == 401
    assert error_code(response) == "AUTH_REQUIRED"


def test_normal_user_cannot_create_user(runtime):
    client = runtime["client"]

    create_user(runtime, email="viewer@example.com", password="Password123456!", role="viewer")
    login(client, email="viewer@example.com", password="Password123456!")

    response = client.post("/api/admin/users", json=_admin_create_payload(email="new@example.com"))

    assert response.status_code == 403
    assert error_code(response) == "ROLE_FORBIDDEN"


@pytest.mark.parametrize("role_to_create", ["viewer", "analyst", "admin"])
def test_admin_can_create_controlled_users_and_token_is_one_time_response(runtime, role_to_create):
    client = runtime["client"]
    database = runtime["database"]
    auth_models = runtime["auth_models"]

    create_user(runtime, email="seed-admin@example.com", password="Password123456!", role="admin")
    login(client, email="seed-admin@example.com", password="Password123456!")

    response = client.post(
        "/api/admin/users",
        json=_admin_create_payload(email=f"{role_to_create}@example.com", role=role_to_create, status="pending"),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["user"]["role"] == role_to_create
    assert payload["user"]["status"] == "pending"
    assert payload["setup_token"]
    assert payload["setup_token"] not in str(payload["user"])

    user_id = payload["user"]["public_id"]
    follow_up = client.get(f"/api/admin/users/{user_id}")
    assert follow_up.status_code == 200
    assert "setup_token" not in str(follow_up.json())

    db = database.SessionLocal()
    try:
        user = db.query(auth_models.User).filter(auth_models.User.public_id == user_id).one()
        token = db.query(auth_models.AccountToken).filter(auth_models.AccountToken.user_id == user.id).one()
        assert user.password_hash.startswith("$argon2id$")
        assert payload["setup_token"] not in str(user.password_hash)
        assert token.purpose == "setup_password"
        assert token.status == "active"
        assert token.expires_at is not None
        assert token.token_hash
        assert payload["setup_token"] not in token.token_hash
    finally:
        db.close()


def test_admin_cannot_create_super_admin(runtime):
    client = runtime["client"]

    create_user(runtime, email="admin@example.com", password="Password123456!", role="admin")
    login(client, email="admin@example.com", password="Password123456!")

    response = client.post(
        "/api/admin/users",
        json=_admin_create_payload(email="root2@example.com", role="super_admin", status="pending"),
    )

    assert response.status_code == 403
    assert error_code(response) == "ROLE_FORBIDDEN"


def test_duplicate_email_creation_is_blocked_and_email_is_normalized(runtime):
    client = runtime["client"]
    database = runtime["database"]
    auth_models = runtime["auth_models"]

    create_user(runtime, email="admin@example.com", password="Password123456!", role="admin")
    login(client, email="admin@example.com", password="Password123456!")

    first = client.post(
        "/api/admin/users",
        json=_admin_create_payload(email="MixedCase@Example.com", role="viewer", status="pending"),
    )
    assert first.status_code == 200
    assert first.json()["user"]["email"] == "mixedcase@example.com"

    second = client.post(
        "/api/admin/users",
        json=_admin_create_payload(email=" mixedcase@example.com ", role="viewer", status="pending"),
    )
    assert second.status_code == 409
    assert error_code(second) == "EMAIL_ALREADY_EXISTS"

    db = database.SessionLocal()
    try:
        rows = db.query(auth_models.User).filter(auth_models.User.email_normalized == "mixedcase@example.com").all()
        assert len(rows) == 1
        assert rows[0].email == "mixedcase@example.com"
    finally:
        db.close()
