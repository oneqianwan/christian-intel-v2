from __future__ import annotations

import importlib
import json
import os
import sys
import uuid
from pathlib import Path

import pytest


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
    "routers.auth",
    "routers.chat",
    "routers.conversations",
    "dependencies",
    "dependencies.auth",
    "dependencies.chat_auth",
    "queue_client",
    "services",
    "services.auth_service",
    "services.brain",
    "services.brain_planner",
    "services.chat_ownership",
    "services.mission_service",
    "services.score_draft_service",
    "services.mission_runner",
]


class FakeRedis:
    def set(self, *_args, **_kwargs):
        return True

    def eval(self, *_args, **_kwargs):
        return 1


def _purge_modules() -> None:
    for module_name in MODULES_TO_PURGE:
        sys.modules.pop(module_name, None)


@pytest.fixture()
def isolated_runtime(tmp_path: Path):
    test_db_path = tmp_path / f"intelligence_loop_e2e_{uuid.uuid4().hex}.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{test_db_path.as_posix()}"
    _purge_modules()

    database = importlib.import_module("models.database")
    mission_service = importlib.import_module("services.mission_service")
    score_draft_service = importlib.import_module("services.score_draft_service")
    brain_module = importlib.import_module("services.brain")

    database.init_db()

    yield {
        "database": database,
        "mission_service": mission_service,
        "score_draft_service": score_draft_service,
        "brain_module": brain_module,
        "db_path": test_db_path,
    }

    database.engine.dispose()
    _purge_modules()
    if test_db_path.exists():
        test_db_path.unlink()


def _seed_org(runtime, *, org_id: str, name: str, people_score=None, digital_score=None, intel_score=None):
    database = runtime["database"]
    db = database.SessionLocal()
    try:
        db.query(database.OrganizationProfile).filter(database.OrganizationProfile.name == name).delete()
        org = database.OrganizationProfile(
            id=org_id,
            name=name,
            country="Philippines",
            source_name="unit_test",
            official_website=f"https://{name.lower().replace(' ', '-')}.example.com",
        )
        if people_score is not None:
            org.people_score = people_score
        if digital_score is not None:
            org.digital_score = digital_score
        if intel_score is not None:
            org.intel_score = intel_score
        db.add(org)
        db.commit()
        db.refresh(org)
        org.people_score = people_score if people_score is not None else None
        org.digital_score = digital_score if digital_score is not None else None
        org.intel_score = intel_score if intel_score is not None else None
        db.commit()
        db.refresh(org)
        return org
    finally:
        db.close()


def _load_mission_payload(runtime, mission_id: str) -> dict:
    database = runtime["database"]
    db = database.SessionLocal()
    try:
        mission = db.query(database.Mission).filter(database.Mission.id == mission_id).first()
        assert mission is not None
        query = str(mission.query or "")
        prefix = runtime["mission_service"].MISSION_PAYLOAD_PREFIX
        assert query.startswith(prefix)
        return json.loads(query[len(prefix) :])
    finally:
        db.close()


def _create_persistent_collection_mission(runtime, *, query: str, country: str, target_entity: str, metadata: dict):
    database = runtime["database"]
    mission_service = runtime["mission_service"]
    db = database.SessionLocal()
    try:
        mission = database.Mission(
            id=f"mission-{uuid.uuid4().hex[:12]}",
            query=mission_service.MISSION_PAYLOAD_PREFIX
            + json.dumps(
                {
                    "query": query,
                    "source": None,
                    "keywords": [],
                    "limit_per_keyword": None,
                    "metadata": metadata,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            country=country,
            target_entity=target_entity,
            status="queued",
            priority=5,
        )
        db.add(mission)
        db.commit()
        db.refresh(mission)
        return mission
    finally:
        db.close()


def test_score_db_miss_to_collection_to_writeback_to_requery_e2e(isolated_runtime, monkeypatch):
    runtime = isolated_runtime
    database = runtime["database"]
    mission_service = runtime["mission_service"]
    score_draft_service = runtime["score_draft_service"]
    brain_module = runtime["brain_module"]

    protected_name = "Victory Philippines"
    target_name = "E2E Unknown Church"
    _seed_org(
        runtime,
        org_id="org-victory-ph",
        name=protected_name,
        people_score=64,
        digital_score=28,
        intel_score=65,
    )
    _seed_org(
        runtime,
        org_id="org-e2e-unknown",
        name=target_name,
        people_score=None,
        digital_score=None,
        intel_score=None,
    )

    monkeypatch.setattr(brain_module.Brain, "_call_llm", lambda *_a, **_k: pytest.fail("_call_llm should not be called"))
    monkeypatch.setattr(
        brain_module.Brain,
        "_call_llm_stream",
        lambda *_a, **_k: pytest.fail("_call_llm_stream should not be called"),
    )
    monkeypatch.setattr(mission_service, "_get_mission_lock_redis_client", lambda: FakeRedis())
    monkeypatch.setattr(mission_service, "enqueue_collection_mission", lambda *_a, **_k: None)
    monkeypatch.setattr(
        mission_service,
        "_dispatch_collection_runner_adapter",
        lambda **_kwargs: {
            "status": "completed",
            "sources_checked": ["rss", "website"],
            "raw_items_count": 3,
            "collection_summary": "fake local collector result for e2e",
            "raw_items": [
                {"title": "Leadership page updated", "source_type": "website"},
                {"title": "Recent ministry news", "source_type": "rss"},
            ],
            "scoring_ready": False,
        },
    )
    monkeypatch.setattr(
        score_draft_service,
        "_score_draft_runner_adapter",
        lambda *, scorer_input: {
            "people_score": 72,
            "digital_score": 65,
            "intel_score": 58,
            "scoring_ready": True,
            "scorer_versions": {"people": "mock-e2e", "digital": "mock-e2e", "intel": "mock-e2e"},
        },
    )

    monkeypatch.setattr(
        brain_module.Brain,
        "_create_score_lookup_collection_mission",
        lambda _self, *, organization_name, requested_scores, request_id: {
            "collection_required": True,
            "mission_created": True,
            "mission_id": _create_persistent_collection_mission(
                runtime,
                query=organization_name,
                country="全球",
                target_entity=organization_name,
                metadata={
                    "mission_type": "organization_score_data_collection",
                    "organization_name": organization_name,
                    "reason": "score_lookup_db_miss",
                    "requested_scores": requested_scores,
                    "collection_targets": ["website", "rss", "youtube", "telegram", "web_search"],
                    "created_by": "brain_score_lookup",
                    "request_id": request_id,
                },
            ).id,
            "mission_mode": "created_persistent_mission",
            "mission_draft": None,
            "collection_targets": ["website", "rss", "youtube", "telegram", "web_search"],
        },
    )
    brain = brain_module.Brain()

    first_lookup = brain._resolve_score_lookup_if_applicable(
        user_message=f"{target_name} 的评分是多少？",
        conversation_id="phase57e-e2e-first",
        route="simple",
    )
    assert first_lookup is not None
    assert first_lookup["mission_created"] is True
    assert first_lookup["mission_id"]
    assert brain.last_score_lookup_trace["db_hit"] is False
    assert brain.last_score_lookup_trace["collection_required"] is True
    assert "People Score:" not in first_lookup["answer"]
    assert "Digital Score:" not in first_lookup["answer"]
    assert "Intel Score:" not in first_lookup["answer"]
    assert "confidence" not in first_lookup["answer"].lower()

    mission_id = first_lookup["mission_id"]

    db = database.SessionLocal()
    try:
        dispatch_result = mission_service.dispatch_collection_mission(mission_id=mission_id, db=db)
        assert dispatch_result["status"] == "completed"
        assert dispatch_result["organization_name"] == target_name
        assert dispatch_result["raw_items_count"] == 3
    finally:
        db.close()

    mission_payload_after_dispatch = _load_mission_payload(runtime, mission_id)
    collection_result = mission_payload_after_dispatch.get("collection_result")
    assert isinstance(collection_result, dict)
    assert collection_result["raw_items_count"] == 3
    assert collection_result["collection_summary"] == "fake local collector result for e2e"

    db = database.SessionLocal()
    try:
        draft = score_draft_service.create_score_draft_from_collection_result(mission_id=mission_id, db=db)
        assert draft["score_draft"] is True
        assert draft["writeback"] is False
        assert draft["data_source"] == "collection_result"
        assert draft["organization_name"] == target_name
        assert draft["evidence_summary"]
        assert draft["people_score"] == 72
        assert draft["digital_score"] == 65
        assert draft["intel_score"] == 58
        assert 0 <= draft["people_score"] <= 100
        assert 0 <= draft["digital_score"] <= 100
        assert 0 <= draft["intel_score"] <= 100
        assert "people_score" in draft["requested_scores"]
        assert "digital_score" in draft["requested_scores"]
        assert "intel_score" in draft["requested_scores"]
    finally:
        db.close()

    db = database.SessionLocal()
    try:
        not_approved = score_draft_service.writeback_score_draft(
            mission_id=mission_id,
            score_draft=draft,
            approved=False,
            writeback_reason="e2e-not-approved",
            db=db,
        )
        assert not_approved["writeback"] is False
        assert not_approved["reason"] == "not_approved"

        profile = db.query(database.OrganizationProfile).filter(database.OrganizationProfile.name == target_name).first()
        assert profile is not None
        assert profile.people_score is None
        assert profile.digital_score is None
        assert profile.intel_score is None
    finally:
        db.close()

    db = database.SessionLocal()
    try:
        approved = score_draft_service.writeback_score_draft(
            mission_id=mission_id,
            score_draft=draft,
            approved=True,
            writeback_reason="e2e-approved-writeback",
            db=db,
        )
        assert approved["writeback"] is True
        assert approved["status"] == "completed"
        assert approved["mission_id"] == mission_id
        assert approved["data_source"] == "collection_result"
        assert approved["writeback_reason"] == "e2e-approved-writeback"

        updated = db.query(database.OrganizationProfile).filter(database.OrganizationProfile.name == target_name).first()
        assert updated is not None
        assert updated.people_score == draft["people_score"]
        assert updated.digital_score == draft["digital_score"]
        assert updated.intel_score == draft["intel_score"]
    finally:
        db.close()

    second_lookup = brain._resolve_score_lookup_if_applicable(
        user_message=f"{target_name} 的评分是多少？",
        conversation_id="phase57e-e2e-second",
        route="simple",
    )
    assert second_lookup is not None
    assert "People Score: 72" in second_lookup["answer"]
    assert "Digital Score: 65" in second_lookup["answer"]
    assert "Intel Score: 58" in second_lookup["answer"]
    assert "not_found" not in second_lookup["answer"].lower()
    assert second_lookup["mission_id"] is None
    assert brain.last_score_lookup_trace["db_hit"] is True
    assert brain.last_score_lookup_trace["llm_called"] is False

    db = database.SessionLocal()
    try:
        victory = db.query(database.OrganizationProfile).filter(database.OrganizationProfile.name == protected_name).first()
        assert victory is not None
        assert victory.people_score == 64
        assert victory.digital_score == 28
        assert victory.intel_score == 65
    finally:
        db.close()
