from __future__ import annotations

import importlib

from test_production_readiness_core_uat import _block_llm_and_network, seeded_runtime
from test_production_readiness_startup_checks import startup_runtime


def test_b3c2_keeps_b3c1_b3b_b2_b1_and_a3_readiness_contracts(startup_runtime):
    tenant_context = importlib.import_module("dependencies.tenant_context")
    tenant_scope = importlib.import_module("services.tenant_scope")
    checker = startup_runtime["readiness_module"].ProductionReadinessChecker()
    report = checker.build_report()
    imports = checker._collect_imports()
    controlled_beta_auth_ready = checker._is_controlled_beta_auth_ready(
        settings=imports.get("settings"),
        environment=report["environment"],
    )
    tenant_readiness = report["tenant_readiness"]
    reasons = set(report["commercial_readiness"]["reason_public_saas_not_ready"])

    assert hasattr(tenant_context, "get_current_tenant_context")
    assert hasattr(tenant_scope, "filter_by_tenant")
    assert tenant_readiness["tenant_core_models_ready"] is True
    assert tenant_readiness["private_tenant_schema_ready"] in {"yes", "partial"}
    assert tenant_readiness["conversation_router_tenant_scoped_ready"] is True
    assert tenant_readiness["message_router_tenant_scoped_ready"] is True
    assert tenant_readiness["bookmark_router_tenant_scoped_ready"] is True
    assert tenant_readiness["feedback_router_tenant_scoped_ready"] is True
    assert tenant_readiness["feedback_stats_tenant_scoped_ready"] is True
    assert tenant_readiness["chat_message_tenant_write_ready"] is True
    assert tenant_readiness["private_router_tenant_binding_ready"] == "yes"
    assert tenant_readiness["tenant_isolation_readiness"] == "ready"
    assert tenant_readiness["controlled_beta_tenant_ready"] is False
    assert controlled_beta_auth_ready is True
    assert report["commercial_readiness"]["public_saas_ready"] is False
    assert "production_authentication_not_fully_validated" not in reasons
    assert "multi_tenant_isolation_not_fully_validated" not in reasons
    assert "billing_not_implemented" in reasons
    assert "rate_limit_not_fully_validated" in reasons
    assert "monitoring_alerting_not_fully_validated" in reasons
    assert "backup_recovery_not_fully_validated" in reasons
    assert "deployment_health_checks_not_fully_validated" in reasons


def test_b3c2_keeps_public_score_graph_and_contact_queries_stable(seeded_runtime, monkeypatch):
    brain_module = seeded_runtime["brain_module"]
    _block_llm_and_network(monkeypatch, brain_module)
    brain = brain_module.Brain()

    score_contract = brain.think("Victory Philippines 评分是多少？", conversation_id="b3c2-reg-score")["response_contract"]
    graph_contract = brain.think("Victory Philippines 的关系图谱", conversation_id="b3c2-reg-graph")["response_contract"]
    contact_contract = brain.think("Victory Philippines 怎么联系？", conversation_id="b3c2-reg-contact")["response_contract"]

    assert score_contract["payload_type"] == "score_snapshot"
    assert graph_contract["payload_type"] == "relationship_graph"
    assert contact_contract["payload_type"] == "contact_intelligence"
    assert score_contract["audit"]["no_llm"] is True
    assert graph_contract["audit"]["no_network"] is True
    assert contact_contract["audit"]["no_fabrication"] is True
