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
    "services.intent_router_final",
    "services.query_parser",
]


def _purge_modules() -> None:
    for module_name in MODULES_TO_PURGE:
        sys.modules.pop(module_name, None)


@pytest.fixture()
def parser_runtime(tmp_path: Path):
    test_db_path = tmp_path / f"intent_router_priority_{uuid.uuid4().hex}.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{test_db_path.as_posix()}"
    _purge_modules()

    database = importlib.import_module("models.database")
    importlib.import_module("models.auth")
    importlib.import_module("models.watch_alert")
    query_parser = importlib.import_module("services.query_parser")
    database.init_db()

    yield {
        "database": database,
        "query_parser": query_parser,
        "db_path": test_db_path,
    }

    database.engine.dispose()
    _purge_modules()
    if test_db_path.exists():
        test_db_path.unlink()


@pytest.mark.parametrize(
    ("message", "expected_intent"),
    [
        ("Victory Philippines 的评分是多少？", "organization_score_lookup"),
        ("Victory Philippines 怎么联系？", "organization_contact_lookup"),
        ("Victory Philippines 的关系图谱", "organization_relationship_graph_lookup"),
        ("推荐合作对象有哪些", "organization_partnership_recommendation_lookup"),
        ("下一步怎么做？", "organization_partnership_action_plan_lookup"),
        ("为什么推荐？", "organization_partnership_evidence_brief_lookup"),
    ],
)
def test_priority_matrix_routes_core_queries(parser_runtime, message: str, expected_intent: str):
    parser = parser_runtime["query_parser"].QueryParser()
    try:
        result = parser.parse_intent_final(message)
    finally:
        parser.close()

    assert result["intent"] == expected_intent


def test_priority_matrix_action_plan_wins_for_combined_recommendation_and_action_plan(parser_runtime):
    parser = parser_runtime["query_parser"].QueryParser()
    try:
        result = parser.parse_intent_final("优先联系谁，下一步怎么做？")
    finally:
        parser.close()

    assert result["intent"] == "organization_partnership_action_plan_lookup"
    assert [item["intent"] for item in result["candidate_intents"]][:2] == [
        "organization_partnership_action_plan_lookup",
        "organization_partnership_recommendation_lookup",
    ]
    assert "combined_recommendation_and_action_plan_action_plan_wins" in result["reason_codes"]


def test_priority_matrix_action_plan_wins_for_combined_contact_and_action_plan(parser_runtime):
    parser = parser_runtime["query_parser"].QueryParser()
    try:
        result = parser.parse_intent_final("Victory Philippines 怎么联系，下一步怎么做？")
    finally:
        parser.close()

    assert result["intent"] == "organization_partnership_action_plan_lookup"
    assert [item["intent"] for item in result["candidate_intents"]][:2] == [
        "organization_partnership_action_plan_lookup",
        "organization_contact_lookup",
    ]
    assert "combined_contact_and_action_plan_action_plan_wins" in result["reason_codes"]


def test_priority_matrix_evidence_brief_wins_over_recommendation(parser_runtime):
    parser = parser_runtime["query_parser"].QueryParser()
    try:
        result = parser.parse_intent_final("为什么这个机构值得联系？")
    finally:
        parser.close()

    assert result["intent"] == "organization_partnership_evidence_brief_lookup"
    assert result["candidate_intents"][0]["intent"] == "organization_partnership_evidence_brief_lookup"


def test_recommendation_query_is_not_misclassified_as_evidence_brief(parser_runtime):
    parser = parser_runtime["query_parser"].QueryParser()
    try:
        result = parser.parse_intent_final("推荐合作对象有哪些？")
    finally:
        parser.close()

    assert result["intent"] == "organization_partnership_recommendation_lookup"
