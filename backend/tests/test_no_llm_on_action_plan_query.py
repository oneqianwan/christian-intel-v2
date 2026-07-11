from __future__ import annotations

import importlib
import os
import socket
import sys
import uuid
from datetime import date
from pathlib import Path

import httpx
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
    test_db_path = tmp_path / f"action_plan_no_llm_query_{uuid.uuid4().hex}.db"
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


def _seed_org(runtime, *, org_id: str, name: str, email: str | None = None, website: str | None = "https://example.org", source_url: str | None = "https://example.org/source"):
    database = runtime["database"]
    db = database.SessionLocal()
    try:
        org = database.OrganizationProfile(
            id=org_id,
            name=name,
            country="Philippines",
            city="Manila",
            denomination="Evangelical",
            people_score=64,
            digital_score=58,
            intel_score=67,
            official_website=website,
            contact_email=email,
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


def test_action_plan_simple_and_stream_queries_do_not_call_llm_or_real_network(isolated_runtime, monkeypatch):
    runtime = isolated_runtime
    brain_module = runtime["brain_module"]

    _seed_org(runtime, org_id="org-source", name="Harbor Church", email="hello@harbor.org", website="https://harbor.org", source_url="https://harbor.org/source")
    _seed_org(runtime, org_id="org-target", name="Bridge Ministry", email="connect@bridge.org", website="https://bridge.org", source_url="https://bridge.org/source")
    _seed_edge(runtime, edge_id="edge-source-target", source_id="org-source", target_id="org-target")

    monkeypatch.setattr(
        brain_module.Brain,
        "_call_llm",
        lambda *_args, **_kwargs: pytest.fail("_call_llm must not be used by action plan query"),
    )
    monkeypatch.setattr(
        brain_module.Brain,
        "_call_llm_stream",
        lambda *_args, **_kwargs: pytest.fail("_call_llm_stream must not be used by action plan query"),
    )
    monkeypatch.setattr(
        socket,
        "create_connection",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("real network must not be used")),
    )
    monkeypatch.setattr(
        httpx,
        "request",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("httpx.request must not be used")),
    )

    brain = brain_module.Brain()
    simple_result = brain.think("What are the next steps for Harbor Church?", conversation_id="action-plan-no-llm-simple")
    stream_chunks = list(brain.think_stream("What are the next steps for Harbor Church?", "action-plan-no-llm-stream"))
    stream_done = next(chunk for chunk in stream_chunks if isinstance(chunk, dict) and chunk.get("type") == "done")

    assert simple_result["partnership_action_plan"]["summary"]["plan_available"] is True
    assert stream_done["partnership_action_plan"]["summary"]["plan_available"] is True
