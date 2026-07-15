from __future__ import annotations

import importlib
import json
import os
import sys
import uuid

from pathlib import Path

import pytest
from fastapi.testclient import TestClient


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

TEST_DB_DIR = BACKEND_DIR / "data"
MODULES_TO_PURGE = [
    "config",
    "main",
    "models",
    "models.database",
    "models.auth",
    "models.schemas",
    "routers",
    "routers.auth",
    "routers.chat",
    "routers.conversations",
    "dependencies",
    "dependencies.auth",
    "dependencies.chat_auth",
    "services",
    "services.auth_service",
    "services.brain",
    "services.brain_planner",
    "services.chat_ownership",
]


def _purge_modules() -> None:
    for module_name in MODULES_TO_PURGE:
        sys.modules.pop(module_name, None)


def _set_flags(
    runtime,
    *,
    chat_ownership: bool = False,
    auth_enabled: bool = True,
) -> None:
    config = runtime["config"]
    config.settings.CHAT_USER_OWNERSHIP_ENABLED = chat_ownership
    config.settings.AUTH_V1_ENABLED = auth_enabled
    config.settings.AUTH_COOKIE_REQUIRED = False
    config.settings.ALLOW_PUBLIC_CORE_APIS = (not chat_ownership) and (not auth_enabled)


@pytest.fixture(scope="module")
def chat_runtime():
    TEST_DB_DIR.mkdir(parents=True, exist_ok=True)
    test_db_path = TEST_DB_DIR / f"chat_phase54a_ownership_test_{uuid.uuid4().hex}.db"

    os.environ["DATABASE_URL"] = f"sqlite:///{test_db_path.as_posix()}"
    _purge_modules()

    config = importlib.import_module("config")
    database = importlib.import_module("models.database")
    auth_models = importlib.import_module("models.auth")
    auth_service = importlib.import_module("services.auth_service")
    chat_router = importlib.import_module("routers.chat")
    main = importlib.import_module("main")

    database.init_db()

    client_ctx = TestClient(main.app)
    client = client_ctx.__enter__()
    yield {
        "config": config,
        "database": database,
        "auth_models": auth_models,
        "auth_service": auth_service,
        "chat_router": chat_router,
        "app": main.app,
        "client": client,
    }
    client_ctx.__exit__(None, None, None)
    database.engine.dispose()
    _purge_modules()
    if test_db_path.exists():
        test_db_path.unlink()


@pytest.fixture(autouse=True)
def reset_chat_runtime(chat_runtime):
    _set_flags(chat_runtime, chat_ownership=True, auth_enabled=True)
    chat_runtime["client"].cookies.clear()

    limiter = getattr(chat_runtime["auth_service"], "_default_rate_limiter", None)
    if limiter is not None and hasattr(limiter, "_attempts"):
        limiter._attempts.clear()

    database = chat_runtime["database"]
    auth_models = chat_runtime["auth_models"]
    session = database.SessionLocal()
    try:
        session.query(database.RequestTrace).delete()
        session.query(database.Message).delete()
        session.query(database.Conversation).delete()
        session.query(database.UserProfile).delete()
        session.query(auth_models.AuthSession).delete()
        session.query(auth_models.User).delete()
        session.commit()
    finally:
        session.close()
    yield


def session(chat_runtime):
    return chat_runtime["database"].SessionLocal()


def create_user(chat_runtime, *, email: str, password: str, role: str = "analyst", status: str = "active"):
    db = session(chat_runtime)
    try:
        user = chat_runtime["auth_models"].User(
            email=email,
            email_normalized=email.strip().lower(),
            password_hash=chat_runtime["auth_service"].hash_password(password),
            display_name=email.split("@", 1)[0],
            role=role,
            status=status,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    finally:
        db.close()


def login(client: TestClient, *, email: str, password: str):
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response


def create_session_token(chat_runtime, user):
    db = session(chat_runtime)
    try:
        _, token = chat_runtime["auth_service"].create_auth_session(db, user=user)
        return token
    finally:
        db.close()


def error_code(response) -> str | None:
    payload = response.json()
    detail = payload.get("detail")
    if isinstance(detail, dict):
        return detail.get("error_code")
    return payload.get("error_code")


def seed_conversation(chat_runtime, *, conversation_id: str, title: str = "Seed", owner_user_id: str | None = None):
    db = session(chat_runtime)
    try:
        conversation = chat_runtime["database"].Conversation(
            id=conversation_id,
            title=title,
            owner_user_id=owner_user_id,
        )
        db.add(conversation)
        db.commit()
        db.refresh(conversation)
        return conversation
    finally:
        db.close()


def seed_message(chat_runtime, *, conversation_id: str, role: str, content: str):
    db = session(chat_runtime)
    try:
        message = chat_runtime["database"].Message(
            id=f"msg-{conversation_id}-{role}-{abs(hash(content))}",
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


def parse_sse_text(raw_text: str) -> list[dict]:
    events: list[dict] = []
    for chunk in raw_text.split("\n\n"):
        chunk = chunk.strip()
        if not chunk or chunk == "data: [DONE]":
            continue
        if not chunk.startswith("data: "):
            continue
        payload = chunk[len("data: ") :]
        events.append(json.loads(payload))
    return events
