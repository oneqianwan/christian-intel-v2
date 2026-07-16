from __future__ import annotations

import pytest

from account_lifecycle_testkit import create_user, error_code, login, runtime, set_production_auth_defaults, set_test_mode
from production_auth_testkit import reset_runtime_state
from tenant_testkit import create_tenant, ensure_default_tenant, unique_tenant_slug


@pytest.fixture(autouse=True)
def _reset_runtime(runtime):
    reset_runtime_state(runtime)
    set_production_auth_defaults(runtime)
    ensure_default_tenant(runtime)
    yield


def _payload(*, email: str, role: str = "viewer", status: str = "pending", tenant_id: str | None = None) -> dict:
    payload = {
        "email": email,
        "display_name": "Provisioned User",
        "role": role,
        "status": status,
    }
    if tenant_id is not None:
        payload["tenant_id"] = tenant_id
    return payload


def test_super_admin_can_assign_tenant_and_membership(runtime):
    client = runtime["client"]
    database = runtime["database"]
    auth_models = runtime["auth_models"]
    tenant = create_tenant(runtime, name="Tenant Alpha", slug=unique_tenant_slug("tenant-alpha"))

    create_user(runtime, email="root@example.com", password="Password123456!", role="super_admin")
    login(client, email="root@example.com", password="Password123456!")

    response = client.post("/api/admin/users", json=_payload(email="invitee@example.com", tenant_id=tenant.public_id))
    assert response.status_code == 200
    payload = response.json()
    assert payload["user"]["default_tenant_id"] == tenant.public_id
    assert payload["setup_token"]

    db = database.SessionLocal()
    try:
        user = db.query(auth_models.User).filter(auth_models.User.email_normalized == "invitee@example.com").one()
        membership = (
            db.query(auth_models.TenantMembership)
            .filter(
                auth_models.TenantMembership.user_id == user.id,
                auth_models.TenantMembership.tenant_id == tenant.id,
                auth_models.TenantMembership.deleted_at.is_(None),
            )
            .one()
        )
        assert user.default_tenant_id == tenant.id
        assert membership.role == "viewer"
        assert membership.status == "pending"
    finally:
        db.close()


def test_default_tenant_used_when_missing(runtime):
    client = runtime["client"]
    database = runtime["database"]
    auth_models = runtime["auth_models"]

    default_tenant = ensure_default_tenant(runtime)
    create_user(runtime, email="root@example.com", password="Password123456!", role="super_admin")
    login(client, email="root@example.com", password="Password123456!")

    response = client.post("/api/admin/users", json=_payload(email="invitee@example.com"))
    assert response.status_code == 200
    assert response.json()["user"]["default_tenant_id"] == default_tenant.public_id

    db = database.SessionLocal()
    try:
        user = db.query(auth_models.User).filter(auth_models.User.email_normalized == "invitee@example.com").one()
        assert user.default_tenant_id == default_tenant.id
    finally:
        db.close()


def test_normal_user_cannot_create_tenant_user(runtime):
    client = runtime["client"]
    tenant = create_tenant(runtime, name="Tenant Alpha", slug=unique_tenant_slug("tenant-alpha"))
    create_user(runtime, email="viewer@example.com", password="Password123456!", role="viewer")
    login(client, email="viewer@example.com", password="Password123456!")

    response = client.post("/api/admin/users", json=_payload(email="new@example.com", tenant_id=tenant.public_id))
    assert response.status_code == 403
    assert error_code(response) == "ROLE_FORBIDDEN"


def test_admin_cannot_create_super_admin_regression(runtime):
    client = runtime["client"]
    tenant = create_tenant(runtime, name="Tenant Alpha", slug=unique_tenant_slug("tenant-alpha"))
    create_user(runtime, email="admin@example.com", password="Password123456!", role="admin")
    login(client, email="admin@example.com", password="Password123456!")

    response = client.post("/api/admin/users", json=_payload(email="root2@example.com", role="super_admin", tenant_id=tenant.public_id))
    assert response.status_code == 403
    assert error_code(response) == "ROLE_FORBIDDEN"


def test_setup_password_and_password_reset_regression_under_tenant_assignment(runtime):
    client = runtime["client"]
    tenant = create_tenant(runtime, name="Tenant Alpha", slug=unique_tenant_slug("tenant-alpha"))
    create_user(runtime, email="root@example.com", password="Password123456!", role="super_admin")
    login(client, email="root@example.com", password="Password123456!")

    created = client.post("/api/admin/users", json=_payload(email="invitee@example.com", tenant_id=tenant.public_id))
    assert created.status_code == 200
    setup_token = created.json()["setup_token"]

    setup = client.post(
        "/api/auth/setup-password",
        json={
            "token": setup_token,
            "new_password": "NewPassword123456!",
            "confirm_password": "NewPassword123456!",
        },
    )
    assert setup.status_code == 200

    login_response = client.post(
        "/api/auth/login",
        json={"email": "invitee@example.com", "password": "NewPassword123456!"},
    )
    assert login_response.status_code == 200
    assert login_response.json()["user"]["default_tenant_id"] == tenant.public_id

    set_test_mode(runtime)
    reset_request = client.post("/api/auth/password-reset/request", json={"email": "invitee@example.com"})
    assert reset_request.status_code == 200
    reset_token = reset_request.json()["reset_token"]
    assert reset_token

    reset_confirm = client.post(
        "/api/auth/password-reset/confirm",
        json={
            "token": reset_token,
            "new_password": "AnotherPassword123456!",
            "confirm_password": "AnotherPassword123456!",
        },
    )
    assert reset_confirm.status_code == 200


def test_duplicate_email_still_blocked(runtime):
    client = runtime["client"]
    tenant = create_tenant(runtime, name="Tenant Alpha", slug=unique_tenant_slug("tenant-alpha"))
    create_user(runtime, email="root@example.com", password="Password123456!", role="super_admin")
    login(client, email="root@example.com", password="Password123456!")

    first = client.post("/api/admin/users", json=_payload(email="MixedCase@Example.com", tenant_id=tenant.public_id))
    assert first.status_code == 200

    second = client.post("/api/admin/users", json=_payload(email=" mixedcase@example.com ", tenant_id=tenant.public_id))
    assert second.status_code == 409
    assert error_code(second) == "EMAIL_ALREADY_EXISTS"
