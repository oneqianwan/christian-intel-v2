from __future__ import annotations

import importlib
import os
import socket
import sys
import uuid
from pathlib import Path

import httpx
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
    "services.response_contract",
]


def _purge_modules() -> None:
    for module_name in MODULES_TO_PURGE:
        sys.modules.pop(module_name, None)


@pytest.fixture()
def builder_runtime(tmp_path: Path):
    test_db_path = tmp_path / f"response_contract_builder_{uuid.uuid4().hex}.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{test_db_path.as_posix()}"
    _purge_modules()

    database = importlib.import_module("models.database")
    importlib.import_module("models.auth")
    importlib.import_module("models.watch_alert")
    response_contract_module = importlib.import_module("services.response_contract")
    database.init_db()

    yield response_contract_module

    database.engine.dispose()
    _purge_modules()
    if test_db_path.exists():
        test_db_path.unlink()


def _sample_decision() -> dict:
    return {
        "query": "How can I contact Victory Philippines?",
        "normalized_query": "how can i contact victory philippines",
        "route_status": "ready",
        "selected_intent": "organization_contact_lookup",
        "selected_module": "contact_intelligence",
        "organization_name": "Victory Philippines",
        "target_organization_name": None,
        "missing_parameters": [],
        "warnings": [],
        "reason_codes": ["contact_keyword_detected", "organization_segment_extracted_only"],
        "trace": [
            {"step": "intent_router", "status": "pass", "reason_codes": ["contact_keyword_detected"]},
            {"step": "organization_resolver", "status": "pass", "reason_codes": ["organization_segment_extracted_only"]},
            {"step": "policy_guard", "status": "pass", "reason_codes": ["llm_disabled"]},
            {"step": "module_dispatcher", "status": "pass", "reason_codes": ["contact_keyword_detected"]},
            {"step": "final_route_decision", "status": "pass", "reason_codes": ["route_status_ready"]},
        ],
        "policy": {
            "db_first": True,
            "allow_llm": False,
            "allow_network": False,
            "allow_fabrication": False,
        },
        "dispatch": {
            "module": "contact_intelligence",
            "method": "_resolve_contact_lookup_if_applicable",
            "payload_type": "contact_intelligence",
            "required_parameters": ["organization_name"],
            "optional_parameters": [],
        },
        "intent_result": {
            "intent": "organization_contact_lookup",
            "intent_group": "contact",
            "confidence": 0.88,
        },
        "organization_resolution": {
            "organization_name": "Victory Philippines",
            "canonical_name": "Victory Philippines",
            "organization_id": None,
            "resolution_status": "resolved",
            "confidence": 0.72,
        },
        "target_organization_resolution": {
            "target_organization_name": None,
            "target_organization_id": None,
            "target_canonical_name": None,
            "target_candidates": [],
        },
    }


def test_builder_contract_is_complete_and_local_only(builder_runtime, monkeypatch):
    monkeypatch.setattr(
        socket,
        "create_connection",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("real network must not be used")),
    )
    monkeypatch.setattr(
        httpx,
        "request",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("httpx.request must not be used")),
    )

    builder = builder_runtime.ResponseContractBuilder()
    decision = _sample_decision()
    payload = {
        "organization": {"name": "Victory Philippines"},
        "contacts": [{"channel": "email", "value": "info@victory.org.ph"}],
        "summary": {"contact_count": 1},
        "warnings": [],
        "found": True,
    }

    result = builder.build(
        query=decision["query"],
        orchestration_result=decision,
        payload=payload,
        legacy_payload=payload,
        answer="response_contract=contact_lookup\nllm_used=false",
        data_source="database",
    )

    assert set(result.keys()) >= {
        "response_contract_version",
        "response_id",
        "trace_id",
        "query",
        "normalized_query",
        "route_status",
        "intent",
        "intent_group",
        "payload_type",
        "selected_module",
        "data_found",
        "confidence",
        "source",
        "organization",
        "target_organization",
        "payload",
        "legacy_payload",
        "safe_message",
        "missing_parameters",
        "warnings",
        "reason_codes",
        "fallback_reason",
        "policy",
        "audit",
        "trace",
        "errors",
    }
    assert result["response_contract_version"] == "6.0D"
    assert result["response_id"]
    assert result["trace_id"]
    assert 0.0 <= float(result["confidence"]) <= 1.0
    assert result["payload_type"] == "contact_intelligence"
    assert result["selected_module"] == "contact_intelligence"
    assert result["source"] == "database"
    assert result["data_found"] is True
    assert result["organization"]["name"] == "Victory Philippines"
    assert result["organization"]["organization_id"] is None
    assert result["policy"] == {
        "db_first": True,
        "allow_llm": False,
        "allow_network": False,
        "allow_fabrication": False,
    }
    assert result["audit"]["no_llm"] is True
    assert result["audit"]["no_network"] is True
    assert result["audit"]["no_fabrication"] is True
    assert result["audit"]["db_first"] is True
    assert result["audit"]["contract_builder"] == "response_contract"
    assert len(result["trace"]) == 5


def test_builder_rejects_unknown_payload_type_with_safe_fallback(builder_runtime):
    builder = builder_runtime.ResponseContractBuilder()
    decision = _sample_decision()
    decision["dispatch"] = {
        "module": "contact_intelligence",
        "method": "_resolve_contact_lookup_if_applicable",
        "payload_type": "unknown_payload",
        "required_parameters": ["organization_name"],
        "optional_parameters": [],
    }

    result = builder.build(
        query=decision["query"],
        orchestration_result=decision,
        payload={"found": True},
        legacy_payload={},
        answer="safe",
        data_source="database",
    )

    assert result["payload_type"] == "safe_fallback"
