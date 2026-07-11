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
]


def _purge_modules() -> None:
    for module_name in MODULES_TO_PURGE:
        sys.modules.pop(module_name, None)


@pytest.fixture()
def isolated_runtime(tmp_path: Path):
    test_db_path = tmp_path / f"recommendation_parser_{uuid.uuid4().hex}.db"
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


def test_chinese_recommendation_query_is_parsed(isolated_runtime):
    parser = isolated_runtime["query_parser"].QueryParser()
    try:
        parsed = parser.parse("给我 Harbor Church 的推荐合作对象", conversation_id="rec-zh")
    finally:
        parser.close()

    assert parsed["intent"] == "organization_partnership_recommendation_lookup"
    assert parsed["response_contract"] == "partnership_recommendations"
    assert parsed["organization_name"] == "Harbor Church"


def test_chinese_priority_contact_query_is_parsed_without_org_name(isolated_runtime):
    parser = isolated_runtime["query_parser"].QueryParser()
    try:
        parsed = parser.parse("我应该优先联系哪些机构？", conversation_id="rec-zh-generic")
    finally:
        parser.close()

    assert parsed["intent"] == "organization_partnership_recommendation_lookup"
    assert parsed["response_contract"] == "partnership_recommendations"
    assert parsed["organization_name"] == ""


def test_english_recommendation_queries_are_parsed(isolated_runtime):
    parser = isolated_runtime["query_parser"].QueryParser()
    try:
        parsed_partner = parser.parse("Who should Harbor Church partner with?", conversation_id="rec-en-partner")
        parsed_contact = parser.parse("Who should I contact first?", conversation_id="rec-en-contact-first")
        parsed_recommend = parser.parse(
            "Recommend partner organizations for Victory Philippines.",
            conversation_id="rec-en-recommend-orgs",
        )
    finally:
        parser.close()

    assert parsed_partner["intent"] == "organization_partnership_recommendation_lookup"
    assert parsed_partner["organization_name"] == "Harbor Church"
    assert parsed_contact["intent"] == "organization_partnership_recommendation_lookup"
    assert parsed_contact["organization_name"] == ""
    assert parsed_recommend["intent"] == "organization_partnership_recommendation_lookup"
    assert parsed_recommend["organization_name"] == "Victory Philippines"


def test_recommendation_parser_does_not_misclassify_score_contact_graph_or_normal_chat(isolated_runtime):
    parser = isolated_runtime["query_parser"].QueryParser()
    try:
        score_parsed = parser.parse("Harbor Church 的评分是多少？", conversation_id="score")
        contact_parsed = parser.parse("How can I contact Harbor Church?", conversation_id="contact")
        graph_parsed = parser.parse("Show me the relationship graph of Harbor Church", conversation_id="graph")
        normal_parsed = parser.parse("Hello there", conversation_id="normal")
    finally:
        parser.close()

    assert score_parsed["intent"] == "organization_score_lookup"
    assert contact_parsed["intent"] == "organization_contact_lookup"
    assert graph_parsed["intent"] == "organization_relationship_graph_lookup"
    assert normal_parsed is None or normal_parsed.get("intent") != "organization_partnership_recommendation_lookup"
