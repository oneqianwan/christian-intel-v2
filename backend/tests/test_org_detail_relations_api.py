from __future__ import annotations

import importlib
import json
import os
import sys
import uuid
from datetime import date
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
    "models.schemas",
    "routers",
    "routers.org_detail",
    "services",
    "services.relation_mapper",
]


def _purge_modules() -> None:
    for module_name in MODULES_TO_PURGE:
        sys.modules.pop(module_name, None)


@pytest.fixture()
def isolated_runtime(tmp_path: Path):
    test_db_path = tmp_path / f"org_detail_relations_{uuid.uuid4().hex}.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{test_db_path.as_posix()}"
    os.environ["AUTH_CORS_ALLOW_ORIGINS"] = "http://127.0.0.1:4173"
    _purge_modules()

    database = importlib.import_module("models.database")
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
    state_province: str = "Metro Manila",
    denomination: str = "Evangelical",
    people_score: int = 60,
    digital_score: int = 40,
    intel_score: int = 55,
):
    database = runtime["database"]
    db = database.SessionLocal()
    try:
        org = database.OrganizationProfile(
            id=org_id,
            name=name,
            country=country,
            state_province=state_province,
            denomination=denomination,
            people_score=people_score,
            digital_score=digital_score,
            intel_score=intel_score,
            source_name="unit_test",
            source_url=f"https://{org_id}.example.com/source",
            data_sources_json=json.dumps([{"source": "unit_test_seed"}]),
        )
        db.add(org)
        db.commit()
        db.refresh(org)
        return org
    finally:
        db.close()


def _seed_edge(
    runtime,
    *,
    edge_id: str,
    source_id: str,
    target_id: str,
    relation_type: str,
    confidence: float = 0.82,
    is_verified: bool = True,
    evidence_url: str | None = "https://example.com/partner-proof",
    evidence_source: str | None = "Public partnership page",
):
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
            is_verified=is_verified,
            evidence_url=evidence_url,
            evidence_source=evidence_source,
            evidence_date=date(2026, 7, 10) if evidence_url else None,
        )
        db.add(edge)
        db.commit()
        db.refresh(edge)
        return edge
    finally:
        db.close()


def test_org_detail_relations_api_returns_graph_payload(isolated_runtime):
    runtime = isolated_runtime
    client = runtime["client"]
    _seed_org(runtime, org_id="org-center", name="Victory Philippines", people_score=64, digital_score=28, intel_score=65)
    _seed_org(runtime, org_id="org-ally", name="Life.Church", people_score=70, digital_score=50, intel_score=60)
    _seed_edge(runtime, edge_id="edge-verified", source_id="org-center", target_id="org-ally", relation_type="partner")

    response = client.get("/api/dashboard/org/org-center/relations")
    assert response.status_code == 200

    payload = response.json()
    assert payload["total"] == 1
    assert len(payload["relations"]) == 1
    graph = payload["graph"]
    assert graph["center"]["id"] == "org-center"
    assert graph["center"]["name"] == "Victory Philippines"
    assert len(graph["nodes"]) == 1
    assert graph["nodes"][0]["entity_id"] == "org-ally"
    assert graph["nodes"][0]["name"] == "Life.Church"
    assert len(graph["edges"]) == 1
    assert graph["edges"][0]["id"] == "edge:edge-verified"
    assert graph["edges"][0]["evidence_url"] == "https://example.com/partner-proof"
    assert graph["edges"][0]["evidence_source"] == "Public partnership page"
    assert graph["edges"][0]["confidence"] == 0.82
    assert graph["edges"][0]["is_verified"] is True
    assert graph["summary"] == {
        "node_count": 2,
        "edge_count": 1,
        "verified_edge_count": 1,
        "unverified_edge_count": 0,
        "missing_evidence_count": 0,
    }


def test_org_detail_relations_api_returns_empty_graph_without_fabrication(isolated_runtime):
    runtime = isolated_runtime
    client = runtime["client"]
    _seed_org(runtime, org_id="org-solo", name="Solo Ministry", people_score=50, digital_score=20, intel_score=30)

    response = client.get("/api/dashboard/org/org-solo/relations")
    assert response.status_code == 200

    payload = response.json()
    assert payload["total"] == 0
    assert payload["relations"] == []
    assert payload["graph"]["center"]["id"] == "org-solo"
    assert payload["graph"]["nodes"] == []
    assert payload["graph"]["edges"] == []
    assert payload["graph"]["summary"] == {
        "node_count": 1,
        "edge_count": 0,
        "verified_edge_count": 0,
        "unverified_edge_count": 0,
        "missing_evidence_count": 0,
    }
    assert any(warning["code"] == "no_relations" for warning in payload["graph"]["warnings"])


def test_org_detail_relations_api_returns_404_for_missing_org(isolated_runtime):
    runtime = isolated_runtime
    client = runtime["client"]

    response = client.get("/api/dashboard/org/org-missing/relations")
    assert response.status_code == 404
    assert response.json()["detail"] == "Organization not found"
