from __future__ import annotations

import importlib
import os
import socket
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
    "services.brain",
    "services.relation_mapper",
]


def _purge_modules() -> None:
    for module_name in MODULES_TO_PURGE:
        sys.modules.pop(module_name, None)


@pytest.fixture()
def isolated_runtime(tmp_path: Path):
    test_db_path = tmp_path / f"graph_contract_no_llm_{uuid.uuid4().hex}.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{test_db_path.as_posix()}"
    os.environ["AUTH_CORS_ALLOW_ORIGINS"] = "http://127.0.0.1:4173"
    _purge_modules()

    database = importlib.import_module("models.database")
    relation_mapper = importlib.import_module("services.relation_mapper")
    brain_module = importlib.import_module("services.brain")
    main = importlib.import_module("main")
    database.init_db()

    client_ctx = TestClient(main.app)
    client = client_ctx.__enter__()

    yield {
        "database": database,
        "relation_mapper": relation_mapper,
        "brain_module": brain_module,
        "client": client,
        "db_path": test_db_path,
    }

    client_ctx.__exit__(None, None, None)
    database.engine.dispose()
    _purge_modules()
    if test_db_path.exists():
        test_db_path.unlink()


def _seed_org(runtime, *, org_id: str, name: str):
    database = runtime["database"]
    db = database.SessionLocal()
    try:
        org = database.OrganizationProfile(
            id=org_id,
            name=name,
            country="Philippines",
            source_name="unit_test",
            source_url=f"https://{org_id}.example.com/source",
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
            confidence=0.77,
            is_verified=True,
            evidence_url="https://example.com/proof",
            evidence_source="Public source",
            evidence_date=date(2026, 7, 10),
        )
        db.add(edge)
        db.commit()
        db.refresh(edge)
        return edge
    finally:
        db.close()


def test_graph_service_and_api_do_not_call_llm_or_real_network(isolated_runtime, monkeypatch):
    runtime = isolated_runtime
    database = runtime["database"]
    relation_mapper = runtime["relation_mapper"]
    brain_module = runtime["brain_module"]
    client = runtime["client"]

    _seed_org(runtime, org_id="org-center", name="Victory Philippines")
    _seed_org(runtime, org_id="org-ally", name="Life.Church")
    _seed_edge(runtime, edge_id="edge-verified", source_id="org-center", target_id="org-ally")

    monkeypatch.setattr(
        brain_module.Brain,
        "_call_llm",
        lambda *_args, **_kwargs: pytest.fail("_call_llm must not be used by graph service or graph API"),
    )
    monkeypatch.setattr(
        brain_module.Brain,
        "_call_llm_stream",
        lambda *_args, **_kwargs: pytest.fail("_call_llm_stream must not be used by graph service or graph API"),
    )
    monkeypatch.setattr(
        socket,
        "create_connection",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("real network must not be used")),
    )

    db = database.SessionLocal()
    try:
        graph = relation_mapper.build_organization_graph(db=db, org_id="org-center")
    finally:
        db.close()

    assert graph["found"] is True
    assert graph["summary"]["edge_count"] == 1

    response = client.get("/api/dashboard/org/org-center/relations")
    assert response.status_code == 200
    payload = response.json()
    assert payload["graph"]["summary"]["edge_count"] == 1
