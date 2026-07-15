from __future__ import annotations

import uuid

import pytest

from test_auth_api import _reset_auth_settings, runtime


_RUNTIME_CONFIG = None
_RUNTIME_MAIN = None


@pytest.fixture(autouse=True)
def reset_db(runtime):
    global _RUNTIME_CONFIG, _RUNTIME_MAIN
    database = runtime["database"]
    auth_models = runtime["auth_models"]
    client = runtime["client"]
    auth_service = runtime["auth_service"]
    _RUNTIME_CONFIG = runtime["config"]
    _RUNTIME_MAIN = runtime["main"]

    db = database.SessionLocal()
    try:
        db.execute(database.text("DELETE FROM bookmarks"))
        db.execute(database.text("DELETE FROM user_feedbacks"))
        db.execute(database.text("DELETE FROM intelligence_items"))
        db.execute(database.text("DELETE FROM pages"))
        db.execute(database.text("DELETE FROM sources"))
        db.query(auth_models.AuthSession).delete()
        db.query(auth_models.User).delete()
        db.commit()
    finally:
        db.close()

    client.cookies.clear()
    limiter = getattr(auth_service, "_default_rate_limiter", None)
    if limiter is not None:
        lock = getattr(limiter, "_lock", None)
        attempts = getattr(limiter, "_attempts", None)
        if lock is not None and attempts is not None:
            with lock:
                attempts.clear()
    _reset_auth_settings(runtime)


def _error_code(response) -> str | None:
    payload = response.json()
    detail = payload.get("detail")
    if isinstance(detail, dict):
        return detail.get("error_code")
    return payload.get("error_code")


def _set_auth_enabled(enabled: bool) -> None:
    value = bool(enabled)
    if _RUNTIME_CONFIG is not None:
        _RUNTIME_CONFIG.settings.AUTH_V1_ENABLED = value
    import sys

    config_module = sys.modules.get("config")
    if config_module is not None:
        config_module.settings.AUTH_V1_ENABLED = value
    auth_dependencies = sys.modules.get("dependencies.auth")
    if auth_dependencies is not None:
        auth_dependencies.config.settings.AUTH_V1_ENABLED = value
    if _RUNTIME_MAIN is not None:
        visited: set[int] = set()

        def _sync_dependant(dependant) -> None:
            for dependency in getattr(dependant, "dependencies", []):
                _sync_dependant(dependency)
            call = getattr(dependant, "call", None)
            if call is None or id(call) in visited:
                return
            visited.add(id(call))
            globals_dict = getattr(call, "__globals__", {})
            config_module = globals_dict.get("config")
            settings = getattr(config_module, "settings", None)
            if settings is not None and hasattr(settings, "AUTH_V1_ENABLED"):
                settings.AUTH_V1_ENABLED = value

        for route in getattr(_RUNTIME_MAIN.app, "routes", []):
            dependant = getattr(route, "dependant", None)
            if dependant is not None:
                _sync_dependant(dependant)


def _create_user(runtime, *, email: str, password: str, role: str = "viewer", status: str = "active"):
    database = runtime["database"]
    auth_models = runtime["auth_models"]
    auth_service = runtime["auth_service"]
    db = database.SessionLocal()
    try:
        user = auth_models.User(
            email=email,
            email_normalized=auth_service.normalize_email(email),
            password_hash=auth_service.hash_password(password),
            display_name="User",
            role=role,
            status=status,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    finally:
        db.close()


def _login(client, *, email: str, password: str) -> None:
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200


def _seed_item(runtime, *, item_id: str = "item-1", title: str = "Intel 1"):
    database = runtime["database"]
    db = database.SessionLocal()
    try:
        source = database.Source(
            id=f"source-{uuid.uuid4().hex}",
            name="Source",
            url="https://source.example.com",
            type="rss",
            country="PH",
        )
        db.add(source)
        page = database.Page(
            id=f"page-{uuid.uuid4().hex}",
            source_id=source.id,
            url="https://source.example.com/page",
            title="Page",
        )
        db.add(page)
        item = database.IntelligenceItem(
            id=item_id,
            page_id=page.id,
            source_id=source.id,
            title=title,
            source_name="Source",
            source_url="https://source.example.com/page",
            country="PH",
            entity_name="Org",
            entity_type="organization",
            category="news",
        )
        db.add(item)
        db.commit()
        return item
    finally:
        db.close()


def test_01_feedback_auth_mode_ignores_x_session_id_and_binds_current_user(runtime):
    client = runtime["client"]
    database = runtime["database"]
    _set_auth_enabled(True)
    user = _create_user(runtime, email="viewer@example.com", password="Password123456!")

    _login(client, email="viewer@example.com", password="Password123456!")
    response = client.post(
        "/api/feedback",
        headers={"x-session-id": "forged-session"},
        json={"feedback_type": "match_useful", "content": "useful"},
    )

    assert response.status_code == 200

    db = database.SessionLocal()
    try:
        record = db.query(database.UserFeedback).one()
        assert record.user_id == str(user.id)
        assert record.session_id == f"user:{user.id}"
        assert record.session_id != "forged-session"
        assert record.session_id != "session-1"
    finally:
        db.close()


def test_02_feedback_auth_mode_unauthenticated_returns_401(runtime):
    client = runtime["client"]
    _set_auth_enabled(True)

    response = client.post("/api/feedback", json={"feedback_type": "match_useful"})

    assert response.status_code == 401
    assert _error_code(response) == "AUTH_REQUIRED"


def test_03_feedback_auth_disabled_fails_closed(runtime):
    client = runtime["client"]
    _set_auth_enabled(False)

    response = client.post(
        "/api/feedback",
        headers={"x-session-id": "legacy-123"},
        json={"feedback_type": "match_not_useful", "content": "legacy"},
    )

    assert response.status_code == 503
    assert _error_code(response) == "AUTH_DISABLED"


def test_04_feedback_auth_disabled_without_header_fails_closed(runtime):
    client = runtime["client"]
    _set_auth_enabled(False)

    response = client.post("/api/feedback", json={"feedback_type": "match_useful"})

    assert response.status_code == 503
    assert _error_code(response) == "AUTH_DISABLED"


def test_05_bookmarks_auth_mode_uses_current_user_not_default(runtime):
    client = runtime["client"]
    database = runtime["database"]
    _set_auth_enabled(True)
    user = _create_user(runtime, email="user@example.com", password="Password123456!")
    _seed_item(runtime, item_id="item-a")

    _login(client, email="user@example.com", password="Password123456!")
    response = client.post("/api/bookmarks", params={"item_id": "item-a", "note": "mine"}, headers={"x-session-id": "forged"})

    assert response.status_code == 200
    assert response.json()["status"] == "created"

    db = database.SessionLocal()
    try:
        bookmark = db.query(database.Bookmark).one()
        assert bookmark.user_id == str(user.id)
        assert bookmark.user_id != "default"
    finally:
        db.close()


def test_06_bookmarks_auth_mode_isolates_users_and_prevents_cross_delete(runtime):
    client = runtime["client"]
    database = runtime["database"]
    _set_auth_enabled(True)
    user_a = _create_user(runtime, email="a@example.com", password="Password123456!")
    user_b = _create_user(runtime, email="b@example.com", password="Password123456!")
    _seed_item(runtime, item_id="item-a", title="Intel A")
    _seed_item(runtime, item_id="item-b", title="Intel B")

    _login(client, email="a@example.com", password="Password123456!")
    create_a = client.post("/api/bookmarks", params={"item_id": "item-a", "note": "A"})
    assert create_a.status_code == 200
    list_a = client.get("/api/bookmarks")
    assert len(list_a.json()) == 1
    bookmark_a_id = list_a.json()[0]["bookmark_id"]

    client.post("/api/auth/logout")
    _login(client, email="b@example.com", password="Password123456!")
    create_b = client.post("/api/bookmarks", params={"item_id": "item-b", "note": "B"})
    assert create_b.status_code == 200
    list_b = client.get("/api/bookmarks")
    assert len(list_b.json()) == 1
    assert list_b.json()[0]["item_id"] == "item-b"

    delete_a_from_b = client.delete(f"/api/bookmarks/{bookmark_a_id}")
    assert delete_a_from_b.status_code == 200
    assert delete_a_from_b.json()["status"] == "not_found"

    db = database.SessionLocal()
    try:
        remaining_a = db.query(database.Bookmark).filter(database.Bookmark.user_id == str(user_a.id)).count()
        remaining_b = db.query(database.Bookmark).filter(database.Bookmark.user_id == str(user_b.id)).count()
        assert remaining_a == 1
        assert remaining_b == 1
    finally:
        db.close()


def test_07_bookmarks_auth_mode_unauthenticated_returns_401(runtime):
    client = runtime["client"]
    _set_auth_enabled(True)
    _seed_item(runtime, item_id="item-a")

    post_response = client.post("/api/bookmarks", params={"item_id": "item-a"})
    list_response = client.get("/api/bookmarks")

    assert post_response.status_code == 401
    assert _error_code(post_response) == "AUTH_REQUIRED"
    assert list_response.status_code == 401
    assert _error_code(list_response) == "AUTH_REQUIRED"


def test_08_bookmarks_auth_disabled_fails_closed(runtime):
    client = runtime["client"]
    _set_auth_enabled(False)
    _seed_item(runtime, item_id="item-legacy")

    create_response = client.post("/api/bookmarks", params={"item_id": "item-legacy", "note": "legacy"})
    list_response = client.get("/api/bookmarks")

    assert create_response.status_code == 503
    assert _error_code(create_response) == "AUTH_DISABLED"
    assert list_response.status_code == 503
    assert _error_code(list_response) == "AUTH_DISABLED"
