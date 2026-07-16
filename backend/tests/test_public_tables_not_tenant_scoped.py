from __future__ import annotations

import importlib

from test_production_readiness_core_uat import _block_llm_and_network, seeded_runtime
from test_production_readiness_startup_checks import startup_runtime


def test_public_global_tables_do_not_gain_tenant_id(startup_runtime):
    database = startup_runtime["database"]
    inspector = importlib.import_module("sqlalchemy").inspect(database.engine)

    for table_name in (
        "organization_profiles",
        "knowledge_entities",
        "sources",
        "pages",
        "intelligence_items",
        "relation_edges",
        "funding_rounds",
        "investments",
        "organization_types",
        "theological_positions",
    ):
        columns = {column["name"] for column in inspector.get_columns(table_name)}
        assert "tenant_id" not in columns


def test_public_score_graph_and_contact_queries_still_work(seeded_runtime, monkeypatch):
    brain_module = seeded_runtime["brain_module"]
    _block_llm_and_network(monkeypatch, brain_module)

    brain = brain_module.Brain()
    score_contract = brain.think("Victory Philippines 评分是多少？", conversation_id="b3b-score")["response_contract"]
    graph_contract = brain.think("Victory Philippines 的关系图谱", conversation_id="b3b-graph")["response_contract"]
    contact_contract = brain.think("Victory Philippines 怎么联系？", conversation_id="b3b-contact")["response_contract"]

    assert score_contract["payload_type"] == "score_snapshot"
    assert graph_contract["payload_type"] == "relationship_graph"
    assert contact_contract["payload_type"] == "contact_intelligence"
    assert score_contract["source"] != "llm"
    assert graph_contract["source"] != "llm"
    assert contact_contract["source"] != "llm"
