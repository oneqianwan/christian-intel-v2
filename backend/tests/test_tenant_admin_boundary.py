from __future__ import annotations

import pytest

from account_lifecycle_testkit import create_user, error_code, login, runtime, set_production_auth_defaults
from production_auth_testkit import reset_runtime_state
from tenant_testkit import create_membership, create_tenant, ensure_default_tenant, unique_tenant_slug


def _assign_default_tenant(runtime, *, user, tenant) -> None:
    database = runtime["database"]
    auth_models = runtime["auth_models"]
    db = database.SessionLocal()
    try:
        row = db.query(auth_models.User).filter(auth_models.User.id == user.id).one()
        row.default_tenant_id = str(tenant.id)
        db.add(row)
        db.commit()
    finally:
        db.close()


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


@pytest.fixture(autouse=True)
def _reset_runtime(runtime):
    reset_runtime_state(runtime)
    set_production_auth_defaults(runtime)
    ensure_default_tenant(runtime)
    yield


def test_tenant_admin_can_view_own_tenant_members(runtime):
    client = runtime["client"]
    tenant = create_tenant(runtime, name="Tenant Alpha", slug=unique_tenant_slug("tenant-alpha"))
    actor = create_user(runtime, email="tenant-admin@example.com", password="Password123456!", role="viewer")
    target = create_user(runtime, email="member@example.com", password="Password123456!", role="viewer")
    _assign_default_tenant(runtime, user=actor, tenant=tenant)
    _assign_default_tenant(runtime, user=target, tenant=tenant)
    create_membership(runtime, tenant=tenant, user=actor, role="tenant_admin", status="active")
    create_membership(runtime, tenant=tenant, user=target, role="viewer", status="active")

    login(client, email="tenant-admin@example.com", password="Password123456!")
    response = client.get("/api/admin/users")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 2
    emails = {item["email"] for item in payload["items"]}
    assert {"tenant-admin@example.com", "member@example.com"} <= emails


def test_tenant_admin_cannot_view_other_tenant_members(runtime):
    client = runtime["client"]
    tenant_a = create_tenant(runtime, name="Tenant Alpha", slug=unique_tenant_slug("tenant-alpha"))
    tenant_b = create_tenant(runtime, name="Tenant Beta", slug=unique_tenant_slug("tenant-beta"))
    actor = create_user(runtime, email="tenant-admin@example.com", password="Password123456!", role="viewer")
    target = create_user(runtime, email="foreign@example.com", password="Password123456!", role="viewer")
    _assign_default_tenant(runtime, user=actor, tenant=tenant_a)
    _assign_default_tenant(runtime, user=target, tenant=tenant_b)
    create_membership(runtime, tenant=tenant_a, user=actor, role="tenant_admin", status="active")
    create_membership(runtime, tenant=tenant_b, user=target, role="viewer", status="active")

    login(client, email="tenant-admin@example.com", password="Password123456!")
    response = client.get(f"/api/admin/users/{target.public_id}")

    assert response.status_code == 403
    assert error_code(response) == "TENANT_SCOPE_FORBIDDEN"


def test_tenant_admin_can_invite_user_in_own_tenant(runtime):
    client = runtime["client"]
    tenant = create_tenant(runtime, name="Tenant Alpha", slug=unique_tenant_slug("tenant-alpha"))
    actor = create_user(runtime, email="tenant-admin@example.com", password="Password123456!", role="viewer")
    _assign_default_tenant(runtime, user=actor, tenant=tenant)
    create_membership(runtime, tenant=tenant, user=actor, role="tenant_admin", status="active")

    login(client, email="tenant-admin@example.com", password="Password123456!")
    response = client.post("/api/admin/users", json=_payload(email="invitee@example.com", tenant_id=tenant.public_id))

    assert response.status_code == 200
    assert response.json()["user"]["default_tenant_id"] == tenant.public_id


def test_tenant_admin_cannot_invite_user_in_other_tenant(runtime):
    client = runtime["client"]
    own_tenant = create_tenant(runtime, name="Tenant Alpha", slug=unique_tenant_slug("tenant-alpha"))
    foreign_tenant = create_tenant(runtime, name="Tenant Beta", slug=unique_tenant_slug("tenant-beta"))
    actor = create_user(runtime, email="tenant-admin@example.com", password="Password123456!", role="viewer")
    _assign_default_tenant(runtime, user=actor, tenant=own_tenant)
    create_membership(runtime, tenant=own_tenant, user=actor, role="tenant_admin", status="active")

    login(client, email="tenant-admin@example.com", password="Password123456!")
    response = client.post("/api/admin/users", json=_payload(email="invitee@example.com", tenant_id=foreign_tenant.public_id))

    assert response.status_code == 403
    assert error_code(response) == "ROLE_FORBIDDEN"


def test_tenant_admin_cannot_create_super_admin(runtime):
    client = runtime["client"]
    tenant = create_tenant(runtime, name="Tenant Alpha", slug=unique_tenant_slug("tenant-alpha"))
    actor = create_user(runtime, email="tenant-admin@example.com", password="Password123456!", role="viewer")
    _assign_default_tenant(runtime, user=actor, tenant=tenant)
    create_membership(runtime, tenant=tenant, user=actor, role="tenant_admin", status="active")

    login(client, email="tenant-admin@example.com", password="Password123456!")
    response = client.post(
        "/api/admin/users",
        json=_payload(email="root2@example.com", role="super_admin", tenant_id=tenant.public_id),
    )

    assert response.status_code == 403
    assert error_code(response) == "ROLE_FORBIDDEN"


def test_analyst_cannot_manage_members(runtime):
    client = runtime["client"]
    tenant = create_tenant(runtime, name="Tenant Alpha", slug=unique_tenant_slug("tenant-alpha"))
    actor = create_user(runtime, email="analyst@example.com", password="Password123456!", role="analyst")
    _assign_default_tenant(runtime, user=actor, tenant=tenant)
    create_membership(runtime, tenant=tenant, user=actor, role="analyst", status="active")

    login(client, email="analyst@example.com", password="Password123456!")
    response = client.post("/api/admin/users", json=_payload(email="new@example.com", tenant_id=tenant.public_id))

    assert response.status_code == 403
    assert error_code(response) == "ROLE_FORBIDDEN"


def test_viewer_cannot_manage_members(runtime):
    client = runtime["client"]
    tenant = create_tenant(runtime, name="Tenant Alpha", slug=unique_tenant_slug("tenant-alpha"))
    actor = create_user(runtime, email="viewer@example.com", password="Password123456!", role="viewer")
    _assign_default_tenant(runtime, user=actor, tenant=tenant)
    create_membership(runtime, tenant=tenant, user=actor, role="viewer", status="active")

    login(client, email="viewer@example.com", password="Password123456!")
    response = client.get("/api/admin/users")

    assert response.status_code == 403
    assert error_code(response) == "ROLE_FORBIDDEN"


def test_super_admin_can_manage_across_tenants(runtime):
    client = runtime["client"]
    tenant = create_tenant(runtime, name="Tenant Alpha", slug=unique_tenant_slug("tenant-alpha"))
    create_user(runtime, email="root@example.com", password="Password123456!", role="super_admin")

    login(client, email="root@example.com", password="Password123456!")
    response = client.post("/api/admin/users", json=_payload(email="invitee@example.com", tenant_id=tenant.public_id))

    assert response.status_code == 200
    assert response.json()["user"]["default_tenant_id"] == tenant.public_id


def test_unauthenticated_tenant_admin_api_returns_401(runtime):
    response = runtime["client"].get("/api/admin/users")
    assert response.status_code == 401
    assert error_code(response) == "AUTH_REQUIRED"
