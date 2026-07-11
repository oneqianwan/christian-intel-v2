from __future__ import annotations

import importlib
import os
import socket
import sys
import uuid
from pathlib import Path

import pytest


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


MODULES_TO_PURGE = [
    "config",
    "models",
    "models.database",
    "models.auth",
    "models.watch_alert",
    "services",
    "services.brain",
    "services.query_parser",
    "services.contact_intelligence",
]


def _purge_modules() -> None:
    for module_name in MODULES_TO_PURGE:
        sys.modules.pop(module_name, None)


@pytest.fixture()
def isolated_runtime(tmp_path: Path):
    test_db_path = tmp_path / f"contact_same_contract_{uuid.uuid4().hex}.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{test_db_path.as_posix()}"
    _purge_modules()

    database = importlib.import_module("models.database")
    importlib.import_module("models.auth")
    importlib.import_module("models.watch_alert")
    brain_module = importlib.import_module("services.brain")
    database.init_db()

    yield {
        "database": database,
        "brain_module": brain_module,
        "db_path": test_db_path,
    }

    database.engine.dispose()
    _purge_modules()
    if test_db_path.exists():
        test_db_path.unlink()


def _seed_org(runtime, *, org_id: str, name: str):
    database = runtime["database"]
    db = database.SessionLocal()
    try:
        org = database.OrganizationProfile(
            id=org_id,
            name=name,
            country="Philippines",
            source_name="manual_seed",
            source_url=f"https://{org_id}.example.com/source",
            official_website="https://victory.org.ph",
            contact_email="info@victory.org.ph",
            phone_public="+63 2 1234 5678",
            facebook_url="https://facebook.com/victoryph",
            telegram_username="victoryph",
            confidence=0.82,
        )
        db.add(org)
        db.commit()
        db.refresh(org)
        return org
    finally:
        db.close()


def test_simple_and_stream_contact_query_return_same_contract(isolated_runtime, monkeypatch):
    runtime = isolated_runtime
    brain_module = runtime["brain_module"]
    _seed_org(runtime, org_id="org-victory", name="Victory Philippines")

    monkeypatch.setattr(
        brain_module.Brain,
        "_call_llm",
        lambda *_args, **_kwargs: pytest.fail("_call_llm must not be called"),
    )
    monkeypatch.setattr(
        brain_module.Brain,
        "_call_llm_stream",
        lambda *_args, **_kwargs: pytest.fail("_call_llm_stream must not be called"),
    )
    monkeypatch.setattr(
        socket,
        "create_connection",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("real network must not be used")),
    )

    message = "How can I contact Victory Philippines?"
    brain = brain_module.Brain()
    simple_result = brain.think(message, conversation_id="contact-same-simple")
    stream_chunks = list(brain.think_stream(message, "contact-same-stream"))
    stream_done = next(chunk for chunk in stream_chunks if isinstance(chunk, dict) and chunk.get("type") == "done")

    assert "contact_lookup" in simple_result
    assert "contact_lookup" in stream_done
    assert simple_result["answer"] == stream_done["full_content"]
    assert simple_result["contact_lookup"] == stream_done["contact_lookup"]
    for snippet in [
        "response_contract=contact_lookup",
        "Victory Philippines",
        "https://victory.org.ph",
        "info@victory.org.ph",
        "https://facebook.com/victoryph",
        "verification_status: unverified",
        "llm_used=false",
    ]:
        assert snippet in simple_result["answer"]
        assert snippet in stream_done["full_content"]
    assert "unknown@" not in simple_result["answer"].lower()
    assert "unknown@" not in stream_done["full_content"].lower()
