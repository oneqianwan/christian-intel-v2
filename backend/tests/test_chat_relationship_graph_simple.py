from __future__ import annotations

import importlib
import os
import socket
import sys
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
    "services.relation_mapper",
]


def _purge_modules() -> None:
    for module_name in MODULES_TO_PURGE:
        sys.modules.pop(module_name, None)


@pytest.fixture()
def isolated_runtime(tmp_path: Path):
    test_db_path = tmp_path / f"chat_graph_simple_{uuid.uuid4().hex}.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{test_db_path.as_posix()}"
    _purge_modules()

    database = importlib.import_module("models.database")
    importlib.import_module("models.auth")
    importlib.import_module("models.watch_alert")
    brain_module = importlib.import_module("services.brain")
    database.init_db()

    yield {
        "database": database,
        "brain_module": brain_module,
        "db_path": test_db_path,
    }

    database.engine.dispose()
    _purge_modules()
    if test_db_path.exists():
        test_db_path.unlink()


def _seed_org(runtime, *, org_id: str, name: str, people_score: int = 64, digital_score: int = 28, intel_score: int = 65):
    database = runtime["database"]
    db = database.SessionLocal()
    try:
        org = database.OrganizationProfile(
            id=org_id,
            name=name,
            country="Philippines",
            state_province="Metro Manila",
            denomination="Evangelical",
            source_name="manual_seed",
            source_url=f"https://{org_id}.example.com/source",
            official_website=f"https://{org_id}.example.com",
            people_score=people_score,
            digital_score=digital_score,
            intel_score=intel_score,
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
            confidence=0.82,
            is_verified=True,
            evidence_url="https://example.com/partner-proof",
            evidence_source="Public partnership page",
            evidence_date=date(2026, 7, 10),
        )
        db.add(edge)
        db.commit()
        db.refresh(edge)
        return edge
    finally:
        db.close()


def test_brain_simple_relationship_graph_query_returns_database_graph(isolated_runtime, monkeypatch):
    runtime = isolated_runtime
    brain_module = runtime["brain_module"]
    _seed_org(runtime, org_id="org-victory", name="Victory Philippines")
    _seed_org(runtime, org_id="org-life", name="Life.Church", people_score=70, digital_score=50, intel_score=60)
    _seed_edge(runtime, edge_id="edge-victory-life", source_id="org-victory", target_id="org-life")

    monkeypatch.setattr(
        brain_module.Brain,
        "_call_llm",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("_call_llm must not be called")),
    )
    monkeypatch.setattr(
        brain_module.Brain,
        "_call_llm_stream",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("_call_llm_stream must not be called")),
    )
    monkeypatch.setattr(
        socket,
        "create_connection",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("real network must not be used")),
    )

    brain = brain_module.Brain()
    result = brain.think("说明 Victory Philippines 的关系图谱", conversation_id="graph-simple")

    assert result["relationship_graph"]["center"]["name"] == "Victory Philippines"
    assert result["relationship_graph"]["summary"]["edge_count"] == 1
    assert "response_contract=relationship_graph" in result["answer"]
    assert "以下关系来自数据库证据，不是推测" in result["answer"]
    assert "Life.Church" in result["answer"]
    assert "relation_type: partner" in result["answer"]
    assert "evidence: https://example.com/partner-proof" in result["answer"]
    assert "confidence: 0.82" in result["answer"]
    assert "is_verified: true" in result["answer"]
    assert "llm_used=false" in result["answer"]


def test_brain_simple_relationship_graph_query_handles_no_relations_without_fabrication(isolated_runtime, monkeypatch):
    runtime = isolated_runtime
    brain_module = runtime["brain_module"]
    _seed_org(runtime, org_id="org-victory", name="Victory Philippines")

    monkeypatch.setattr(
        brain_module.Brain,
        "_call_llm",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("_call_llm must not be called")),
    )
    monkeypatch.setattr(
        socket,
        "create_connection",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("real network must not be used")),
    )

    brain = brain_module.Brain()
    result = brain.think("Victory Philippines 和哪些机构有关联？", conversation_id="graph-no-relations")

    assert result["relationship_graph"]["center"]["name"] == "Victory Philippines"
    assert result["relationship_graph"]["edges"] == []
    assert "当前数据库还没有发现 Victory Philippines 的有证据关系图谱" in result["answer"]
    assert "我不会编造关系" in result["answer"]
    assert "response_contract=relationship_graph" in result["answer"]


def test_brain_simple_relationship_graph_query_handles_org_not_found(isolated_runtime, monkeypatch):
    runtime = isolated_runtime
    brain_module = runtime["brain_module"]

    monkeypatch.setattr(
        brain_module.Brain,
        "_call_llm",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("_call_llm must not be called")),
    )
    monkeypatch.setattr(
        socket,
        "create_connection",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("real network must not be used")),
    )

    brain = brain_module.Brain()
    result = brain.think("给我 Unknown Church 的关系图谱", conversation_id="graph-not-found")

    assert result["relationship_graph"]["found"] is False
    assert result["relationship_graph"]["center"] is None
    assert "status=not_found" in result["answer"]
    assert "response_contract=relationship_graph" in result["answer"]
    assert "我不会编造关系" in result["answer"]
