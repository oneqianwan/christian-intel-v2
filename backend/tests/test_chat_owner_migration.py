from __future__ import annotations

import importlib
import os
import subprocess
import sys

from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = BACKEND_DIR.parent
SCRIPT_PATH = BACKEND_DIR / "scripts" / "migrate_legacy_chat_owner.py"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

MODULES_TO_PURGE = [
    "config",
    "models.database",
    "models.auth",
    "services.auth_service",
]


def _purge_modules() -> None:
    for module_name in MODULES_TO_PURGE:
        sys.modules.pop(module_name, None)


def _bootstrap_runtime(db_path: Path):
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"
    _purge_modules()
    config = importlib.import_module("config")
    database = importlib.import_module("models.database")
    auth_models = importlib.import_module("models.auth")
    auth_service = importlib.import_module("services.auth_service")
    database.init_db()
    return config, database, auth_models, auth_service


def _seed_user(database, auth_models, auth_service, *, email: str, password: str, status: str = "active"):
    session = database.SessionLocal()
    try:
        user = auth_models.User(
            email=email,
            email_normalized=email.strip().lower(),
            password_hash=auth_service.hash_password(password),
            display_name=email.split("@", 1)[0],
            role="analyst",
            status=status,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        return user
    finally:
        session.close()


def _seed_conversation(database, *, conversation_id: str, owner_user_id: str | None = None):
    session = database.SessionLocal()
    try:
        conversation = database.Conversation(
            id=conversation_id,
            title=conversation_id,
            owner_user_id=owner_user_id,
        )
        session.add(conversation)
        session.commit()
        session.refresh(conversation)

        message = database.Message(
            id=f"msg-{conversation_id}",
            conversation_id=conversation_id,
            role="user",
            content=f"content-{conversation_id}",
            sources=[],
        )
        session.add(message)
        session.commit()
        session.refresh(message)
        return conversation.id, message.id
    finally:
        session.close()


def _state(database, auth_models, *, conversation_id: str):
    session = database.SessionLocal()
    try:
        conversation = session.query(database.Conversation).filter_by(id=conversation_id).first()
        messages = session.query(database.Message).filter_by(conversation_id=conversation_id).count()
        users = session.query(auth_models.User).count()
        auth_sessions = session.query(auth_models.AuthSession).count()
        return {
            "owner_user_id": None if conversation is None else conversation.owner_user_id,
            "message_count": messages,
            "user_count": users,
            "auth_session_count": auth_sessions,
        }
    finally:
        session.close()


def _run_cli(db_path: Path, *args: str):
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--database",
            str(db_path),
            *args,
        ],
        cwd=str(REPO_DIR),
        capture_output=True,
        text=True,
    )


def test_01_dry_run_does_not_write(tmp_path):
    db_path = tmp_path / "chat_owner_dry_run.db"
    _, database, auth_models, auth_service = _bootstrap_runtime(db_path)
    _seed_user(database, auth_models, auth_service, email="target@example.com", password="StrongPass123!")
    _seed_conversation(database, conversation_id="legacy-a", owner_user_id=None)
    before = _state(database, auth_models, conversation_id="legacy-a")

    result = _run_cli(
        db_path,
        "--email",
        "target@example.com",
        "--legacy-conversation-id",
        "legacy-a",
        "--dry-run",
    )

    after = _state(database, auth_models, conversation_id="legacy-a")
    database.engine.dispose()

    assert result.returncode == 0, result.stdout + result.stderr
    assert "MODE=dry-run" in result.stdout
    assert "CONVERSATIONS matched=1 updated=1 skipped=0 conflicts=0" in result.stdout
    assert before == after


def test_02_apply_sets_conversation_owner_and_leaves_messages_linked(tmp_path):
    db_path = tmp_path / "chat_owner_apply.db"
    _, database, auth_models, auth_service = _bootstrap_runtime(db_path)
    user = _seed_user(database, auth_models, auth_service, email="target@example.com", password="StrongPass123!")
    _seed_conversation(database, conversation_id="legacy-a", owner_user_id=None)

    result = _run_cli(
        db_path,
        "--email",
        "target@example.com",
        "--legacy-conversation-id",
        "legacy-a",
        "--apply",
    )
    state = _state(database, auth_models, conversation_id="legacy-a")
    database.engine.dispose()

    assert result.returncode == 0, result.stdout + result.stderr
    assert "CONSISTENCY_CHECK=PASS" in result.stdout
    assert state["owner_user_id"] == str(user.id)
    assert state["message_count"] == 1


def test_03_apply_is_idempotent(tmp_path):
    db_path = tmp_path / "chat_owner_idempotent.db"
    _, database, auth_models, auth_service = _bootstrap_runtime(db_path)
    user = _seed_user(database, auth_models, auth_service, email="target@example.com", password="StrongPass123!")
    _seed_conversation(database, conversation_id="legacy-a", owner_user_id=str(user.id))

    result = _run_cli(
        db_path,
        "--email",
        "target@example.com",
        "--legacy-conversation-id",
        "legacy-a",
        "--apply",
    )
    state = _state(database, auth_models, conversation_id="legacy-a")
    database.engine.dispose()

    assert result.returncode == 0, result.stdout + result.stderr
    assert "CONVERSATIONS matched=1 updated=0 skipped=1 conflicts=0" in result.stdout
    assert state["owner_user_id"] == str(user.id)


def test_04_missing_user_fails(tmp_path):
    db_path = tmp_path / "chat_owner_missing_user.db"
    _, database, auth_models, auth_service = _bootstrap_runtime(db_path)
    _seed_conversation(database, conversation_id="legacy-a", owner_user_id=None)

    result = _run_cli(
        db_path,
        "--email",
        "missing@example.com",
        "--legacy-conversation-id",
        "legacy-a",
        "--apply",
    )
    database.engine.dispose()

    assert result.returncode == 1
    assert "ERROR=USER_NOT_FOUND" in result.stdout


def test_05_disabled_user_fails(tmp_path):
    db_path = tmp_path / "chat_owner_disabled_user.db"
    _, database, auth_models, auth_service = _bootstrap_runtime(db_path)
    _seed_user(database, auth_models, auth_service, email="disabled@example.com", password="StrongPass123!", status="disabled")
    _seed_conversation(database, conversation_id="legacy-a", owner_user_id=None)

    result = _run_cli(
        db_path,
        "--email",
        "disabled@example.com",
        "--legacy-conversation-id",
        "legacy-a",
        "--apply",
    )
    database.engine.dispose()

    assert result.returncode == 1
    assert "ERROR=USER_NOT_ACTIVE" in result.stdout


def test_06_missing_conversation_returns_safe_zero(tmp_path):
    db_path = tmp_path / "chat_owner_missing_conversation.db"
    _, database, auth_models, auth_service = _bootstrap_runtime(db_path)
    _seed_user(database, auth_models, auth_service, email="target@example.com", password="StrongPass123!")

    result = _run_cli(
        db_path,
        "--email",
        "target@example.com",
        "--legacy-conversation-id",
        "missing-conv",
        "--apply",
    )
    database.engine.dispose()

    assert result.returncode == 0
    assert "CONVERSATIONS matched=0 updated=0 skipped=0 conflicts=0" in result.stdout


def test_07_other_owner_not_overwritten_and_auth_session_unchanged(tmp_path):
    db_path = tmp_path / "chat_owner_conflict.db"
    _, database, auth_models, auth_service = _bootstrap_runtime(db_path)
    target = _seed_user(database, auth_models, auth_service, email="target@example.com", password="StrongPass123!")
    other = _seed_user(database, auth_models, auth_service, email="other@example.com", password="OtherStrong123!")
    _seed_conversation(database, conversation_id="legacy-a", owner_user_id=str(other.id))
    before = _state(database, auth_models, conversation_id="legacy-a")

    result = _run_cli(
        db_path,
        "--email",
        "target@example.com",
        "--legacy-conversation-id",
        "legacy-a",
        "--apply",
    )
    after = _state(database, auth_models, conversation_id="legacy-a")
    database.engine.dispose()

    assert result.returncode == 0
    assert "CONVERSATIONS matched=1 updated=0 skipped=0 conflicts=1" in result.stdout
    assert before["owner_user_id"] == after["owner_user_id"] == str(other.id)
    assert before["user_count"] == after["user_count"]
    assert before["auth_session_count"] == after["auth_session_count"]
    assert str(target.id) not in result.stdout
