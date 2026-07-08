from __future__ import annotations

pytest_plugins = ["chat_ownership_testkit"]

from chat_ownership_testkit import (
    create_user,
    error_code,
    login,
    parse_sse_text,
    seed_conversation,
    seed_message,
)


def _set_flags(chat_runtime, *, ownership: bool, auth_enabled: bool = True) -> None:
    chat_runtime["config"].settings.CHAT_USER_OWNERSHIP_ENABLED = ownership
    chat_runtime["config"].settings.AUTH_V1_ENABLED = auth_enabled
    chat_runtime["config"].settings.AUTH_COOKIE_REQUIRED = False


class _FakeBrain:
    def think_stream(self, user_message: str, conversation_id: str, history):
        assert isinstance(history, list)
        yield {"type": "thinking"}
        yield {"type": "token", "content": f"reply:{user_message}:{conversation_id}:{len(history)}"}
        yield {"type": "done", "evidence": [{"kind": "test"}]}


def test_01_unauthenticated_stream_rejected_before_200(chat_runtime, monkeypatch):
    client = chat_runtime["client"]
    _set_flags(chat_runtime, ownership=True, auth_enabled=True)
    monkeypatch.setattr(chat_runtime["chat_router"], "Brain", _FakeBrain)

    response = client.post("/api/chat/stream", json={"message": "hello"})
    assert response.status_code == 401
    assert error_code(response) == "AUTH_REQUIRED"


def test_02_stream_creates_owned_conversation_and_messages(chat_runtime, monkeypatch):
    client = chat_runtime["client"]
    _set_flags(chat_runtime, ownership=True, auth_enabled=True)
    monkeypatch.setattr(chat_runtime["chat_router"], "Brain", _FakeBrain)

    user_a = create_user(chat_runtime, email="stream-a@example.com", password="StrongPass123!")
    login(client, email="stream-a@example.com", password="StrongPass123!")

    response = client.post("/api/chat/stream", json={"message": "hello stream"})
    assert response.status_code == 200
    events = parse_sse_text(response.text)
    done_event = next(item for item in events if item["type"] == "done")
    conversation_id = done_event["conversation_id"]

    db = chat_runtime["database"].SessionLocal()
    try:
        conversation = db.query(chat_runtime["database"].Conversation).filter_by(id=conversation_id).first()
        messages = (
            db.query(chat_runtime["database"].Message)
            .filter(chat_runtime["database"].Message.conversation_id == conversation_id)
            .order_by(chat_runtime["database"].Message.created_at.asc())
            .all()
        )
        assert conversation is not None
        assert conversation.owner_user_id == str(user_a.id)
        assert [message.role for message in messages] == ["user", "assistant"]
        assert messages[0].content == "hello stream"
        assert messages[1].content.startswith("reply:hello stream:")
    finally:
        db.close()


def test_03_stream_cannot_cross_user_conversation_boundary(chat_runtime, monkeypatch):
    client = chat_runtime["client"]
    _set_flags(chat_runtime, ownership=True, auth_enabled=True)
    monkeypatch.setattr(chat_runtime["chat_router"], "Brain", _FakeBrain)

    user_a = create_user(chat_runtime, email="stream-owner@example.com", password="StrongPass123!")
    create_user(chat_runtime, email="stream-other@example.com", password="OtherStrong123!")
    seed_conversation(chat_runtime, conversation_id="stream-a1", title="A1", owner_user_id=str(user_a.id))
    seed_message(chat_runtime, conversation_id="stream-a1", role="user", content="existing")

    login(client, email="stream-other@example.com", password="OtherStrong123!")
    response = client.post(
        "/api/chat/stream",
        headers={"x-session-id": "forged-session"},
        json={"message": "cross", "conversation_id": "stream-a1"},
    )
    assert response.status_code == 404
    assert error_code(response) == "CONVERSATION_NOT_FOUND"


def test_04_flag_false_stream_behavior_remains_legacy(chat_runtime, monkeypatch):
    client = chat_runtime["client"]
    _set_flags(chat_runtime, ownership=False, auth_enabled=False)
    monkeypatch.setattr(chat_runtime["chat_router"], "Brain", _FakeBrain)

    response = client.post("/api/chat/stream", json={"message": "legacy stream"})
    assert response.status_code == 200
    events = parse_sse_text(response.text)
    done_event = next(item for item in events if item["type"] == "done")
    conversation_id = done_event["conversation_id"]

    db = chat_runtime["database"].SessionLocal()
    try:
        conversation = db.query(chat_runtime["database"].Conversation).filter_by(id=conversation_id).first()
        messages = db.query(chat_runtime["database"].Message).filter_by(conversation_id=conversation_id).count()
        assert conversation is None
        assert messages == 0
    finally:
        db.close()
