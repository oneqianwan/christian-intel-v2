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
    "services.relation_mapper",
]


def _purge_modules() -> None:
    for module_name in MODULES_TO_PURGE:
        sys.modules.pop(module_name, None)


@pytest.fixture()
def isolated_runtime(tmp_path: Path):
    test_db_path = tmp_path / f"org_detail_recommendations_{uuid.uuid4().hex}.db"
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


def test_org_detail_recommendations_api_returns_structured_payload(isolated_runtime):
    runtime = isolated_runtime
    client = runtime["client"]

    _seed_org(runtime, org_id="org-source", name="Harbor Church", email="hello@harbor.org", phone="+63 2 1111 2222", website="https://harbor.org", source_url="https://harbor.org/source")
    _seed_org(runtime, org_id="org-target", name="Bridge Ministry", email="connect@bridge.org", phone="+63 2 1234 5678", website="https://bridge.org", source_url="https://bridge.org/source")
    _seed_edge(runtime, edge_id="edge-harbor-bridge", source_id="org-source", target_id="org-target")

    response = client.get("/api/dashboard/org/org-source/recommendations")
    assert response.status_code == 200

    payload = response.json()
    assert payload["found"] is True
    assert payload["organization"]["id"] == "org-source"
    assert "summary" in payload
    assert "recommendations" in payload
    assert "warnings" in payload
    assert payload["summary"]["recommended_count"] >= 1

    recommendation = next(item for item in payload["recommendations"] if item["target_org"]["id"] == "org-target")
    assert 0 <= recommendation["recommendation_score"] <= 100
    assert recommendation["priority"] in {"high", "medium", "low"}
    assert recommendation["reason_codes"]
    assert "score_snapshot" in recommendation
    assert "relationship_snapshot" in recommendation
    assert "contact_snapshot" in recommendation
    assert "risks" in recommendation
    assert "warnings" in recommendation


def test_org_detail_recommendations_api_returns_empty_without_candidates(isolated_runtime):
    runtime = isolated_runtime
    client = runtime["client"]

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

    response = client.get("/api/dashboard/org/org-alone/recommendations")
    assert response.status_code == 200

    payload = response.json()
    assert payload["recommendations"] == []
    assert "no_recommendation_candidates_found" in payload["warnings"]


def test_org_detail_recommendations_api_returns_404_for_missing_org(isolated_runtime):
    runtime = isolated_runtime
    client = runtime["client"]

    response = client.get("/api/dashboard/org/org-missing/recommendations")
    assert response.status_code == 404
    assert response.json()["detail"] == "Organization not found"
