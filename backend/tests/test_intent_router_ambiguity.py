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
    test_db_path = tmp_path / f"intent_router_ambiguity_{uuid.uuid4().hex}.db"
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


def test_broad_query_requires_safe_clarification(parser_runtime):
    parser = parser_runtime["query_parser"].QueryParser()
    try:
        result = parser.parse_intent_final("帮我分析 Victory Philippines")
    finally:
        parser.close()

    assert result["intent"] == "unsupported_or_ambiguous"
    assert result["ambiguous"] is True
    assert result["routing_decision"] == "ask_clarification"
    assert "broad_analysis_query" in result["warnings"]


def test_progress_query_keeps_action_plan_but_surfaces_recommendation_candidate(parser_runtime):
    parser = parser_runtime["query_parser"].QueryParser()
    try:
        result = parser.parse_intent_final("Victory Philippines 怎么推进？")
    finally:
        parser.close()

    assert result["intent"] == "organization_partnership_action_plan_lookup"
    top_intents = [item["intent"] for item in result["candidate_intents"]]
    assert "organization_partnership_action_plan_lookup" in top_intents
    assert "organization_partnership_recommendation_lookup" in top_intents
    assert result["ambiguous"] is True or result["routing_decision"] == "safe_default"


def test_why_worth_contact_prefers_evidence_brief(parser_runtime):
    parser = parser_runtime["query_parser"].QueryParser()
    try:
        result = parser.parse_intent_final("为什么这个机构值得联系？")
    finally:
        parser.close()

    assert result["intent"] == "organization_partnership_evidence_brief_lookup"
    assert "contact_decision_rationale_prefers_evidence_brief" in result["reason_codes"]


def test_unsupported_query_returns_safe_result_without_lookup(parser_runtime):
    parser = parser_runtime["query_parser"].QueryParser()
    try:
        result = parser.parse_intent_final("Tell me a joke about satellites")
    finally:
        parser.close()

    assert result["intent"] == "unsupported_or_ambiguous"
    assert result["routing_decision"] == "unsupported"
    assert result["safe_default_intent"] == "unsupported_or_ambiguous"
    assert result["candidate_intents"] == []
