from __future__ import annotations

import importlib
import importlib.util
import os
import socket
import sys
import types
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


def _ensure_service_module(module_name: str):
    full_name = f"services.{module_name}"
    if full_name in sys.modules:
        return sys.modules[full_name]
    package = sys.modules.get("services")
    if package is None:
        package = types.ModuleType("services")
        package.__path__ = [str(BACKEND_DIR / "services")]
        sys.modules["services"] = package
    module_path = BACKEND_DIR / "services" / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(full_name, module_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = module
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def runtime(tmp_path: Path, monkeypatch):
    test_db_path = tmp_path / f"final_commercial_uat_{uuid.uuid4().hex}.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{test_db_path.as_posix()}")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")
    _purge_modules()

    database = importlib.import_module("models.database")
    importlib.import_module("models.auth")
    importlib.import_module("models.watch_alert")
    _ensure_service_module("query_parser")
    _ensure_service_module("intent_router_final")
    _ensure_service_module("organization_resolver")
    _ensure_service_module("brain_orchestrator")
    brain_module = importlib.import_module("services.brain")
    _ensure_service_module("audit_trail")
    _ensure_service_module("observability")
    _ensure_service_module("response_contract")
    readiness_module = _ensure_service_module("production_readiness")
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
    _seed_edge(runtime, edge_id="edge-victory-bridge", source_id="org-victory", target_id="org-bridge")
    _seed_org(runtime, org_id="org-victory-church", name="Victory Church", source_url="https://victory-church.example/source")

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
    contact_email: str | None = "hello@example.org",
    phone_public: str | None = "+63 2 1234 5678",
    facebook_url: str | None = "https://facebook.com/exampleorg",
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


def _simple_and_stream_contracts(brain_module, message: str):
    brain = brain_module.Brain()
    simple = brain.think(message, conversation_id=f"simple-{uuid.uuid4().hex}")["response_contract"]
    stream_done = next(
        item
        for item in brain.think_stream(message, f"stream-{uuid.uuid4().hex}")
        if isinstance(item, dict) and item.get("type") == "done"
    )
    return simple, stream_done["response_contract"]


@pytest.mark.parametrize(
    ("message", "route_status_values", "payload_type_values"),
    [
        ("Victory Philippines 评分是多少？", {"ready"}, {"score_snapshot"}),
        ("Victory Philippines 的关系图谱", {"ready"}, {"relationship_graph"}),
        ("Victory Philippines 怎么联系？", {"ready"}, {"contact_intelligence"}),
        ("Victory Philippines 推荐合作对象有哪些？", {"ready"}, {"partnership_recommendation"}),
        ("What are the next steps for Victory Philippines?", {"ready"}, {"partnership_action_plan"}),
        ("Give me an evidence brief for Victory Philippines.", {"ready"}, {"partnership_evidence_brief"}),
        ("这个机构怎么联系？", {"ask_clarification"}, {"ask_clarification"}),
        ("推荐合作对象有哪些？", {"ask_clarification"}, {"ask_clarification"}),
        ("随便帮我看看", {"unsupported", "ask_clarification"}, {"unsupported", "ask_clarification"}),
    ],
)
def test_final_commercial_core_uat_simple_stream_consistency(runtime, monkeypatch, message, route_status_values, payload_type_values):
    brain_module = runtime["brain_module"]
    _block_llm_and_network(monkeypatch, brain_module)

    simple, stream = _simple_and_stream_contracts(brain_module, message)
    assert simple["route_status"] == stream["route_status"]
    assert simple["route_status"] in route_status_values
    assert simple["payload_type"] == stream["payload_type"]
    assert simple["payload_type"] in payload_type_values
    assert simple["intent"] == stream["intent"]
    assert simple["selected_module"] == stream["selected_module"]
    assert simple["policy"]["allow_llm"] is False
    assert simple["policy"]["allow_network"] is False
    assert simple["policy"]["allow_fabrication"] is False
    assert simple["observability"]["audit_summary"]["no_llm"] is True
    assert simple["observability"]["audit_summary"]["no_network"] is True


def test_final_commercial_core_uat_ambiguous_org_safe_fallback(runtime, monkeypatch):
    brain_module = runtime["brain_module"]
    _block_llm_and_network(monkeypatch, brain_module)

    def fake_decision(_self, _message, _conversation_id):
        return {
            "query": "Victory 怎么联系？",
            "normalized_query": "victory 怎么联系",
            "route_status": "ambiguous",
            "selected_intent": "organization_contact_lookup",
            "selected_module": "contact_intelligence",
            "organization_name": None,
            "target_organization_name": None,
            "missing_parameters": ["organization_name"],
            "candidate_intents": [{"intent": "organization_contact_lookup"}],
            "candidate_organizations": [
                {"name": "Victory Philippines", "canonical_name": "Victory Philippines", "organization_id": None},
                {"name": "Victory Church", "canonical_name": "Victory Church", "organization_id": None},
            ],
            "requires_clarification": True,
            "clarification_prompt": "我找到了多个可能机构，请选择。",
            "warnings": ["multiple_organization_candidates"],
            "reason_codes": ["multiple_organization_candidates_detected"],
            "policy": {
                "db_first": True,
                "allow_llm": False,
                "allow_network": False,
                "allow_fabrication": False,
            },
            "dispatch": {
                "module": "contact_intelligence",
                "method": None,
                "payload_type": "contact_intelligence",
                "required_parameters": ["organization_name"],
                "optional_parameters": [],
            },
            "intent_result": {"confidence": 0.76},
            "organization_resolution": {
                "organization_name": None,
                "canonical_name": None,
                "organization_id": None,
                "resolution_status": "ambiguous",
                "confidence": 0.76,
                "context_reference": False,
            },
            "target_organization_resolution": {
                "target_organization_name": None,
                "target_organization_id": None,
                "target_canonical_name": None,
                "target_candidates": [],
            },
            "trace": [
                {"step": "intent_router", "status": "pass", "reason_codes": ["contact_keyword_detected"]},
                {"step": "organization_resolver", "status": "blocked", "reason_codes": ["multiple_organization_candidates_detected"]},
                {"step": "policy_guard", "status": "pass", "reason_codes": ["llm_disabled"]},
                {"step": "module_dispatcher", "status": "blocked", "reason_codes": ["route_status_ambiguous"]},
                {"step": "final_route_decision", "status": "blocked", "reason_codes": ["route_status_ambiguous"]},
            ],
        }

    monkeypatch.setattr(brain_module.Brain, "_get_orchestration_decision", fake_decision)
    monkeypatch.setattr(
        brain_module.Brain,
        "_run_orchestrated_lookup",
        lambda *_args, **_kwargs: pytest.fail("_run_orchestrated_lookup must not be called"),
    )

    simple, stream = _simple_and_stream_contracts(brain_module, "Victory 怎么联系？")
    assert simple["route_status"] == stream["route_status"] == "ambiguous"
    assert simple["data_found"] is False
    assert stream["data_found"] is False
    assert simple["organization"]["organization_id"] is None
    assert stream["organization"]["organization_id"] is None


def test_final_commercial_report_marks_demo_and_internal_beta_ready(runtime, monkeypatch):
    brain_module = runtime["brain_module"]
    _block_llm_and_network(monkeypatch, brain_module)

    contracts = []
    for message in [
        "Victory Philippines 评分是多少？",
        "Victory Philippines 的关系图谱",
        "Victory Philippines 怎么联系？",
        "Victory Philippines 推荐合作对象有哪些？",
        "What are the next steps for Victory Philippines?",
        "Give me an evidence brief for Victory Philippines.",
        "推荐合作对象有哪些？",
    ]:
        contracts.append(brain_module.Brain().think(message, conversation_id=f"readiness-{uuid.uuid4().hex}")["response_contract"])

    report = runtime["readiness_module"].ProductionReadinessChecker().build_report(contracts=contracts)
    assert report["readiness_version"] == "6.0F"
    assert report["commercial_readiness"]["demo_ready"] is True
    assert report["commercial_readiness"]["internal_beta_ready"] is True
    assert report["commercial_readiness"]["public_saas_ready"] is False
