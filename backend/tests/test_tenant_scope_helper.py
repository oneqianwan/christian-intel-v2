from __future__ import annotations

import json

import pytest

from account_lifecycle_testkit import create_user, runtime
from production_auth_testkit import reset_runtime_state
from services import tenant_scope
from tenant_testkit import create_membership, create_tenant, ensure_default_tenant, unique_tenant_slug


class _UnsupportedModel:
    pass


@pytest.fixture(autouse=True)
def _reset_runtime(runtime):
    reset_runtime_state(runtime)
    ensure_default_tenant(runtime)
    yield


def test_filter_by_tenant_adds_tenant_id_condition(runtime):
    database = runtime["database"]
    auth_models = runtime["auth_models"]
    tenant_a = create_tenant(runtime, name="Tenant Alpha", slug=unique_tenant_slug("tenant-alpha"))
    tenant_b = create_tenant(runtime, name="Tenant Beta", slug=unique_tenant_slug("tenant-beta"))
    user = create_user(runtime, email="viewer@example.com", password="Password123456!", role="viewer")
    create_membership(runtime, tenant=tenant_a, user=user, role="viewer", status="active")
    create_membership(runtime, tenant=tenant_b, user=user, role="viewer", status="active")

    db = database.SessionLocal()
    try:
        query = db.query(auth_models.TenantMembership)
        scoped = tenant_scope.filter_by_tenant(query, auth_models.TenantMembership, tenant_a.id)
        rows = scoped.all()
        assert len(rows) == 1
        assert rows[0].tenant_id == tenant_a.id
    finally:
        db.close()


def test_assert_same_tenant_passes_for_matching_tenant(runtime):
    tenant = create_tenant(runtime, name="Tenant Alpha", slug=unique_tenant_slug("tenant-alpha"))
    assert tenant_scope.assert_same_tenant(tenant.id, tenant) is True


def test_assert_same_tenant_blocks_cross_tenant(runtime):
    tenant_a = create_tenant(runtime, name="Tenant Alpha", slug=unique_tenant_slug("tenant-alpha"))
    tenant_b = create_tenant(runtime, name="Tenant Beta", slug=unique_tenant_slug("tenant-beta"))
    with pytest.raises(tenant_scope.TenantScopeError) as exc:
        tenant_scope.assert_same_tenant(tenant_a.id, tenant_b)
    assert exc.value.error_code == "TENANT_SCOPE_FORBIDDEN"


def test_unsupported_model_does_not_silently_pass(runtime):
    database = runtime["database"]
    db = database.SessionLocal()
    try:
        with pytest.raises(tenant_scope.TenantScopeError) as exc:
            tenant_scope.filter_by_tenant(db.query(runtime["auth_models"].User), _UnsupportedModel, "tenant-1")
        assert exc.value.error_code == "TENANT_SCOPE_UNSUPPORTED_MODEL"
    finally:
        db.close()


def test_create_payload_automatically_injects_tenant_id(runtime):
    tenant = create_tenant(runtime, name="Tenant Alpha", slug=unique_tenant_slug("tenant-alpha"))
    payload = tenant_scope.ensure_tenant_id_for_create({"name": "record"}, tenant)
    assert payload["tenant_id"] == tenant.id


def test_tenant_scope_metadata_contains_user_tenant_and_role(runtime):
    tenant = create_tenant(runtime, name="Tenant Alpha", slug=unique_tenant_slug("tenant-alpha"))
    user = create_user(runtime, email="analyst@example.com", password="Password123456!", role="analyst")
    membership = create_membership(runtime, tenant=tenant, user=user, role="analyst", status="active")

    metadata = tenant_scope.build_tenant_scope_metadata(user, tenant, membership)

    assert metadata["user_id"] == user.id
    assert metadata["tenant_id"] == tenant.id
    assert metadata["tenant_role"] == "analyst"
    assert metadata["global_role"] == "analyst"


def test_disabled_tenant_does_not_generate_valid_scope(runtime):
    tenant = create_tenant(runtime, name="Tenant Alpha", slug=unique_tenant_slug("tenant-alpha"), status="disabled")
    user = create_user(runtime, email="viewer@example.com", password="Password123456!", role="viewer")

    with pytest.raises(tenant_scope.TenantScopeError) as exc:
        tenant_scope.build_tenant_scope_metadata(user, tenant, None)
    assert exc.value.error_code == "TENANT_DISABLED"


def test_require_record_tenant_blocks_cross_tenant_record(runtime):
    tenant_a = create_tenant(runtime, name="Tenant Alpha", slug=unique_tenant_slug("tenant-alpha"))
    tenant_b = create_tenant(runtime, name="Tenant Beta", slug=unique_tenant_slug("tenant-beta"))
    user = create_user(runtime, email="viewer@example.com", password="Password123456!", role="viewer")
    membership = create_membership(runtime, tenant=tenant_a, user=user, role="viewer", status="active")

    with pytest.raises(tenant_scope.TenantScopeError) as exc:
        tenant_scope.require_record_tenant(membership, tenant_b)
    assert exc.value.error_code == "TENANT_SCOPE_FORBIDDEN"


def test_scope_helper_does_not_print_secret_like_values(runtime):
    tenant = create_tenant(runtime, name="Tenant Alpha", slug=unique_tenant_slug("tenant-alpha"))
    user = create_user(runtime, email="viewer@example.com", password="Password123456!", role="viewer")
    membership = create_membership(runtime, tenant=tenant, user=user, role="viewer", status="active")

    serialized = json.dumps(tenant_scope.build_tenant_scope_metadata(user, tenant, membership), ensure_ascii=False).lower()
    assert "password" not in serialized
    assert "token" not in serialized
    assert "secret" not in serialized
