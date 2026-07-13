from __future__ import annotations

import importlib
import importlib.util
import os
import sys
import types
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
    "services.brain",
    "services.query_parser",
    "services.intent_router_final",
    "services.organization_resolver",
    "services.brain_orchestrator",
    "services.response_contract",
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
def runtime(tmp_path: Path):
    test_db_path = tmp_path / f"response_contract_reg60c_{uuid.uuid4().hex}.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{test_db_path.as_posix()}"
    _purge_modules()
    importlib.invalidate_caches()

    database = importlib.import_module("models.database")
    importlib.import_module("models.auth")
    importlib.import_module("models.watch_alert")
    _ensure_service_module("brain_orchestrator")
    _ensure_service_module("response_contract")
    brain_module = importlib.import_module("services.brain")
    database.init_db()

    db = database.SessionLocal()
    try:
        db.add(
            database.OrganizationProfile(
                id="org-victory",
                name="Victory Philippines",
                country="Philippines",
                source_name="unit_test_seed",
                official_website="https://victory.org.ph",
                contact_email="info@victory.org.ph",
                phone_public="+63 2 1234 5678",
                people_score=64,
                digital_score=58,
                intel_score=67,
            )
        )
        db.commit()
    finally:
        db.close()

    yield {"brain_module": brain_module, "database": database}

    database.engine.dispose()
    _purge_modules()
    if test_db_path.exists():
        test_db_path.unlink()


def test_trace_and_policy_from_orchestrator_are_preserved(runtime):
    brain = runtime["brain_module"].Brain()
    contract = brain.think("How can I contact Victory Philippines?", conversation_id=f"ready-{uuid.uuid4().hex}")["response_contract"]

    assert [item["step"] for item in contract["trace"]] == [
        "intent_router",
        "organization_resolver",
        "policy_guard",
        "module_dispatcher",
        "final_route_decision",
    ]
    assert contract["selected_module"] == "contact_intelligence"
    assert contract["policy"]["allow_llm"] is False
    assert contract["policy"]["allow_network"] is False
    assert contract["policy"]["allow_fabrication"] is False


def test_missing_org_and_context_reference_do_not_enter_business_module(runtime, monkeypatch):
    brain_module = runtime["brain_module"]
    monkeypatch.setattr(
        brain_module.Brain,
        "_run_orchestrated_lookup",
        lambda *_args, **_kwargs: pytest.fail("_run_orchestrated_lookup must not be called"),
    )

    brain = brain_module.Brain()
    missing_org = brain.think("推荐合作对象有哪些？", conversation_id=f"missing-{uuid.uuid4().hex}")["response_contract"]
    context_ref = brain.think("这个机构怎么联系？", conversation_id=f"context-{uuid.uuid4().hex}")["response_contract"]

    assert missing_org["route_status"] == "ask_clarification"
    assert context_ref["route_status"] == "ask_clarification"
    assert context_ref["fallback_reason"] == "context_reference_requires_previous_organization"


def test_ambiguous_org_and_simple_stream_consistency_do_not_regress(runtime, monkeypatch):
    brain_module = runtime["brain_module"]
    original_decision = {
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

    monkeypatch.setattr(
        brain_module.Brain,
        "_get_orchestration_decision",
        lambda *_args, **_kwargs: dict(original_decision),
    )
    monkeypatch.setattr(
        brain_module.Brain,
        "_run_orchestrated_lookup",
        lambda *_args, **_kwargs: pytest.fail("_run_orchestrated_lookup must not be called"),
    )

    brain = brain_module.Brain()
    simple = brain.think("Victory 怎么联系？", conversation_id=f"simple-{uuid.uuid4().hex}")["response_contract"]
    stream_done = next(
        item
        for item in brain.think_stream("Victory 怎么联系？", f"stream-{uuid.uuid4().hex}")
        if isinstance(item, dict) and item.get("type") == "done"
    )
    stream = stream_done["response_contract"]

    assert simple["route_status"] == stream["route_status"] == "ambiguous"
    assert simple["selected_module"] == stream["selected_module"] == "contact_intelligence"
    assert simple["payload_type"] == stream["payload_type"] == "ambiguous"
