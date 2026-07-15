from __future__ import annotations

pytest_plugins = ["chat_ownership_testkit"]

from chat_ownership_testkit import create_user, login
from test_production_readiness_core_uat import _block_llm_and_network, seeded_runtime


def test_authenticated_chat_simple_still_works_under_production_auth(chat_runtime, monkeypatch):
    client = chat_runtime["client"]
    settings = chat_runtime["config"].settings
    settings.AUTH_V1_ENABLED = True
    settings.AUTH_COOKIE_REQUIRED = True
    settings.CHAT_USER_OWNERSHIP_ENABLED = True
    settings.ALLOW_PUBLIC_CORE_APIS = False
    monkeypatch.setattr(
        chat_runtime["chat_router"],
        "think",
        lambda *_args, **_kwargs: {"answer": "authenticated-ok", "evidence": [{"kind": "unit-test"}]},
    )

    create_user(chat_runtime, email="regression@example.com", password="StrongPass123!")
    login(client, email="regression@example.com", password="StrongPass123!")
    response = client.post("/api/chat/simple", json={"message": "Victory Philippines 评分是多少？"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["reply"] == "authenticated-ok"
    assert payload["conversation_id"]
    assert payload["delivery"]["status"] == "success"
    assert payload["delivery"]["sources"] == [{"kind": "unit-test"}]


def test_response_contract_and_observability_remain_intact(seeded_runtime, monkeypatch):
    brain_module = seeded_runtime["brain_module"]
    _block_llm_and_network(monkeypatch, brain_module)

    contract = brain_module.Brain().think(
        "Victory Philippines 评分是多少？",
        conversation_id="production-auth-regression",
    )["response_contract"]

    assert contract["response_contract_version"] == "6.0D"
    assert contract["payload_type"] == "score_snapshot"
    assert contract["source"] != "llm"
    assert contract["policy"]["allow_llm"] is False
    assert contract["policy"]["allow_network"] is False
    assert contract["policy"]["allow_fabrication"] is False
    assert contract["audit"]["no_llm"] is True
    assert contract["audit"]["no_network"] is True
    assert contract["audit"]["no_fabrication"] is True
    assert contract["observability"]["audit_summary"]["audit_version"] == "6.0E"
    assert contract["observability"]["audit_summary"]
    assert contract["observability"]["trace_events"]


def test_production_readiness_report_remains_60f(seeded_runtime, monkeypatch):
    brain_module = seeded_runtime["brain_module"]
    checker = seeded_runtime["readiness_module"].ProductionReadinessChecker()
    _block_llm_and_network(monkeypatch, brain_module)

    contract = brain_module.Brain().think(
        "Victory Philippines 怎么联系？",
        conversation_id="production-readiness-auth-regression",
    )["response_contract"]
    report = checker.build_report(contracts=[contract])

    assert report["readiness_version"] == "6.0F"
    assert report["commercial_readiness"]["demo_ready"] is True
    assert report["commercial_readiness"]["internal_beta_ready"] is True
    assert report["commercial_readiness"]["public_saas_ready"] is False
    assert report["contracts"]["unified_response_contract"] == "pass"
    assert report["contracts"]["observability_contract"] == "pass"
    assert report["core_brain"]["response_contract_ok"] is True
    assert report["core_brain"]["observability_ok"] is True
    assert report["safety"]["no_llm_for_structured_lookup"] is True
    assert report["safety"]["no_network_for_structured_lookup"] is True
    assert report["safety"]["no_fabrication"] is True
