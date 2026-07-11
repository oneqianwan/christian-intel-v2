from __future__ import annotations

import importlib
import os
import sys
import uuid
from datetime import date, datetime
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
def isolated_runtime(tmp_path: Path):
    test_db_path = tmp_path / f"partnership_evidence_brief_contract_{uuid.uuid4().hex}.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{test_db_path.as_posix()}"
    _purge_modules()

    database = importlib.import_module("models.database")
    importlib.import_module("models.auth")
    importlib.import_module("models.watch_alert")
    brief_module = importlib.import_module("services.partnership_evidence_brief")
    database.init_db()

    yield {
        "database": database,
        "brief_module": brief_module,
        "db_path": test_db_path,
    }

    database.engine.dispose()
    _purge_modules()
    if test_db_path.exists():
        test_db_path.unlink()


def _seed_org(
    runtime,
    *,
    org_id: str,
    name: str,
    country: str = "Philippines",
    city: str = "Manila",
    denomination: str = "Evangelical",
    people_score: int | None = 60,
    digital_score: int | None = 55,
    intel_score: int | None = 62,
    website: str | None = "https://example.org",
    email: str | None = None,
    phone: str | None = None,
    facebook: str | None = None,
    source_url: str | None = "https://example.org/source",
    source_name: str | None = "unit_test_seed",
):
    database = runtime["database"]
    db = database.SessionLocal()
    try:
        org = database.OrganizationProfile(
            id=org_id,
            name=name,
            country=country,
            city=city,
            denomination=denomination,
            people_score=people_score,
            digital_score=digital_score,
            intel_score=intel_score,
            official_website=website,
            contact_email=email,
            phone_public=phone,
            facebook_url=facebook,
            source_url=source_url,
            source_name=source_name,
            updated_at=datetime.utcnow(),
        )
        db.add(org)
        db.commit()
        db.refresh(org)
        return org
    finally:
        db.close()


def _seed_edge(runtime, *, edge_id: str, source_id: str, target_id: str, relation_type: str = "partner", confidence: float = 0.86):
    database = runtime["database"]
    db = database.SessionLocal()
    try:
        edge = database.RelationEdge(
            id=edge_id,
            source_id=source_id,
            target_id=target_id,
            source_type="organization",
            target_type="organization",
            relation_type=relation_type,
            confidence=confidence,
            is_verified=True,
            evidence_url=f"https://evidence.example/{edge_id}",
            evidence_source="unit_test_evidence",
            evidence_date=date(2026, 7, 11),
        )
        db.add(edge)
        db.commit()
        db.refresh(edge)
        return edge
    finally:
        db.close()


def test_build_partnership_evidence_brief_returns_structured_brief_for_top_recommendation(isolated_runtime):
    runtime = isolated_runtime
    database = runtime["database"]
    brief_module = runtime["brief_module"]

    _seed_org(runtime, org_id="org-source", name="Harbor Church", email="hello@harbor.org", website="https://harbor.org", source_url="https://harbor.org/source")
    _seed_org(runtime, org_id="org-target", name="Bridge Ministry", people_score=78, digital_score=74, intel_score=81, email="connect@bridge.org", phone="+63 2 1234 5678", facebook="https://facebook.com/bridgeorg", website="https://bridge.org", source_url="https://bridge.org/source")
    _seed_edge(runtime, edge_id="edge-source-target", source_id="org-source", target_id="org-target")

    db = database.SessionLocal()
    try:
        payload = brief_module.build_partnership_evidence_brief(db=db, org_id="org-source")
    finally:
        db.close()

    assert payload["organization"]["id"] == "org-source"
    assert payload["target_org"]["id"] == "org-target"
    assert payload["summary"]["brief_available"] is True
    assert payload["summary"]["decision"] in {"proceed", "research_more", "manual_review", "do_not_contact"}
    assert payload["summary"]["priority"] in {"high", "medium", "low"}
    assert 0.0 <= payload["summary"]["confidence"] <= 1.0
    assert payload["summary"]["risk_level"] in {"low", "medium", "high"}
    assert "recommended_channel" in payload["summary"]
    assert payload["decision_rationale"]["headline"]
    assert isinstance(payload["decision_rationale"]["reason_codes"], list)
    assert isinstance(payload["decision_rationale"]["supporting_points"], list)
    assert isinstance(payload["decision_rationale"]["limiting_factors"], list)
    assert set(payload["evidence_sections"].keys()) == {
        "score_evidence",
        "relationship_evidence",
        "contact_evidence",
        "recommendation_evidence",
        "action_plan_evidence",
    }
    assert payload["evidence_sections"]["score_evidence"]["people_score"] == 78
    assert payload["evidence_sections"]["relationship_evidence"]["has_relationship_path"] is True
    assert payload["evidence_sections"]["contact_evidence"]["recommended_contact"]["type"] == "email"
    assert payload["evidence_sections"]["recommendation_evidence"]["recommendation_score"] >= 0
    assert payload["evidence_sections"]["action_plan_evidence"]["step_count"] >= 1
    assert payload["risk_register"]
    assert all(set(item.keys()) == {"risk_code", "severity", "description", "mitigation"} for item in payload["risk_register"])
    assert payload["recommended_next_actions"]
    assert payload["recommended_next_actions"] == payload["evidence_sections"]["action_plan_evidence"]["first_steps"]
    assert payload["do_not_proceed_if"]
    assert payload["audit"]["generated_by"] == "rule_based_evidence_brief"
    assert payload["audit"]["no_llm"] is True


def test_build_partnership_evidence_brief_supports_target_org_parameter_and_explicit_warning(isolated_runtime):
    runtime = isolated_runtime
    database = runtime["database"]
    brief_module = runtime["brief_module"]

    _seed_org(runtime, org_id="org-source", name="Beacon Network", email="hello@beacon.org", website="https://beacon.org", source_url="https://beacon.org/source")
    _seed_org(runtime, org_id="org-target-a", name="First Partner", people_score=78, digital_score=76, intel_score=80, email="team@first.org", website="https://first.org", source_url="https://first.org/source")
    _seed_org(runtime, org_id="org-target-b", name="Second Partner", country="Japan", city="Tokyo", denomination="Independent", people_score=52, digital_score=48, intel_score=45, email=None, phone=None, facebook=None, website=None, source_url="https://second.org/source")
    _seed_edge(runtime, edge_id="edge-source-a", source_id="org-source", target_id="org-target-a")

    db = database.SessionLocal()
    try:
        payload = brief_module.build_partnership_evidence_brief(db=db, org_id="org-source", target_org_id="org-target-b")
    finally:
        db.close()

    assert payload["target_org"]["id"] == "org-target-b"
    assert payload["summary"]["brief_available"] is True
    assert "target_not_in_recommendations" in payload["warnings"]
    assert payload["summary"]["decision"] != "proceed"
    assert payload["evidence_sections"]["contact_evidence"]["recommended_contact"] is None
    assert payload["evidence_sections"]["relationship_evidence"]["relationship_path_summary"] == []


def test_build_partnership_evidence_brief_returns_unavailable_when_no_recommendation_candidates(isolated_runtime):
    runtime = isolated_runtime
    database = runtime["database"]
    brief_module = runtime["brief_module"]

    _seed_org(runtime, org_id="org-alone", name="Quiet Valley Church", country="Philippines", city="Davao", denomination="Independent", people_score=40, digital_score=35, intel_score=32, email=None, phone=None, facebook=None, website=None, source_url="https://quiet.example/source")

    db = database.SessionLocal()
    try:
        payload = brief_module.build_partnership_evidence_brief(db=db, org_id="org-alone")
    finally:
        db.close()

    assert payload["summary"]["brief_available"] is False
    assert payload["summary"]["decision"] == "research_more"
    assert payload["target_org"] is None
    assert "no_recommendation_candidates_found" in payload["warnings"]
    assert payload["recommended_next_actions"] == ["research_more"]


def test_missing_evidence_lowers_confidence_and_high_risk_prevents_proceed(isolated_runtime):
    runtime = isolated_runtime
    database = runtime["database"]
    brief_module = runtime["brief_module"]

    _seed_org(runtime, org_id="org-source", name="Anchor Network", email="hello@anchor.org", website="https://anchor.org", source_url="https://anchor.org/source")
    _seed_org(runtime, org_id="org-strong", name="Partner Strong", people_score=79, digital_score=77, intel_score=80, email="team@partnerstrong.org", phone="+63 2 1234 5678", website="https://partnerstrong.org", source_url="https://partnerstrong.org/source")
    _seed_org(runtime, org_id="org-risky", name="Partner Risky", people_score=None, digital_score=None, intel_score=None, email=None, phone=None, facebook=None, website=None, source_url="https://risky.example/source")
    _seed_edge(runtime, edge_id="edge-source-strong", source_id="org-source", target_id="org-strong")
    _seed_edge(runtime, edge_id="edge-source-risky", source_id="org-source", target_id="org-risky")

    db = database.SessionLocal()
    try:
        strong_payload = brief_module.build_partnership_evidence_brief(db=db, org_id="org-source", target_org_id="org-strong")
        risky_payload = brief_module.build_partnership_evidence_brief(db=db, org_id="org-source", target_org_id="org-risky")
    finally:
        db.close()

    assert risky_payload["summary"]["confidence"] < strong_payload["summary"]["confidence"]
    assert risky_payload["summary"]["decision"] != "proceed"
    assert risky_payload["summary"]["risk_level"] == "high"
    assert "missing_scores" in risky_payload["warnings"]
    assert "missing_contact" in risky_payload["warnings"]
    assert "no_safe_contact_channel" in risky_payload["warnings"]
