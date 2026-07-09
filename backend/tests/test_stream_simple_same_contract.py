from __future__ import annotations

pytest_plugins = ["chat_ownership_testkit"]

from chat_ownership_testkit import create_user, login, parse_sse_text


def _set_flags(chat_runtime, *, ownership: bool, auth_enabled: bool = True) -> None:
    chat_runtime["config"].settings.CHAT_USER_OWNERSHIP_ENABLED = ownership
    chat_runtime["config"].settings.AUTH_V1_ENABLED = auth_enabled
    chat_runtime["config"].settings.AUTH_COOKIE_REQUIRED = False


def _seed_victory_philippines(chat_runtime) -> None:
    db = chat_runtime["database"].SessionLocal()
    try:
        db.query(chat_runtime["database"].OrganizationProfile).filter(
            chat_runtime["database"].OrganizationProfile.name == "Victory Philippines"
        ).delete()
        db.add(
            chat_runtime["database"].OrganizationProfile(
                id="org-victory-same-contract",
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


def test_simple_and_stream_return_same_score_contract(chat_runtime):
    client = chat_runtime["client"]
    _set_flags(chat_runtime, ownership=True, auth_enabled=True)
    _seed_victory_philippines(chat_runtime)

    create_user(chat_runtime, email="same-contract@example.com", password="StrongPass123!")
    login(client, email="same-contract@example.com", password="StrongPass123!")

    message = "Victory Philippines 的评分是多少？"

    simple_response = client.post("/api/chat/simple", json={"message": message})
    assert simple_response.status_code == 200
    simple_text = simple_response.json()["reply"]

    stream_response = client.post("/api/chat/stream", json={"message": message})
    assert stream_response.status_code == 200
    events = parse_sse_text(stream_response.text)
    done_event = next(item for item in events if item["type"] == "done")
    stream_text = done_event["full_content"]

    assert simple_text == stream_text
    for snippet in [
        "Victory Philippines",
        "People Score: 64",
        "Digital Score: 28",
        "Intel Score: 65",
        "llm_used=false",
    ]:
        assert snippet in simple_text
        assert snippet in stream_text
