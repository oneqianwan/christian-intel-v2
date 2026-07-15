from __future__ import annotations

import importlib

pytest_plugins = ["chat_ownership_testkit"]

from chat_ownership_testkit import create_user, login, parse_sse_text


def _set_flags(chat_runtime, *, ownership: bool, auth_enabled: bool = True) -> None:
    chat_runtime["config"].settings.CHAT_USER_OWNERSHIP_ENABLED = ownership
    chat_runtime["config"].settings.AUTH_V1_ENABLED = auth_enabled
    chat_runtime["config"].settings.AUTH_COOKIE_REQUIRED = False
    chat_runtime["config"].settings.ALLOW_PUBLIC_CORE_APIS = (not ownership) and (not auth_enabled)


def _seed_victory_philippines(chat_runtime, *, org_id: str) -> None:
    db = chat_runtime["database"].SessionLocal()
    try:
        db.query(chat_runtime["database"].OrganizationProfile).filter(
            chat_runtime["database"].OrganizationProfile.name == "Victory Philippines"
        ).delete()
        db.add(
            chat_runtime["database"].OrganizationProfile(
                id=org_id,
                name="Victory Philippines",
                country="Philippines",
                source_name="manual_seed",
                official_website="https://victory.org.ph",
                people_score=64,
                digital_score=28,
                intel_score=65,
            )
        )
        db.commit()
    finally:
        db.close()


class _FailPlannerPipeline:
    def run(self, *_args, **_kwargs):
        raise AssertionError("planner should be bypassed on score DB hit")


def test_simple_db_hit_does_not_call_llm(chat_runtime, monkeypatch):
    client = chat_runtime["client"]
    _set_flags(chat_runtime, ownership=True, auth_enabled=True)
    _seed_victory_philippines(chat_runtime, org_id="org-victory-no-llm-simple")

    create_user(chat_runtime, email="no-llm-simple@example.com", password="StrongPass123!")
    login(client, email="no-llm-simple@example.com", password="StrongPass123!")

    brain_module = importlib.import_module("services.brain")
    monkeypatch.setattr(brain_module.Brain, "_call_llm", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("_call_llm should not be called on score DB hit")))
    monkeypatch.setattr(
        brain_module.Brain,
        "_call_llm_stream",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("_call_llm_stream should not be called on score DB hit")),
    )
    monkeypatch.setattr(brain_module, "BrainPlannerPipeline", _FailPlannerPipeline)

    response = client.post("/api/chat/simple", json={"message": "Victory Philippines people score?"})
    assert response.status_code == 200
    assert "People Score: 64" in response.json()["reply"]
    assert "llm_used=false" in response.json()["reply"]


def test_stream_db_hit_does_not_call_llm_stream(chat_runtime, monkeypatch):
    client = chat_runtime["client"]
    _set_flags(chat_runtime, ownership=True, auth_enabled=True)
    _seed_victory_philippines(chat_runtime, org_id="org-victory-no-llm-stream")

    create_user(chat_runtime, email="no-llm-stream@example.com", password="StrongPass123!")
    login(client, email="no-llm-stream@example.com", password="StrongPass123!")

    brain_module = importlib.import_module("services.brain")
    monkeypatch.setattr(brain_module.Brain, "_call_llm", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("_call_llm should not be called on score DB hit")))
    monkeypatch.setattr(
        brain_module.Brain,
        "_call_llm_stream",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("_call_llm_stream should not be called on score DB hit")),
    )
    monkeypatch.setattr(brain_module, "BrainPlannerPipeline", _FailPlannerPipeline)

    response = client.post("/api/chat/stream", json={"message": "Victory Philippines intel score?"})
    assert response.status_code == 200
    events = parse_sse_text(response.text)
    done_event = next(item for item in events if item["type"] == "done")
    assert "Intel Score: 65" in done_event["full_content"]
    assert "llm_used=false" in done_event["full_content"]
