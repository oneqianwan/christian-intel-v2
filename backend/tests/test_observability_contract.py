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
    "services.audit_trail",
    "services.observability",
    "services.response_contract",
]


def _purge_modules() -> None:
    for module_name in MODULES_TO_PURGE:
        sys.modules.pop(module_name, None)


@pytest.fixture()
def builder_runtime(tmp_path: Path):
    test_db_path = tmp_path / f"observability_contract_{uuid.uuid4().hex}.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{test_db_path.as_posix()}"
    _purge_modules()

    database = importlib.import_module("models.database")
    importlib.import_module("models.auth")
    importlib.import_module("models.watch_alert")
    response_contract_module = importlib.import_module("services.response_contract")
    observability_module = importlib.import_module("services.observability")
    database.init_db()

    yield {
        "response_contract_module": response_contract_module,
        "observability_module": observability_module,
        "database": database,
    }

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


def test_observability_contract_is_complete_and_local_only(builder_runtime, monkeypatch):
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

    builder = builder_runtime["response_contract_module"].ResponseContractBuilder()
    observability_module = builder_runtime["observability_module"]
    decision = _sample_decision()
    contract = builder.build(
        query=decision["query"],
        orchestration_result=decision,
        payload={
            "organization": {"name": "Victory Philippines"},
            "contacts": [{"channel": "email", "value": "info@victory.org.ph"}],
            "summary": {"contact_count": 1},
            "found": True,
        },
        legacy_payload={"organization": {"name": "Victory Philippines"}},
        answer="response_contract=contact_lookup\nllm_used=false",
        data_source="database",
    )

    observability = contract["observability"]
    audit_summary = observability["audit_summary"]
    trace_events = observability["trace_events"]
    metrics = observability["metrics"]

    assert set(observability.keys()) == {"audit_summary", "trace_events", "metrics"}
    assert set(audit_summary.keys()) >= {
        "audit_version",
        "trace_id",
        "response_id",
        "query_fingerprint",
        "query_redacted",
        "intent",
        "route_status",
        "payload_type",
        "selected_module",
        "organization_resolution_status",
        "target_organization_resolution_status",
        "data_found",
        "db_first",
        "no_llm",
        "no_network",
        "no_fabrication",
        "safe_fallback_used",
        "fallback_reason",
        "warnings_count",
        "errors_count",
        "trace_steps_count",
        "total_duration_ms",
        "created_at",
        "redaction_applied",
    }
    assert audit_summary["audit_version"] == "6.0E"
    assert audit_summary["trace_id"] == contract["trace_id"]
    assert audit_summary["response_id"] == contract["response_id"]
    assert audit_summary["db_first"] is True
    assert audit_summary["no_llm"] is True
    assert audit_summary["no_network"] is True
    assert audit_summary["no_fabrication"] is True
    assert audit_summary["total_duration_ms"] >= 0
    assert audit_summary["trace_steps_count"] == len(trace_events)

    assert metrics["total_duration_ms"] >= 0
    assert isinstance(metrics["stage_durations"], dict)

    assert trace_events
    for item in trace_events:
        assert set(item.keys()) == {
            "trace_id",
            "span_id",
            "parent_span_id",
            "step",
            "status",
            "started_at",
            "ended_at",
            "duration_ms",
            "selected_value",
            "reason_codes",
            "warnings",
            "errors",
            "metadata",
        }
        assert item["trace_id"] == contract["trace_id"]
        assert item["span_id"]
        assert item["duration_ms"] >= 0
        assert item["step"] in observability_module.ResponseObservabilityBuilder.TRACE_STEP_WHITELIST
        assert item["status"] in observability_module.ResponseObservabilityBuilder.TRACE_STATUS_WHITELIST
        assert isinstance(item["reason_codes"], list)
        assert isinstance(item["warnings"], list)
        assert isinstance(item["errors"], list)
        assert isinstance(item["metadata"], dict)
