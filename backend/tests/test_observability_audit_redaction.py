from __future__ import annotations

import importlib
import json
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
def modules(tmp_path: Path):
    test_db_path = tmp_path / f"observability_redaction_{uuid.uuid4().hex}.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{test_db_path.as_posix()}"
    _purge_modules()

    database = importlib.import_module("models.database")
    importlib.import_module("models.auth")
    importlib.import_module("models.watch_alert")
    audit_trail_module = importlib.import_module("services.audit_trail")
    response_contract_module = importlib.import_module("services.response_contract")
    database.init_db()

    yield {
        "audit_trail_module": audit_trail_module,
        "response_contract_module": response_contract_module,
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
        "reason_codes": ["contact_keyword_detected"],
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
        "intent_result": {"intent": "organization_contact_lookup", "confidence": 0.88},
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


def test_redaction_masks_sensitive_values_without_over_redacting_organizations(modules):
    audit_trail = modules["audit_trail_module"]
    redactor = audit_trail.AuditTrailRedactor()

    text = (
        "Victory Philippines contact test@example.com or +1 555-123-4567 "
        "token=abcdefghijklmnopqrstuvwxyz1234567890 "
        "Authorization: Bearer super-secret-token-value "
        "cookie=sessionid1234567890 session=abcdef1234567890"
    )
    redacted = redactor.redact_text(text)

    assert "[REDACTED_EMAIL]" in redacted
    assert "[REDACTED_PHONE]" in redacted
    assert "[REDACTED_SECRET]" in redacted
    assert "Victory Philippines" in redacted
    assert "test@example.com" not in redacted
    assert "+1 555-123-4567" not in redacted
    assert "super-secret-token-value" not in redacted


def test_audit_summary_and_trace_metadata_do_not_store_raw_secrets(modules):
    builder = modules["response_contract_module"].ResponseContractBuilder()
    secret_query = (
        "Contact Victory Philippines at test@example.com or 0917-123-4567 "
        "api_key=abcdefghijklmnopqrstuvwxyz1234567890 "
        "Cookie: session=abcdef1234567890 Authorization: Bearer super-secret-token-value"
    )
    contract = builder.build(
        query=secret_query,
        orchestration_result=_sample_decision(),
        payload={"organization": {"name": "Victory Philippines"}, "summary": {"contact_count": 1}, "found": True},
        legacy_payload={"organization": {"name": "Victory Philippines"}},
        answer="contact_lookup\nllm_used=false",
        data_source="database",
    )

    audit_summary = contract["observability"]["audit_summary"]
    serialized = json.dumps(contract["observability"], ensure_ascii=False)

    assert audit_summary["query_redacted"] != secret_query
    assert audit_summary["query_fingerprint"] != secret_query
    assert "[REDACTED_EMAIL]" in audit_summary["query_redacted"]
    assert "[REDACTED_PHONE]" in audit_summary["query_redacted"]
    assert "[REDACTED_SECRET]" in audit_summary["query_redacted"]
    assert "Victory Philippines" in audit_summary["query_redacted"]
    assert "test@example.com" not in serialized
    assert "0917-123-4567" not in serialized
    assert "super-secret-token-value" not in serialized
    assert "abcdefghijklmnopqrstuvwxyz1234567890" not in serialized
