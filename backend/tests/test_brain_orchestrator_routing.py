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
    test_db_path = tmp_path / f"brain_orchestrator_routing_{uuid.uuid4().hex}.db"
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


@pytest.mark.parametrize(
    ("query", "expected_intent", "expected_module"),
    [
        ("Show me Victory Philippines scores", "organization_score_lookup", "score_lookup"),
        ("Show me the relationship graph of Victory Philippines", "organization_relationship_graph_lookup", "relationship_graph"),
        ("Contact info for Victory Philippines", "organization_contact_lookup", "contact_intelligence"),
        ("Recommend partner organizations for Victory Philippines", "organization_partnership_recommendation_lookup", "partnership_recommender"),
        ("What are the next steps for Victory Philippines?", "organization_partnership_action_plan_lookup", "partnership_action_planner"),
        ("Give me an evidence brief for Victory Philippines", "organization_partnership_evidence_brief_lookup", "partnership_evidence_brief"),
    ],
)
def test_core_queries_route_to_whitelisted_modules(orchestrator_runtime, query, expected_intent, expected_module):
    orchestrator = orchestrator_runtime.BrainOrchestrator()
    result = orchestrator.orchestrate(query)

    assert result["route_status"] == "ready"
    assert result["selected_intent"] == expected_intent
    assert result["selected_module"] == expected_module
    assert result["dispatch"]["module"] == expected_module


def test_combined_contact_and_action_plan_routes_to_action_plan(orchestrator_runtime):
    orchestrator = orchestrator_runtime.BrainOrchestrator()
    result = orchestrator.orchestrate("给我 Victory Philippines 联系 Alpha Church 的行动计划")

    assert result["route_status"] == "ready"
    assert result["selected_intent"] == "organization_partnership_action_plan_lookup"
    assert result["selected_module"] == "partnership_action_planner"
    assert result["organization_name"] == "Victory Philippines"
    assert result["target_organization_name"] == "Alpha Church"


def test_why_recommend_routes_to_evidence_brief(orchestrator_runtime):
    orchestrator = orchestrator_runtime.BrainOrchestrator()
    result = orchestrator.orchestrate("为什么推荐 Victory Philippines")

    assert result["route_status"] == "ready"
    assert result["selected_intent"] == "organization_partnership_evidence_brief_lookup"
    assert result["selected_module"] == "partnership_evidence_brief"
    assert "evidence_brief_wins_over_recommendation_reason_query" in result["reason_codes"] or "matched_evidence_brief_signal" in result["reason_codes"]
