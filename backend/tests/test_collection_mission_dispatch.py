from __future__ import annotations

import importlib
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


def _make_mission(*, mission_id: str, mission_type: str, organization_name: str = "Unknown Church", requested_scores=None):
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
            "request_id": "req-123",
        },
    }
    mission_service = importlib.import_module("services.mission_service")
    return SimpleNamespace(
        id=mission_id,
        query=mission_service.MISSION_PAYLOAD_PREFIX + __import__("json").dumps(payload, ensure_ascii=False, separators=(",", ":")),
        country="全球",
        target_entity=organization_name,
        status="queued",
        priority=5,
        composite_task_id=None,
        composite_status=None,
        updated_at=None,
    )


def test_dispatch_collection_mission_success(monkeypatch):
    mission_service = importlib.import_module("services.mission_service")
    session = FakeSession()
    mission = _make_mission(mission_id="mission-success", mission_type="organization_score_data_collection")

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

    result = mission_service.dispatch_collection_mission(mission=mission, db=session)

    assert mission.status == "done"
    assert result["status"] == "completed"
    assert result["organization_name"] == "Unknown Church"
    assert result["sources_checked"] == ["rss", "website"]
    assert result["scoring_ready"] is False
    assert "People Score:" not in repr(result)
    assert "Digital Score:" not in repr(result)
    assert "Intel Score:" not in repr(result)


def test_dispatch_collection_mission_failure(monkeypatch):
    mission_service = importlib.import_module("services.mission_service")
    session = FakeSession()
    mission = _make_mission(mission_id="mission-failure", mission_type="organization_score_data_collection")

    def _raise_failure(**_kwargs):
        raise RuntimeError("api_key=secret-token should not leak")

    monkeypatch.setattr(mission_service, "_dispatch_collection_runner_adapter", _raise_failure)

    result = mission_service.dispatch_collection_mission(mission=mission, db=session)

    assert mission.status == "failed"
    assert result["status"] == "failed"
    assert result["error_message"]
    lowered = result["error_message"].lower()
    assert "password" not in lowered
    assert "token" not in lowered
    assert "api_key" not in lowered
    assert "authorization" not in lowered


def test_dispatch_only_handles_collection_mission_type():
    mission_service = importlib.import_module("services.mission_service")
    session = FakeSession()
    mission = _make_mission(mission_id="mission-skip", mission_type="other_mission_type")

    result = mission_service.dispatch_collection_mission(mission=mission, db=session)

    assert result["status"] == "skipped"
    assert result["reason"] == "unsupported_mission_type"
    assert mission.status == "queued"


def test_score_db_miss_created_mission_can_be_dispatched(monkeypatch):
    mission_service = importlib.import_module("services.mission_service")
    brain_module = importlib.import_module("services.brain")
    session = FakeSession()
    created_mission = _make_mission(
        mission_id="mission-from-brain",
        mission_type="organization_score_data_collection",
        organization_name="Unknown Church",
    )

    monkeypatch.setattr(brain_module.Brain, "_find_organization_for_score_lookup", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        mission_service,
        "create_collection_mission",
        lambda **_kwargs: created_mission,
    )
    monkeypatch.setattr(
        mission_service,
        "_load_mission_by_id",
        lambda _session, mission_id: created_mission if mission_id == "mission-from-brain" else None,
    )
    monkeypatch.setattr(
        mission_service,
        "_dispatch_collection_runner_adapter",
        lambda **_kwargs: {
            "status": "completed",
            "sources_checked": ["rss", "website"],
            "raw_items_count": 2,
            "collection_summary": "brain-created mission dispatched",
            "scoring_ready": False,
        },
    )

    brain = brain_module.Brain()
    result = brain._resolve_score_lookup_if_applicable(
        user_message="Unknown Church 的评分是多少？",
        conversation_id="phase57b-brain-create",
        route="simple",
    )

    assert result is not None
    mission_id = result["mission_id"]
    assert mission_id == "mission-from-brain"

    dispatch_result = mission_service.dispatch_collection_mission(mission_id=mission_id, db=session)
    assert dispatch_result["status"] == "completed"
    assert dispatch_result["organization_name"] == "Unknown Church"
    assert "people_score" in dispatch_result["requested_scores"]
    assert "digital_score" in dispatch_result["requested_scores"]
    assert "intel_score" in dispatch_result["requested_scores"]


def test_victory_philippines_db_hit_does_not_dispatch_collection(monkeypatch):
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

    dispatched = {"called": False}

    mission_service = importlib.import_module("services.mission_service")
    monkeypatch.setattr(
        mission_service,
        "dispatch_collection_mission",
        lambda **_kwargs: dispatched.__setitem__("called", True),
    )

    result = brain._resolve_score_lookup_if_applicable(
        user_message="Victory Philippines 的评分是多少？",
        conversation_id="phase57b-victory-hit",
        route="simple",
    )

    assert result is not None
    assert "People Score: 64" in result["answer"]
    assert "Digital Score: 28" in result["answer"]
    assert "Intel Score: 65" in result["answer"]
    assert brain.last_score_lookup_trace["db_hit"] is True
    assert brain.last_score_lookup_trace["collection_required"] is False
    assert brain.last_score_lookup_trace["mission_created"] is False
    assert dispatched["called"] is False
