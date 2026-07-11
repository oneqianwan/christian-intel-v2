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
    "services.contact_intelligence",
    "services.partnership_recommender",
    "services.relation_mapper",
]


def _purge_modules() -> None:
    for module_name in MODULES_TO_PURGE:
        sys.modules.pop(module_name, None)


@pytest.fixture()
def isolated_runtime(tmp_path: Path):
    test_db_path = tmp_path / f"chat_recommendation_simple_{uuid.uuid4().hex}.db"
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


def _seed_org(
    runtime,
    *,
    org_id: str,
    name: str,
    country: str = "Philippines",
    city: str = "Manila",
    denomination: str = "Evangelical",
    people_score: int | None = 64,
    digital_score: int | None = 58,
    intel_score: int | None = 67,
    official_website: str | None = "https://example.org",
    contact_email: str | None = None,
    phone_public: str | None = None,
    facebook_url: str | None = None,
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
            official_website=official_website,
            contact_email=contact_email,
            phone_public=phone_public,
            facebook_url=facebook_url,
            source_url=source_url,
            source_name=source_name,
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
            confidence=0.84,
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


def _block_llm_and_network(monkeypatch, brain_module):
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


def test_brain_simple_recommendation_query_returns_database_payload(isolated_runtime, monkeypatch):
    runtime = isolated_runtime
    brain_module = runtime["brain_module"]
    _seed_org(runtime, org_id="org-victory", name="Victory Philippines")
    _seed_org(
        runtime,
        org_id="org-bridge",
        name="Bridge Ministry",
        people_score=78,
        digital_score=74,
        intel_score=81,
        official_website="https://bridge.org",
        contact_email="connect@bridge.org",
        phone_public="+63 2 1234 5678",
        facebook_url="https://facebook.com/bridgeorg",
        source_url="https://bridge.org/source",
    )
    _seed_edge(runtime, edge_id="edge-victory-bridge", source_id="org-victory", target_id="org-bridge")
    _block_llm_and_network(monkeypatch, brain_module)

    brain = brain_module.Brain()
    result = brain.think("Who should Victory Philippines partner with?", conversation_id="recommendation-simple")

    payload = result["partnership_recommendations"]
    first = payload["recommendations"][0]
    assert payload["organization"]["name"] == "Victory Philippines"
    assert payload["recommendations"]
    assert first["target_org"]["name"] == "Bridge Ministry"
    assert isinstance(first["recommendation_score"], int)
    assert first["priority"] in {"high", "medium", "low"}
    assert first["reason_codes"]
    assert "score_snapshot" in first
    assert "relationship_snapshot" in first
    assert "contact_snapshot" in first
    assert "recommended_next_action" in first
    assert "response_contract=partnership_recommendations" in result["answer"]
    assert "Bridge Ministry" in result["answer"]
    assert "priority:" in result["answer"]
    assert "recommendation_score:" in result["answer"]
    assert "llm_used=false" in result["answer"]


def test_brain_simple_recommendation_query_handles_no_candidates_without_fabrication(isolated_runtime, monkeypatch):
    runtime = isolated_runtime
    brain_module = runtime["brain_module"]
    _seed_org(runtime, org_id="org-victory", name="Victory Philippines")
    _block_llm_and_network(monkeypatch, brain_module)

    brain = brain_module.Brain()
    result = brain.think("推荐 Victory Philippines 适合合作的机构", conversation_id="recommendation-simple-empty")

    payload = result["partnership_recommendations"]
    assert payload["organization"]["name"] == "Victory Philippines"
    assert payload["recommendations"] == []
    assert "no_recommendation_candidates_found" in payload["warnings"]
    assert "没有足够候选" in result["answer"]
    assert "我不会编造推荐机构" in result["answer"]
    assert "response_contract=partnership_recommendations" in result["answer"]


def test_brain_simple_recommendation_query_handles_org_not_found(isolated_runtime, monkeypatch):
    runtime = isolated_runtime
    brain_module = runtime["brain_module"]
    _block_llm_and_network(monkeypatch, brain_module)

    brain = brain_module.Brain()
    result = brain.think("Recommend partner organizations for Unknown Church.", conversation_id="recommendation-simple-not-found")

    payload = result["partnership_recommendations"]
    assert payload["found"] is False
    assert payload["organization"] is None
    assert payload["recommendations"] == []
    assert "status=not_found" in result["answer"]
    assert "数据库中没有找到该机构" in result["answer"] or "The organization was not found in the database." in result["answer"]
    assert "I will not fabricate recommendation targets" in result["answer"] or "我不会编造推荐对象" in result["answer"]
