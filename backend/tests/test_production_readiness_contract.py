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
    "services.production_readiness",
]


def _purge_modules() -> None:
    for module_name in MODULES_TO_PURGE:
        sys.modules.pop(module_name, None)


@pytest.fixture()
def readiness_runtime(tmp_path: Path, monkeypatch):
    test_db_path = tmp_path / f"production_readiness_contract_{uuid.uuid4().hex}.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{test_db_path.as_posix()}")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "super-secret-production-key-should-not-appear")
    _purge_modules()

    database = importlib.import_module("models.database")
    importlib.import_module("models.auth")
    importlib.import_module("models.watch_alert")
    readiness_module = importlib.import_module("services.production_readiness")
    database.init_db()

    yield {
        "database": database,
        "readiness_module": readiness_module,
    }

    database.engine.dispose()
    _purge_modules()
    if test_db_path.exists():
        test_db_path.unlink()


def _sample_contract() -> dict:
    return {
        "response_contract_version": "6.0D",
        "response_id": f"resp_{uuid.uuid4().hex}",
        "trace_id": f"trace_{uuid.uuid4().hex}",
        "route_status": "ready",
        "intent": "organization_contact_lookup",
        "payload_type": "contact_intelligence",
        "selected_module": "contact_intelligence",
        "source": "database",
        "organization": {
            "name": "Victory Philippines",
            "canonical_name": "Victory Philippines",
            "organization_id": None,
            "resolution_status": "resolved",
            "confidence": 0.8,
        },
        "target_organization": {
            "name": None,
            "canonical_name": None,
            "organization_id": None,
            "resolution_status": None,
            "confidence": None,
        },
        "policy": {
            "db_first": True,
            "allow_llm": False,
            "allow_network": False,
            "allow_fabrication": False,
        },
        "audit": {
            "no_llm": True,
            "no_network": True,
            "no_fabrication": True,
            "db_first": True,
        },
        "trace": [{"step": "intent_router"}],
        "observability": {
            "audit_summary": {
                "audit_version": "6.0E",
                "trace_id": "trace_static",
                "response_id": "resp_static",
                "query_fingerprint": "fingerprint",
                "query_redacted": "Victory Philippines [REDACTED_EMAIL]",
            },
            "trace_events": [{"step": "request_received"}],
            "metrics": {"total_duration_ms": 0, "stage_durations": {}},
        },
    }


def test_production_readiness_report_contract_is_complete(readiness_runtime):
    checker = readiness_runtime["readiness_module"].ProductionReadinessChecker()
    report = checker.build_report(contracts=[_sample_contract()])

    assert report["readiness_version"] == "6.0F"
    assert report["status"] in {"ready", "degraded", "blocked"}
    assert set(report["environment"].keys()) == {
        "python_ok",
        "backend_import_ok",
        "database_config_ok",
        "required_env_present",
        "dangerous_debug_mode",
    }
    assert set(report["core_brain"].keys()) == {
        "intent_router_ok",
        "organization_resolver_ok",
        "brain_orchestrator_ok",
        "response_contract_ok",
        "observability_ok",
    }
    assert set(report["safety"].keys()) == {
        "db_first",
        "no_llm_for_structured_lookup",
        "no_network_for_structured_lookup",
        "no_fabrication",
        "safe_fallback_enabled",
        "redaction_enabled",
    }
    assert set(report["modules"].keys()) == {
        "score_lookup",
        "relationship_graph",
        "contact_intelligence",
        "partnership_recommendation",
        "partnership_action_plan",
        "partnership_evidence_brief",
    }
    assert set(report["contracts"].keys()) == {
        "intent_result",
        "organization_resolve_result",
        "brain_orchestration_result",
        "unified_response_contract",
        "observability_contract",
    }
    assert set(report["commercial_readiness"].keys()) == {
        "demo_ready",
        "internal_beta_ready",
        "public_saas_ready",
        "reason_public_saas_not_ready",
    }
    assert report["commercial_readiness"]["demo_ready"] is True
    assert report["commercial_readiness"]["internal_beta_ready"] is True
    assert report["commercial_readiness"]["public_saas_ready"] is False


def test_production_readiness_report_does_not_print_secrets(readiness_runtime):
    checker = readiness_runtime["readiness_module"].ProductionReadinessChecker()
    report = checker.build_report(contracts=[_sample_contract()])
    serialized = json.dumps(report, ensure_ascii=False)

    assert "super-secret-production-key-should-not-appear" not in serialized
    assert report["environment"]["backend_import_ok"] is True
    assert report["safety"]["no_llm_for_structured_lookup"] is True
    assert report["safety"]["no_network_for_structured_lookup"] is True
