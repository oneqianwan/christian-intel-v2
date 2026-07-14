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
    "services.response_contract",
]


def _purge_modules() -> None:
    for module_name in MODULES_TO_PURGE:
        sys.modules.pop(module_name, None)


@pytest.fixture()
def response_contract_module(tmp_path: Path):
    test_db_path = tmp_path / f"observability_trace_{uuid.uuid4().hex}.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{test_db_path.as_posix()}"
    _purge_modules()

    database = importlib.import_module("models.database")
    importlib.import_module("models.auth")
    importlib.import_module("models.watch_alert")
    module = importlib.import_module("services.response_contract")
    database.init_db()

    yield module

    database.engine.dispose()
    _purge_modules()
    if test_db_path.exists():
        test_db_path.unlink()


def _decision(route_status: str = "ready") -> dict:
    return {
        "query": "How can I contact Victory Philippines?",
        "normalized_query": "how can i contact victory philippines",
        "route_status": route_status,
        "selected_intent": "organization_contact_lookup",
        "selected_module": "contact_intelligence",
        "organization_name": "Victory Philippines" if route_status == "ready" else None,
        "target_organization_name": None,
        "missing_parameters": [] if route_status == "ready" else ["organization_name"],
        "warnings": [] if route_status == "ready" else ["organization_name_missing"],
        "reason_codes": ["contact_keyword_detected"],
        "trace": [
            {"step": "intent_router", "status": "pass", "reason_codes": ["contact_keyword_detected"]},
            {"step": "organization_resolver", "status": "pass" if route_status == "ready" else "blocked", "reason_codes": ["organization_name_missing" if route_status != "ready" else "organization_segment_extracted_only"]},
            {"step": "policy_guard", "status": "pass", "reason_codes": ["llm_disabled"]},
            {"step": "module_dispatcher", "status": "pass" if route_status == "ready" else "blocked", "reason_codes": [f"route_status_{route_status}"]},
            {"step": "final_route_decision", "status": "pass" if route_status == "ready" else "blocked", "reason_codes": [f"route_status_{route_status}"]},
        ],
        "policy": {
            "db_first": True,
            "allow_llm": False,
            "allow_network": False,
            "allow_fabrication": False,
        },
        "dispatch": {
            "module": "contact_intelligence",
            "method": "_resolve_contact_lookup_if_applicable" if route_status == "ready" else None,
            "payload_type": "contact_intelligence",
            "required_parameters": ["organization_name"],
            "optional_parameters": [],
        },
        "intent_result": {"intent": "organization_contact_lookup", "confidence": 0.88},
        "organization_resolution": {
            "organization_name": "Victory Philippines" if route_status == "ready" else None,
            "canonical_name": "Victory Philippines" if route_status == "ready" else None,
            "organization_id": None,
            "resolution_status": "resolved" if route_status == "ready" else "missing",
            "confidence": 0.72 if route_status == "ready" else 0.0,
            "context_reference": False,
        },
        "target_organization_resolution": {
            "target_organization_name": None,
            "target_organization_id": None,
            "target_canonical_name": None,
            "target_candidates": [],
        },
        "requires_clarification": route_status != "ready",
        "clarification_prompt": "I need you to specify an organization first." if route_status != "ready" else None,
    }


def test_ready_trace_events_include_required_steps_and_stable_order(response_contract_module):
    builder = response_contract_module.ResponseContractBuilder()
    contract = builder.build(
        query="How can I contact Victory Philippines?",
        orchestration_result=_decision("ready"),
        payload={"organization": {"name": "Victory Philippines"}, "summary": {"contact_count": 1}, "found": True},
        legacy_payload={"organization": {"name": "Victory Philippines"}},
        answer="contact_lookup\nllm_used=false",
        data_source="database",
    )

    steps = [item["step"] for item in contract["observability"]["trace_events"]]
    assert steps == [
        "request_received",
        "intent_router",
        "organization_resolver",
        "policy_guard",
        "module_dispatcher",
        "final_route_decision",
        "module_execution",
        "response_contract_builder",
        "response_ready",
    ]
    assert contract["observability"]["audit_summary"]["trace_steps_count"] == len(steps)


def test_safe_fallback_trace_events_include_safe_fallback_builder(response_contract_module):
    builder = response_contract_module.ResponseContractBuilder()
    contract = builder.build(
        query="推荐合作对象有哪些？",
        orchestration_result=_decision("ask_clarification"),
        payload={"missing_parameters": ["organization_name"], "found": False},
        legacy_payload={},
        answer="safe_fallback\nllm_used=false",
        safe_message="我需要你先指定一个机构，例如 Victory Philippines。",
        data_source=None,
    )

    steps = [item["step"] for item in contract["observability"]["trace_events"]]
    assert steps == [
        "request_received",
        "intent_router",
        "organization_resolver",
        "policy_guard",
        "module_dispatcher",
        "final_route_decision",
        "safe_fallback_builder",
        "response_contract_builder",
        "response_ready",
    ]
    assert "module_execution" not in steps
    assert contract["observability"]["audit_summary"]["trace_steps_count"] == len(steps)
