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
    "services.partnership_action_planner",
    "services.relation_mapper",
]


def _purge_modules() -> None:
    for module_name in MODULES_TO_PURGE:
        sys.modules.pop(module_name, None)


@pytest.fixture()
def isolated_runtime(tmp_path: Path):
    test_db_path = tmp_path / f"chat_action_plan_stream_{uuid.uuid4().hex}.db"
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
            source_name=source_name,
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


def _done_chunk(chunks: list[dict]) -> dict:
    return next(chunk for chunk in chunks if isinstance(chunk, dict) and chunk.get("type") == "done")


def test_brain_stream_action_plan_query_returns_database_payload(isolated_runtime, monkeypatch):
    runtime = isolated_runtime
    brain_module = runtime["brain_module"]
    _seed_org(runtime, org_id="org-source", name="Harbor Church")
    _seed_org(
        runtime,
        org_id="org-target",
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
    _seed_edge(runtime, edge_id="edge-source-target", source_id="org-source", target_id="org-target")
    _block_llm_and_network(monkeypatch, brain_module)

    brain = brain_module.Brain()
    chunks = list(brain.think_stream("What are the next steps for Harbor Church?", "action-plan-stream"))
    done_chunk = _done_chunk(chunks)
    payload = done_chunk["partnership_action_plan"]
    first_step = payload["action_plan"][0]

    assert payload["organization"]["name"] == "Harbor Church"
    assert payload["target_org"]["name"] == "Bridge Ministry"
    assert set(payload.keys()) >= {"organization", "target_org", "summary", "action_plan", "evidence", "warnings"}
    assert "recommended_channel" in payload["summary"]
    assert "risk_level" in payload["summary"]
    assert "confidence" in payload["summary"]
    assert set(first_step.keys()) >= {"step_number", "action_type", "channel", "uses_contact", "risk_flags"}
    assert "response_contract=partnership_action_plan" in done_chunk["full_content"]
    assert "llm_used=false" in done_chunk["full_content"]


def test_brain_stream_action_plan_query_handles_blocked_without_fabrication(isolated_runtime, monkeypatch):
    runtime = isolated_runtime
    brain_module = runtime["brain_module"]
    _seed_org(runtime, org_id="org-source", name="Harbor Church")
    _block_llm_and_network(monkeypatch, brain_module)

    brain = brain_module.Brain()
    chunks = list(brain.think_stream("给我 Harbor Church 的合作行动计划", "action-plan-stream-blocked"))
    done_chunk = _done_chunk(chunks)
    payload = done_chunk["partnership_action_plan"]

    assert payload["organization"]["name"] == "Harbor Church"
    assert payload["summary"]["blocked"] is True
    assert payload["action_plan"] == []
    assert "no_recommendation_candidates_found" in payload["warnings"]
    assert "status=blocked" in done_chunk["full_content"]


def test_brain_stream_action_plan_query_handles_org_and_target_not_found(isolated_runtime, monkeypatch):
    runtime = isolated_runtime
    brain_module = runtime["brain_module"]
    _seed_org(runtime, org_id="org-source", name="Harbor Church")
    _block_llm_and_network(monkeypatch, brain_module)

    brain = brain_module.Brain()
    org_not_found_done = _done_chunk(
        list(brain.think_stream("What are the next steps for Missing Church?", "action-plan-stream-org-not-found"))
    )
    target_not_found_done = _done_chunk(
        list(brain.think_stream("给我 Harbor Church 联系 Missing Partner 的行动计划", "action-plan-stream-target-not-found"))
    )

    org_payload = org_not_found_done["partnership_action_plan"]
    target_payload = target_not_found_done["partnership_action_plan"]
    assert org_payload["found"] is False
    assert org_payload["organization"] is None
    assert "status=not_found" in org_not_found_done["full_content"]

    assert target_payload["organization"]["name"] == "Harbor Church"
    assert "target_organization_not_found" in target_payload["warnings"]
    assert "status=target_not_found" in target_not_found_done["full_content"]
