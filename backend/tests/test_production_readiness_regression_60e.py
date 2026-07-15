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
    "services.audit_trail",
    "services.observability",
    "services.production_readiness",
    "services.brain",
    "services.query_parser",
    "services.intent_router_final",
    "services.organization_resolver",
    "services.brain_orchestrator",
    "services.response_contract",
]


def _purge_modules() -> None:
    for module_name in MODULES_TO_PURGE:
        sys.modules.pop(module_name, None)


@pytest.fixture()
def runtime(tmp_path: Path, monkeypatch):
    test_db_path = tmp_path / f"production_readiness_regression_{uuid.uuid4().hex}.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{test_db_path.as_posix()}")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")
    _purge_modules()

    database = importlib.import_module("models.database")
    importlib.import_module("models.auth")
    importlib.import_module("models.watch_alert")
    brain_module = importlib.import_module("services.brain")
    database.init_db()

    db = database.SessionLocal()
    try:
        db.add(
            database.OrganizationProfile(
                id="org-victory",
                name="Victory Philippines",
                country="Philippines",
                city="Manila",
                denomination="Evangelical",
                official_website="https://victory.org.ph",
                contact_email="info@victory.org.ph",
                phone_public="+63 2 1234 5678",
                source_url="https://victory.org.ph/source",
                source_name="unit_test_seed",
                people_score=64,
                digital_score=58,
                intel_score=67,
            )
        )
        db.commit()
    finally:
        db.close()

    yield {"database": database, "brain_module": brain_module}

    database.engine.dispose()
    _purge_modules()
    if test_db_path.exists():
        test_db_path.unlink()


def test_phase60e_contract_and_observability_are_preserved(runtime, monkeypatch):
    brain_module = runtime["brain_module"]
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

    brain = brain_module.Brain()
    simple_contract = brain.think("Victory Philippines 怎么联系？", conversation_id=f"simple-{uuid.uuid4().hex}")["response_contract"]
    stream_done = next(
        item
        for item in brain.think_stream("Victory Philippines 怎么联系？", f"stream-{uuid.uuid4().hex}")
        if isinstance(item, dict) and item.get("type") == "done"
    )
    stream_contract = stream_done["response_contract"]

    for contract in (simple_contract, stream_contract):
        assert contract["response_contract_version"] == "6.0D"
        assert contract["observability"]["audit_summary"]["audit_version"] == "6.0E"
        assert contract["observability"]["trace_events"]
        assert contract["observability"]["audit_summary"]
        assert contract["observability"]["audit_summary"]["query_redacted"]

    assert simple_contract["payload_type"] == stream_contract["payload_type"]
    assert simple_contract["route_status"] == stream_contract["route_status"]
    assert simple_contract["selected_module"] == stream_contract["selected_module"]
