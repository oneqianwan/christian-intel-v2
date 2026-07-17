from __future__ import annotations

import uuid

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


def _seed_public_item(runtime, *, item_id: str = "item-global-1", title: str = "Global Item"):
    db = runtime["database"].SessionLocal()
    try:
        source = runtime["database"].Source(
            id=f"source-{item_id}",
            name="Global Source",
            url=f"https://example.com/{item_id}",
            type="website",
            country="PH",
            scope="global",
        )
        item = runtime["database"].IntelligenceItem(
            id=item_id,
            source_id=source.id,
            title=title,
            entity_name="Victory Philippines",
            entity_type="organization",
            country="PH",
            category="public_intelligence",
            source_url=f"https://example.com/{item_id}",
            source_name=source.name,
            scope="global",
        )
        db.add(source)
        db.add(item)
        db.commit()
        db.refresh(item)
        return item
    finally:
        db.close()


def _seed_bookmark(runtime, *, bookmark_id: str, tenant_id: str | None, user_id: str | None, item_id: str, note: str = "legacy"):
    db = runtime["database"].SessionLocal()
    try:
        bookmark = runtime["database"].Bookmark(
            id=bookmark_id,
            tenant_id=tenant_id,
            user_id=user_id,
            intelligence_item_id=item_id,
            note=note,
        )
        db.add(bookmark)
        db.commit()
        db.refresh(bookmark)
        return bookmark
    finally:
        db.close()


def test_bookmarks_are_tenant_scoped_and_same_item_can_be_bookmarked_by_multiple_tenants(runtime):
    client = runtime["client"]
    tenant_a = create_tenant(runtime, name="Tenant A", slug=unique_tenant_slug("bookmark-a"))
    tenant_b = create_tenant(runtime, name="Tenant B", slug=unique_tenant_slug("bookmark-b"))
    user_a = _create_tenant_user(runtime, tenant=tenant_a, email="bookmark-a@example.com", password="Password123456!")
    _create_tenant_user(runtime, tenant=tenant_b, email="bookmark-b@example.com", password="Password123456!")
    item = _seed_public_item(runtime, item_id="item-global-bookmark", title="Victory Philippines")

    login(client, email="bookmark-a@example.com", password="Password123456!")
    create_a = client.post(
        "/api/bookmarks",
        params={"item_id": item.id, "note": "tenant-a", "tenant_id": tenant_b.public_id},
        headers={"X-Tenant-ID": tenant_a.public_id},
    )
    assert create_a.status_code == 200
    assert create_a.json()["status"] == "created"
    bookmark_a_id = create_a.json()["bookmark_id"]

    get_a = client.get(f"/api/bookmarks/{bookmark_a_id}", headers={"X-Tenant-ID": tenant_a.public_id})
    assert get_a.status_code == 200
    assert get_a.json()["item_id"] == item.id
    assert get_a.json()["title"] == "Victory Philippines"

    client.cookies.clear()
    login(client, email="bookmark-b@example.com", password="Password123456!")
    create_b = client.post(
        "/api/bookmarks",
        params={"item_id": item.id, "note": "tenant-b"},
        headers={"X-Tenant-ID": tenant_b.public_id},
    )
    assert create_b.status_code == 200
    assert create_b.json()["status"] == "created"
    bookmark_b_id = create_b.json()["bookmark_id"]

    list_b = client.get("/api/bookmarks", headers={"X-Tenant-ID": tenant_b.public_id})
    cross_get = client.get(f"/api/bookmarks/{bookmark_a_id}", headers={"X-Tenant-ID": tenant_b.public_id})
    cross_delete = client.delete(f"/api/bookmarks/{bookmark_a_id}", headers={"X-Tenant-ID": tenant_b.public_id})
    assert list_b.status_code == 200
    assert [item["bookmark_id"] for item in list_b.json()] == [bookmark_b_id]
    assert cross_get.status_code == 404
    assert error_code(cross_get) == "BOOKMARK_NOT_FOUND"
    assert cross_delete.status_code == 404
    assert error_code(cross_delete) == "BOOKMARK_NOT_FOUND"

    client.cookies.clear()
    login(client, email="bookmark-a@example.com", password="Password123456!")
    list_a = client.get("/api/bookmarks", headers={"X-Tenant-ID": tenant_a.public_id})
    delete_a = client.delete(f"/api/bookmarks/{bookmark_a_id}", headers={"X-Tenant-ID": tenant_a.public_id})
    assert list_a.status_code == 200
    assert [item["bookmark_id"] for item in list_a.json()] == [bookmark_a_id]
    assert delete_a.status_code == 200
    assert delete_a.json()["status"] == "deleted"

    client.cookies.clear()
    login(client, email="bookmark-b@example.com", password="Password123456!")
    list_b_after = client.get("/api/bookmarks", headers={"X-Tenant-ID": tenant_b.public_id})
    assert [item["bookmark_id"] for item in list_b_after.json()] == [bookmark_b_id]

    db = runtime["database"].SessionLocal()
    try:
        bookmark_b = db.query(runtime["database"].Bookmark).filter_by(id=bookmark_b_id).one()
        remaining_ids = {row.id for row in db.query(runtime["database"].Bookmark).all()}
        assert bookmark_b.tenant_id == str(tenant_b.id)
        assert bookmark_b.user_id != str(user_a.id)
        assert bookmark_a_id not in remaining_ids
    finally:
        db.close()


def test_null_tenant_bookmark_is_hidden_and_super_admin_requires_explicit_tenant_context(runtime):
    client = runtime["client"]
    default_tenant = ensure_default_tenant(runtime)
    tenant = create_tenant(runtime, name="Tenant Bookmark", slug=unique_tenant_slug("bookmark-null"))
    owner = _create_tenant_user(runtime, tenant=tenant, email="bookmark-owner@example.com", password="Password123456!")
    item = _seed_public_item(runtime, item_id="item-global-null", title="Legacy Global")
    _seed_bookmark(
        runtime,
        bookmark_id="legacy-null-bookmark",
        tenant_id=None,
        user_id=str(owner.id),
        item_id=item.id,
    )
    _seed_bookmark(
        runtime,
        bookmark_id="foreign-tenant-bookmark",
        tenant_id=str(tenant.id),
        user_id=str(owner.id),
        item_id=item.id,
        note="tenant-owned",
    )

    login(client, email="bookmark-owner@example.com", password="Password123456!")
    list_response = client.get("/api/bookmarks", headers={"X-Tenant-ID": tenant.public_id})
    get_response = client.get("/api/bookmarks/legacy-null-bookmark", headers={"X-Tenant-ID": tenant.public_id})
    delete_response = client.delete("/api/bookmarks/legacy-null-bookmark", headers={"X-Tenant-ID": tenant.public_id})
    assert list_response.status_code == 200
    assert [item["bookmark_id"] for item in list_response.json()] == ["foreign-tenant-bookmark"]
    assert get_response.status_code == 404
    assert error_code(get_response) == "BOOKMARK_NOT_FOUND"
    assert delete_response.status_code == 404
    assert error_code(delete_response) == "BOOKMARK_NOT_FOUND"

    super_admin = create_user(
        runtime,
        email="bookmark-super-admin@example.com",
        password="Password123456!",
        role="super_admin",
        display_name="Super Admin",
    )
    _set_user_default_tenant(runtime, user=super_admin, tenant=default_tenant)

    client.cookies.clear()
    login(client, email="bookmark-super-admin@example.com", password="Password123456!")
    no_context = client.get("/api/bookmarks/foreign-tenant-bookmark")
    explicit_context = client.get(
        "/api/bookmarks/foreign-tenant-bookmark",
        headers={"X-Tenant-ID": tenant.public_id},
    )
    assert no_context.status_code == 404
    assert error_code(no_context) == "BOOKMARK_NOT_FOUND"
    assert explicit_context.status_code == 200
    assert explicit_context.json()["bookmark_id"] == "foreign-tenant-bookmark"


def test_disabled_tenant_and_disabled_membership_are_blocked_for_bookmarks(runtime):
    client = runtime["client"]
    default_tenant = ensure_default_tenant(runtime)
    disabled_tenant = create_tenant(runtime, name="Tenant Disabled", slug=unique_tenant_slug("bookmark-disabled"), status="disabled")
    inactive_membership_tenant = create_tenant(runtime, name="Tenant Inactive Membership", slug=unique_tenant_slug("bookmark-membership"))
    _seed_public_item(runtime, item_id="item-global-disabled", title="Disabled Item")
    user = _create_tenant_user(runtime, tenant=default_tenant, email="bookmark-blocked@example.com", password="Password123456!")
    create_membership(runtime, tenant=disabled_tenant, user=user, role="viewer", status="active")
    create_membership(runtime, tenant=inactive_membership_tenant, user=user, role="viewer", status="disabled")

    login(client, email="bookmark-blocked@example.com", password="Password123456!")
    disabled_tenant_response = client.get("/api/bookmarks", headers={"X-Tenant-ID": disabled_tenant.public_id})
    inactive_membership_response = client.get("/api/bookmarks", headers={"X-Tenant-ID": inactive_membership_tenant.public_id})

    assert disabled_tenant_response.status_code == 403
    assert error_code(disabled_tenant_response) == "TENANT_DISABLED"
    assert inactive_membership_response.status_code == 403
    assert error_code(inactive_membership_response) == "TENANT_MEMBERSHIP_INACTIVE"
