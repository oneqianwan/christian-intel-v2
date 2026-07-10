from __future__ import annotations

import importlib
from types import SimpleNamespace


def _make_org(name: str = "Victory Philippines") -> SimpleNamespace:
    return SimpleNamespace(
        name=name,
        people_score=64,
        digital_score=28,
        intel_score=65,
        composite_score=None,
    )


def test_score_db_miss_marks_collection_required(monkeypatch):
    brain_module = importlib.import_module("services.brain")
    brain = brain_module.Brain()
    monkeypatch.setattr(brain, "_find_organization_for_score_lookup", lambda _name: None)
    monkeypatch.setattr(
        brain,
        "_create_score_lookup_collection_mission",
        lambda **kwargs: {
            "collection_required": True,
            "mission_created": False,
            "mission_id": None,
            "mission_mode": "mission_draft_only",
            "mission_draft": {
                "mission_type": "organization_score_data_collection",
                "organization_name": kwargs["organization_name"],
                "reason": "score_lookup_db_miss",
                "requested_scores": kwargs["requested_scores"],
                "status": "draft",
                "collection_required": True,
                "collection_targets": ["website", "rss", "youtube", "telegram", "web_search"],
                "created_by": "brain_score_lookup",
                "request_id": kwargs["request_id"],
            },
            "collection_targets": ["website", "rss", "youtube", "telegram", "web_search"],
        },
    )

    result = brain._resolve_score_lookup_if_applicable(
        user_message="Unknown Church 的评分是多少？",
        conversation_id="phase57a-miss-required",
        route="simple",
    )

    assert result is not None
    trace = brain.last_score_lookup_trace
    assert trace["db_hit"] is False
    assert trace["collection_required"] is True
    assert trace["organization_name"] == "Unknown Church"
    assert trace["answer_contract"] in {"not_found_collection_required", "not_found"}
    assert "People Score: 64" not in result["answer"]
    assert "Digital Score: 28" not in result["answer"]
    assert "Intel Score: 65" not in result["answer"]


def test_score_db_miss_creates_or_drafts_mission(monkeypatch):
    brain_module = importlib.import_module("services.brain")
    brain = brain_module.Brain()
    monkeypatch.setattr(brain, "_find_organization_for_score_lookup", lambda _name: None)
    monkeypatch.setattr(
        brain,
        "_create_score_lookup_collection_mission",
        lambda **kwargs: {
            "collection_required": True,
            "mission_created": True,
            "mission_id": "mission-123",
            "mission_mode": "created_persistent_mission",
            "mission_draft": None,
            "collection_targets": ["website", "rss", "youtube", "telegram", "web_search"],
        },
    )

    result = brain._resolve_score_lookup_if_applicable(
        user_message="Nonexistent Organization score?",
        conversation_id="phase57a-create-mission",
        route="simple",
    )

    assert result is not None
    assert result["mission_created"] is True
    assert result["mission_id"] == "mission-123"
    assert brain.last_score_lookup_trace["mission_created"] is True
    assert brain.last_score_lookup_trace["mission_id"] == "mission-123"


def test_collection_mission_contains_requested_scores(monkeypatch):
    brain_module = importlib.import_module("services.brain")
    brain = brain_module.Brain()
    monkeypatch.setattr(brain, "_find_organization_for_score_lookup", lambda _name: None)

    result = brain._resolve_score_lookup_if_applicable(
        user_message="Give me Unknown Mission people/digital/intel scores",
        conversation_id="phase57a-requested-scores",
        route="simple",
    )

    assert result is not None
    trace = brain.last_score_lookup_trace
    assert "people_score" in trace["requested_scores"]
    assert "digital_score" in trace["requested_scores"]
    assert "intel_score" in trace["requested_scores"]
    mission_draft = result.get("mission_draft")
    if mission_draft is not None:
        assert "people_score" in mission_draft["requested_scores"]
        assert "digital_score" in mission_draft["requested_scores"]
        assert "intel_score" in mission_draft["requested_scores"]


def test_collection_mission_does_not_call_llm(monkeypatch):
    brain_module = importlib.import_module("services.brain")
    brain = brain_module.Brain()
    monkeypatch.setattr(brain, "_find_organization_for_score_lookup", lambda _name: None)
    monkeypatch.setattr(
        brain_module.Brain,
        "_call_llm",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("_call_llm should not be called on score DB miss collection")),
    )
    monkeypatch.setattr(
        brain_module.Brain,
        "_call_llm_stream",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("_call_llm_stream should not be called on score DB miss collection")),
    )

    result = brain._resolve_score_lookup_if_applicable(
        user_message="Unknown Church 的评分是多少？",
        conversation_id="phase57a-no-llm",
        route="simple",
    )

    assert result is not None
    assert brain.last_score_lookup_trace["llm_called"] is False


def test_victory_philippines_db_hit_does_not_create_collection_mission(monkeypatch):
    brain_module = importlib.import_module("services.brain")
    brain = brain_module.Brain()
    monkeypatch.setattr(brain, "_find_organization_for_score_lookup", lambda _name: _make_org())
    monkeypatch.setattr(brain, "_evidence_from_organization_profile", lambda *_args, **_kwargs: {"type": "organization_score_lookup"})

    result = brain._resolve_score_lookup_if_applicable(
        user_message="Victory Philippines 的评分是多少？",
        conversation_id="phase57a-hit-no-mission",
        route="simple",
    )

    assert result is not None
    assert "People Score: 64" in result["answer"]
    assert "Digital Score: 28" in result["answer"]
    assert "Intel Score: 65" in result["answer"]
    trace = brain.last_score_lookup_trace
    assert trace["db_hit"] is True
    assert trace["collection_required"] is False
    assert trace["mission_created"] is False
    assert result["mission_id"] is None
