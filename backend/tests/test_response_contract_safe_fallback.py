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
    "services.intent_router_final",
    "services.organization_resolver",
    "services.brain_orchestrator",
    "services.response_contract",
]


def _purge_modules() -> None:
    for module_name in MODULES_TO_PURGE:
        sys.modules.pop(module_name, None)


@pytest.fixture()
def runtime(tmp_path: Path):
    test_db_path = tmp_path / f"response_contract_fallback_{uuid.uuid4().hex}.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{test_db_path.as_posix()}"
    _purge_modules()

    database = importlib.import_module("models.database")
    importlib.import_module("models.auth")
    importlib.import_module("models.watch_alert")
    brain_module = importlib.import_module("services.brain")
    database.init_db()

    yield {"database": database, "brain_module": brain_module}

    database.engine.dispose()
    _purge_modules()
    if test_db_path.exists():
        test_db_path.unlink()


def test_missing_org_context_reference_and_unsupported_are_safe(runtime, monkeypatch):
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
    missing_org = brain.think("推荐合作对象有哪些？", conversation_id=f"missing-{uuid.uuid4().hex}")["response_contract"]
    context_ref = brain.think("这个机构怎么联系？", conversation_id=f"context-{uuid.uuid4().hex}")["response_contract"]
    unsupported = brain.think("随便帮我看看", conversation_id=f"unsupported-{uuid.uuid4().hex}")["response_contract"]

    assert missing_org["route_status"] == "ask_clarification"
    assert missing_org["data_found"] is False
    assert missing_org["safe_message"]
    assert "organization_name" in missing_org["missing_parameters"]
    assert missing_org["policy"]["allow_llm"] is False
    assert missing_org["audit"]["no_llm"] is True

    assert context_ref["route_status"] == "ask_clarification"
    assert context_ref["data_found"] is False
    assert context_ref["fallback_reason"] == "context_reference_requires_previous_organization"
    assert context_ref["organization"]["organization_id"] is None

    assert unsupported["route_status"] in {"unsupported", "ask_clarification"}
    assert unsupported["data_found"] is False
    assert unsupported["safe_message"]
    assert unsupported["source"] == "fallback"


def test_ambiguous_org_contract_does_not_fabricate_and_stays_local(runtime, monkeypatch):
    brain_module = runtime["brain_module"]
    monkeypatch.setattr(
        brain_module.Brain,
        "_run_orchestrated_lookup",
        lambda *_args, **_kwargs: pytest.fail("_run_orchestrated_lookup must not be called"),
    )

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
            "clarification_prompt": "我找到了多个可能机构，请选择。\n- Victory Philippines\n- Victory Church",
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

    brain = brain_module.Brain()
    contract = brain.think("Victory 怎么联系？", conversation_id=f"ambiguous-{uuid.uuid4().hex}")["response_contract"]

    assert contract["route_status"] == "ambiguous"
    assert contract["payload_type"] == "ambiguous"
    assert contract["data_found"] is False
    assert contract["safe_message"]
    assert contract["organization"]["organization_id"] is None
    assert len(contract["payload"]["candidate_organizations"]) == 2
