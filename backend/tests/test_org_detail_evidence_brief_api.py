from __future__ import annotations

import importlib
import os
import sys
import uuid
from datetime import date, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


MODULES_TO_PURGE = [
    "config",
    "main",
    "models",
    "models.database",
    "models.auth",
    "models.watch_alert",
    "models.schemas",
    "routers",
    "routers.org_detail",
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
    test_db_path = tmp_path / f"org_detail_evidence_brief_{uuid.uuid4().hex}.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{test_db_path.as_posix()}"
    os.environ["AUTH_CORS_ALLOW_ORIGINS"] = "http://127.0.0.1:4173"
    _purge_modules()

    database = importlib.import_module("models.database")
    importlib.import_module("models.auth")
    importlib.import_module("models.watch_alert")
    main = importlib.import_module("main")
    database.init_db()

    client_ctx = TestClient(main.app)
    client = client_ctx.__enter__()

    yield {
        "database": database,
        "client": client,
        "db_path": test_db_path,
    }

    client_ctx.__exit__(None, None, None)
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


def _seed_edge(runtime, *, edge_id: str, source_id: str, target_id: str):
    database = runtime["database"]
    db = database.SessionLocal()
    try:
        edge = database.RelationEdge(
            id=edge_id,
            source_id=source_id,
            target_id=target_id,
            source_type="organization",
            target_type="organization",
            relation_type="partner",
            confidence=0.88,
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


def test_org_detail_evidence_brief_api_returns_structured_payload(isolated_runtime):
    runtime = isolated_runtime
    client = runtime["client"]

    _seed_org(runtime, org_id="org-source", name="Harbor Church", email="hello@harbor.org", website="https://harbor.org", source_url="https://harbor.org/source")
    _seed_org(runtime, org_id="org-target", name="Bridge Ministry", people_score=78, digital_score=74, intel_score=81, email="connect@bridge.org", phone="+63 2 1234 5678", website="https://bridge.org", source_url="https://bridge.org/source")
    _seed_edge(runtime, edge_id="edge-source-target", source_id="org-source", target_id="org-target")

    response = client.get("/api/dashboard/org/org-source/evidence-brief")
    assert response.status_code == 200
    payload = response.json()

    assert payload["organization"]["id"] == "org-source"
    assert payload["target_org"]["id"] == "org-target"
    assert "summary" in payload
    assert "evidence_sections" in payload
    assert "risk_register" in payload
    assert "audit" in payload
    assert "warnings" in payload
    assert payload["summary"]["brief_available"] is True
    assert payload["audit"]["no_llm"] is True


def test_org_detail_evidence_brief_api_supports_target_org_parameter(isolated_runtime):
    runtime = isolated_runtime
    client = runtime["client"]

    _seed_org(runtime, org_id="org-source", name="Beacon Network", email="hello@beacon.org", website="https://beacon.org", source_url="https://beacon.org/source")
    _seed_org(runtime, org_id="org-target-a", name="First Partner", people_score=78, digital_score=76, intel_score=80, email="team@first.org", website="https://first.org", source_url="https://first.org/source")
    _seed_org(runtime, org_id="org-target-b", name="Second Partner", people_score=58, digital_score=53, intel_score=55, email="team@second.org", website="https://second.org", source_url="https://second.org/source")
    _seed_edge(runtime, edge_id="edge-source-a", source_id="org-source", target_id="org-target-a")
    _seed_edge(runtime, edge_id="edge-source-b", source_id="org-source", target_id="org-target-b")

    response = client.get("/api/dashboard/org/org-source/evidence-brief?target_org_id=org-target-b")
    assert response.status_code == 200
    assert response.json()["target_org"]["id"] == "org-target-b"


def test_org_detail_evidence_brief_api_returns_404_for_missing_org_and_target(isolated_runtime):
    runtime = isolated_runtime
    client = runtime["client"]
    _seed_org(runtime, org_id="org-source", name="Harbor Church", email="hello@harbor.org", website="https://harbor.org", source_url="https://harbor.org/source")

    missing_org = client.get("/api/dashboard/org/org-missing/evidence-brief")
    missing_target = client.get("/api/dashboard/org/org-source/evidence-brief?target_org_id=org-target-missing")

    assert missing_org.status_code == 404
    assert missing_org.json()["detail"] == "Organization not found"
    assert missing_target.status_code == 404
    assert missing_target.json()["detail"] == "Target organization not found"


def test_org_detail_evidence_brief_api_returns_unavailable_brief_without_recommendations(isolated_runtime):
    runtime = isolated_runtime
    client = runtime["client"]
    _seed_org(runtime, org_id="org-alone", name="Quiet Valley Church", country="Philippines", city="Davao", denomination="Independent", people_score=40, digital_score=35, intel_score=32, email=None, phone=None, website=None, source_url="https://quiet.example/source")

    response = client.get("/api/dashboard/org/org-alone/evidence-brief")
    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"]["brief_available"] is False
    assert payload["summary"]["decision"] == "research_more"
    assert "no_recommendation_candidates_found" in payload["warnings"]
