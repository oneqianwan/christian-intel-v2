from __future__ import annotations

pytest_plugins = ["chat_ownership_testkit"]

from chat_ownership_testkit import create_user, login, parse_sse_text


def _set_flags(chat_runtime, *, ownership: bool, auth_enabled: bool = True) -> None:
    chat_runtime["config"].settings.CHAT_USER_OWNERSHIP_ENABLED = ownership
    chat_runtime["config"].settings.AUTH_V1_ENABLED = auth_enabled
    chat_runtime["config"].settings.AUTH_COOKIE_REQUIRED = False
    chat_runtime["config"].settings.ALLOW_PUBLIC_CORE_APIS = (not ownership) and (not auth_enabled)


def _seed_victory_philippines(chat_runtime) -> None:
    db = chat_runtime["database"].SessionLocal()
    try:
        db.query(chat_runtime["database"].OrganizationProfile).filter(
            chat_runtime["database"].OrganizationProfile.name == "Victory Philippines"
        ).delete()
        db.add(
            chat_runtime["database"].OrganizationProfile(
                id="org-victory-philippines-score-stream",
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


def test_stream_score_query_db_hit(chat_runtime):
    client = chat_runtime["client"]
    _set_flags(chat_runtime, ownership=True, auth_enabled=True)
    _seed_victory_philippines(chat_runtime)

    create_user(chat_runtime, email="score-stream@example.com", password="StrongPass123!")
    login(client, email="score-stream@example.com", password="StrongPass123!")

    response = client.post("/api/chat/stream", json={"message": "Show me Victory Philippines scores"})
    assert response.status_code == 200

    events = parse_sse_text(response.text)
    done_event = next(item for item in events if item["type"] == "done")
    full_text = done_event["full_content"]

    assert "Victory Philippines" in full_text
    assert "People Score: 64" in full_text
    assert "Digital Score: 28" in full_text
    assert "Intel Score: 65" in full_text
    assert "llm_used=false" in full_text
    assert "Every Nation" not in full_text
    assert "confidence" not in full_text.lower()
