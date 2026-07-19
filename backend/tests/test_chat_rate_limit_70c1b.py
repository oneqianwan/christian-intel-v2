from __future__ import annotations

from types import SimpleNamespace

import pytest

from chat_ownership_testkit import create_user, login
from tenant_testkit import create_membership, create_tenant, ensure_default_tenant, unique_tenant_slug


pytest_plugins = ["chat_ownership_testkit"]


def _set_user_default_tenant(chat_runtime, *, user, tenant) -> None:
    db = chat_runtime["database"].SessionLocal()
    try:
        row = db.query(chat_runtime["auth_models"].User).filter(chat_runtime["auth_models"].User.id == user.id).one()
        row.default_tenant_id = str(tenant.id)
        db.add(row)
        db.commit()
    finally:
        db.close()


def _create_tenant_user(chat_runtime, *, tenant, email: str, password: str):
    user = create_user(chat_runtime, email=email, password=password, role="viewer")
    _set_user_default_tenant(chat_runtime, user=user, tenant=tenant)
    create_membership(chat_runtime, tenant=tenant, user=user, role="viewer", status="active")
    return user


def _patch_chat_limiter(monkeypatch, *, limit_simple: int = 2, limit_stream: int = 1):
    import dependencies.rate_limit as rate_limit_module
    from services.rate_limiter import InMemoryRateLimiter, RateLimitRule

    limiter = InMemoryRateLimiter(
        rules={
            "chat_simple": RateLimitRule(
                name="chat_simple",
                limit=limit_simple,
                window_seconds=60,
                key_parts=("tenant_id", "user_id", "route"),
            ),
            "chat_stream": RateLimitRule(
                name="chat_stream",
                limit=limit_stream,
                window_seconds=60,
                key_parts=("tenant_id", "user_id", "route"),
            ),
        }
    )
    limiter.set_time_for_tests(1000)
    monkeypatch.setattr(rate_limit_module, "get_rate_limiter", lambda: limiter)
    return limiter


def test_chat_simple_rate_limit_is_scoped_by_tenant_user_and_route(chat_runtime, monkeypatch):
    client = chat_runtime["client"]
    chat_runtime["config"].settings.AUTH_LOGIN_RATE_LIMIT_ENABLED = False
    ensure_default_tenant(chat_runtime)
    tenant_a = create_tenant(chat_runtime, name="Chat Tenant A", slug=unique_tenant_slug("chat-a"))
    tenant_b = create_tenant(chat_runtime, name="Chat Tenant B", slug=unique_tenant_slug("chat-b"))
    _create_tenant_user(chat_runtime, tenant=tenant_a, email="chat-a-user-a@example.com", password="Password123456!")
    _create_tenant_user(chat_runtime, tenant=tenant_a, email="chat-a-user-b@example.com", password="Password123456!")
    _create_tenant_user(chat_runtime, tenant=tenant_b, email="chat-b-user-a@example.com", password="Password123456!")

    _patch_chat_limiter(monkeypatch, limit_simple=2, limit_stream=1)
    call_counter = {"count": 0}

    def fake_think(message: str, conversation_id: str, history: list):
        call_counter["count"] += 1
        return {"answer": f"ok:{message}", "evidence": []}

    monkeypatch.setattr(chat_runtime["chat_router"], "think", fake_think)

    login(client, email="chat-a-user-a@example.com", password="Password123456!")
    headers_a = {"X-Tenant-ID": tenant_a.public_id}
    first = client.post("/api/chat/simple", headers=headers_a, json={"message": "hello-1"})
    second = client.post("/api/chat/simple", headers=headers_a, json={"message": "hello-2"})
    blocked = client.post("/api/chat/simple", headers=headers_a, json={"message": "hello-3"})

    assert first.status_code == 200
    assert second.status_code == 200
    assert blocked.status_code == 429
    assert blocked.json()["detail"]["error_code"] == "RATE_LIMITED"
    assert call_counter["count"] == 2

    client.cookies.clear()
    login(client, email="chat-a-user-b@example.com", password="Password123456!")
    user_b = client.post("/api/chat/simple", headers=headers_a, json={"message": "hello-user-b"})
    assert user_b.status_code == 200

    client.cookies.clear()
    login(client, email="chat-b-user-a@example.com", password="Password123456!")
    tenant_b_response = client.post(
        "/api/chat/simple",
        headers={"X-Tenant-ID": tenant_b.public_id},
        json={"message": "hello-tenant-b"},
    )
    assert tenant_b_response.status_code == 200
    assert call_counter["count"] == 4


def test_chat_stream_returns_429_before_stream_starts_and_does_not_call_brain(chat_runtime, monkeypatch):
    client = chat_runtime["client"]
    chat_runtime["config"].settings.AUTH_LOGIN_RATE_LIMIT_ENABLED = False
    ensure_default_tenant(chat_runtime)
    tenant = create_tenant(chat_runtime, name="Stream Tenant", slug=unique_tenant_slug("chat-stream"))
    user = _create_tenant_user(chat_runtime, tenant=tenant, email="chat-stream@example.com", password="Password123456!")

    limiter = _patch_chat_limiter(monkeypatch, limit_simple=2, limit_stream=1)
    stream_counter = {"count": 0}

    def fake_think_stream(message: str, conversation_id: str, history: list):
        stream_counter["count"] += 1
        yield {"type": "token", "content": "stream-ok"}
        yield {"type": "done", "evidence": []}

    monkeypatch.setattr(chat_runtime["chat_router"].Brain, "think_stream", staticmethod(fake_think_stream))

    login(client, email="chat-stream@example.com", password="Password123456!")
    headers = {"X-Tenant-ID": tenant.public_id}
    from dependencies.rate_limit import build_rate_limit_key

    limiter.allow(
        key=build_rate_limit_key(
            ip="testclient",
            user_id=str(user.id),
            tenant_id=str(tenant.id),
            route="/api/chat/stream",
            method="POST",
        ),
        rule_name="chat_stream",
    )

    blocked = client.post("/api/chat/stream", headers=headers, json={"message": "stream-blocked"})

    assert blocked.status_code == 429
    assert blocked.json()["detail"]["error_code"] == "RATE_LIMITED"
    assert blocked.headers["Retry-After"] == "60"
    assert stream_counter["count"] == 0
