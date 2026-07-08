from __future__ import annotations

pytest_plugins = ["chat_ownership_testkit"]

from chat_ownership_testkit import (
    create_session_token,
    create_user,
    error_code,
    login,
    seed_conversation,
    seed_message,
)


def _set_flags(chat_runtime, *, ownership: bool, auth_enabled: bool = True) -> None:
    chat_runtime["config"].settings.CHAT_USER_OWNERSHIP_ENABLED = ownership
    chat_runtime["config"].settings.AUTH_V1_ENABLED = auth_enabled
    chat_runtime["config"].settings.AUTH_COOKIE_REQUIRED = False


def test_01_feature_flag_default_false(chat_runtime):
    assert chat_runtime["config"].settings.CHAT_USER_OWNERSHIP_ENABLED is False


def test_02_flag_false_legacy_chat_remains_unauthenticated(chat_runtime, monkeypatch):
    client = chat_runtime["client"]
    _set_flags(chat_runtime, ownership=False, auth_enabled=False)
    monkeypatch.setattr(chat_runtime["chat_router"], "think", lambda *_args, **_kwargs: {"answer": "legacy-ok", "evidence": []})

    response = client.post("/api/chat/simple", json={"message": "hello"})
    assert response.status_code == 200
    conversation_id = response.json()["conversation_id"]

    db = chat_runtime["database"].SessionLocal()
    try:
        conversation = db.query(chat_runtime["database"].Conversation).filter_by(id=conversation_id).first()
        assert conversation is not None
        assert conversation.owner_user_id is None
    finally:
        db.close()


def test_03_flag_true_requires_auth_for_conversations_and_simple(chat_runtime, monkeypatch):
    client = chat_runtime["client"]
    _set_flags(chat_runtime, ownership=True, auth_enabled=True)
    monkeypatch.setattr(chat_runtime["chat_router"], "think", lambda *_args, **_kwargs: {"answer": "should-not-run", "evidence": []})

    list_response = client.get("/api/conversations")
    simple_response = client.post("/api/chat/simple", json={"message": "hello"})

    assert list_response.status_code == 401
    assert error_code(list_response) == "AUTH_REQUIRED"
    assert simple_response.status_code == 401
    assert error_code(simple_response) == "AUTH_REQUIRED"


def test_04_flag_true_auth_disabled_fails_safely(chat_runtime, monkeypatch):
    client = chat_runtime["client"]
    _set_flags(chat_runtime, ownership=True, auth_enabled=False)
    monkeypatch.setattr(chat_runtime["chat_router"], "think", lambda *_args, **_kwargs: {"answer": "should-not-run", "evidence": []})

    simple_response = client.post("/api/chat/simple", json={"message": "hello"})
    list_response = client.get("/api/conversations")

    assert simple_response.status_code == 503
    assert error_code(simple_response) == "AUTH_DISABLED"
    assert list_response.status_code == 503
    assert error_code(list_response) == "AUTH_DISABLED"


def test_05_conversation_routes_are_owner_scoped(chat_runtime):
    client = chat_runtime["client"]
    _set_flags(chat_runtime, ownership=True, auth_enabled=True)

    user_a = create_user(chat_runtime, email="chat-a@example.com", password="StrongPass123!", role="admin")
    user_b = create_user(chat_runtime, email="chat-b@example.com", password="OtherStrong123!", role="viewer")

    login(client, email="chat-a@example.com", password="StrongPass123!")
    create_a = client.post("/api/conversations", json={"title": "A1"})
    assert create_a.status_code == 200
    a_id = create_a.json()["id"]

    client.cookies.clear()
    login(client, email="chat-b@example.com", password="OtherStrong123!")
    create_b = client.post("/api/conversations", json={"title": "B1"})
    assert create_b.status_code == 200
    b_id = create_b.json()["id"]

    list_b = client.get("/api/conversations")
    assert list_b.status_code == 200
    assert [item["id"] for item in list_b.json()] == [b_id]

    get_a_from_b = client.get(f"/api/conversations/{a_id}")
    assert get_a_from_b.status_code == 404
    assert error_code(get_a_from_b) == "CONVERSATION_NOT_FOUND"

    update_a_from_b = client.put(f"/api/conversations/{a_id}", json={"title": "hijack"})
    delete_a_from_b = client.delete(f"/api/conversations/{a_id}")
    assert update_a_from_b.status_code == 404
    assert delete_a_from_b.status_code == 404

    client.cookies.clear()
    login(client, email="chat-a@example.com", password="StrongPass123!")
    list_a = client.get("/api/conversations")
    assert list_a.status_code == 200
    assert [item["id"] for item in list_a.json()] == [a_id]

    pin_a = client.put(f"/api/conversations/{a_id}/pin", json={"pinned": True})
    assert pin_a.status_code == 200
    messages_b_from_a = client.get(f"/api/conversations/{b_id}/messages")
    assert messages_b_from_a.status_code == 404

    db = chat_runtime["database"].SessionLocal()
    try:
        a_conv = db.query(chat_runtime["database"].Conversation).filter_by(id=a_id).first()
        b_conv = db.query(chat_runtime["database"].Conversation).filter_by(id=b_id).first()
        assert a_conv.owner_user_id == str(user_a.id)
        assert b_conv.owner_user_id == str(user_b.id)
    finally:
        db.close()


def test_06_simple_chat_enforces_owner_and_ignores_spoofed_fields(chat_runtime, monkeypatch):
    client = chat_runtime["client"]
    _set_flags(chat_runtime, ownership=True, auth_enabled=True)
    monkeypatch.setattr(chat_runtime["chat_router"], "think", lambda *_args, **_kwargs: {"answer": "owned-reply", "evidence": []})

    user_a = create_user(chat_runtime, email="simple-a@example.com", password="StrongPass123!")
    user_b = create_user(chat_runtime, email="simple-b@example.com", password="OtherStrong123!")

    seed_conversation(chat_runtime, conversation_id="conv-b1", title="B1", owner_user_id=str(user_b.id))
    seed_message(chat_runtime, conversation_id="conv-b1", role="user", content="b history")

    login(client, email="simple-a@example.com", password="StrongPass123!")
    create_response = client.post(
        "/api/chat/simple",
        headers={"x-session-id": "forged-b-session"},
        json={
            "message": "hello owned",
            "owner_user_id": str(user_b.id),
            "user_id": str(user_b.id),
            "public_id": "spoof-public",
        },
    )
    assert create_response.status_code == 200
    new_conversation_id = create_response.json()["conversation_id"]

    cross_response = client.post(
        "/api/chat/simple",
        headers={"x-session-id": "forged-b-session"},
        json={"message": "try cross", "conversation_id": "conv-b1"},
    )
    assert cross_response.status_code == 404
    assert error_code(cross_response) == "CONVERSATION_NOT_FOUND"

    list_response = client.get("/api/conversations", headers={"x-session-id": "spoof"})
    assert list_response.status_code == 200
    returned_ids = {item["id"] for item in list_response.json()}
    assert returned_ids == {new_conversation_id}

    db = chat_runtime["database"].SessionLocal()
    try:
        conversation = db.query(chat_runtime["database"].Conversation).filter_by(id=new_conversation_id).first()
        messages = (
            db.query(chat_runtime["database"].Message)
            .filter(chat_runtime["database"].Message.conversation_id == new_conversation_id)
            .order_by(chat_runtime["database"].Message.created_at.asc())
            .all()
        )
        assert conversation.owner_user_id == str(user_a.id)
        assert [message.role for message in messages] == ["user", "assistant"]
        assert [message.content for message in messages] == ["hello owned", "owned-reply"]
    finally:
        db.close()


def test_07_legacy_null_owner_hidden_when_flag_true(chat_runtime):
    client = chat_runtime["client"]
    _set_flags(chat_runtime, ownership=True, auth_enabled=True)
    create_user(chat_runtime, email="legacy-a@example.com", password="StrongPass123!")
    legacy = seed_conversation(chat_runtime, conversation_id="legacy-null", title="Legacy", owner_user_id=None)
    seed_message(chat_runtime, conversation_id=legacy.id, role="user", content="legacy content")

    login(client, email="legacy-a@example.com", password="StrongPass123!")
    list_response = client.get("/api/conversations")
    detail_response = client.get("/api/conversations/legacy-null")
    message_response = client.get("/api/conversations/legacy-null/messages", headers={"x-session-id": "legacy-session"})

    assert list_response.status_code == 200
    assert list_response.json() == []
    assert detail_response.status_code == 404
    assert message_response.status_code == 404

    client.cookies.clear()
    unauth = client.get("/api/conversations/legacy-null/messages", headers={"x-session-id": "legacy-session"})
    assert unauth.status_code == 401
    assert error_code(unauth) == "AUTH_REQUIRED"

    _set_flags(chat_runtime, ownership=False, auth_enabled=False)
    visible_again = client.get("/api/conversations")
    assert visible_again.status_code == 200
    assert [item["id"] for item in visible_again.json()] == ["legacy-null"]


def test_08_logout_all_invalidates_chat(chat_runtime, monkeypatch):
    client = chat_runtime["client"]
    _set_flags(chat_runtime, ownership=True, auth_enabled=True)
    monkeypatch.setattr(chat_runtime["chat_router"], "think", lambda *_args, **_kwargs: {"answer": "ok", "evidence": []})

    user = create_user(chat_runtime, email="logoutall@example.com", password="StrongPass123!")
    token = create_session_token(chat_runtime, user)
    client.cookies.set(chat_runtime["config"].settings.AUTH_COOKIE_NAME, token, path=chat_runtime["config"].settings.AUTH_COOKIE_PATH)

    created = client.post("/api/chat/simple", json={"message": "before logout all"})
    assert created.status_code == 200

    logout_all = client.post("/api/auth/logout-all")
    assert logout_all.status_code == 200

    client.cookies.clear()
    client.cookies.set(chat_runtime["config"].settings.AUTH_COOKIE_NAME, token, path=chat_runtime["config"].settings.AUTH_COOKIE_PATH)
    blocked = client.get("/api/conversations")
    assert blocked.status_code == 401
    assert error_code(blocked) == "SESSION_REVOKED"


def test_09_password_change_invalidates_chat(chat_runtime, monkeypatch):
    client = chat_runtime["client"]
    _set_flags(chat_runtime, ownership=True, auth_enabled=True)
    monkeypatch.setattr(chat_runtime["chat_router"], "think", lambda *_args, **_kwargs: {"answer": "ok", "evidence": []})

    create_user(chat_runtime, email="changepw@example.com", password="OldPassword123!")
    login_response = login(client, email="changepw@example.com", password="OldPassword123!")
    old_cookie = (login_response.headers.get("set-cookie") or "").split(";", 1)[0].split("=", 1)[1]

    changed = client.post(
        "/api/auth/change-password",
        json={
            "current_password": "OldPassword123!",
            "new_password": "NewPassword123!",
            "confirm_password": "NewPassword123!",
        },
    )
    assert changed.status_code == 200

    client.cookies.clear()
    client.cookies.set(chat_runtime["config"].settings.AUTH_COOKIE_NAME, old_cookie, path=chat_runtime["config"].settings.AUTH_COOKIE_PATH)
    blocked = client.get("/api/conversations")
    assert blocked.status_code == 401
    assert error_code(blocked) == "SESSION_REVOKED"
