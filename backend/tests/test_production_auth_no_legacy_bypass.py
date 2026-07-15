from __future__ import annotations

import pytest

from production_auth_testkit import reset_runtime_state, runtime


@pytest.fixture(autouse=True)
def _reset_runtime(runtime):
    reset_runtime_state(runtime)
    yield


def _error_code(response) -> str | None:
    payload = response.json()
    detail = payload.get("detail")
    if isinstance(detail, dict):
        return detail.get("error_code")
    return payload.get("error_code")


def _set_production_auth_defaults(runtime) -> None:
    settings = runtime["config"].settings
    settings.APP_ENV = "production"
    settings.DEPLOYMENT_ENV = "production"
    settings.AUTH_V1_ENABLED = True
    settings.AUTH_COOKIE_REQUIRED = True
    settings.CHAT_USER_OWNERSHIP_ENABLED = True
    settings.WATCH_ALERT_USER_OWNERSHIP_ENABLED = True
    settings.BOOKMARKS_USER_OWNERSHIP_ENABLED = True
    settings.FEEDBACK_USER_OWNERSHIP_ENABLED = True
    settings.ALLOW_PUBLIC_CORE_APIS = False
    settings.ALLOW_LEGACY_SESSION_ID = False
    settings.ALLOW_ANONYMOUS_FEEDBACK = False
    settings.WATCH_ALERT_V1_ENABLED = True
    settings.WATCH_ALERT_NOTIFICATIONS_ENABLED = True
    settings.WATCH_ALERT_SCHEDULER_ENABLED = True


def _seed_org(runtime, *, org_id: str) -> None:
    database = runtime["database"]
    db = database.SessionLocal()
    try:
        if db.query(database.OrganizationProfile).filter_by(id=org_id).first() is None:
            db.add(
                database.OrganizationProfile(
                    id=org_id,
                    name=org_id,
                    country="PH",
                    leader_name="Leader",
                    official_website="https://example.org",
                    people_score=10,
                    digital_score=20,
                    intel_score=30,
                )
            )
            db.commit()
    finally:
        db.close()


def _seed_item(runtime, *, item_id: str) -> None:
    database = runtime["database"]
    db = database.SessionLocal()
    try:
        source = database.Source(
            id=f"source-{item_id}",
            name="Source",
            url=f"https://example.com/{item_id}",
            type="rss",
            country="PH",
        )
        page = database.Page(
            id=f"page-{item_id}",
            source_id=source.id,
            url=f"https://example.com/{item_id}/page",
            title="Page",
        )
        item = database.IntelligenceItem(
            id=item_id,
            page_id=page.id,
            source_id=source.id,
            title=item_id,
            source_name="Source",
            source_url=page.url,
            country="PH",
            entity_name="Org",
            entity_type="organization",
            category="news",
        )
        db.add(source)
        db.add(page)
        db.add(item)
        db.commit()
    finally:
        db.close()


def test_defaults_are_fail_closed(runtime):
    _set_production_auth_defaults(runtime)
    settings = runtime["config"].settings

    assert settings.AUTH_V1_ENABLED is True
    assert settings.CHAT_USER_OWNERSHIP_ENABLED is True
    assert settings.WATCH_ALERT_USER_OWNERSHIP_ENABLED is True
    assert settings.ALLOW_PUBLIC_CORE_APIS is False
    assert settings.ALLOW_LEGACY_SESSION_ID is False
    assert settings.ALLOW_ANONYMOUS_FEEDBACK is False


def test_production_rejects_x_session_id_watch_bypass(runtime):
    client = runtime["client"]
    _set_production_auth_defaults(runtime)
    runtime["config"].settings.WATCH_ALERT_USER_OWNERSHIP_ENABLED = False
    _seed_org(runtime, org_id="org-watch-prod")

    response = client.post(
        "/api/watch-targets",
        headers={"x-session-id": "legacy-user-a"},
        json={"entity_id": "org-watch-prod", "entity_type": "organization", "frequency": "daily"},
    )

    assert response.status_code == 401
    assert _error_code(response) == "AUTH_REQUIRED"


def test_production_bookmarks_do_not_fall_back_to_default_bucket(runtime):
    client = runtime["client"]
    database = runtime["database"]
    _set_production_auth_defaults(runtime)
    _seed_item(runtime, item_id="bookmark-item")

    response = client.post("/api/bookmarks", params={"item_id": "bookmark-item", "note": "legacy"})

    assert response.status_code == 401
    assert _error_code(response) == "AUTH_REQUIRED"

    db = database.SessionLocal()
    try:
        assert db.query(database.Bookmark).count() == 0
    finally:
        db.close()


def test_production_feedback_rejects_legacy_header_spoof(runtime):
    client = runtime["client"]
    _set_production_auth_defaults(runtime)

    response = client.post(
        "/api/feedback",
        headers={"x-session-id": "forged-session"},
        json={"feedback_type": "match_useful", "content": "forged"},
    )

    assert response.status_code == 401
    assert _error_code(response) == "AUTH_REQUIRED"


def test_explicit_dev_legacy_flag_is_required_for_watch_header_mode(runtime):
    client = runtime["client"]
    _set_production_auth_defaults(runtime)
    runtime["config"].settings.APP_ENV = "development"
    runtime["config"].settings.DEPLOYMENT_ENV = "test"
    runtime["config"].settings.WATCH_ALERT_USER_OWNERSHIP_ENABLED = False
    runtime["config"].settings.ALLOW_LEGACY_SESSION_ID = True
    _seed_org(runtime, org_id="org-watch-dev")

    response = client.post(
        "/api/watch-targets",
        headers={"x-session-id": "legacy-user-a"},
        json={"entity_id": "org-watch-dev", "entity_type": "organization", "frequency": "daily"},
    )

    assert response.status_code == 201
