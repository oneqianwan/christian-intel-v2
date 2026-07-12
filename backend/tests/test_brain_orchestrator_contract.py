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
    "services.query_parser",
    "services.intent_router_final",
    "services.organization_resolver",
    "services.brain_orchestrator",
]


def _purge_modules() -> None:
    for module_name in MODULES_TO_PURGE:
        sys.modules.pop(module_name, None)


@pytest.fixture()
def orchestrator_runtime(tmp_path: Path):
    test_db_path = tmp_path / f"brain_orchestrator_contract_{uuid.uuid4().hex}.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{test_db_path.as_posix()}"
    _purge_modules()

    database = importlib.import_module("models.database")
    importlib.import_module("models.auth")
    importlib.import_module("models.watch_alert")
    orchestrator_module = importlib.import_module("services.brain_orchestrator")
    database.init_db()

    yield {
        "database": database,
        "orchestrator_module": orchestrator_module,
        "db_path": test_db_path,
    }

    database.engine.dispose()
    _purge_modules()
    if test_db_path.exists():
        test_db_path.unlink()


def test_brain_orchestration_result_contract_is_complete(orchestrator_runtime, monkeypatch):
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

    orchestrator = orchestrator_runtime["orchestrator_module"].BrainOrchestrator()
    result = orchestrator.orchestrate("Contact info for Victory Philippines")

    assert set(result.keys()) >= {
        "query",
        "normalized_query",
        "route_status",
        "selected_intent",
        "selected_module",
        "intent_result",
        "organization_resolution",
        "target_organization_resolution",
        "organization_name",
        "target_organization_name",
        "missing_parameters",
        "ambiguous",
        "candidate_intents",
        "candidate_organizations",
        "safe_default_used",
        "requires_clarification",
        "clarification_prompt",
        "policy",
        "dispatch",
        "trace",
        "warnings",
        "reason_codes",
    }
    assert result["route_status"] in {"ready", "ask_clarification", "unsupported", "ambiguous", "blocked"}
    assert result["selected_module"] in {
        "score_lookup",
        "relationship_graph",
        "contact_intelligence",
        "partnership_recommender",
        "partnership_action_planner",
        "partnership_evidence_brief",
        "general_chat",
        None,
    }
    assert result["policy"] == {
        "db_first": True,
        "allow_llm": False,
        "allow_network": False,
        "allow_fabrication": False,
    }
    assert result["organization_name"] == "Victory Philippines"
    assert result["selected_intent"] == "organization_contact_lookup"
    assert result["selected_module"] == "contact_intelligence"
    assert result["dispatch"]["module"] == "contact_intelligence"
    assert result["dispatch"]["payload_type"] == "contact_intelligence"
    assert result["dispatch"]["required_parameters"] == ["organization_name"]
    assert result["candidate_intents"]
    assert result["candidate_organizations"]
    assert 0.0 <= float(result["intent_result"]["confidence"]) <= 1.0


def test_brain_orchestration_trace_and_policy_are_stable(orchestrator_runtime):
    orchestrator = orchestrator_runtime["orchestrator_module"].BrainOrchestrator()
    result = orchestrator.orchestrate("Give me an evidence brief for Victory Philippines")

    steps = [item["step"] for item in result["trace"]]
    assert steps == [
        "intent_router",
        "organization_resolver",
        "policy_guard",
        "module_dispatcher",
        "final_route_decision",
    ]
    assert all(item["reason_codes"] for item in result["trace"])
    assert result["trace"][0]["selected_value"] == "organization_partnership_evidence_brief_lookup"
    assert result["trace"][2]["selected_value"] == "db_first_local_only"
    assert result["trace"][3]["selected_value"] == "partnership_evidence_brief"
