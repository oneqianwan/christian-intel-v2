from __future__ import annotations

import importlib
import os
import socket
import sys
import uuid
from datetime import date
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
    "services.audit_trail",
    "services.observability",
    "services.production_readiness",
    "services.brain",
    "services.query_parser",
    "services.intent_router_final",
    "services.organization_resolver",
    "services.brain_orchestrator",
    "services.response_contract",
    "services.contact_intelligence",
    "services.partnership_recommender",
    "services.partnership_action_planner",
    "services.partnership_evidence_brief",
    "services.relation_mapper",
]


def _purge_modules() -> None:
    for module_name in MODULES_TO_PURGE:
        sys.modules.pop(module_name, None)


@pytest.fixture()
def seeded_runtime(tmp_path: Path, monkeypatch):
    test_db_path = tmp_path / f"production_readiness_core_uat_{uuid.uuid4().hex}.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{test_db_path.as_posix()}")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")
    _purge_modules()

    database = importlib.import_module("models.database")
    importlib.import_module("models.auth")
    importlib.import_module("models.watch_alert")
    brain_module = importlib.import_module("services.brain")
    readiness_module = importlib.import_module("services.production_readiness")
    database.init_db()

    runtime = {
        "database": database,
        "brain_module": brain_module,
        "readiness_module": readiness_module,
    }
    _seed_org(runtime, org_id="org-victory", name="Victory Philippines")
    _seed_org(
        runtime,
        org_id="org-bridge",
        name="Bridge Ministry",
        people_score=78,
        digital_score=74,
        intel_score=81,
        official_website="https://bridge.org",
        contact_email="connect@bridge.org",
        phone_public="+63 2 1234 5678",
        facebook_url="https://facebook.com/bridgeorg",
        source_url="https://bridge.org/source",
    )
    _seed_org(
        runtime,
        org_id="org-harbor",
        name="Harbor Church",
        people_score=66,
        digital_score=54,
        intel_score=69,
        official_website="https://harbor.org",
        contact_email="hello@harbor.org",
        phone_public="+63 2 2345 6789",
        facebook_url="https://facebook.com/harborchurch",
        source_url="https://harbor.org/source",
    )
    _seed_edge(runtime, edge_id="edge-victory-bridge", source_id="org-victory", target_id="org-bridge")
    _seed_edge(runtime, edge_id="edge-harbor-bridge", source_id="org-harbor", target_id="org-bridge")

    yield runtime

    database.engine.dispose()
    _purge_modules()
    if test_db_path.exists():
        test_db_path.unlink()


def _seed_org(
    runtime,
    *,
    org_id: str,
    name: str,
    people_score: int | None = 64,
    digital_score: int | None = 58,
    intel_score: int | None = 67,
    official_website: str | None = "https://example.org",
    contact_email: str | None = None,
    phone_public: str | None = None,
    facebook_url: str | None = None,
    source_url: str | None = "https://example.org/source",
):
    database = runtime["database"]
    db = database.SessionLocal()
    try:
        db.add(
            database.OrganizationProfile(
                id=org_id,
                name=name,
                country="Philippines",
                city="Manila",
                denomination="Evangelical",
                people_score=people_score,
                digital_score=digital_score,
                intel_score=intel_score,
                official_website=official_website,
                contact_email=contact_email,
                phone_public=phone_public,
                facebook_url=facebook_url,
                source_url=source_url,
                source_name="unit_test_seed",
            )
        )
        db.commit()
    finally:
        db.close()


def _seed_edge(runtime, *, edge_id: str, source_id: str, target_id: str):
    database = runtime["database"]
    db = database.SessionLocal()
    try:
        db.add(
            database.RelationEdge(
                id=edge_id,
                source_id=source_id,
                target_id=target_id,
                source_type="organization",
                target_type="organization",
                relation_type="partner",
                confidence=0.84,
                is_verified=True,
                evidence_url=f"https://evidence.example/{edge_id}",
                evidence_source="unit_test_evidence",
                evidence_date=date(2026, 7, 11),
            )
        )
        db.commit()
    finally:
        db.close()


def _block_llm_and_network(monkeypatch, brain_module):
    monkeypatch.setattr(
        brain_module.Brain,
        "_call_llm",
        lambda *_args, **_kwargs: pytest.fail("_call_llm must not be called"),
    )
    monkeypatch.setattr(
        brain_module.Brain,
        "_call_llm_stream",
        lambda *_args, **_kwargs: pytest.fail("_call_llm_stream must not be called"),
    )
    monkeypatch.setattr(
        socket,
        "create_connection",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("real network must not be used")),
    )


@pytest.mark.parametrize(
    ("message", "payload_key", "payload_type"),
    [
        ("Victory Philippines 评分是多少？", "response_contract", "score_snapshot"),
        ("Victory Philippines 的关系图谱", "response_contract", "relationship_graph"),
        ("Victory Philippines 怎么联系？", "response_contract", "contact_intelligence"),
        ("Victory Philippines 推荐合作对象有哪些？", "response_contract", "partnership_recommendation"),
        ("What are the next steps for Harbor Church?", "response_contract", "partnership_action_plan"),
        ("Give me an evidence brief for Harbor Church.", "response_contract", "partnership_evidence_brief"),
    ],
)
def test_core_uat_routes_have_response_contract_and_observability(seeded_runtime, monkeypatch, message, payload_key, payload_type):
    brain_module = seeded_runtime["brain_module"]
    _block_llm_and_network(monkeypatch, brain_module)
    brain = brain_module.Brain()

    result = brain.think(message, conversation_id=f"core-uat-{uuid.uuid4().hex}")
    contract = result[payload_key]

    assert contract["payload_type"] == payload_type
    assert contract["observability"]["audit_summary"]["audit_version"] == "6.0E"
    assert contract["observability"]["audit_summary"]["no_llm"] is True
    assert contract["observability"]["audit_summary"]["no_network"] is True
    assert "audit_summary" in contract["observability"]
    assert "trace_events" in contract["observability"]


def test_core_uat_builds_ready_production_report(seeded_runtime, monkeypatch):
    brain_module = seeded_runtime["brain_module"]
    readiness_module = seeded_runtime["readiness_module"]
    _block_llm_and_network(monkeypatch, brain_module)

    brain = brain_module.Brain()
    contracts = [
        brain.think("Victory Philippines 评分是多少？", conversation_id=f"report-score-{uuid.uuid4().hex}")["response_contract"],
        brain.think("Victory Philippines 的关系图谱", conversation_id=f"report-graph-{uuid.uuid4().hex}")["response_contract"],
        brain.think("Victory Philippines 怎么联系？", conversation_id=f"report-contact-{uuid.uuid4().hex}")["response_contract"],
        brain.think("Victory Philippines 推荐合作对象有哪些？", conversation_id=f"report-rec-{uuid.uuid4().hex}")["response_contract"],
        brain.think("What are the next steps for Harbor Church?", conversation_id=f"report-plan-{uuid.uuid4().hex}")["response_contract"],
        brain.think("Give me an evidence brief for Harbor Church.", conversation_id=f"report-brief-{uuid.uuid4().hex}")["response_contract"],
        brain.think("推荐合作对象有哪些？", conversation_id=f"report-fallback-{uuid.uuid4().hex}")["response_contract"],
    ]
    report = readiness_module.ProductionReadinessChecker().build_report(contracts=contracts)

    assert report["status"] == "ready"
    assert all(value == "pass" for value in report["modules"].values())
    assert all(value == "pass" for value in report["contracts"].values())
