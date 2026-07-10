from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


class FakeSession:
    def __init__(self):
        self.commits = 0
        self.refreshed = []

    def commit(self):
        self.commits += 1

    def refresh(self, obj):
        self.refreshed.append(obj)

    def close(self):
        return None


def _make_mission(
    *,
    mission_id: str,
    mission_type: str,
    organization_name: str = "Unknown Church",
    requested_scores=None,
    status: str = "queued",
    include_collection_result: bool = False,
):
    requested_scores = list(requested_scores or ["people_score", "digital_score", "intel_score"])
    payload = {
        "query": organization_name,
        "metadata": {
            "mission_type": mission_type,
            "organization_name": organization_name,
            "reason": "score_lookup_db_miss",
            "requested_scores": requested_scores,
            "collection_targets": ["rss", "website"],
            "created_by": "brain_score_lookup",
            "request_id": "req-57c",
        },
    }
    if include_collection_result:
        payload["collection_result"] = {
            "sources_checked": ["rss", "website"],
            "raw_items_count": 2,
            "collection_summary": "mock collection result",
        }
    mission_service = importlib.import_module("services.mission_service")
    return SimpleNamespace(
        id=mission_id,
        query=mission_service.MISSION_PAYLOAD_PREFIX
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        country="全球",
        target_entity=organization_name,
        status=status,
        priority=5,
        composite_task_id=None,
        composite_status=None,
        updated_at=None,
    )


def test_completed_collection_mission_builds_score_draft(monkeypatch):
    mission_service = importlib.import_module("services.mission_service")
    score_draft_service = importlib.import_module("services.score_draft_service")
    session = FakeSession()
    mission = _make_mission(mission_id="mission-57c-success", mission_type="organization_score_data_collection")

    monkeypatch.setattr(
        mission_service,
        "_dispatch_collection_runner_adapter",
        lambda **_kwargs: {
            "status": "completed",
            "sources_checked": ["rss", "website"],
            "raw_items_count": 3,
            "collection_summary": "mock collected 3 raw items",
            "scoring_ready": False,
        },
    )
    dispatch_result = mission_service.dispatch_collection_mission(mission=mission, db=session)
    assert dispatch_result["status"] == "completed"
    assert mission.status == "done"

    monkeypatch.setattr(
        score_draft_service,
        "_score_draft_runner_adapter",
        lambda *, scorer_input: {
            "people_score": 10,
            "digital_score": 20,
            "intel_score": 30,
            "scoring_ready": True,
            "scorer_versions": {"people": "mock", "digital": "mock", "intel": "mock"},
        },
    )
    draft = score_draft_service.create_score_draft_from_collection_result(mission=mission, db=session)
    assert draft["status"] == "completed"
    assert draft["organization_name"] == "Unknown Church"
    assert draft["data_source"] == "collection_result"
    assert draft["writeback"] is False
    assert draft["people_score"] == 10
    assert draft["digital_score"] == 20
    assert draft["intel_score"] == 30
    assert draft["scoring_ready"] is True


def test_score_draft_requires_completed_collection_result():
    score_draft_service = importlib.import_module("services.score_draft_service")
    session = FakeSession()
    mission = _make_mission(
        mission_id="mission-57c-not-ready",
        mission_type="organization_score_data_collection",
        status="queued",
        include_collection_result=False,
    )

    result = score_draft_service.create_score_draft_from_collection_result(mission=mission, db=session)
    assert result["status"] == "not_ready"
    assert result["reason"] == "insufficient_collection_result"


def test_score_draft_does_not_call_llm(monkeypatch):
    brain_module = importlib.import_module("services.brain")
    score_draft_service = importlib.import_module("services.score_draft_service")
    session = FakeSession()
    mission = _make_mission(
        mission_id="mission-57c-no-llm",
        mission_type="organization_score_data_collection",
        status="done",
        include_collection_result=True,
    )

    monkeypatch.setattr(
        brain_module.Brain,
        "_call_llm",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("_call_llm should not be called in score draft")),
    )
    monkeypatch.setattr(
        brain_module.Brain,
        "_call_llm_stream",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("_call_llm_stream should not be called in score draft")
        ),
    )

    result = score_draft_service.create_score_draft_from_collection_result(mission=mission, db=session)
    assert result["status"] == "completed"


def test_score_draft_does_not_writeback_to_database():
    score_draft_service = importlib.import_module("services.score_draft_service")
    session = FakeSession()
    mission = _make_mission(
        mission_id="mission-57c-writeback-false",
        mission_type="organization_score_data_collection",
        status="done",
        include_collection_result=True,
    )

    draft = score_draft_service.create_score_draft_from_collection_result(mission=mission, db=session)
    assert draft["status"] == "completed"
    assert draft["writeback"] is False
    assert '"score_draft"' in str(mission.query)


def test_score_draft_contains_requested_scores(monkeypatch):
    score_draft_service = importlib.import_module("services.score_draft_service")
    session = FakeSession()
    mission = _make_mission(
        mission_id="mission-57c-requested-scores",
        mission_type="organization_score_data_collection",
        requested_scores=["people_score", "digital_score", "intel_score"],
        status="done",
        include_collection_result=True,
    )

    monkeypatch.setattr(
        score_draft_service,
        "_score_draft_runner_adapter",
        lambda *, scorer_input: {
            "people_score": None,
            "digital_score": None,
            "intel_score": None,
            "scoring_ready": False,
            "scorer_versions": {"people": "mock", "digital": "mock", "intel": "mock"},
        },
    )

    draft = score_draft_service.create_score_draft_from_collection_result(mission=mission, db=session)
    assert draft["status"] == "completed"
    assert "people_score" in draft["requested_scores"]
    assert "digital_score" in draft["requested_scores"]
    assert "intel_score" in draft["requested_scores"]
    assert "people_score" in draft
    assert "digital_score" in draft
    assert "intel_score" in draft


def test_victory_philippines_db_hit_does_not_create_score_draft(monkeypatch):
    brain_module = importlib.import_module("services.brain")
    brain = brain_module.Brain()
    monkeypatch.setattr(
        brain,
        "_find_organization_for_score_lookup",
        lambda _name: SimpleNamespace(
            name="Victory Philippines",
            people_score=64,
            digital_score=28,
            intel_score=65,
            composite_score=None,
        ),
    )
    monkeypatch.setattr(brain, "_evidence_from_organization_profile", lambda *_args, **_kwargs: {"type": "organization_score_lookup"})

    result = brain._resolve_score_lookup_if_applicable(
        user_message="Victory Philippines 的评分是多少？",
        conversation_id="phase57c-victory-hit",
        route="simple",
    )

    assert result is not None
    assert "People Score: 64" in result["answer"]
    assert "Digital Score: 28" in result["answer"]
    assert "Intel Score: 65" in result["answer"]
    assert result.get("mission_id") is None
    assert "score_draft" not in result
    assert brain.last_score_lookup_trace["db_hit"] is True
    assert brain.last_score_lookup_trace["collection_required"] is False

