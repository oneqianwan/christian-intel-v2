from __future__ import annotations

import importlib
import json
import os
import sys
import uuid
from datetime import date
from pathlib import Path

import pytest


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


MODULES_TO_PURGE = [
    "models",
    "models.database",
    "models.auth",
    "models.watch_alert",
    "services",
    "services.relation_mapper",
]


def _purge_modules() -> None:
    for module_name in MODULES_TO_PURGE:
        sys.modules.pop(module_name, None)


@pytest.fixture()
def isolated_runtime(tmp_path: Path):
    test_db_path = tmp_path / f"relation_mapper_{uuid.uuid4().hex}.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{test_db_path.as_posix()}"
    _purge_modules()

    database = importlib.import_module("models.database")
    importlib.import_module("models.auth")
    relation_mapper = importlib.import_module("services.relation_mapper")
    database.init_db()

    yield {
        "database": database,
        "relation_mapper": relation_mapper,
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
    confidence: float,
    is_verified: bool,
    evidence_url: str | None,
    evidence_source: str | None,
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


def _seed_graph_fixture(runtime) -> None:
    _seed_org(runtime, org_id="org-center", name="Victory Philippines", people_score=64, digital_score=28, intel_score=65)
    _seed_org(runtime, org_id="org-ally", name="Life.Church", people_score=70, digital_score=50, intel_score=60)
    _seed_org(runtime, org_id="org-unused", name="Unused Ministry", people_score=45, digital_score=35, intel_score=30)

    _seed_edge(
        runtime,
        edge_id="edge-verified",
        source_id="org-center",
        target_id="org-ally",
        relation_type="partner",
        confidence=0.82,
        is_verified=True,
        evidence_url="https://example.com/partner-proof",
        evidence_source="Public partnership page",
    )
    _seed_edge(
        runtime,
        edge_id="edge-unverified",
        source_id="org-center",
        target_id="org-ally",
        relation_type="affiliate",
        confidence=0.61,
        is_verified=False,
        evidence_url=None,
        evidence_source=None,
    )


def test_build_organization_graph_returns_center_nodes_edges_and_dedupes(isolated_runtime):
    runtime = isolated_runtime
    database = runtime["database"]
    relation_mapper = runtime["relation_mapper"]
    _seed_graph_fixture(runtime)

    db = database.SessionLocal()
    try:
        graph = relation_mapper.build_organization_graph(
            db=db,
            org_id="org-center",
            depth=1,
            limit=50,
        )
    finally:
        db.close()

    assert graph["found"] is True
    assert graph["center"]["id"] == "org-center"
    assert graph["center"]["graph_id"] == "org:org-center"
    assert graph["center"]["name"] == "Victory Philippines"
    assert len(graph["nodes"]) == 1
    assert graph["nodes"][0]["entity_id"] == "org-ally"
    assert graph["nodes"][0]["id"] == "org:org-ally"
    assert len(graph["edges"]) == 1
    assert graph["edges"][0]["id"] == "edge:edge-verified"
    assert graph["edges"][0]["source"] == "org:org-center"
    assert graph["edges"][0]["target"] == "org:org-ally"
    assert graph["edges"][0]["relation_type"] == "partner"
    assert graph["edges"][0]["evidence_url"] == "https://example.com/partner-proof"
    assert graph["edges"][0]["evidence_source"] == "Public partnership page"
    assert graph["edges"][0]["is_verified"] is True
    assert graph["summary"] == {
        "node_count": 2,
        "edge_count": 1,
        "verified_edge_count": 1,
        "unverified_edge_count": 0,
        "missing_evidence_count": 0,
    }
    assert len({node["id"] for node in graph["nodes"]}) == len(graph["nodes"])
    assert len({edge["id"] for edge in graph["edges"]}) == len(graph["edges"])
    assert any(warning["code"] == "unverified_filtered" for warning in graph["warnings"])


def test_build_organization_graph_include_unverified_marks_missing_evidence(isolated_runtime):
    runtime = isolated_runtime
    database = runtime["database"]
    relation_mapper = runtime["relation_mapper"]
    _seed_graph_fixture(runtime)

    db = database.SessionLocal()
    try:
        graph = relation_mapper.build_organization_graph(
            db=db,
            organization_name="Victory Philippines",
            include_unverified=True,
        )
    finally:
        db.close()

    assert graph["found"] is True
    assert len(graph["nodes"]) == 1
    assert len(graph["edges"]) == 2
    assert graph["summary"]["verified_edge_count"] == 1
    assert graph["summary"]["unverified_edge_count"] == 1
    assert graph["summary"]["missing_evidence_count"] == 1
    assert len({node["id"] for node in graph["nodes"]}) == 1
    assert len({edge["id"] for edge in graph["edges"]}) == 2
    warning_codes = {warning["code"] for warning in graph["warnings"]}
    assert "missing_evidence" in warning_codes
    assert "unverified_edge" in warning_codes


def test_build_organization_graph_not_found_returns_empty_graph(isolated_runtime):
    runtime = isolated_runtime
    database = runtime["database"]
    relation_mapper = runtime["relation_mapper"]

    db = database.SessionLocal()
    try:
        graph = relation_mapper.build_organization_graph(db=db, org_id="org-missing")
    finally:
        db.close()

    assert graph["found"] is False
    assert graph["center"] is None
    assert graph["nodes"] == []
    assert graph["edges"] == []
    assert graph["summary"]["node_count"] == 0
    assert graph["summary"]["edge_count"] == 0
    assert graph["warnings"][0]["code"] == "not_found"
