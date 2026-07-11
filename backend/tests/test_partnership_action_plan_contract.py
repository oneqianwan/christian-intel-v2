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
    "services.relation_mapper",
]


def _purge_modules() -> None:
    for module_name in MODULES_TO_PURGE:
        sys.modules.pop(module_name, None)


@pytest.fixture()
def isolated_runtime(tmp_path: Path):
    test_db_path = tmp_path / f"partnership_action_plan_contract_{uuid.uuid4().hex}.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{test_db_path.as_posix()}"
    _purge_modules()

    database = importlib.import_module("models.database")
    importlib.import_module("models.auth")
    importlib.import_module("models.watch_alert")
    planner = importlib.import_module("services.partnership_action_planner")
    database.init_db()

    yield {
        "database": database,
        "planner": planner,
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


def _seed_edge(runtime, *, edge_id: str, source_id: str, target_id: str, relation_type: str = "partner"):
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
            confidence=0.86,
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


def test_build_action_plan_uses_top_recommendation_and_email_channel(isolated_runtime):
    runtime = isolated_runtime
    database = runtime["database"]
    planner = runtime["planner"]

    _seed_org(runtime, org_id="org-source", name="Harbor Church", email="hello@harbor.org", website="https://harbor.org", source_url="https://harbor.org/source")
    _seed_org(runtime, org_id="org-target", name="Bridge Ministry", people_score=78, digital_score=74, intel_score=81, email="connect@bridge.org", phone="+63 2 1234 5678", facebook="https://facebook.com/bridgeorg", website="https://bridge.org", source_url="https://bridge.org/source")
    _seed_edge(runtime, edge_id="edge-source-target", source_id="org-source", target_id="org-target")

    db = database.SessionLocal()
    try:
        payload = planner.build_partnership_action_plan(db=db, org_id="org-source")
    finally:
        db.close()

    assert payload["organization"]["id"] == "org-source"
    assert payload["target_org"]["id"] == "org-target"
    assert payload["summary"]["plan_available"] is True
    assert payload["summary"]["blocked"] is False
    assert payload["summary"]["recommended_channel"] == "email"
    assert payload["summary"]["risk_level"] in {"low", "medium"}
    assert payload["summary"]["confidence"] > 0
    assert payload["evidence"]["recommendation_snapshot"]["target_org_id"] == "org-target"
    assert payload["evidence"]["score_snapshot"] == {"people_score": 78, "digital_score": 74, "intel_score": 81}
    assert payload["evidence"]["relationship_snapshot"]["has_relationship_path"] is True
    assert payload["evidence"]["contact_snapshot"]["has_email"] is True
    assert payload["warnings"]

    steps = payload["action_plan"]
    assert [step["step_number"] for step in steps] == list(range(1, len(steps) + 1))
    assert any(step["action_type"] == "review_relationship" for step in steps)
    assert any(step["action_type"] == "prepare_outreach" for step in steps)
    contact_step = next(step for step in steps if step["action_type"] == "contact")
    assert contact_step["channel"] == "email"
    assert contact_step["uses_contact"]["type"] == "email"
    assert contact_step["uses_contact"]["value"] == "connect@bridge.org"
    assert "contact_source_missing" in contact_step["risk_flags"]
    assert "contact_unverified" in contact_step["risk_flags"]


def test_build_action_plan_supports_target_org_parameter_and_website_channel(isolated_runtime):
    runtime = isolated_runtime
    database = runtime["database"]
    planner = runtime["planner"]

    _seed_org(runtime, org_id="org-source", name="Beacon Network", email="hello@beacon.org", website="https://beacon.org", source_url="https://beacon.org/source")
    _seed_org(runtime, org_id="org-target-email", name="First Partner", people_score=77, digital_score=75, intel_score=80, email="team@firstpartner.org", website="https://firstpartner.org", source_url="https://firstpartner.org/source")
    _seed_org(runtime, org_id="org-target-web", name="Second Partner", people_score=72, digital_score=68, intel_score=70, email=None, phone=None, facebook=None, website="https://secondpartner.org", source_url="https://secondpartner.org/source")
    _seed_edge(runtime, edge_id="edge-source-email", source_id="org-source", target_id="org-target-email")
    _seed_edge(runtime, edge_id="edge-source-web", source_id="org-source", target_id="org-target-web")

    db = database.SessionLocal()
    try:
        payload = planner.build_partnership_action_plan(db=db, org_id="org-source", target_org_id="org-target-web")
    finally:
        db.close()

    assert payload["target_org"]["id"] == "org-target-web"
    assert payload["summary"]["recommended_channel"] == "website"
    assert any(step["action_type"] == "verify_contact" for step in payload["action_plan"])
    contact_steps = [step for step in payload["action_plan"] if step["action_type"] == "contact"]
    if contact_steps:
      assert contact_steps[0]["channel"] == "website"
      assert contact_steps[0]["uses_contact"]["type"] == "website"


def test_build_action_plan_uses_research_first_when_no_contact_and_blocks_direct_contact(isolated_runtime):
    runtime = isolated_runtime
    database = runtime["database"]
    planner = runtime["planner"]

    _seed_org(runtime, org_id="org-source", name="North Ridge Fellowship", email="hello@northridge.org", website="https://northridge.org", source_url="https://northridge.org/source")
    _seed_org(runtime, org_id="org-target", name="Cedar Collective", people_score=66, digital_score=61, intel_score=63, email=None, phone=None, facebook=None, website=None, source_url="https://cedar.example/source")
    _seed_edge(runtime, edge_id="edge-source-target", source_id="org-source", target_id="org-target")

    db = database.SessionLocal()
    try:
        payload = planner.build_partnership_action_plan(db=db, org_id="org-source")
    finally:
        db.close()

    assert payload["summary"]["recommended_channel"] == "research_first"
    assert "missing_contact" in payload["warnings"]
    assert "no_safe_contact_channel" in payload["warnings"]
    assert all(step["action_type"] != "contact" for step in payload["action_plan"])
    assert payload["action_plan"][0]["action_type"] in {"research", "verify_contact"}


def test_missing_scores_lower_confidence_and_target_not_in_recommendations_is_explicit(isolated_runtime):
    runtime = isolated_runtime
    database = runtime["database"]
    planner = runtime["planner"]

    _seed_org(runtime, org_id="org-source", name="Anchor Network", email="hello@anchor.org", website="https://anchor.org", source_url="https://anchor.org/source")
    _seed_org(runtime, org_id="org-strong", name="Partner Strong", people_score=79, digital_score=77, intel_score=80, email="team@partnerstrong.org", website="https://partnerstrong.org", source_url="https://partnerstrong.org/source")
    _seed_org(runtime, org_id="org-missing-scores", name="Partner Missing Scores", people_score=None, digital_score=None, intel_score=None, email="team@missing.org", website="https://missing.org", source_url="https://missing.org/source")
    _seed_org(runtime, org_id="org-manual", name="Manual Review Target", country="Japan", city="Tokyo", denomination="Independent", people_score=30, digital_score=20, intel_score=25, email=None, phone=None, facebook=None, website=None, source_url="https://manual.example/source")
    _seed_edge(runtime, edge_id="edge-source-strong", source_id="org-source", target_id="org-strong")
    _seed_edge(runtime, edge_id="edge-source-missing", source_id="org-source", target_id="org-missing-scores")

    db = database.SessionLocal()
    try:
        strong_payload = planner.build_partnership_action_plan(db=db, org_id="org-source", target_org_id="org-strong")
        missing_payload = planner.build_partnership_action_plan(db=db, org_id="org-source", target_org_id="org-missing-scores")
        manual_payload = planner.build_partnership_action_plan(db=db, org_id="org-source", target_org_id="org-manual")
    finally:
        db.close()

    assert missing_payload["summary"]["confidence"] < strong_payload["summary"]["confidence"]
    assert "missing_scores" in missing_payload["warnings"]
    assert manual_payload["target_org"]["id"] == "org-manual"
    assert "target_not_in_recommendations" in manual_payload["warnings"]
    assert manual_payload["summary"]["recommended_channel"] in {"research_first", "manual_review"}
    assert all(step["action_type"] != "contact" for step in manual_payload["action_plan"])


def test_build_action_plan_returns_blocked_state_when_no_recommendations(isolated_runtime):
    runtime = isolated_runtime
    database = runtime["database"]
    planner = runtime["planner"]

    _seed_org(
        runtime,
        org_id="org-alone",
        name="Quiet Valley Church",
        country="Philippines",
        city="Davao",
        denomination="Independent",
        people_score=40,
        digital_score=35,
        intel_score=32,
        email=None,
        phone=None,
        facebook=None,
        website=None,
        source_url="https://quiet.example/source",
    )

    db = database.SessionLocal()
    try:
        payload = planner.build_partnership_action_plan(db=db, org_id="org-alone")
    finally:
        db.close()

    assert payload["summary"]["blocked"] is True
    assert payload["summary"]["plan_available"] is False
    assert payload["summary"]["step_count"] == 0
    assert "no_recommendation_candidates_found" in payload["summary"]["block_reasons"]
    assert payload["action_plan"] == []
    assert payload["target_org"] is None
