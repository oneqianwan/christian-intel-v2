from __future__ import annotations

pytest_plugins = ["chat_ownership_testkit"]

from chat_ownership_testkit import create_user, login


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
                id="org-victory-philippines-score-simple",
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


def test_simple_score_query_db_hit(chat_runtime):
    client = chat_runtime["client"]
    _set_flags(chat_runtime, ownership=True, auth_enabled=True)
    _seed_victory_philippines(chat_runtime)

    create_user(chat_runtime, email="score-simple@example.com", password="StrongPass123!")
    login(client, email="score-simple@example.com", password="StrongPass123!")

    response = client.post("/api/chat/simple", json={"message": "Victory Philippines 的评分是多少？"})
    assert response.status_code == 200

    reply = response.json()["reply"]
    assert "Victory Philippines" in reply
    assert "People Score: 64" in reply
    assert "Digital Score: 28" in reply
    assert "Intel Score: 65" in reply
    assert "llm_used=false" in reply
    assert "Every Nation" not in reply
    assert "confidence" not in reply.lower()
