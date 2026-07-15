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


@pytest.mark.parametrize(
    ("method", "path", "kwargs"),
    [
        ("post", "/api/chat/simple", {"json": {"message": "hello"}}),
        ("post", "/api/chat/stream", {"json": {"message": "hello"}}),
        ("get", "/api/conversations", {}),
        ("get", "/api/diagnostics/request/request-1", {}),
        ("get", "/api/export/html", {"params": {"query": "victory", "country": "菲律宾"}}),
        ("get", "/api/export/pdf", {"params": {"query": "victory", "country": "菲律宾"}}),
        ("get", "/api/dashboard/overview", {}),
        ("get", "/api/dashboard/scores", {}),
        ("get", "/api/dashboard/org/org-1", {}),
        ("get", "/api/dashboard/relations/org-1", {}),
    ],
)
def test_protected_core_apis_reject_unauthenticated_requests(runtime, method, path, kwargs):
    client = runtime["client"]
    _set_production_auth_defaults(runtime)
    client.cookies.clear()

    response = getattr(client, method)(path, **kwargs)

    assert response.status_code == 401
    assert _error_code(response) == "AUTH_REQUIRED"
