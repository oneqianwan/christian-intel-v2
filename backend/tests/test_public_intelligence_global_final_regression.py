from __future__ import annotations

from sqlalchemy import inspect

from test_production_readiness_core_uat import _block_llm_and_network, seeded_runtime


def test_public_score_graph_and_contact_queries_remain_global(seeded_runtime, monkeypatch):
    brain_module = seeded_runtime["brain_module"]
    _block_llm_and_network(monkeypatch, brain_module)
    brain = brain_module.Brain()

    score_contract = brain.think("Victory Philippines 评分是多少？", conversation_id="b3c4-final-score")["response_contract"]
    graph_contract = brain.think("Victory Philippines 的关系图谱", conversation_id="b3c4-final-graph")["response_contract"]
    contact_contract = brain.think("Victory Philippines 怎么联系？", conversation_id="b3c4-final-contact")["response_contract"]

    assert score_contract["payload_type"] == "score_snapshot"
    assert graph_contract["payload_type"] == "relationship_graph"
    assert contact_contract["payload_type"] == "contact_intelligence"
    assert score_contract["audit"]["no_llm"] is True
    assert graph_contract["audit"]["no_network"] is True
    assert contact_contract["audit"]["no_fabrication"] is True


def test_public_recommendation_action_and_evidence_queries_do_not_regress(seeded_runtime, monkeypatch):
    brain_module = seeded_runtime["brain_module"]
    _block_llm_and_network(monkeypatch, brain_module)
    brain = brain_module.Brain()

    recommendation_contract = brain.think(
        "Victory Philippines 推荐合作对象有哪些？",
        conversation_id="b3c4-final-recommendation",
    )["response_contract"]
    action_contract = brain.think(
        "What are the next steps for Harbor Church?",
        conversation_id="b3c4-final-action",
    )["response_contract"]
    evidence_contract = brain.think(
        "Give me an evidence brief for Harbor Church.",
        conversation_id="b3c4-final-evidence",
    )["response_contract"]

    assert recommendation_contract["payload_type"] == "partnership_recommendation"
    assert action_contract["payload_type"] == "partnership_action_plan"
    assert evidence_contract["payload_type"] == "partnership_evidence_brief"
    assert recommendation_contract["audit"]["no_llm"] is True
    assert action_contract["audit"]["no_network"] is True
    assert evidence_contract["audit"]["no_fabrication"] is True


def test_public_tables_remain_global_without_tenant_scope_columns(seeded_runtime):
    inspector = inspect(seeded_runtime["database"].engine)
    public_tables = (
        "organization_profiles",
        "sources",
        "pages",
        "intelligence_items",
        "relation_edges",
        "funding_rounds",
        "investments",
    )

    for table_name in public_tables:
        columns = {column["name"] for column in inspector.get_columns(table_name)}
        assert "tenant_id" not in columns

    db = seeded_runtime["database"].SessionLocal()
    try:
        assert db.query(seeded_runtime["database"].OrganizationProfile).count() >= 2
        assert db.query(seeded_runtime["database"].RelationEdge).count() >= 2
    finally:
        db.close()
