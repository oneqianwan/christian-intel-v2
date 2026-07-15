from __future__ import annotations

import importlib
import re

pytest_plugins = ["chat_ownership_testkit"]

from chat_ownership_testkit import create_user, login, parse_sse_text


def _set_flags(chat_runtime, *, ownership: bool, auth_enabled: bool = True) -> None:
    chat_runtime["config"].settings.CHAT_USER_OWNERSHIP_ENABLED = ownership
    chat_runtime["config"].settings.AUTH_V1_ENABLED = auth_enabled
    chat_runtime["config"].settings.AUTH_COOKIE_REQUIRED = False
    chat_runtime["config"].settings.ALLOW_PUBLIC_CORE_APIS = (not ownership) and (not auth_enabled)


class _FailPlannerPipeline:
    def run(self, *_args, **_kwargs):
        raise AssertionError("planner should be bypassed on score DB miss")


def _assert_miss_contract(text: str, organization_name: str) -> None:
    lowered = text.lower()
    assert organization_name in text
    assert "not_found" in lowered or "insufficient" in lowered or "未在当前数据库中找到" in text
    assert "llm_used=false" in lowered
    assert "data source: local intelligence database." in lowered or "数据来源：本地 intelligence database。" in text
    assert not re.search(r"People Score:\s*\d+", text)
    assert not re.search(r"Digital Score:\s*\d+", text)
    assert not re.search(r"Intel Score:\s*\d+", text)
    assert not re.search(r"Composite Score:\s*\d+", text)


def test_simple_db_miss_returns_not_found(chat_runtime):
    client = chat_runtime["client"]
    _set_flags(chat_runtime, ownership=True, auth_enabled=True)

    create_user(chat_runtime, email="miss-simple@example.com", password="StrongPass123!")
    login(client, email="miss-simple@example.com", password="StrongPass123!")

    response = client.post("/api/chat/simple", json={"message": "Unknown Church 的评分是多少？"})
    assert response.status_code == 200

    reply = response.json()["reply"]
    _assert_miss_contract(reply, "Unknown Church")


def test_stream_db_miss_returns_not_found(chat_runtime):
    client = chat_runtime["client"]
    _set_flags(chat_runtime, ownership=True, auth_enabled=True)

    create_user(chat_runtime, email="miss-stream@example.com", password="StrongPass123!")
    login(client, email="miss-stream@example.com", password="StrongPass123!")

    response = client.post("/api/chat/stream", json={"message": "Unknown Church 的评分是多少？"})
    assert response.status_code == 200

    events = parse_sse_text(response.text)
    done_event = next(item for item in events if item["type"] == "done")
    full_text = done_event["full_content"]
    _assert_miss_contract(full_text, "Unknown Church")


def test_db_miss_does_not_call_llm(chat_runtime, monkeypatch):
    client = chat_runtime["client"]
    _set_flags(chat_runtime, ownership=True, auth_enabled=True)

    create_user(chat_runtime, email="miss-no-llm@example.com", password="StrongPass123!")
    login(client, email="miss-no-llm@example.com", password="StrongPass123!")

    brain_module = importlib.import_module("services.brain")
    monkeypatch.setattr(
        brain_module.Brain,
        "_call_llm",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("_call_llm should not be called on score DB miss")),
    )
    monkeypatch.setattr(
        brain_module.Brain,
        "_call_llm_stream",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("_call_llm_stream should not be called on score DB miss")),
    )
    monkeypatch.setattr(brain_module, "BrainPlannerPipeline", _FailPlannerPipeline)

    simple_response = client.post("/api/chat/simple", json={"message": "Nonexistent Organization score?"})
    assert simple_response.status_code == 200
    _assert_miss_contract(simple_response.json()["reply"], "Nonexistent Organization")

    stream_response = client.post("/api/chat/stream", json={"message": "Nonexistent Organization score?"})
    assert stream_response.status_code == 200
    events = parse_sse_text(stream_response.text)
    done_event = next(item for item in events if item["type"] == "done")
    _assert_miss_contract(done_event["full_content"], "Nonexistent Organization")


def test_db_miss_does_not_include_confidence(chat_runtime):
    client = chat_runtime["client"]
    _set_flags(chat_runtime, ownership=True, auth_enabled=True)

    create_user(chat_runtime, email="miss-confidence@example.com", password="StrongPass123!")
    login(client, email="miss-confidence@example.com", password="StrongPass123!")

    response = client.post("/api/chat/simple", json={"message": "Unknown Church 的评分是多少？"})
    assert response.status_code == 200

    reply = response.json()["reply"]
    for forbidden in ["confidence", "Confidence", "置信度", "可靠度", "评分置信"]:
        assert forbidden not in reply
    assert not re.search(r"confidence\s*:\s*\d+", reply, re.IGNORECASE)


def test_db_miss_does_not_recommend_action_based_on_fake_score(chat_runtime):
    client = chat_runtime["client"]
    _set_flags(chat_runtime, ownership=True, auth_enabled=True)

    create_user(chat_runtime, email="miss-action@example.com", password="StrongPass123!")
    login(client, email="miss-action@example.com", password="StrongPass123!")

    response = client.post("/api/chat/simple", json={"message": "Give me Unknown Mission people/digital/intel scores"})
    assert response.status_code == 200

    reply = response.json()["reply"]
    for forbidden in ["建议投资", "建议合作", "high potential", "low risk", "confidence 49", "recommend investing", "recommend partnership"]:
        assert forbidden not in reply


def test_non_score_query_still_allowed_to_use_normal_path():
    brain_module = importlib.import_module("services.brain")
    brain = brain_module.Brain()
    result = brain._resolve_score_lookup_if_applicable(
        user_message="Tell me about Unknown Church",
        conversation_id="phase56c-non-score",
    )
    assert result is None
