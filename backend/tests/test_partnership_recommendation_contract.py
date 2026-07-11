from __future__ import annotations

import importlib
import os
import sys
import uuid
from datetime import date, datetime, timedelta
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
    "services.relation_mapper",
]


def _purge_modules() -> None:
    for module_name in MODULES_TO_PURGE:
        sys.modules.pop(module_name, None)


@pytest.fixture()
def isolated_runtime(tmp_path: Path):
    test_db_path = tmp_path / f"partnership_recommendation_contract_{uuid.uuid4().hex}.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{test_db_path.as_posix()}"
    _purge_modules()

    database = importlib.import_module("models.database")
    importlib.import_module("models.auth")
    importlib.import_module("models.watch_alert")
    recommender = importlib.import_module("services.partnership_recommender")
    database.init_db()

    yield {
        "database": database,
        "recommender": recommender,
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
    digital_score: int | None = 50,
    intel_score: int | None = 55,
    website: str | None = "https://example.org",
    email: str | None = None,
    phone: str | None = None,
    facebook: str | None = None,
    source_url: str | None = "https://example.org/source",
    source_name: str | None = "unit_test_seed",
    updated_at: datetime | None = None,
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
            updated_at=updated_at or datetime.utcnow(),
        )
        db.add(org)
        db.commit()
        db.refresh(org)
        return org
    finally:
        db.close()


def _seed_edge(runtime, *, edge_id: str, source_id: str, target_id: str, relation_type: str = "partner", confidence: float = 0.82):
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


def test_build_partnership_recommendations_returns_rule_based_candidates(isolated_runtime):
    runtime = isolated_runtime
    database = runtime["database"]
    recommender = runtime["recommender"]

    _seed_org(
        runtime,
        org_id="org-source",
        name="Harbor Church",
        country="Philippines",
        city="Manila",
        denomination="Evangelical",
        people_score=62,
        digital_score=48,
        intel_score=66,
        website="https://harbor.org",
        source_url="https://harbor.org/source",
    )
    _seed_org(
        runtime,
        org_id="org-ally-strong",
        name="Bridge Ministry",
        country="Philippines",
        city="Manila",
        denomination="Evangelical",
        people_score=78,
        digital_score=74,
        intel_score=81,
        website="https://bridge.org",
        email="connect@bridge.org",
        phone="+63 2 1234 5678",
        facebook="https://facebook.com/bridgeorg",
        source_url="https://bridge.org/source",
    )
    _seed_org(
        runtime,
        org_id="org-ally-weak",
        name="Waypoint Collective",
        country="Philippines",
        city="Cebu",
        denomination="Evangelical",
        people_score=None,
        digital_score=None,
        intel_score=None,
        website=None,
        email=None,
        phone=None,
        facebook=None,
        source_url=None,
        source_name=None,
        updated_at=datetime.utcnow() - timedelta(days=500),
    )
    _seed_edge(runtime, edge_id="edge-source-bridge", source_id="org-source", target_id="org-ally-strong")

    db = database.SessionLocal()
    try:
        payload = recommender.build_partnership_recommendations(db=db, org_id="org-source", limit=10)
    finally:
        db.close()

    assert payload["found"] is True
    assert payload["organization"]["id"] == "org-source"
    assert payload["summary"]["candidate_count"] >= 2
    assert payload["summary"]["recommended_count"] >= 2
    assert len(payload["recommendations"]) >= 2

    strong = next(item for item in payload["recommendations"] if item["target_org"]["id"] == "org-ally-strong")
    weak = next(item for item in payload["recommendations"] if item["target_org"]["id"] == "org-ally-weak")

    assert 0 <= strong["recommendation_score"] <= 100
    assert strong["priority"] in {"high", "medium", "low"}
    assert strong["reason_codes"]
    assert "Bridge Ministry" not in strong["explanation"]
    assert strong["score_snapshot"] == {"people_score": 78, "digital_score": 74, "intel_score": 81}
    assert strong["relationship_snapshot"]["has_relationship_path"] is True
    assert strong["relationship_snapshot"]["relationship_count"] == 1
    assert strong["contact_snapshot"]["has_email"] is True
    assert strong["contact_snapshot"]["has_phone"] is True
    assert strong["contact_snapshot"]["has_social"] is True
    assert strong["recommended_next_action"] == "contact"

    assert weak["confidence"] < strong["confidence"]
    assert "missing_scores" in weak["risks"]
    assert "missing_contact" in weak["risks"]
    assert "stale_data" in weak["warnings"]
    assert weak["recommended_next_action"] in {"research_more", "review_manually", "skip"}


def test_build_partnership_recommendations_returns_empty_without_fabrication(isolated_runtime):
    runtime = isolated_runtime
    database = runtime["database"]
    recommender = runtime["recommender"]

    _seed_org(
        runtime,
        org_id="org-alone",
        name="North Ridge Church",
        country="Philippines",
        city="Davao",
        denomination="Independent",
        people_score=40,
        digital_score=35,
        intel_score=32,
    )

    db = database.SessionLocal()
    try:
        payload = recommender.build_partnership_recommendations(db=db, org_id="org-alone", limit=10)
    finally:
        db.close()

    assert payload["found"] is True
    assert payload["recommendations"] == []
    assert payload["summary"]["candidate_count"] == 0
    assert "no_recommendation_candidates_found" in payload["warnings"]
