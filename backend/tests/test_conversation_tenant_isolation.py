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


def _seed_conversation(runtime, *, conversation_id: str, tenant_id: str | None, owner_user_id: str | None, title: str = "Seed"):
    db = runtime["database"].SessionLocal()
    try:
        conversation = runtime["database"].Conversation(
            id=conversation_id,
            title=title,
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
        )
        db.add(conversation)
        db.commit()
        db.refresh(conversation)
        return conversation
    finally:
        db.close()


def test_conversations_are_tenant_scoped_and_cross_tenant_access_is_blocked(runtime):
    client = runtime["client"]
    tenant_a = create_tenant(runtime, name="Tenant A", slug=unique_tenant_slug("tenant-a"))
    tenant_b = create_tenant(runtime, name="Tenant B", slug=unique_tenant_slug("tenant-b"))
    user_a = _create_tenant_user(runtime, tenant=tenant_a, email="conv-a@example.com", password="Password123456!")
    _create_tenant_user(runtime, tenant=tenant_b, email="conv-b@example.com", password="Password123456!")

    login(client, email="conv-a@example.com", password="Password123456!")
    create_a = client.post("/api/conversations", headers={"X-Tenant-ID": tenant_a.public_id}, json={"title": "A1"})
    assert create_a.status_code == 200
    a_id = create_a.json()["id"]

    client.cookies.clear()
    login(client, email="conv-b@example.com", password="Password123456!")
    create_b = client.post("/api/conversations", headers={"X-Tenant-ID": tenant_b.public_id}, json={"title": "B1"})
    assert create_b.status_code == 200
    b_id = create_b.json()["id"]

    list_b = client.get("/api/conversations", headers={"X-Tenant-ID": tenant_b.public_id})
    assert list_b.status_code == 200
    assert [item["id"] for item in list_b.json()] == [b_id]

    get_a_from_b = client.get(f"/api/conversations/{a_id}", headers={"X-Tenant-ID": tenant_b.public_id})
    update_a_from_b = client.put(
        f"/api/conversations/{a_id}",
        headers={"X-Tenant-ID": tenant_b.public_id},
        json={"title": "hijack"},
    )
    delete_a_from_b = client.delete(f"/api/conversations/{a_id}", headers={"X-Tenant-ID": tenant_b.public_id})
    assert get_a_from_b.status_code == 404
    assert error_code(get_a_from_b) == "CONVERSATION_NOT_FOUND"
    assert update_a_from_b.status_code == 404
    assert delete_a_from_b.status_code == 404

    client.cookies.clear()
    login(client, email="conv-a@example.com", password="Password123456!")
    list_a = client.get("/api/conversations", headers={"X-Tenant-ID": tenant_a.public_id})
    assert list_a.status_code == 200
    assert [item["id"] for item in list_a.json()] == [a_id]

    db = runtime["database"].SessionLocal()
    try:
        conversation_a = db.query(runtime["database"].Conversation).filter_by(id=a_id).one()
        conversation_b = db.query(runtime["database"].Conversation).filter_by(id=b_id).one()
        assert conversation_a.tenant_id == str(tenant_a.id)
        assert conversation_b.tenant_id == str(tenant_b.id)
        assert conversation_a.owner_user_id == str(user_a.id)
    finally:
        db.close()


def test_null_tenant_conversation_is_hidden_from_regular_tenant_members(runtime):
    client = runtime["client"]
    tenant = create_tenant(runtime, name="Tenant Null", slug=unique_tenant_slug("tenant-null"))
    user = _create_tenant_user(runtime, tenant=tenant, email="null-conv@example.com", password="Password123456!")
    _seed_conversation(runtime, conversation_id="legacy-null-conv", tenant_id=None, owner_user_id=str(user.id), title="Legacy")

    login(client, email="null-conv@example.com", password="Password123456!")
    list_response = client.get("/api/conversations", headers={"X-Tenant-ID": tenant.public_id})
    detail_response = client.get("/api/conversations/legacy-null-conv", headers={"X-Tenant-ID": tenant.public_id})

    assert list_response.status_code == 200
    assert list_response.json() == []
    assert detail_response.status_code == 404
    assert error_code(detail_response) == "CONVERSATION_NOT_FOUND"


def test_disabled_tenant_and_disabled_membership_are_blocked(runtime):
    client = runtime["client"]
    default_tenant = ensure_default_tenant(runtime)
    disabled_tenant = create_tenant(runtime, name="Tenant Disabled", slug=unique_tenant_slug("tenant-disabled"), status="disabled")
    disabled_membership_tenant = create_tenant(runtime, name="Tenant Inactive Membership", slug=unique_tenant_slug("tenant-membership"))
    user = _create_tenant_user(runtime, tenant=default_tenant, email="conv-blocked@example.com", password="Password123456!")
    create_membership(runtime, tenant=disabled_tenant, user=user, role="viewer", status="active")
    create_membership(runtime, tenant=disabled_membership_tenant, user=user, role="viewer", status="disabled")

    login(client, email="conv-blocked@example.com", password="Password123456!")
    disabled_tenant_response = client.get("/api/conversations", headers={"X-Tenant-ID": disabled_tenant.public_id})
    disabled_membership_response = client.get(
        "/api/conversations",
        headers={"X-Tenant-ID": disabled_membership_tenant.public_id},
    )

    assert disabled_tenant_response.status_code == 403
    assert error_code(disabled_tenant_response) == "TENANT_DISABLED"
    assert disabled_membership_response.status_code == 403
    assert error_code(disabled_membership_response) == "TENANT_MEMBERSHIP_INACTIVE"


def test_super_admin_requires_explicit_tenant_context_for_cross_tenant_conversation_access(runtime):
    client = runtime["client"]
    default_tenant = ensure_default_tenant(runtime)
    foreign_tenant = create_tenant(runtime, name="Tenant Foreign", slug=unique_tenant_slug("tenant-foreign"))
    owner = _create_tenant_user(runtime, tenant=foreign_tenant, email="conv-owner@example.com", password="Password123456!")
    _seed_conversation(
        runtime,
        conversation_id="foreign-conv",
        tenant_id=str(foreign_tenant.id),
        owner_user_id=str(owner.id),
        title="Foreign",
    )

    super_admin = create_user(
        runtime,
        email="super-admin@example.com",
        password="Password123456!",
        role="super_admin",
        display_name="Super Admin",
    )
    _set_user_default_tenant(runtime, user=super_admin, tenant=default_tenant)

    login(client, email="super-admin@example.com", password="Password123456!")
    no_context_response = client.get("/api/conversations/foreign-conv")
    explicit_context_response = client.get(
        "/api/conversations/foreign-conv",
        headers={"X-Tenant-ID": foreign_tenant.public_id},
    )

    assert no_context_response.status_code == 404
    assert error_code(no_context_response) == "CONVERSATION_NOT_FOUND"
    assert explicit_context_response.status_code == 200
    assert explicit_context_response.json()["id"] == "foreign-conv"
