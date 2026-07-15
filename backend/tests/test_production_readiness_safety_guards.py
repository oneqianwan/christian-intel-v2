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
    test_db_path = tmp_path / f"production_readiness_safety_{uuid.uuid4().hex}.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{test_db_path.as_posix()}")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")
    _purge_modules()

    database = importlib.import_module("models.database")
    importlib.import_module("models.auth")
    importlib.import_module("models.watch_alert")
    brain_module = importlib.import_module("services.brain")
    readiness_module = importlib.import_module("services.production_readiness")
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
        db.add(
            database.OrganizationProfile(
                id="org-victory-church",
                name="Victory Church",
                country="Philippines",
                city="Quezon City",
                denomination="Evangelical",
                source_name="unit_test_seed",
                source_url="https://victory-church.example/source",
            )
        )
        db.commit()
    finally:
        db.close()

    yield {
        "database": database,
        "brain_module": brain_module,
        "readiness_module": readiness_module,
    }

    database.engine.dispose()
    _purge_modules()
    if test_db_path.exists():
        test_db_path.unlink()


def _block_llm_and_network(monkeypatch, brain_module):
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


def test_safety_guards_hold_for_ready_and_safe_fallback_paths(runtime, monkeypatch):
    brain_module = runtime["brain_module"]
    _block_llm_and_network(monkeypatch, brain_module)

    brain = brain_module.Brain()
    ready = brain.think("Victory Philippines 怎么联系？", conversation_id=f"ready-{uuid.uuid4().hex}")["response_contract"]
    missing_org = brain.think("推荐合作对象有哪些？", conversation_id=f"missing-{uuid.uuid4().hex}")["response_contract"]
    context_ref = brain.think("这个机构怎么联系？", conversation_id=f"context-{uuid.uuid4().hex}")["response_contract"]
    unsupported = brain.think("随便帮我看看", conversation_id=f"unsupported-{uuid.uuid4().hex}")["response_contract"]

    for contract in (ready, missing_org, context_ref, unsupported):
        assert contract["source"] != "llm"
        assert contract["payload_type"] in {
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
        assert contract["selected_module"] in {
            "score_lookup",
            "relationship_graph",
            "contact_intelligence",
            "partnership_recommender",
            "partnership_action_planner",
            "partnership_evidence_brief",
            "general_chat",
            None,
        }
        assert contract["policy"]["allow_llm"] is False
        assert contract["policy"]["allow_network"] is False
        assert contract["policy"]["allow_fabrication"] is False

    assert ready["route_status"] == "ready"
    assert missing_org["route_status"] == "ask_clarification"
    assert "organization_name" in missing_org["missing_parameters"]
    assert context_ref["fallback_reason"] == "context_reference_requires_previous_organization"
    assert unsupported["route_status"] in {"unsupported", "ask_clarification"}


def test_ambiguous_org_does_not_force_selection_and_redaction_is_enabled(runtime, monkeypatch):
    brain_module = runtime["brain_module"]

    def fake_decision(_self, _message, _conversation_id):
        return {
            "query": "Victory 怎么联系？",
            "normalized_query": "victory 怎么联系",
            "route_status": "ambiguous",
            "selected_intent": "organization_contact_lookup",
            "selected_module": "contact_intelligence",
            "organization_name": None,
            "target_organization_name": None,
            "missing_parameters": ["organization_name"],
            "candidate_intents": [{"intent": "organization_contact_lookup"}],
            "candidate_organizations": [
                {"name": "Victory Philippines", "canonical_name": "Victory Philippines", "organization_id": None},
                {"name": "Victory Church", "canonical_name": "Victory Church", "organization_id": None},
            ],
            "requires_clarification": True,
            "clarification_prompt": "我找到了多个可能机构，请选择。",
            "warnings": ["multiple_organization_candidates"],
            "reason_codes": ["multiple_organization_candidates_detected"],
            "policy": {
                "db_first": True,
                "allow_llm": False,
                "allow_network": False,
                "allow_fabrication": False,
            },
            "dispatch": {
                "module": "contact_intelligence",
                "method": None,
                "payload_type": "contact_intelligence",
                "required_parameters": ["organization_name"],
                "optional_parameters": [],
            },
            "intent_result": {"confidence": 0.76},
            "organization_resolution": {
                "organization_name": None,
                "canonical_name": None,
                "organization_id": None,
                "resolution_status": "ambiguous",
                "confidence": 0.76,
                "context_reference": False,
            },
            "target_organization_resolution": {
                "target_organization_name": None,
                "target_organization_id": None,
                "target_canonical_name": None,
                "target_candidates": [],
            },
            "trace": [
                {"step": "intent_router", "status": "pass", "reason_codes": ["contact_keyword_detected"]},
                {"step": "organization_resolver", "status": "blocked", "reason_codes": ["multiple_organization_candidates_detected"]},
                {"step": "policy_guard", "status": "pass", "reason_codes": ["llm_disabled"]},
                {"step": "module_dispatcher", "status": "blocked", "reason_codes": ["route_status_ambiguous"]},
                {"step": "final_route_decision", "status": "blocked", "reason_codes": ["route_status_ambiguous"]},
            ],
        }

    monkeypatch.setattr(brain_module.Brain, "_get_orchestration_decision", fake_decision)
    monkeypatch.setattr(
        brain_module.Brain,
        "_run_orchestrated_lookup",
        lambda *_args, **_kwargs: pytest.fail("_run_orchestrated_lookup must not be called"),
    )

    brain = brain_module.Brain()
    contract = brain.think("Victory 怎么联系？", conversation_id=f"ambiguous-{uuid.uuid4().hex}")["response_contract"]
    report = runtime["readiness_module"].ProductionReadinessChecker().build_report(contracts=[contract])

    assert contract["route_status"] == "ambiguous"
    assert contract["organization"]["organization_id"] is None
    assert report["safety"]["redaction_enabled"] is True
