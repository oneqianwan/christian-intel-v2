from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from account_lifecycle_testkit import create_user, runtime
from production_auth_testkit import reset_runtime_state
from tenant_testkit import create_membership, create_tenant, ensure_default_tenant, unique_tenant_slug


@pytest.fixture(autouse=True)
def _reset_runtime(runtime):
    reset_runtime_state(runtime)
    ensure_default_tenant(runtime)
    yield


def test_tenant_and_membership_models_exist(runtime):
    auth_models = runtime["auth_models"]

    assert hasattr(auth_models, "Tenant")
    assert hasattr(auth_models, "TenantMembership")
    assert hasattr(auth_models.User, "default_tenant_id")


def test_default_tenant_bootstrap_has_public_id_slug_status_and_soft_delete(runtime):
    database = runtime["database"]
    auth_models = runtime["auth_models"]

    db = database.SessionLocal()
    try:
        tenant = db.query(auth_models.Tenant).filter(auth_models.Tenant.slug == "default").one()
        assert tenant.public_id
        assert tenant.status == "active"
        assert tenant.deleted_at is None
    finally:
        db.close()


def test_tenant_slug_unique(runtime):
    slug = unique_tenant_slug("tenant-alpha")
    create_tenant(runtime, name="Tenant Alpha", slug=slug)

    database = runtime["database"]
    auth_models = runtime["auth_models"]
    db = database.SessionLocal()
    try:
        db.add(
            auth_models.Tenant(
                name="Duplicate",
                slug=slug,
                status="active",
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()
    finally:
        db.rollback()
        db.close()


def test_duplicate_active_membership_blocked(runtime):
    tenant = create_tenant(runtime, name="Tenant Alpha", slug=unique_tenant_slug("tenant-alpha"))
    user = create_user(runtime, email="viewer@example.com", password="Password123456!", role="viewer")
    create_membership(runtime, tenant=tenant, user=user, role="viewer", status="active")

    database = runtime["database"]
    auth_models = runtime["auth_models"]
    db = database.SessionLocal()
    try:
        db.add(
            auth_models.TenantMembership(
                tenant_id=tenant.id,
                user_id=user.id,
                role="viewer",
                status="active",
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()
    finally:
        db.rollback()
        db.close()


def test_user_can_belong_to_multiple_tenants(runtime):
    tenant_a = create_tenant(runtime, name="Tenant Alpha", slug=unique_tenant_slug("tenant-alpha"))
    tenant_b = create_tenant(runtime, name="Tenant Beta", slug=unique_tenant_slug("tenant-beta"))
    user = create_user(runtime, email="analyst@example.com", password="Password123456!", role="analyst")

    membership_a = create_membership(runtime, tenant=tenant_a, user=user, role="analyst", status="active")
    membership_b = create_membership(runtime, tenant=tenant_b, user=user, role="viewer", status="active")

    assert membership_a.tenant_id != membership_b.tenant_id


def test_super_admin_membership_does_not_define_platform_role(runtime):
    tenant = create_tenant(runtime, name="Tenant Alpha", slug=unique_tenant_slug("tenant-alpha"))
    user = create_user(runtime, email="root@example.com", password="Password123456!", role="super_admin")
    membership = create_membership(runtime, tenant=tenant, user=user, role="tenant_admin", status="active")

    assert user.role == "super_admin"
    assert membership.role == "tenant_admin"
