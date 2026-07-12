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
    "services.organization_resolver",
    "services.intent_router_final",
    "services.query_parser",
]


def _purge_modules() -> None:
    for module_name in MODULES_TO_PURGE:
        sys.modules.pop(module_name, None)


@pytest.fixture()
def parser_runtime(tmp_path: Path):
    test_db_path = tmp_path / f"organization_resolver_regression_{uuid.uuid4().hex}.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{test_db_path.as_posix()}"
    _purge_modules()

    database = importlib.import_module("models.database")
    importlib.import_module("models.auth")
    importlib.import_module("models.watch_alert")
    query_parser_module = importlib.import_module("services.query_parser")
    database.init_db()

    parser = query_parser_module.QueryParser()
    yield parser

    parser.close()
    database.engine.dispose()
    _purge_modules()
    if test_db_path.exists():
        test_db_path.unlink()


def test_score_contact_graph_recommendation_action_evidence_keep_organization(parser_runtime):
    parser = parser_runtime

    messages = [
        ("Victory Philippines 的评分是多少？", "organization_score_lookup"),
        ("给我 Victory Philippines 的联系方式", "organization_contact_lookup"),
        ("Show me the relationship graph of Victory Philippines", "organization_relationship_graph_lookup"),
        ("给我 Victory Philippines 的推荐合作对象", "organization_partnership_recommendation_lookup"),
        ("What are the next steps for Victory Philippines?", "organization_partnership_action_plan_lookup"),
        ("Give me an evidence brief for Victory Philippines", "organization_partnership_evidence_brief_lookup"),
    ]

    for message, expected_intent in messages:
        result = parser.parse_intent_final(message)
        assert result["intent"] == expected_intent
        assert result["organization_name"] == "Victory Philippines"


def test_combined_contact_and_action_plan_still_prefers_action_plan(parser_runtime):
    parser = parser_runtime

    result = parser.parse_intent_final("Victory Philippines 怎么联系，下一步怎么做？")

    assert result["intent"] == "organization_partnership_action_plan_lookup"
    assert "combined_contact_and_action_plan_action_plan_wins" in result["reason_codes"]


def test_why_recommend_still_prefers_evidence_brief(parser_runtime):
    parser = parser_runtime

    result = parser.parse_intent_final("为什么推荐 Victory Philippines？")

    assert result["intent"] == "organization_partnership_evidence_brief_lookup"


def test_context_reference_still_requires_clarification(parser_runtime):
    parser = parser_runtime

    result = parser.parse_intent_final("这个机构怎么联系？")

    assert result["routing_decision"] == "ask_clarification"
    assert result["organization_name"] is None
    assert result["organization_resolution"]["resolution_status"] == "context_required"
