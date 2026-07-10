from __future__ import annotations

import importlib
import logging
from types import SimpleNamespace


def _make_org(name: str = "Victory Philippines") -> SimpleNamespace:
    return SimpleNamespace(
        name=name,
        people_score=64,
        digital_score=28,
        intel_score=65,
        composite_score=None,
    )


def _assert_common_trace_fields(trace: dict, *, route: str, organization_name: str, db_hit: bool, answer_contract: str) -> None:
    assert trace["request_id"]
    assert trace["route"] == route
    assert trace["organization_name"] == organization_name
    assert trace["db_hit"] is db_hit
    assert trace["llm_called"] is False
    assert trace["fallback_used"] is False
    assert trace["answer_contract"] == answer_contract
    assert isinstance(trace["total_ms"], float)
    assert trace["total_ms"] >= 0.0
    assert isinstance(trace["db_lookup_ms"], float)
    assert trace["db_lookup_ms"] >= 0.0
    assert isinstance(trace["intent_detection_ms"], float)
    assert trace["intent_detection_ms"] >= 0.0
    assert trace["planner_ms"] == 0.0
    assert trace["llm_ms"] == 0.0


def test_simple_score_db_hit_records_latency_span(monkeypatch):
    brain_module = importlib.import_module("services.brain")
    brain = brain_module.Brain()
    monkeypatch.setattr(brain, "_find_organization_for_score_lookup", lambda _name: _make_org())
    monkeypatch.setattr(brain, "_evidence_from_organization_profile", lambda *_args, **_kwargs: {"type": "organization_score_lookup"})

    result = brain._resolve_score_lookup_if_applicable(
        user_message="Victory Philippines 的评分是多少？",
        conversation_id="phase56d-simple-hit",
        route="simple",
    )

    assert result is not None
    assert "People Score: 64" in result["answer"]
    trace = brain.last_score_lookup_trace
    _assert_common_trace_fields(
        trace,
        route="simple",
        organization_name="Victory Philippines",
        db_hit=True,
        answer_contract="score_lookup",
    )


def test_stream_score_db_hit_records_latency_span(monkeypatch):
    brain_module = importlib.import_module("services.brain")
    brain = brain_module.Brain()
    monkeypatch.setattr(brain, "_find_organization_for_score_lookup", lambda _name: _make_org())
    monkeypatch.setattr(brain, "_evidence_from_organization_profile", lambda *_args, **_kwargs: {"type": "organization_score_lookup"})

    result = brain._resolve_score_lookup_if_applicable(
        user_message="Victory Philippines 的评分是多少？",
        conversation_id="phase56d-stream-hit",
        route="stream",
    )

    assert result is not None
    trace = brain.last_score_lookup_trace
    _assert_common_trace_fields(
        trace,
        route="stream",
        organization_name="Victory Philippines",
        db_hit=True,
        answer_contract="score_lookup",
    )


def test_simple_score_db_miss_records_not_found_span(monkeypatch):
    brain_module = importlib.import_module("services.brain")
    brain = brain_module.Brain()
    monkeypatch.setattr(brain, "_find_organization_for_score_lookup", lambda _name: None)

    result = brain._resolve_score_lookup_if_applicable(
        user_message="Unknown Church 的评分是多少？",
        conversation_id="phase56d-simple-miss",
        route="simple",
    )

    assert result is not None
    assert "Unknown Church" in result["answer"]
    trace = brain.last_score_lookup_trace
    _assert_common_trace_fields(
        trace,
        route="simple",
        organization_name="Unknown Church",
        db_hit=False,
        answer_contract="not_found",
    )


def test_stream_score_db_miss_records_not_found_span(monkeypatch):
    brain_module = importlib.import_module("services.brain")
    brain = brain_module.Brain()
    monkeypatch.setattr(brain, "_find_organization_for_score_lookup", lambda _name: None)

    result = brain._resolve_score_lookup_if_applicable(
        user_message="Unknown Church 的评分是多少？",
        conversation_id="phase56d-stream-miss",
        route="stream",
    )

    assert result is not None
    trace = brain.last_score_lookup_trace
    _assert_common_trace_fields(
        trace,
        route="stream",
        organization_name="Unknown Church",
        db_hit=False,
        answer_contract="not_found",
    )


def test_score_lookup_logs_do_not_expose_sensitive_values(monkeypatch, caplog):
    brain_module = importlib.import_module("services.brain")
    brain = brain_module.Brain()
    monkeypatch.setattr(brain, "_find_organization_for_score_lookup", lambda _name: _make_org())
    monkeypatch.setattr(brain, "_evidence_from_organization_profile", lambda *_args, **_kwargs: {"type": "organization_score_lookup"})

    with caplog.at_level(logging.INFO, logger="services.brain"):
        result = brain._resolve_score_lookup_if_applicable(
            user_message="Victory Philippines 的评分是多少？",
            conversation_id="phase56d-sensitive",
            route="simple",
        )

    assert result is not None
    trace = brain.last_score_lookup_trace
    serialized_trace = repr(trace).lower()
    assert "password" not in serialized_trace
    assert "token" not in serialized_trace
    assert "api_key" not in serialized_trace
    assert "authorization" not in serialized_trace
    assert "session secret" not in serialized_trace

    log_text = caplog.text.lower()
    assert "event=brain.score_lookup" in log_text
    assert "password" not in log_text
    assert "token" not in log_text
    assert "api_key" not in log_text
    assert "authorization" not in log_text
    assert "session secret" not in log_text
