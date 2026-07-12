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
    test_db_path = tmp_path / f"intent_router_regression_{uuid.uuid4().hex}.db"
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
    ("message", "expected_intent", "expected_contract", "expected_org"),
    [
        ("Victory Philippines 的评分是多少？", "organization_score_lookup", "score_lookup", "Victory Philippines"),
        ("Show me the relationship graph of Victory Philippines", "organization_relationship_graph_lookup", "relationship_graph", "Victory Philippines"),
        ("Victory Philippines 怎么联系？", "organization_contact_lookup", "contact_lookup", "Victory Philippines"),
        ("给我 Harbor Church 的推荐合作对象", "organization_partnership_recommendation_lookup", "partnership_recommendations", "Harbor Church"),
        ("Harbor Church 下一步应该怎么做？", "organization_partnership_action_plan_lookup", "partnership_action_plan", "Harbor Church"),
        ("Give me an evidence brief for Harbor Church.", "organization_partnership_evidence_brief_lookup", "partnership_evidence_brief", "Harbor Church"),
    ],
)
def test_phase59_parser_contracts_do_not_regress(parser_runtime, message: str, expected_intent: str, expected_contract: str, expected_org: str):
    parser = parser_runtime["query_parser"].QueryParser()
    try:
        result = parser.parse(message)
    finally:
        parser.close()

    assert result is not None
    assert result["intent"] == expected_intent
    assert result["response_contract"] == expected_contract
    assert result["organization_name"] == expected_org
    assert result["requires_database_lookup"] is True


def test_backward_compatibility_keeps_final_intent_result_attached(parser_runtime):
    parser = parser_runtime["query_parser"].QueryParser()
    try:
        result = parser.parse("Give me an evidence brief for Harbor Church.")
    finally:
        parser.close()

    assert result is not None
    assert "final_intent_result" in result
    assert result["final_intent_result"]["intent"] == "organization_partnership_evidence_brief_lookup"
    assert result["final_intent_result"]["response_contract"] == "partnership_evidence_brief"
