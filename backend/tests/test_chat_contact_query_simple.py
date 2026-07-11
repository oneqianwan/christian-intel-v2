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
    test_db_path = tmp_path / f"chat_contact_simple_{uuid.uuid4().hex}.db"
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


def _seed_org(
    runtime,
    *,
    org_id: str,
    name: str,
    official_website: str | None = "https://victory.org.ph",
    contact_email: str | None = "info@victory.org.ph",
    phone_public: str | None = "+63 2 1234 5678",
    facebook_url: str | None = "https://facebook.com/victoryph",
    youtube_url: str | None = "https://youtube.com/@victoryph",
    telegram_username: str | None = "victoryph",
):
    database = runtime["database"]
    db = database.SessionLocal()
    try:
        org = database.OrganizationProfile(
            id=org_id,
            name=name,
            country="Philippines",
            source_name="manual_seed",
            source_url=f"https://{org_id}.example.com/source",
            official_website=official_website,
            contact_email=contact_email,
            phone_public=phone_public,
            facebook_url=facebook_url,
            youtube_url=youtube_url,
            telegram_username=telegram_username,
            confidence=0.82,
        )
        db.add(org)
        db.commit()
        db.refresh(org)
        return org
    finally:
        db.close()


def test_brain_simple_contact_query_returns_database_contacts(isolated_runtime, monkeypatch):
    runtime = isolated_runtime
    brain_module = runtime["brain_module"]
    _seed_org(runtime, org_id="org-victory", name="Victory Philippines")

    monkeypatch.setattr(
        brain_module.Brain,
        "_call_llm",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("_call_llm must not be called")),
    )
    monkeypatch.setattr(
        brain_module.Brain,
        "_call_llm_stream",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("_call_llm_stream must not be called")),
    )
    monkeypatch.setattr(
        socket,
        "create_connection",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("real network must not be used")),
    )

    brain = brain_module.Brain()
    result = brain.think("Victory Philippines 怎么联系？", conversation_id="contact-simple")

    assert result["contact_lookup"]["organization"]["name"] == "Victory Philippines"
    assert result["contact_lookup"]["summary"]["contact_count"] >= 4
    assert "response_contract=contact_lookup" in result["answer"]
    assert "来自数据库记录，不是推测" in result["answer"]
    assert "https://victory.org.ph" in result["answer"]
    assert "info@victory.org.ph" in result["answer"]
    assert "+63 2 1234 5678" in result["answer"]
    assert "https://facebook.com/victoryph" in result["answer"]
    assert "source_url:" in result["answer"]
    assert "source_name:" in result["answer"]
    assert "verification_status: unverified" in result["answer"]
    assert "field_level_source_missing" in result["answer"]
    assert "llm_used=false" in result["answer"]


def test_brain_simple_contact_query_handles_no_contacts_without_fabrication(isolated_runtime, monkeypatch):
    runtime = isolated_runtime
    brain_module = runtime["brain_module"]
    _seed_org(
        runtime,
        org_id="org-victory",
        name="Victory Philippines",
        official_website=None,
        contact_email=None,
        phone_public=None,
        facebook_url=None,
        youtube_url=None,
        telegram_username=None,
    )

    monkeypatch.setattr(
        brain_module.Brain,
        "_call_llm",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("_call_llm must not be called")),
    )
    monkeypatch.setattr(
        socket,
        "create_connection",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("real network must not be used")),
    )

    brain = brain_module.Brain()
    result = brain.think("给我 Victory Philippines 的邮箱", conversation_id="contact-no-contacts")

    assert result["contact_lookup"]["organization"]["name"] == "Victory Philippines"
    assert result["contact_lookup"]["contacts"] == []
    assert "当前数据库没有已记录的公开联系方式" in result["answer"]
    assert "我不会编造联系方式" in result["answer"]
    assert "response_contract=contact_lookup" in result["answer"]


def test_brain_simple_contact_query_handles_org_not_found(isolated_runtime, monkeypatch):
    runtime = isolated_runtime
    brain_module = runtime["brain_module"]

    monkeypatch.setattr(
        brain_module.Brain,
        "_call_llm",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("_call_llm must not be called")),
    )
    monkeypatch.setattr(
        socket,
        "create_connection",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("real network must not be used")),
    )

    brain = brain_module.Brain()
    result = brain.think("How can I contact Unknown Church?", conversation_id="contact-not-found")

    assert result["contact_lookup"]["found"] is False
    assert result["contact_lookup"]["organization"] is None
    assert "status=not_found" in result["answer"]
    assert "response_contract=contact_lookup" in result["answer"]
    assert "我不会编造联系方式" in result["answer"] or "I will not fabricate contact channels." in result["answer"]
