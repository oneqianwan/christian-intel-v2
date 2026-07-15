from __future__ import annotations

pytest_plugins = ["chat_ownership_testkit"]

import pytest

from account_lifecycle_testkit import create_user, error_code, login, runtime, set_production_auth_defaults
from production_auth_testkit import reset_runtime_state
from test_production_readiness_core_uat import _block_llm_and_network, seeded_runtime


@pytest.fixture(autouse=True)
def _reset_runtime(runtime):
    reset_runtime_state(runtime)
    set_production_auth_defaults(runtime)
    yield


@pytest.mark.parametrize(
    ("method", "path", "kwargs"),
    [
        ("post", "/api/chat/simple", {"json": {"message": "hello"}}),
        ("post", "/api/chat/stream", {"json": {"message": "hello"}}),
        ("get", "/api/conversations", {}),
        ("get", "/api/export/html", {"params": {"query": "victory", "country": "菲律宾"}}),
        ("get", "/api/dashboard/overview", {}),
    ],
)
def test_a1_core_apis_still_require_auth(runtime, method, path, kwargs):
    client = runtime["client"]

    response = getattr(client, method)(path, **kwargs)

    assert response.status_code == 401
    assert error_code(response) == "AUTH_REQUIRED"


def test_legacy_bypasses_and_default_bucket_remain_disabled(runtime):
    client = runtime["client"]
    database = runtime["database"]
    runtime["config"].settings.WATCH_ALERT_USER_OWNERSHIP_ENABLED = False

    response_watch = client.post(
        "/api/watch-targets",
        headers={"x-session-id": "legacy-user"},
        json={"entity_id": "org-1", "entity_type": "organization", "frequency": "daily"},
    )
    response_bookmark = client.post("/api/bookmarks", params={"item_id": "bookmark-item", "note": "legacy"})
    response_feedback = client.post(
        "/api/feedback",
        headers={"x-session-id": "legacy-session"},
        json={"feedback_type": "match_useful", "content": "legacy"},
    )

    assert response_watch.status_code == 401
    assert error_code(response_watch) == "AUTH_REQUIRED"
    assert response_bookmark.status_code == 401
    assert error_code(response_bookmark) == "AUTH_REQUIRED"
    assert response_feedback.status_code == 401
    assert error_code(response_feedback) == "AUTH_REQUIRED"

    db = database.SessionLocal()
    try:
        assert db.query(database.Bookmark).count() == 0
        assert db.query(database.UserFeedback).count() == 0
    finally:
        db.close()


def test_admin_unauthorized_and_fail_closed_regressions_hold(runtime):
    client = runtime["client"]

    create_user(runtime, email="viewer@example.com", password="Password123456!", role="viewer")
    login(client, email="viewer@example.com", password="Password123456!")
    forbidden = client.get("/api/admin/users")
    assert forbidden.status_code == 403
    assert error_code(forbidden) == "ROLE_FORBIDDEN"

    client.cookies.clear()
    runtime["config"].settings.AUTH_V1_ENABLED = False
    admin_response = client.get("/api/admin/users")
    chat_response = client.post("/api/chat/simple", json={"message": "hello"})

    assert admin_response.status_code == 503
    assert error_code(admin_response) == "AUTH_DISABLED"
    assert chat_response.status_code == 503
    assert error_code(chat_response) == "AUTH_DISABLED"


def test_response_contract_observability_and_no_llm_do_not_regress(seeded_runtime, monkeypatch):
    brain_module = seeded_runtime["brain_module"]
    checker = seeded_runtime["readiness_module"].ProductionReadinessChecker()
    _block_llm_and_network(monkeypatch, brain_module)

    contract = brain_module.Brain().think(
        "Victory Philippines 评分是多少？",
        conversation_id="auth-lifecycle-regression-70a2",
    )["response_contract"]
    report = checker.build_report(contracts=[contract])

    assert contract["response_contract_version"] == "6.0D"
    assert contract["observability"]["audit_summary"]["audit_version"] == "6.0E"
    assert contract["audit"]["no_llm"] is True
    assert contract["audit"]["no_network"] is True
    assert contract["audit"]["no_fabrication"] is True
    assert report["readiness_version"] == "6.0F"
    assert report["core_brain"]["response_contract_ok"] is True
    assert report["core_brain"]["observability_ok"] is True
    assert report["safety"]["no_llm_for_structured_lookup"] is True
    assert report["safety"]["no_network_for_structured_lookup"] is True
    assert report["safety"]["no_fabrication"] is True
