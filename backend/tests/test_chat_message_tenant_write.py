from __future__ import annotations

import importlib

import pytest

from account_lifecycle_testkit import create_user, login, runtime, set_production_auth_defaults
from chat_ownership_testkit import parse_sse_text
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


def _create_tenant_user(runtime, *, tenant, email: str, password: str):
    user = create_user(runtime, email=email, password=password, role="viewer", display_name=email.split("@", 1)[0])
    _set_user_default_tenant(runtime, user=user, tenant=tenant)
    create_membership(runtime, tenant=tenant, user=user, role="viewer", status="active")
    return user


class _FakeBrain:
    def think_stream(self, user_message: str, conversation_id: str, history):
        assert isinstance(history, list)
        yield {"type": "thinking"}
        yield {"type": "token", "content": f"stream:{user_message}:{conversation_id}:{len(history)}"}
        yield {"type": "done", "evidence": [{"kind": "test"}]}


def test_chat_simple_and_stream_write_tenant_ids_and_keep_contract(runtime, monkeypatch):
    client = runtime["client"]
    chat_router = importlib.import_module("routers.chat")
    monkeypatch.setattr(chat_router, "think", lambda *_args, **_kwargs: {"answer": "simple-ok", "evidence": [{"kind": "simple"}]})
    monkeypatch.setattr(chat_router, "Brain", _FakeBrain)

    tenant = create_tenant(runtime, name="Tenant Chat", slug=unique_tenant_slug("tenant-chat"))
    _create_tenant_user(runtime, tenant=tenant, email="chat-tenant@example.com", password="Password123456!")

    login(client, email="chat-tenant@example.com", password="Password123456!")
    simple_response = client.post("/api/chat/simple", headers={"X-Tenant-ID": tenant.public_id}, json={"message": "hello simple"})
    stream_response = client.post("/api/chat/stream", headers={"X-Tenant-ID": tenant.public_id}, json={"message": "hello stream"})

    assert simple_response.status_code == 200
    assert set(simple_response.json().keys()) == {"reply", "delivery", "conversation_id"}
    assert simple_response.json()["delivery"]["status"] == "success"
    assert stream_response.status_code == 200

    events = parse_sse_text(stream_response.text)
    done_event = next(item for item in events if item["type"] == "done")
    assert {"conversation_id", "delivery", "message_id", "request_id", "type", "full_content", "welcome_reply_uuid"}.issubset(done_event.keys())
    assert done_event["delivery"]["status"] == "success"

    db = runtime["database"].SessionLocal()
    try:
        simple_conversation_id = simple_response.json()["conversation_id"]
        stream_conversation_id = done_event["conversation_id"]
        simple_conversation = db.query(runtime["database"].Conversation).filter_by(id=simple_conversation_id).one()
        stream_conversation = db.query(runtime["database"].Conversation).filter_by(id=stream_conversation_id).one()
        simple_messages = (
            db.query(runtime["database"].Message)
            .filter(runtime["database"].Message.conversation_id == simple_conversation_id)
            .order_by(runtime["database"].Message.created_at.asc())
            .all()
        )
        stream_messages = (
            db.query(runtime["database"].Message)
            .filter(runtime["database"].Message.conversation_id == stream_conversation_id)
            .order_by(runtime["database"].Message.created_at.asc())
            .all()
        )
        assert simple_conversation.tenant_id == str(tenant.id)
        assert stream_conversation.tenant_id == str(tenant.id)
        assert [message.tenant_id for message in simple_messages] == [str(tenant.id), str(tenant.id)]
        assert [message.tenant_id for message in stream_messages] == [str(tenant.id), str(tenant.id)]
    finally:
        db.close()


def test_chat_does_not_write_into_other_tenant_conversation(runtime, monkeypatch):
    client = runtime["client"]
    chat_router = importlib.import_module("routers.chat")
    monkeypatch.setattr(chat_router, "think", lambda *_args, **_kwargs: {"answer": "simple-ok", "evidence": []})
    monkeypatch.setattr(chat_router, "Brain", _FakeBrain)

    tenant_a = create_tenant(runtime, name="Tenant A", slug=unique_tenant_slug("tenant-a"))
    tenant_b = create_tenant(runtime, name="Tenant B", slug=unique_tenant_slug("tenant-b"))
    _create_tenant_user(runtime, tenant=tenant_a, email="chat-a@example.com", password="Password123456!")
    _create_tenant_user(runtime, tenant=tenant_b, email="chat-b@example.com", password="Password123456!")

    login(client, email="chat-a@example.com", password="Password123456!")
    response_a = client.post("/api/chat/simple", headers={"X-Tenant-ID": tenant_a.public_id}, json={"message": "owner"})
    assert response_a.status_code == 200
    conversation_a = response_a.json()["conversation_id"]

    client.cookies.clear()
    login(client, email="chat-b@example.com", password="Password123456!")
    cross_simple = client.post(
        "/api/chat/simple",
        headers={"X-Tenant-ID": tenant_b.public_id},
        json={"message": "cross", "conversation_id": conversation_a},
    )
    cross_stream = client.post(
        "/api/chat/stream",
        headers={"X-Tenant-ID": tenant_b.public_id},
        json={"message": "cross-stream", "conversation_id": conversation_a},
    )

    assert cross_simple.status_code == 404
    assert cross_stream.status_code == 404

    db = runtime["database"].SessionLocal()
    try:
        messages = (
            db.query(runtime["database"].Message)
            .filter(runtime["database"].Message.conversation_id == conversation_a)
            .order_by(runtime["database"].Message.created_at.asc())
            .all()
        )
        assert len(messages) == 2
        assert all(message.tenant_id == str(tenant_a.id) for message in messages)
    finally:
        db.close()
