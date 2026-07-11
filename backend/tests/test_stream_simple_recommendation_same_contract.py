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
    test_db_path = tmp_path / f"recommendation_same_contract_{uuid.uuid4().hex}.db"
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
    people_score: int | None = 64,
    digital_score: int | None = 58,
    intel_score: int | None = 67,
    official_website: str | None = "https://example.org",
    contact_email: str | None = None,
    phone_public: str | None = None,
    source_url: str | None = "https://example.org/source",
):
    database = runtime["database"]
    db = database.SessionLocal()
    try:
        org = database.OrganizationProfile(
            id=org_id,
            name=name,
            country="Philippines",
            city="Manila",
            denomination="Evangelical",
            people_score=people_score,
            digital_score=digital_score,
            intel_score=intel_score,
            official_website=official_website,
            contact_email=contact_email,
            phone_public=phone_public,
            source_url=source_url,
            source_name="unit_test_seed",
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


def test_simple_and_stream_recommendation_return_same_contract(isolated_runtime, monkeypatch):
    runtime = isolated_runtime
    brain_module = runtime["brain_module"]
    _seed_org(runtime, org_id="org-victory", name="Victory Philippines", contact_email="info@victory.org.ph", source_url="https://victory.org.ph/source")
    _seed_org(runtime, org_id="org-bridge", name="Bridge Ministry", people_score=78, digital_score=74, intel_score=81, contact_email="connect@bridge.org", phone_public="+63 2 1234 5678", source_url="https://bridge.org/source")
    _seed_org(runtime, org_id="org-waypoint", name="Waypoint Collective", people_score=62, digital_score=54, intel_score=59, contact_email="hello@waypoint.org", source_url="https://waypoint.org/source")
    _seed_edge(runtime, edge_id="edge-victory-bridge", source_id="org-victory", target_id="org-bridge")
    _seed_edge(runtime, edge_id="edge-victory-waypoint", source_id="org-victory", target_id="org-waypoint")

    monkeypatch.setattr(
        brain_module.Brain,
        "_call_llm",
        lambda *_args, **_kwargs: pytest.fail("_call_llm must not be called"),
    )
    monkeypatch.setattr(
        brain_module.Brain,
        "_call_llm_stream",
        lambda *_args, **_kwargs: pytest.fail("_call_llm_stream must not be called"),
    )
    monkeypatch.setattr(
        socket,
        "create_connection",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("real network must not be used")),
    )

    message = "Who should Victory Philippines partner with?"
    brain = brain_module.Brain()
    simple_result = brain.think(message, conversation_id="recommendation-same-simple")
    stream_chunks = list(brain.think_stream(message, "recommendation-same-stream"))
    stream_done = next(chunk for chunk in stream_chunks if isinstance(chunk, dict) and chunk.get("type") == "done")

    simple_payload = simple_result["partnership_recommendations"]
    stream_payload = stream_done["partnership_recommendations"]
    simple_targets = [item["target_org"]["id"] for item in simple_payload["recommendations"]]
    stream_targets = [item["target_org"]["id"] for item in stream_payload["recommendations"]]

    assert simple_result["answer"] == stream_done["full_content"]
    assert simple_payload == stream_payload
    assert simple_payload["organization"] == stream_payload["organization"]
    assert simple_payload["summary"] == stream_payload["summary"]
    assert simple_payload["warnings"] == stream_payload["warnings"]
    assert simple_targets == stream_targets
    assert simple_payload["recommendations"]
    for item in simple_payload["recommendations"]:
        assert set(item.keys()) >= {
            "target_org",
            "recommendation_score",
            "priority",
            "confidence",
            "reason_codes",
            "explanation",
            "score_snapshot",
            "relationship_snapshot",
            "contact_snapshot",
            "risks",
            "warnings",
            "recommended_next_action",
        }
