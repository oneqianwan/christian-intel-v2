from __future__ import annotations

import importlib
import os
import sys
import uuid

from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

TEST_DB_PATH = BACKEND_DIR / "data" / "auth_models_test.db"
MODULES_TO_PURGE = [
    "config",
    "models.database",
    "models.auth",
]


def _purge_modules() -> None:
    for module_name in MODULES_TO_PURGE:
        sys.modules.pop(module_name, None)


@pytest.fixture(scope="module")
def runtime():
    TEST_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()

    os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH.as_posix()}"
    _purge_modules()

    database = importlib.import_module("models.database")
    auth = importlib.import_module("models.auth")

    database.Base.metadata.create_all(bind=database.engine, tables=[auth.User.__table__, auth.AuthSession.__table__])

    yield {"database": database, "auth": auth}

    database.engine.dispose()
    _purge_modules()
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()


def test_user_can_create(runtime):
    database = runtime["database"]
    auth = runtime["auth"]

    db = database.SessionLocal()
    try:
        user = auth.User(
            email="User@example.com",
            email_normalized="user@example.com",
            password_hash="hash",
            display_name="User",
            role="viewer",
            status="active",
        )
        db.add(user)
        db.commit()
        assert user.id
        assert user.public_id
    finally:
        db.close()


def test_public_id_unique(runtime):
    database = runtime["database"]
    auth = runtime["auth"]

    public_id = str(uuid.uuid4())

    db = database.SessionLocal()
    try:
        user1 = auth.User(
            public_id=public_id,
            email="a@example.com",
            email_normalized="a@example.com",
            password_hash="hash",
            display_name="A",
        )
        user2 = auth.User(
            public_id=public_id,
            email="b@example.com",
            email_normalized="b@example.com",
            password_hash="hash",
            display_name="B",
        )
        db.add_all([user1, user2])
        with pytest.raises(IntegrityError):
            db.commit()
    finally:
        db.rollback()
        db.close()


def test_email_normalized_unique_case_insensitive(runtime):
    database = runtime["database"]
    auth = runtime["auth"]

    db = database.SessionLocal()
    try:
        user1 = auth.User(
            email="Case@Example.com",
            email_normalized="case@example.com",
            password_hash="hash",
            display_name="Case 1",
        )
        user2 = auth.User(
            email="case@example.com",
            email_normalized="case@example.com",
            password_hash="hash",
            display_name="Case 2",
        )
        db.add(user1)
        db.commit()

        db.add(user2)
        with pytest.raises(IntegrityError):
            db.commit()
    finally:
        db.rollback()
        db.close()


def test_password_hash_required(runtime):
    database = runtime["database"]
    auth = runtime["auth"]

    db = database.SessionLocal()
    try:
        user = auth.User(
            email="nopw@example.com",
            email_normalized="nopw@example.com",
            password_hash=None,
            display_name="NoPW",
        )
        db.add(user)
        with pytest.raises(IntegrityError):
            db.commit()
    finally:
        db.rollback()
        db.close()


def test_role_check_constraint(runtime):
    database = runtime["database"]
    auth = runtime["auth"]

    db = database.SessionLocal()
    try:
        user = auth.User(
            email="role@example.com",
            email_normalized="role@example.com",
            password_hash="hash",
            display_name="Role",
            role="hacker",
        )
        db.add(user)
        with pytest.raises(IntegrityError):
            db.commit()
    finally:
        db.rollback()
        db.close()


def test_status_check_constraint(runtime):
    database = runtime["database"]
    auth = runtime["auth"]

    db = database.SessionLocal()
    try:
        user = auth.User(
            email="status@example.com",
            email_normalized="status@example.com",
            password_hash="hash",
            display_name="Status",
            status="unknown",
        )
        db.add(user)
        with pytest.raises(IntegrityError):
            db.commit()
    finally:
        db.rollback()
        db.close()


def test_auth_session_can_create_and_query_relationship(runtime):
    database = runtime["database"]
    auth = runtime["auth"]

    db = database.SessionLocal()
    try:
        user = auth.User(
            email="sess@example.com",
            email_normalized="sess@example.com",
            password_hash="hash",
            display_name="Sess",
            role="viewer",
            status="active",
        )
        db.add(user)
        db.flush()

        token_hash = "c" * 64
        session = auth.AuthSession(
            user_id=user.id,
            token_hash=token_hash,
            status="active",
            expires_at=datetime.utcnow() + timedelta(days=7),
        )
        db.add(session)
        db.commit()

        loaded = db.query(auth.User).filter(auth.User.id == user.id).one()
        assert len(loaded.auth_sessions) == 1
        assert loaded.auth_sessions[0].token_hash == token_hash

        loaded_session = db.query(auth.AuthSession).filter(auth.AuthSession.id == session.id).one()
        assert loaded_session.user.id == user.id
    finally:
        db.rollback()
        db.close()


def test_auth_session_token_hash_unique(runtime):
    database = runtime["database"]
    auth = runtime["auth"]

    db = database.SessionLocal()
    try:
        user = auth.User(
            email="uniq@example.com",
            email_normalized="uniq@example.com",
            password_hash="hash",
            display_name="Uniq",
        )
        db.add(user)
        db.flush()

        token_hash = "d" * 64
        s1 = auth.AuthSession(user_id=user.id, token_hash=token_hash, expires_at=datetime.utcnow() + timedelta(days=1))
        s2 = auth.AuthSession(user_id=user.id, token_hash=token_hash, expires_at=datetime.utcnow() + timedelta(days=1))
        db.add_all([s1, s2])
        with pytest.raises(IntegrityError):
            db.commit()
    finally:
        db.rollback()
        db.close()


def test_no_raw_token_columns(runtime):
    database = runtime["database"]

    from sqlalchemy import inspect

    inspector = inspect(database.engine)
    cols = {col["name"] for col in inspector.get_columns("auth_sessions")} | {col["name"] for col in inspector.get_columns("users")}
    forbidden = [name for name in sorted(cols) if "raw_token" in name or "session_token" in name or "cookie_token" in name]
    assert forbidden == []
