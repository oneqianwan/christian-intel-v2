from __future__ import annotations

import importlib
import importlib.util
import os
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
def seeded_runtime(tmp_path: Path):
    test_db_path = tmp_path / f"response_contract_backward_{uuid.uuid4().hex}.db"
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

    runtime = {"database": database, "brain_module": brain_module}
    _seed_org(runtime, org_id="org-victory", name="Victory Philippines")
    _seed_org(runtime, org_id="org-harbor", name="Harbor Church", contact_email="hello@harbor.org", source_url="https://harbor.org/source")
    _seed_org(runtime, org_id="org-bridge", name="Bridge Ministry", people_score=78, digital_score=74, intel_score=81, contact_email="connect@bridge.org", source_url="https://bridge.org/source")
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


def test_existing_payload_keys_remain_additive(seeded_runtime):
    brain = seeded_runtime["brain_module"].Brain()

    score = brain.think("Show me Victory Philippines scores", conversation_id=f"score-{uuid.uuid4().hex}")
    graph = brain.think("Who are Harbor Church partners?", conversation_id=f"graph-{uuid.uuid4().hex}")
    contact = brain.think("How can I contact Victory Philippines?", conversation_id=f"contact-{uuid.uuid4().hex}")
    recommendation = brain.think("Who should Victory Philippines partner with?", conversation_id=f"rec-{uuid.uuid4().hex}")
    action_plan = brain.think("What are the next steps for Harbor Church?", conversation_id=f"action-{uuid.uuid4().hex}")
    evidence = brain.think("Give me an evidence brief for Harbor Church.", conversation_id=f"evidence-{uuid.uuid4().hex}")

    assert "answer" in score and "evidence" in score and "response_contract" in score
    assert "relationship_graph" in graph and "response_contract" in graph
    assert "contact_lookup" in contact and "response_contract" in contact
    assert "partnership_recommendations" in recommendation and "response_contract" in recommendation
    assert "partnership_action_plan" in action_plan and "response_contract" in action_plan
    assert "partnership_evidence_brief" in evidence and "response_contract" in evidence

    assert graph["relationship_graph"] == graph["response_contract"]["legacy_payload"]
    assert contact["contact_lookup"] == contact["response_contract"]["legacy_payload"]
    assert recommendation["partnership_recommendations"] == recommendation["response_contract"]["legacy_payload"]
    assert action_plan["partnership_action_plan"] == action_plan["response_contract"]["legacy_payload"]
    assert evidence["partnership_evidence_brief"] == evidence["response_contract"]["legacy_payload"]
