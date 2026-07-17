from __future__ import annotations

import pytest

from account_lifecycle_testkit import create_user, error_code, login, runtime, set_production_auth_defaults
from production_auth_testkit import reset_runtime_state
from tenant_testkit import create_membership, create_tenant, ensure_default_tenant, unique_tenant_slug


@pytest.fixture(autouse=True)
def _reset_runtime(runtime):
    reset_runtime_state(runtime)
    set_production_auth_defaults(runtime)
    ensure_default_tenant(runtime)
    yield


def _set_user_default_tenant(runtime, *, user, tenant) -> None:
    db = runtime["database"].SessionLocal()
    try:
        row = db.query(runtime["auth_models"].User).filter(runtime["auth_models"].User.id == user.id).one()
        row.default_tenant_id = str(tenant.id)
        db.add(row)
        db.commit()
    finally:
        db.close()


def _create_tenant_user(runtime, *, tenant, email: str, password: str, role: str = "viewer", tenant_role: str = "viewer"):
    user = create_user(runtime, email=email, password=password, role=role, display_name=email.split("@", 1)[0])
    _set_user_default_tenant(runtime, user=user, tenant=tenant)
    create_membership(runtime, tenant=tenant, user=user, role=tenant_role, status="active")
    return user


def _seed_public_org(runtime, *, org_id: str, name: str = "Victory Philippines"):
    db = runtime["database"].SessionLocal()
    try:
        row = runtime["database"].OrganizationProfile(
            id=org_id,
            name=name,
            country="PH",
            official_website="https://example.org",
        )
        db.add(row)
        db.commit()
        return row
    finally:
        db.close()


def _seed_watch_target(
    runtime,
    *,
    watch_target_id: str,
    tenant_id: str | None,
    user_id: str,
    owner_user_id: str | None,
    entity_id: str,
):
    db = runtime["database"].SessionLocal()
    try:
        row = runtime["database"].WatchTarget(
            id=watch_target_id,
            tenant_id=tenant_id,
            user_id=user_id,
            owner_user_id=owner_user_id,
            entity_id=entity_id,
            entity_type="organization",
            status="active",
            frequency="daily",
        )
        db.add(row)
        db.commit()
        return row
    finally:
        db.close()


def test_watch_targets_are_tenant_scoped_and_same_org_can_be_watched_by_multiple_tenants(runtime):
    client = runtime["client"]
    tenant_a = create_tenant(runtime, name="Tenant A", slug=unique_tenant_slug("watch-a"))
    tenant_b = create_tenant(runtime, name="Tenant B", slug=unique_tenant_slug("watch-b"))
    _create_tenant_user(runtime, tenant=tenant_a, email="watch-a@example.com", password="Password123456!")
    _create_tenant_user(runtime, tenant=tenant_b, email="watch-b@example.com", password="Password123456!")
    _seed_public_org(runtime, org_id="org-watch-shared")

    login(client, email="watch-a@example.com", password="Password123456!")
    create_a = client.post(
        "/api/watch-targets",
        headers={"X-Tenant-ID": tenant_a.public_id},
        json={
            "entity_id": "org-watch-shared",
            "entity_type": "organization",
            "frequency": "daily",
            "tenant_id": tenant_b.public_id,
        },
    )
    assert create_a.status_code == 201
    watch_a_id = create_a.json()["id"]

    get_a = client.get(f"/api/watch-targets/{watch_a_id}", headers={"X-Tenant-ID": tenant_a.public_id})
    assert get_a.status_code == 200
    assert get_a.json()["entity_id"] == "org-watch-shared"

    client.cookies.clear()
    login(client, email="watch-b@example.com", password="Password123456!")
    create_b = client.post(
        "/api/watch-targets",
        headers={"X-Tenant-ID": tenant_b.public_id},
        json={"entity_id": "org-watch-shared", "entity_type": "organization", "frequency": "weekly"},
    )
    assert create_b.status_code == 201
    watch_b_id = create_b.json()["id"]

    list_b = client.get("/api/watch-targets", headers={"X-Tenant-ID": tenant_b.public_id})
    get_cross = client.get(f"/api/watch-targets/{watch_a_id}", headers={"X-Tenant-ID": tenant_b.public_id})
    patch_cross = client.patch(
        f"/api/watch-targets/{watch_a_id}",
        headers={"X-Tenant-ID": tenant_b.public_id},
        json={"status": "paused"},
    )
    delete_cross = client.delete(f"/api/watch-targets/{watch_a_id}", headers={"X-Tenant-ID": tenant_b.public_id})
    assert list_b.status_code == 200
    assert [item["id"] for item in list_b.json()["items"]] == [watch_b_id]
    assert get_cross.status_code == 404
    assert error_code(get_cross) == "WATCH_TARGET_NOT_FOUND"
    assert patch_cross.status_code == 404
    assert error_code(patch_cross) == "WATCH_TARGET_NOT_FOUND"
    assert delete_cross.status_code == 404
    assert error_code(delete_cross) == "WATCH_TARGET_NOT_FOUND"

    client.cookies.clear()
    login(client, email="watch-a@example.com", password="Password123456!")
    delete_a = client.delete(f"/api/watch-targets/{watch_a_id}", headers={"X-Tenant-ID": tenant_a.public_id})
    list_a = client.get("/api/watch-targets", headers={"X-Tenant-ID": tenant_a.public_id})
    assert delete_a.status_code == 204
    assert list_a.status_code == 200
    assert list_a.json()["total"] == 0

    client.cookies.clear()
    login(client, email="watch-b@example.com", password="Password123456!")
    list_b_after = client.get("/api/watch-targets", headers={"X-Tenant-ID": tenant_b.public_id})
    assert list_b_after.json()["total"] == 1
    assert list_b_after.json()["items"][0]["id"] == watch_b_id

    db = runtime["database"].SessionLocal()
    try:
        row_b = db.query(runtime["database"].WatchTarget).filter_by(id=watch_b_id).one()
        assert row_b.tenant_id == str(tenant_b.id)
        assert db.query(runtime["database"].OrganizationProfile).filter_by(id="org-watch-shared").count() == 1
    finally:
        db.close()


def test_null_tenant_watch_target_is_hidden_and_super_admin_requires_explicit_tenant_context(runtime):
    client = runtime["client"]
    default_tenant = ensure_default_tenant(runtime)
    tenant = create_tenant(runtime, name="Tenant Scoped", slug=unique_tenant_slug("watch-null"))
    owner = _create_tenant_user(runtime, tenant=tenant, email="watch-owner@example.com", password="Password123456!")
    _seed_public_org(runtime, org_id="org-watch-null", name="Legacy Org")
    _seed_public_org(runtime, org_id="org-watch-owned", name="Scoped Org")
    _seed_watch_target(
        runtime,
        watch_target_id="watch-null-legacy",
        tenant_id=None,
        user_id=str(owner.id),
        owner_user_id=str(owner.id),
        entity_id="org-watch-null",
    )
    _seed_watch_target(
        runtime,
        watch_target_id="watch-tenant-owned",
        tenant_id=str(tenant.id),
        user_id=str(owner.id),
        owner_user_id=str(owner.id),
        entity_id="org-watch-owned",
    )

    login(client, email="watch-owner@example.com", password="Password123456!")
    list_response = client.get("/api/watch-targets", headers={"X-Tenant-ID": tenant.public_id})
    get_response = client.get("/api/watch-targets/watch-null-legacy", headers={"X-Tenant-ID": tenant.public_id})
    patch_response = client.patch(
        "/api/watch-targets/watch-null-legacy",
        headers={"X-Tenant-ID": tenant.public_id},
        json={"status": "paused"},
    )
    delete_response = client.delete("/api/watch-targets/watch-null-legacy", headers={"X-Tenant-ID": tenant.public_id})
    assert list_response.status_code == 200
    assert [item["id"] for item in list_response.json()["items"]] == ["watch-tenant-owned"]
    assert get_response.status_code == 404
    assert error_code(get_response) == "WATCH_TARGET_NOT_FOUND"
    assert patch_response.status_code == 404
    assert error_code(patch_response) == "WATCH_TARGET_NOT_FOUND"
    assert delete_response.status_code == 404
    assert error_code(delete_response) == "WATCH_TARGET_NOT_FOUND"

    super_admin = create_user(
        runtime,
        email="watch-super-admin@example.com",
        password="Password123456!",
        role="super_admin",
        display_name="Super Admin",
    )
    _set_user_default_tenant(runtime, user=super_admin, tenant=default_tenant)

    client.cookies.clear()
    login(client, email="watch-super-admin@example.com", password="Password123456!")
    no_context = client.get("/api/watch-targets/watch-tenant-owned")
    explicit_context = client.get("/api/watch-targets/watch-tenant-owned", headers={"X-Tenant-ID": tenant.public_id})
    assert no_context.status_code == 404
    assert error_code(no_context) == "WATCH_TARGET_NOT_FOUND"
    assert explicit_context.status_code == 200
    assert explicit_context.json()["id"] == "watch-tenant-owned"


def test_disabled_tenant_and_disabled_membership_are_blocked_for_watch_targets(runtime):
    client = runtime["client"]
    default_tenant = ensure_default_tenant(runtime)
    disabled_tenant = create_tenant(runtime, name="Tenant Disabled", slug=unique_tenant_slug("watch-disabled"), status="disabled")
    inactive_membership_tenant = create_tenant(runtime, name="Tenant Membership", slug=unique_tenant_slug("watch-membership"))
    _seed_public_org(runtime, org_id="org-watch-disabled", name="Disabled Org")
    user = _create_tenant_user(runtime, tenant=default_tenant, email="watch-blocked@example.com", password="Password123456!")
    create_membership(runtime, tenant=disabled_tenant, user=user, role="viewer", status="active")
    create_membership(runtime, tenant=inactive_membership_tenant, user=user, role="viewer", status="disabled")

    login(client, email="watch-blocked@example.com", password="Password123456!")
    disabled_tenant_response = client.get("/api/watch-targets", headers={"X-Tenant-ID": disabled_tenant.public_id})
    disabled_membership_response = client.get("/api/watch-targets", headers={"X-Tenant-ID": inactive_membership_tenant.public_id})

    assert disabled_tenant_response.status_code == 403
    assert error_code(disabled_tenant_response) == "TENANT_DISABLED"
    assert disabled_membership_response.status_code == 403
    assert error_code(disabled_membership_response) == "TENANT_MEMBERSHIP_INACTIVE"
