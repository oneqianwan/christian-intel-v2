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
    test_db_path = tmp_path / f"evidence_brief_parser_{uuid.uuid4().hex}.db"
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


def test_chinese_evidence_brief_queries_are_parsed(isolated_runtime):
    parser = isolated_runtime["query_parser"].QueryParser()
    try:
        parsed_brief = parser.parse("给我 Harbor Church 的合作证据简报", conversation_id="eb-zh-brief")
        parsed_why = parser.parse("为什么推荐 Harbor Church？", conversation_id="eb-zh-why")
        parsed_target = parser.parse("给我 Harbor Church 联系 Bridge Ministry 的证据简报", conversation_id="eb-zh-target")
    finally:
        parser.close()

    assert parsed_brief["intent"] == "organization_partnership_evidence_brief_lookup"
    assert parsed_brief["response_contract"] == "partnership_evidence_brief"
    assert parsed_brief["organization_name"] == "Harbor Church"

    assert parsed_why["intent"] == "organization_partnership_evidence_brief_lookup"
    assert parsed_why["organization_name"] == "Harbor Church"

    assert parsed_target["intent"] == "organization_partnership_evidence_brief_lookup"
    assert parsed_target["organization_name"] == "Harbor Church"
    assert parsed_target["target_organization_name"] == "Bridge Ministry"


def test_english_evidence_brief_queries_are_parsed(isolated_runtime):
    parser = isolated_runtime["query_parser"].QueryParser()
    try:
        parsed_brief = parser.parse("Give me an evidence brief for Harbor Church.", conversation_id="eb-en-brief")
        parsed_rationale = parser.parse("What is the decision rationale for Harbor Church?", conversation_id="eb-en-rationale")
        parsed_why_contact = parser.parse("Why should Harbor Church contact this partner?", conversation_id="eb-en-why-contact")
        parsed_target = parser.parse(
            "Give me an evidence brief for Harbor Church to contact Bridge Ministry.",
            conversation_id="eb-en-target",
        )
        parsed_target_id = parser.parse(
            "Give me an evidence brief for Harbor Church target_org_id=org-bridge",
            conversation_id="eb-en-target-id",
        )
    finally:
        parser.close()

    assert parsed_brief["intent"] == "organization_partnership_evidence_brief_lookup"
    assert parsed_brief["organization_name"] == "Harbor Church"

    assert parsed_rationale["intent"] == "organization_partnership_evidence_brief_lookup"
    assert parsed_rationale["organization_name"] == "Harbor Church"

    assert parsed_why_contact["intent"] == "organization_partnership_evidence_brief_lookup"
    assert parsed_why_contact["organization_name"] == "Harbor Church"

    assert parsed_target["intent"] == "organization_partnership_evidence_brief_lookup"
    assert parsed_target["organization_name"] == "Harbor Church"
    assert parsed_target["target_organization_name"] == "Bridge Ministry"

    assert parsed_target_id["intent"] == "organization_partnership_evidence_brief_lookup"
    assert parsed_target_id["organization_name"] == "Harbor Church"
    assert parsed_target_id["target_org_id"] == "org-bridge"


def test_evidence_brief_parser_does_not_misclassify_other_queries(isolated_runtime):
    parser = isolated_runtime["query_parser"].QueryParser()
    try:
        score_parsed = parser.parse("Harbor Church 的评分是多少？", conversation_id="eb-score")
        contact_parsed = parser.parse("How can I contact Harbor Church?", conversation_id="eb-contact")
        graph_parsed = parser.parse("Show me the relationship graph of Harbor Church", conversation_id="eb-graph")
        recommendation_parsed = parser.parse("推荐 Harbor Church 适合合作的机构", conversation_id="eb-recommendation")
        action_plan_parsed = parser.parse("Harbor Church 下一步应该怎么做？", conversation_id="eb-action-plan")
        normal_parsed = parser.parse("Hello there", conversation_id="eb-normal")
    finally:
        parser.close()

    assert score_parsed["intent"] == "organization_score_lookup"
    assert contact_parsed["intent"] == "organization_contact_lookup"
    assert graph_parsed["intent"] == "organization_relationship_graph_lookup"
    assert recommendation_parsed["intent"] == "organization_partnership_recommendation_lookup"
    assert action_plan_parsed["intent"] == "organization_partnership_action_plan_lookup"
    assert normal_parsed is None or normal_parsed.get("intent") != "organization_partnership_evidence_brief_lookup"
