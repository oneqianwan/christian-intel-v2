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
    test_db_path = tmp_path / f"brain_orchestrator_consistency_{uuid.uuid4().hex}.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{test_db_path.as_posix()}"
    _purge_modules()

    database = importlib.import_module("models.database")
    importlib.import_module("models.auth")
    importlib.import_module("models.watch_alert")
    brain_orchestrator_module = importlib.import_module("services.brain_orchestrator")
    brain_module = importlib.import_module("services.brain")
    database.init_db()

    yield {
        "database": database,
        "brain_module": brain_module,
        "brain_orchestrator_module": brain_orchestrator_module,
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
    contact_email: str | None = "hello@example.org",
    phone_public: str | None = "+63 2 1234 5678",
    facebook_url: str | None = "https://facebook.com/exampleorg",
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
            facebook_url=facebook_url,
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


@pytest.fixture()
def seeded_runtime(isolated_runtime):
    runtime = isolated_runtime
    _seed_org(runtime, org_id="org-victory", name="Victory Philippines")
    _seed_org(runtime, org_id="org-harbor", name="Harbor Church", contact_email="hello@harbor.org", source_url="https://harbor.org/source")
    _seed_org(runtime, org_id="org-bridge", name="Bridge Ministry", people_score=78, digital_score=74, intel_score=81, contact_email="connect@bridge.org", source_url="https://bridge.org/source")
    _seed_edge(runtime, edge_id="edge-harbor-bridge", source_id="org-harbor", target_id="org-bridge")
    return runtime


@pytest.mark.parametrize(
    ("message", "expected_module", "payload_key"),
    [
        ("Show me Victory Philippines scores", "score_lookup", None),
        ("How can I contact Victory Philippines?", "contact_intelligence", "contact_lookup"),
        ("Who should Victory Philippines partner with?", "partnership_recommender", "partnership_recommendations"),
        ("What are the next steps for Harbor Church?", "partnership_action_planner", "partnership_action_plan"),
        ("Give me an evidence brief for Harbor Church.", "partnership_evidence_brief", "partnership_evidence_brief"),
    ],
)
def test_simple_and_stream_use_same_selected_module(seeded_runtime, monkeypatch, message, expected_module, payload_key):
    runtime = seeded_runtime
    brain_module = runtime["brain_module"]
    orchestrator_module = runtime["brain_orchestrator_module"]
    decisions: list[tuple[str | None, str | None]] = []
    original_orchestrate = orchestrator_module.BrainOrchestrator.orchestrate

    def traced_orchestrate(self, query, *args, **kwargs):
        result = original_orchestrate(self, query, *args, **kwargs)
        decisions.append((result.get("selected_module"), result.get("route_status")))
        return result

    monkeypatch.setattr(orchestrator_module.BrainOrchestrator, "orchestrate", traced_orchestrate)
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
    simple_result = brain.think(message, conversation_id=f"simple-{uuid.uuid4().hex}")
    stream_chunks = list(brain.think_stream(message, f"stream-{uuid.uuid4().hex}"))
    stream_done = next(chunk for chunk in stream_chunks if isinstance(chunk, dict) and chunk.get("type") == "done")

    assert decisions[-2][0] == expected_module
    assert decisions[-1][0] == expected_module
    assert decisions[-2][1] == "ready"
    assert decisions[-1][1] == "ready"
    assert "llm_used=false" in simple_result["answer"]
    assert "llm_used=false" in stream_done["full_content"]
    if payload_key is not None:
        assert simple_result[payload_key] == stream_done[payload_key]


def test_missing_organization_safely_falls_back_in_simple_and_stream(seeded_runtime, monkeypatch):
    runtime = seeded_runtime
    brain_module = runtime["brain_module"]
    orchestrator_module = runtime["brain_orchestrator_module"]
    decisions: list[tuple[str | None, str | None]] = []
    original_orchestrate = orchestrator_module.BrainOrchestrator.orchestrate

    def traced_orchestrate(self, query, *args, **kwargs):
        result = original_orchestrate(self, query, *args, **kwargs)
        decisions.append((result.get("selected_module"), result.get("route_status")))
        return result

    monkeypatch.setattr(orchestrator_module.BrainOrchestrator, "orchestrate", traced_orchestrate)
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

    message = "推荐合作对象有哪些？"
    brain = brain_module.Brain()
    simple_result = brain.think(message, conversation_id=f"simple-missing-{uuid.uuid4().hex}")
    stream_chunks = list(brain.think_stream(message, f"stream-missing-{uuid.uuid4().hex}"))
    stream_done = next(chunk for chunk in stream_chunks if isinstance(chunk, dict) and chunk.get("type") == "done")

    assert decisions[-2][0] == "partnership_recommender"
    assert decisions[-1][0] == "partnership_recommender"
    assert decisions[-2][1] == "ask_clarification"
    assert decisions[-1][1] == "ask_clarification"
    assert "Victory Philippines" in simple_result["answer"]
    assert "llm_used=false" in simple_result["answer"]
    assert "Victory Philippines" in stream_done["full_content"]
    assert "llm_used=false" in stream_done["full_content"]
