from __future__ import annotations

from fastapi import Depends
import pytest

from account_lifecycle_testkit import create_user, error_code, login, runtime, set_production_auth_defaults
from production_auth_testkit import reset_runtime_state
from tenant_testkit import create_membership, create_tenant, ensure_default_tenant, unique_tenant_slug


def _ensure_probe_route(runtime):
    app = runtime["main"].app
    if any(getattr(route, "path", None) == "/api/test-tenant-context/current" for route in app.routes):
        return
    tenant_context_module = __import__("dependencies.tenant_context", fromlist=["get_current_tenant_context"])

    @app.get("/api/test-tenant-context/current")
    def tenant_context_probe(context=Depends(tenant_context_module.get_current_tenant_context)):
        return {
            "tenant_public_id": str(context.tenant.public_id),
            "tenant_slug": str(context.tenant.slug),
            "membership_role": str(getattr(context.membership, "role", "") or "") or None,
            "global_role": str(context.global_role),
            "tenant_role": str(context.tenant_role or "") or None,
        }
@pytest.fixture(autouse=True)
def _reset_runtime(runtime):
    reset_runtime_state(runtime)
    set_production_auth_defaults(runtime)
    ensure_default_tenant(runtime)
    _ensure_probe_route(runtime)
    yield


def test_unauthenticated_user_cannot_resolve_current_tenant(runtime):
    response = runtime["client"].get("/api/test-tenant-context/current")
    assert response.status_code == 401
    assert error_code(response) == "AUTH_REQUIRED"


def test_logged_in_user_uses_default_tenant(runtime):
    client = runtime["client"]
    default_tenant = ensure_default_tenant(runtime)
    user = create_user(runtime, email="viewer@example.com", password="Password123456!", role="viewer")
    create_membership(runtime, tenant=default_tenant, user=user, role="viewer", status="active")

    login(client, email="viewer@example.com", password="Password123456!")
    response = client.get("/api/test-tenant-context/current")

    assert response.status_code == 200
    assert response.json()["tenant_public_id"] == default_tenant.public_id
    assert response.json()["membership_role"] == "viewer"


def test_explicit_tenant_public_id_can_be_resolved(runtime):
    client = runtime["client"]
    default_tenant = ensure_default_tenant(runtime)
    second_tenant = create_tenant(runtime, name="Tenant Alpha", slug=unique_tenant_slug("tenant-alpha"))
    user = create_user(runtime, email="analyst@example.com", password="Password123456!", role="analyst")
    create_membership(runtime, tenant=default_tenant, user=user, role="analyst", status="active")
    create_membership(runtime, tenant=second_tenant, user=user, role="analyst", status="active")

    login(client, email="analyst@example.com", password="Password123456!")
    response = client.get("/api/test-tenant-context/current", params={"tenant_id": second_tenant.public_id})

    assert response.status_code == 200
    assert response.json()["tenant_public_id"] == second_tenant.public_id


def test_explicit_tenant_slug_can_be_resolved(runtime):
    client = runtime["client"]
    default_tenant = ensure_default_tenant(runtime)
    second_tenant = create_tenant(runtime, name="Tenant Beta", slug=unique_tenant_slug("tenant-beta"))
    user = create_user(runtime, email="member@example.com", password="Password123456!", role="viewer")
    create_membership(runtime, tenant=default_tenant, user=user, role="viewer", status="active")
    create_membership(runtime, tenant=second_tenant, user=user, role="viewer", status="active")

    login(client, email="member@example.com", password="Password123456!")
    response = client.get("/api/test-tenant-context/current", params={"tenant_slug": second_tenant.slug})

    assert response.status_code == 200
    assert response.json()["tenant_slug"] == second_tenant.slug


def test_non_member_tenant_access_is_blocked(runtime):
    client = runtime["client"]
    ensure_default_tenant(runtime)
    foreign_tenant = create_tenant(runtime, name="Tenant Gamma", slug=unique_tenant_slug("tenant-gamma"))
    user = create_user(runtime, email="viewer@example.com", password="Password123456!", role="viewer")

    login(client, email="viewer@example.com", password="Password123456!")
    response = client.get("/api/test-tenant-context/current", params={"tenant_id": foreign_tenant.public_id})

    assert response.status_code == 403
    assert error_code(response) == "TENANT_MEMBERSHIP_REQUIRED"


def test_disabled_membership_is_rejected(runtime):
    client = runtime["client"]
    ensure_default_tenant(runtime)
    tenant = create_tenant(runtime, name="Tenant Delta", slug=unique_tenant_slug("tenant-delta"))
    user = create_user(runtime, email="viewer@example.com", password="Password123456!", role="viewer")
    create_membership(runtime, tenant=tenant, user=user, role="viewer", status="disabled")

    login(client, email="viewer@example.com", password="Password123456!")
    response = client.get("/api/test-tenant-context/current", params={"tenant_id": tenant.public_id})

    assert response.status_code == 403
    assert error_code(response) == "TENANT_MEMBERSHIP_INACTIVE"


def test_pending_membership_is_rejected(runtime):
    client = runtime["client"]
    ensure_default_tenant(runtime)
    tenant = create_tenant(runtime, name="Tenant Epsilon", slug=unique_tenant_slug("tenant-epsilon"))
    user = create_user(runtime, email="viewer@example.com", password="Password123456!", role="viewer")
    create_membership(runtime, tenant=tenant, user=user, role="viewer", status="pending")

    login(client, email="viewer@example.com", password="Password123456!")
    response = client.get("/api/test-tenant-context/current", params={"tenant_id": tenant.public_id})

    assert response.status_code == 403
    assert error_code(response) == "TENANT_MEMBERSHIP_INACTIVE"


def test_disabled_tenant_is_rejected(runtime):
    client = runtime["client"]
    tenant = create_tenant(runtime, name="Tenant Zeta", slug=unique_tenant_slug("tenant-zeta"), status="disabled")
    user = create_user(runtime, email="viewer@example.com", password="Password123456!", role="viewer")
    create_membership(runtime, tenant=tenant, user=user, role="viewer", status="active")

    login(client, email="viewer@example.com", password="Password123456!")
    response = client.get("/api/test-tenant-context/current", params={"tenant_id": tenant.public_id})

    assert response.status_code == 403
    assert error_code(response) == "TENANT_DISABLED"


def test_super_admin_can_resolve_any_active_tenant(runtime):
    client = runtime["client"]
    foreign_tenant = create_tenant(runtime, name="Tenant Eta", slug=unique_tenant_slug("tenant-eta"))
    create_user(runtime, email="root@example.com", password="Password123456!", role="super_admin")

    login(client, email="root@example.com", password="Password123456!")
    response = client.get("/api/test-tenant-context/current", params={"tenant_id": foreign_tenant.public_id})

    assert response.status_code == 200
    assert response.json()["tenant_public_id"] == foreign_tenant.public_id
    assert response.json()["membership_role"] is None


def test_missing_default_tenant_fails_closed(runtime):
    client = runtime["client"]
    user = create_user(runtime, email="viewer@example.com", password="Password123456!", role="viewer")

    database = runtime["database"]
    auth_models = runtime["auth_models"]
    db = database.SessionLocal()
    try:
        row = db.query(auth_models.User).filter(auth_models.User.id == user.id).one()
        row.default_tenant_id = ""
        db.add(row)
        db.commit()
    finally:
        db.close()

    login_response = client.post("/api/auth/login", json={"email": "viewer@example.com", "password": "Password123456!"})
    assert login_response.status_code == 403
    assert error_code(login_response) == "TENANT_REQUIRED"

    response = client.get("/api/test-tenant-context/current")
    assert response.status_code == 401
    assert error_code(response) == "AUTH_REQUIRED"
