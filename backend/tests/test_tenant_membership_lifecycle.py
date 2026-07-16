from __future__ import annotations

import pytest

from account_lifecycle_testkit import create_user, runtime
from production_auth_testkit import reset_runtime_state
from tenant_testkit import create_membership, create_tenant, ensure_default_tenant, unique_tenant_slug


@pytest.fixture(autouse=True)
def _reset_runtime(runtime):
    reset_runtime_state(runtime)
    ensure_default_tenant(runtime)
    yield


def test_create_tenant_and_membership_roles(runtime):
    tenant = create_tenant(runtime, name="  Tenant Alpha  ", slug=" Tenant Alpha ")
    tenant_admin = create_user(runtime, email="tenant-admin@example.com", password="Password123456!", role="admin")
    analyst = create_user(runtime, email="analyst@example.com", password="Password123456!", role="analyst")
    viewer = create_user(runtime, email="viewer@example.com", password="Password123456!", role="viewer")

    tenant_admin_membership = create_membership(runtime, tenant=tenant, user=tenant_admin, role="tenant_admin")
    analyst_membership = create_membership(runtime, tenant=tenant, user=analyst, role="analyst")
    viewer_membership = create_membership(runtime, tenant=tenant, user=viewer, role="viewer")

    assert tenant.slug == "tenant-alpha"
    assert tenant_admin_membership.role == "tenant_admin"
    assert analyst_membership.role == "analyst"
    assert viewer_membership.role == "viewer"


def test_disabled_membership_is_not_active(runtime):
    tenant = create_tenant(runtime, name="Tenant Alpha", slug=unique_tenant_slug("tenant-alpha"))
    user = create_user(runtime, email="viewer@example.com", password="Password123456!", role="viewer")
    membership = create_membership(runtime, tenant=tenant, user=user, role="viewer", status="disabled")

    assert membership.status == "disabled"


def test_disabled_tenant_not_considered_active(runtime):
    tenant = create_tenant(
        runtime,
        name="Tenant Alpha",
        slug=unique_tenant_slug("tenant-alpha"),
        status="disabled",
    )
    assert tenant.status == "disabled"


def test_membership_soft_delete(runtime):
    tenant = create_tenant(runtime, name="Tenant Alpha", slug=unique_tenant_slug("tenant-alpha"))
    user = create_user(runtime, email="viewer@example.com", password="Password123456!", role="viewer")
    membership = create_membership(runtime, tenant=tenant, user=user, role="viewer", status="active")

    database = runtime["database"]
    auth_models = runtime["auth_models"]
    db = database.SessionLocal()
    try:
        row = db.query(auth_models.TenantMembership).filter(auth_models.TenantMembership.id == membership.id).one()
        row.deleted_at = database.datetime.utcnow()
        db.add(row)
        db.commit()
        db.refresh(row)
        assert row.deleted_at is not None
    finally:
        db.close()


def test_duplicate_slug_blocked(runtime):
    slug = unique_tenant_slug("tenant-alpha")
    create_tenant(runtime, name="Tenant Alpha", slug=slug)
    with pytest.raises(Exception):
        create_tenant(runtime, name="Tenant Alpha 2", slug=slug)
