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
    "services.intent_router_final",
    "services.organization_resolver",
    "services.brain_orchestrator",
    "services.response_contract",
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
def seeded_runtime(tmp_path: Path):
    test_db_path = tmp_path / f"response_contract_consistency_{uuid.uuid4().hex}.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{test_db_path.as_posix()}"
    _purge_modules()

    database = importlib.import_module("models.database")
    importlib.import_module("models.auth")
    importlib.import_module("models.watch_alert")
    brain_module = importlib.import_module("services.brain")
    database.init_db()

    runtime = {"database": database, "brain_module": brain_module}
    _seed_org(runtime, org_id="org-victory", name="Victory Philippines")
    _seed_org(runtime, org_id="org-harbor", name="Harbor Church", contact_email="hello@harbor.org", source_url="https://harbor.org/source")
    _seed_org(runtime, org_id="org-bridge", name="Bridge Ministry", people_score=78, digital_score=74, intel_score=81, contact_email="connect@bridge.org", source_url="https://bridge.org/source")
    _seed_edge(runtime, edge_id="edge-harbor-bridge", source_id="org-harbor", target_id="org-bridge")

    yield runtime

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
    contact_email: str | None = "hello@example.org",
    phone_public: str | None = "+63 2 1234 5678",
    facebook_url: str | None = "https://facebook.com/exampleorg",
    source_url: str | None = "https://example.org/source",
):
    database = runtime["database"]
    db = database.SessionLocal()
    try:
        db.add(
            database.OrganizationProfile(
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
                facebook_url=facebook_url,
                source_url=source_url,
                source_name="unit_test_seed",
            )
        )
        db.commit()
    finally:
        db.close()


def _seed_edge(runtime, *, edge_id: str, source_id: str, target_id: str):
    database = runtime["database"]
    db = database.SessionLocal()
    try:
        db.add(
            database.RelationEdge(
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
        )
        db.commit()
    finally:
        db.close()


@pytest.mark.parametrize(
    "message",
    [
        "Show me Victory Philippines scores",
        "How can I contact Victory Philippines?",
        "Who should Victory Philippines partner with?",
        "What are the next steps for Harbor Church?",
        "Give me an evidence brief for Harbor Church.",
    ],
)
def test_simple_and_stream_contracts_match_for_ready_routes(seeded_runtime, monkeypatch, message):
    brain_module = seeded_runtime["brain_module"]
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

    brain = brain_module.Brain()
    simple = brain.think(message, conversation_id=f"simple-{uuid.uuid4().hex}")["response_contract"]
    stream_done = next(
        item for item in brain.think_stream(message, f"stream-{uuid.uuid4().hex}") if isinstance(item, dict) and item.get("type") == "done"
    )
    stream = stream_done["response_contract"]

    assert simple["intent"] == stream["intent"]
    assert simple["selected_module"] == stream["selected_module"]
    assert simple["payload_type"] == stream["payload_type"]
    assert simple["route_status"] == stream["route_status"] == "ready"
    assert simple["trace_id"] != stream["trace_id"]


def test_simple_and_stream_contracts_match_for_safe_fallback(seeded_runtime):
    brain = seeded_runtime["brain_module"].Brain()
    simple = brain.think("推荐合作对象有哪些？", conversation_id=f"simple-fallback-{uuid.uuid4().hex}")["response_contract"]
    stream_done = next(
        item
        for item in brain.think_stream("推荐合作对象有哪些？", f"stream-fallback-{uuid.uuid4().hex}")
        if isinstance(item, dict) and item.get("type") == "done"
    )
    stream = stream_done["response_contract"]

    assert simple["route_status"] == stream["route_status"] == "ask_clarification"
    assert simple["selected_module"] == stream["selected_module"]
    assert simple["payload_type"] == stream["payload_type"]
