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
    "services.brain",
    "services.query_parser",
    "services.intent_router_final",
    "services.organization_resolver",
    "services.brain_orchestrator",
    "services.response_contract",
    "services.contact_intelligence",
]


def _purge_modules() -> None:
    for module_name in MODULES_TO_PURGE:
        sys.modules.pop(module_name, None)


@pytest.fixture()
def runtime(tmp_path: Path):
    test_db_path = tmp_path / f"observability_integration_{uuid.uuid4().hex}.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{test_db_path.as_posix()}"
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
                id="org-victory-ph-observability",
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

    yield {"brain_module": brain_module, "database": database}

    database.engine.dispose()
    _purge_modules()
    if test_db_path.exists():
        test_db_path.unlink()


def test_response_contract_contains_observability_and_preserves_old_fields(runtime, monkeypatch):
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
    result = brain.think("How can I contact Victory Philippines?", conversation_id=f"obs-int-{uuid.uuid4().hex}")

    assert "contact_lookup" in result
    contract = result["response_contract"]
    observability = contract["observability"]

    assert "audit_summary" in observability
    assert "trace_events" in observability
    assert contract["trace_id"] == observability["audit_summary"]["trace_id"]
    assert contract["response_id"] == observability["audit_summary"]["response_id"]
    assert contract["payload_type"] == "contact_intelligence"
    assert contract["legacy_payload"]["organization"]["name"] == "Victory Philippines"
    assert result["contact_lookup"]["organization"]["name"] == "Victory Philippines"
