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
    test_db_path = tmp_path / f"brain_orchestrator_trace_{uuid.uuid4().hex}.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{test_db_path.as_posix()}"
    _purge_modules()

    database = importlib.import_module("models.database")
    importlib.import_module("models.auth")
    importlib.import_module("models.watch_alert")
    orchestrator_module = importlib.import_module("services.brain_orchestrator")
    database.init_db()

    yield orchestrator_module

    database.engine.dispose()
    _purge_modules()
    if test_db_path.exists():
        test_db_path.unlink()


def test_trace_contains_required_steps_in_stable_order(orchestrator_runtime):
    orchestrator = orchestrator_runtime.BrainOrchestrator()
    result = orchestrator.orchestrate("Give me an evidence brief for Victory Philippines")

    trace = result["trace"]
    assert [step["step"] for step in trace] == [
        "intent_router",
        "organization_resolver",
        "policy_guard",
        "module_dispatcher",
        "final_route_decision",
    ]
    assert trace[0]["status"] == "pass"
    assert trace[1]["status"] == "pass"
    assert trace[2]["status"] == "pass"
    assert trace[3]["selected_value"] == "partnership_evidence_brief"
    assert trace[4]["selected_value"] == "ready"


def test_trace_reason_codes_are_explainable_for_fallback(orchestrator_runtime):
    orchestrator = orchestrator_runtime.BrainOrchestrator()
    result = orchestrator.orchestrate("Contact info for this organization")

    trace = result["trace"]
    assert trace[0]["reason_codes"]
    assert trace[1]["reason_codes"]
    assert "context_reference_detected" in trace[1]["reason_codes"]
    assert trace[3]["status"] == "blocked"
    assert trace[4]["selected_value"] == "ask_clarification"
