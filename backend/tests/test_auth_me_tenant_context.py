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


@pytest.fixture(autouse=True)
def _reset_runtime(runtime):
    reset_runtime_state(runtime)
    set_production_auth_defaults(runtime)
    ensure_default_tenant(runtime)
    yield


def test_auth_me_returns_default_tenant_active_tenant_memberships_and_tenant_role(runtime):
    client = runtime["client"]
    tenant_a = create_tenant(runtime, name="Tenant Alpha", slug=unique_tenant_slug("tenant-alpha"))
    tenant_b = create_tenant(runtime, name="Tenant Beta", slug=unique_tenant_slug("tenant-beta"))
    user = create_user(runtime, email="analyst@example.com", password="Password123456!", role="analyst")
    _assign_default_tenant(runtime, user=user, tenant=tenant_a)
    create_membership(runtime, tenant=tenant_a, user=user, role="analyst", status="active")
    create_membership(runtime, tenant=tenant_b, user=user, role="viewer", status="active")

    login(client, email="analyst@example.com", password="Password123456!")
    response = client.get("/api/auth/me")

    assert response.status_code == 200
    payload = response.json()["user"]
    assert payload["default_tenant_id"] == tenant_a.public_id
    assert payload["default_tenant"]["public_id"] == tenant_a.public_id
    assert payload["active_tenant"]["public_id"] == tenant_a.public_id
    assert payload["tenant_role"] == "analyst"
    assert payload["global_role"] == "analyst"
    assert len(payload["memberships"]) == 2


def test_auth_me_explicit_tenant_context_uses_requested_tenant(runtime):
    client = runtime["client"]
    tenant_a = create_tenant(runtime, name="Tenant Alpha", slug=unique_tenant_slug("tenant-alpha"))
    tenant_b = create_tenant(runtime, name="Tenant Beta", slug=unique_tenant_slug("tenant-beta"))
    user = create_user(runtime, email="viewer@example.com", password="Password123456!", role="viewer")
    _assign_default_tenant(runtime, user=user, tenant=tenant_a)
    create_membership(runtime, tenant=tenant_a, user=user, role="viewer", status="active")
    create_membership(runtime, tenant=tenant_b, user=user, role="analyst", status="active")

    login(client, email="viewer@example.com", password="Password123456!")
    response = client.get("/api/auth/me", params={"tenant_id": tenant_b.public_id})

    assert response.status_code == 200
    payload = response.json()["user"]
    assert payload["active_tenant"]["public_id"] == tenant_b.public_id
    assert payload["tenant_role"] == "analyst"


def test_disabled_membership_not_in_active_memberships(runtime):
    client = runtime["client"]
    tenant_a = create_tenant(runtime, name="Tenant Alpha", slug=unique_tenant_slug("tenant-alpha"))
    tenant_b = create_tenant(runtime, name="Tenant Beta", slug=unique_tenant_slug("tenant-beta"))
    user = create_user(runtime, email="viewer@example.com", password="Password123456!", role="viewer")
    _assign_default_tenant(runtime, user=user, tenant=tenant_a)
    create_membership(runtime, tenant=tenant_a, user=user, role="viewer", status="active")
    create_membership(runtime, tenant=tenant_b, user=user, role="viewer", status="disabled")

    login(client, email="viewer@example.com", password="Password123456!")
    response = client.get("/api/auth/me")

    assert response.status_code == 200
    memberships = response.json()["user"]["memberships"]
    membership_tenants = {item["tenant"]["public_id"] for item in memberships}
    assert tenant_a.public_id in membership_tenants
    assert tenant_b.public_id not in membership_tenants


def test_disabled_tenant_does_not_become_active_tenant(runtime):
    client = runtime["client"]
    default_tenant = ensure_default_tenant(runtime)
    disabled_tenant = create_tenant(runtime, name="Tenant Disabled", slug=unique_tenant_slug("tenant-disabled"), status="disabled")
    user = create_user(runtime, email="viewer@example.com", password="Password123456!", role="viewer")
    create_membership(runtime, tenant=default_tenant, user=user, role="viewer", status="active")
    create_membership(runtime, tenant=disabled_tenant, user=user, role="viewer", status="active")

    login(client, email="viewer@example.com", password="Password123456!")
    response = client.get("/api/auth/me", params={"tenant_id": disabled_tenant.public_id})

    assert response.status_code == 200
    payload = response.json()["user"]
    assert payload["active_tenant"] is None
    assert payload["default_tenant"]["public_id"] == default_tenant.public_id


def test_super_admin_preserves_global_role_without_secret_leakage(runtime):
    client = runtime["client"]
    tenant = create_tenant(runtime, name="Tenant Alpha", slug=unique_tenant_slug("tenant-alpha"))
    create_user(runtime, email="root@example.com", password="Password123456!", role="super_admin")

    login(client, email="root@example.com", password="Password123456!")
    response = client.get("/api/auth/me", params={"tenant_id": tenant.public_id})

    assert response.status_code == 200
    payload = response.json()["user"]
    assert payload["global_role"] == "super_admin"
    assert payload["active_tenant"]["public_id"] == tenant.public_id
    serialized = str(response.json()).lower()
    assert "password" not in serialized
    assert "token" not in serialized
    assert "secret" not in serialized


def test_logout_still_blocks_auth_me(runtime):
    client = runtime["client"]
    default_tenant = ensure_default_tenant(runtime)
    user = create_user(runtime, email="viewer@example.com", password="Password123456!", role="viewer")
    create_membership(runtime, tenant=default_tenant, user=user, role="viewer", status="active")

    login(client, email="viewer@example.com", password="Password123456!")
    assert client.get("/api/auth/me").status_code == 200
    assert client.post("/api/auth/logout").status_code == 200

    blocked = client.get("/api/auth/me")
    assert blocked.status_code == 401
    assert error_code(blocked) == "AUTH_REQUIRED"
