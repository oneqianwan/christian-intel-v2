from __future__ import annotations

import importlib

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


def _seed_message(runtime, *, message_id: str, conversation_id: str, tenant_id: str | None, role: str, content: str):
    db = runtime["database"].SessionLocal()
    try:
        message = runtime["database"].Message(
            id=message_id,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            role=role,
            content=content,
            sources=[],
        )
        db.add(message)
        db.commit()
        db.refresh(message)
        return message
    finally:
        db.close()


def test_messages_write_and_read_are_tenant_scoped(runtime, monkeypatch):
    client = runtime["client"]
    chat_router = importlib.import_module("routers.chat")
    monkeypatch.setattr(chat_router, "think", lambda *_args, **_kwargs: {"answer": "ok", "evidence": []})

    tenant_a = create_tenant(runtime, name="Tenant A", slug=unique_tenant_slug("tenant-a"))
    tenant_b = create_tenant(runtime, name="Tenant B", slug=unique_tenant_slug("tenant-b"))
    _create_tenant_user(runtime, tenant=tenant_a, email="msg-a@example.com", password="Password123456!")
    _create_tenant_user(runtime, tenant=tenant_b, email="msg-b@example.com", password="Password123456!")

    login(client, email="msg-a@example.com", password="Password123456!")
    response_a = client.post("/api/chat/simple", headers={"X-Tenant-ID": tenant_a.public_id}, json={"message": "hello a"})
    assert response_a.status_code == 200
    conv_a = response_a.json()["conversation_id"]

    client.cookies.clear()
    login(client, email="msg-b@example.com", password="Password123456!")
    response_b = client.post("/api/chat/simple", headers={"X-Tenant-ID": tenant_b.public_id}, json={"message": "hello b"})
    assert response_b.status_code == 200
    conv_b = response_b.json()["conversation_id"]

    read_b = client.get(f"/api/conversations/{conv_b}/messages", headers={"X-Tenant-ID": tenant_b.public_id})
    assert read_b.status_code == 200
    assert [item["role"] for item in read_b.json()] == ["user", "assistant"]

    cross_read = client.get(f"/api/conversations/{conv_a}/messages", headers={"X-Tenant-ID": tenant_b.public_id})
    cross_write = client.post(
        "/api/chat/simple",
        headers={"X-Tenant-ID": tenant_b.public_id},
        json={"message": "cross", "conversation_id": conv_a},
    )
    assert cross_read.status_code == 404
    assert error_code(cross_read) == "CONVERSATION_NOT_FOUND"
    assert cross_write.status_code == 404
    assert error_code(cross_write) == "CONVERSATION_NOT_FOUND"

    db = runtime["database"].SessionLocal()
    try:
        conversation_a = db.query(runtime["database"].Conversation).filter_by(id=conv_a).one()
        conversation_b = db.query(runtime["database"].Conversation).filter_by(id=conv_b).one()
        messages_a = (
            db.query(runtime["database"].Message)
            .filter(runtime["database"].Message.conversation_id == conv_a)
            .order_by(runtime["database"].Message.created_at.asc())
            .all()
        )
        messages_b = (
            db.query(runtime["database"].Message)
            .filter(runtime["database"].Message.conversation_id == conv_b)
            .order_by(runtime["database"].Message.created_at.asc())
            .all()
        )
        assert all(message.tenant_id == conversation_a.tenant_id == str(tenant_a.id) for message in messages_a)
        assert all(message.tenant_id == conversation_b.tenant_id == str(tenant_b.id) for message in messages_b)
    finally:
        db.close()


def test_null_tenant_messages_are_fail_closed_for_regular_members(runtime):
    client = runtime["client"]
    tenant = create_tenant(runtime, name="Tenant Message", slug=unique_tenant_slug("tenant-message"))
    user = _create_tenant_user(runtime, tenant=tenant, email="msg-null@example.com", password="Password123456!")
    _seed_conversation(runtime, conversation_id="conv-null-msg", tenant_id=str(tenant.id), owner_user_id=str(user.id))
    _seed_message(
        runtime,
        message_id="msg-null",
        conversation_id="conv-null-msg",
        tenant_id=None,
        role="user",
        content="legacy message",
    )

    login(client, email="msg-null@example.com", password="Password123456!")
    response = client.get("/api/conversations/conv-null-msg/messages", headers={"X-Tenant-ID": tenant.public_id})

    assert response.status_code == 200
    assert response.json() == []


def test_super_admin_can_read_messages_only_with_explicit_tenant_context(runtime):
    client = runtime["client"]
    default_tenant = ensure_default_tenant(runtime)
    foreign_tenant = create_tenant(runtime, name="Tenant Foreign", slug=unique_tenant_slug("tenant-foreign"))
    owner = _create_tenant_user(runtime, tenant=foreign_tenant, email="msg-owner@example.com", password="Password123456!")
    _seed_conversation(runtime, conversation_id="foreign-msg-conv", tenant_id=str(foreign_tenant.id), owner_user_id=str(owner.id))
    _seed_message(
        runtime,
        message_id="foreign-msg-1",
        conversation_id="foreign-msg-conv",
        tenant_id=str(foreign_tenant.id),
        role="user",
        content="foreign",
    )

    super_admin = create_user(
        runtime,
        email="msg-super-admin@example.com",
        password="Password123456!",
        role="super_admin",
        display_name="Super Admin",
    )
    _set_user_default_tenant(runtime, user=super_admin, tenant=default_tenant)

    login(client, email="msg-super-admin@example.com", password="Password123456!")
    without_context = client.get("/api/conversations/foreign-msg-conv/messages")
    with_context = client.get(
        "/api/conversations/foreign-msg-conv/messages",
        headers={"X-Tenant-ID": foreign_tenant.public_id},
    )

    assert without_context.status_code == 404
    assert error_code(without_context) == "CONVERSATION_NOT_FOUND"
    assert with_context.status_code == 200
    assert [item["id"] for item in with_context.json()] == ["foreign-msg-1"]
