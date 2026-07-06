from __future__ import annotations

import importlib
import os
import sys

from pathlib import Path

import pytest


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

MODULES_TO_PURGE = [
    "config",
    "services.auth_service",
]


def _purge_modules() -> None:
    for name in MODULES_TO_PURGE:
        sys.modules.pop(name, None)


@pytest.fixture()
def service():
    os.environ["AUTH_PASSWORD_TIME_COST"] = "1"
    os.environ["AUTH_PASSWORD_MEMORY_COST_KIB"] = "8192"
    os.environ["AUTH_PASSWORD_PARALLELISM"] = "1"
    os.environ["AUTH_PASSWORD_HASH_LEN"] = "16"
    os.environ["AUTH_PASSWORD_SALT_LEN"] = "16"
    _purge_modules()
    auth_service = importlib.import_module("services.auth_service")
    yield auth_service
    _purge_modules()


def test_argon2_hash_and_verify(service):
    pw = "CorrectHorseBatteryStaple!"
    h1 = service.hash_password(pw)
    h2 = service.hash_password(pw)
    assert h1 != h2
    assert service.verify_password(h1, pw) is True
    assert service.verify_password(h1, "wrong") is False


def test_corrupted_hash_fails_safely(service):
    assert service.verify_password("not-a-hash", "pw") is False


def test_needs_rehash(service):
    pw = "pw"
    h = service.hash_password(pw)
    assert service.needs_rehash(h) is False
    config = importlib.import_module("config")
    config.settings.AUTH_PASSWORD_TIME_COST = 2
    assert service.needs_rehash(h) is True


def test_session_token_generation_and_hash(service):
    raw = service.generate_session_token()
    token_hash = service.hash_session_token(raw)
    assert raw
    assert token_hash
    assert raw != token_hash
    assert len(token_hash) == 64
    assert all(ch in "0123456789abcdef" for ch in token_hash)


def test_validate_new_password_rules(service):
    ok = "123456789012"
    service.validate_new_password(ok)

    with pytest.raises(service.AuthError) as exc_short:
        service.validate_new_password("short")
    assert exc_short.value.error_code == "PASSWORD_TOO_SHORT"

    with pytest.raises(service.AuthError) as exc_ws:
        service.validate_new_password(" " * 12)
    assert exc_ws.value.error_code == "PASSWORD_WHITESPACE_ONLY"

    with pytest.raises(service.AuthError) as exc_long:
        service.validate_new_password("x" * 129)
    assert exc_long.value.error_code == "PASSWORD_TOO_LONG"
