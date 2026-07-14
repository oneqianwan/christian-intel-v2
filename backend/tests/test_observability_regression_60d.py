from __future__ import annotations

import importlib
import os
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
    test_db_path = tmp_path / f"observability_regression_{uuid.uuid4().hex}.db"
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
                id="org-victory-ph-regression",
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


def test_phase60d_response_contract_fields_are_preserved_with_observability(runtime):
    brain = runtime["brain_module"].Brain()
    ready = brain.think("How can I contact Victory Philippines?", conversation_id=f"ready-{uuid.uuid4().hex}")
    fallback = brain.think("推荐合作对象有哪些？", conversation_id=f"fallback-{uuid.uuid4().hex}")

    ready_contract = ready["response_contract"]
    fallback_contract = fallback["response_contract"]

    assert ready_contract["response_contract_version"] == "6.0D"
    assert ready_contract["payload_type"] in runtime["brain_module"].Brain.RESPONSE_CONTRACT_PAYLOAD_TYPES if hasattr(runtime["brain_module"].Brain, "RESPONSE_CONTRACT_PAYLOAD_TYPES") else {
        "score_snapshot",
        "relationship_graph",
        "contact_intelligence",
        "partnership_recommendation",
        "partnership_action_plan",
        "partnership_evidence_brief",
        "safe_fallback",
        "ask_clarification",
        "unsupported",
        "ambiguous",
    }
    assert ready_contract["source"] in {"database", "database_first", "resolver", "extracted", "fallback", "none"}
    assert ready_contract["policy"]["allow_llm"] is False
    assert ready_contract["policy"]["allow_network"] is False
    assert ready_contract["policy"]["allow_fabrication"] is False
    assert ready_contract["audit"]["no_llm"] is True
    assert ready_contract["audit"]["no_network"] is True
    assert ready_contract["audit"]["no_fabrication"] is True
    assert "observability" in ready_contract
    assert "contact_lookup" in ready

    assert fallback_contract["response_contract_version"] == "6.0D"
    assert fallback_contract["data_found"] is False
    assert fallback_contract["safe_message"]
    assert fallback_contract["observability"]["audit_summary"]["safe_fallback_used"] is True
