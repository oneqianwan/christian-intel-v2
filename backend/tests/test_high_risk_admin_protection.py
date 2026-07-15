from __future__ import annotations

import uuid

import pytest

from test_auth_api import _reset_auth_settings, runtime


_RUNTIME_CONFIG = None
_RUNTIME_MAIN = None


@pytest.fixture(autouse=True)
def reset_db(runtime):
    global _RUNTIME_CONFIG, _RUNTIME_MAIN
    database = runtime["database"]
    auth_models = runtime["auth_models"]
    client = runtime["client"]
    auth_service = runtime["auth_service"]
    _RUNTIME_CONFIG = runtime["config"]
    _RUNTIME_MAIN = runtime["main"]

    db = database.SessionLocal()
    try:
        db.execute(database.text("DELETE FROM bookmarks"))
        db.execute(database.text("DELETE FROM user_feedbacks"))
        db.execute(database.text("DELETE FROM intelligence_items"))
        db.execute(database.text("DELETE FROM pages"))
        db.execute(database.text("DELETE FROM sources"))
        db.execute(database.text("DELETE FROM api_configs"))
        db.execute(database.text("DELETE FROM organization_profiles"))
        db.query(auth_models.AuthSession).delete()
        db.query(auth_models.User).delete()
        db.commit()
    finally:
        db.close()

    client.cookies.clear()
    limiter = getattr(auth_service, "_default_rate_limiter", None)
    if limiter is not None:
        lock = getattr(limiter, "_lock", None)
        attempts = getattr(limiter, "_attempts", None)
        if lock is not None and attempts is not None:
            with lock:
                attempts.clear()
    _reset_auth_settings(runtime)


def _error_code(response) -> str | None:
    payload = response.json()
    detail = payload.get("detail")
    if isinstance(detail, dict):
        return detail.get("error_code")
    return payload.get("error_code")


def _set_auth_enabled(enabled: bool) -> None:
    value = bool(enabled)
    if _RUNTIME_CONFIG is not None:
        _RUNTIME_CONFIG.settings.AUTH_V1_ENABLED = value
    import sys

    config_module = sys.modules.get("config")
    if config_module is not None:
        config_module.settings.AUTH_V1_ENABLED = value
    auth_dependencies = sys.modules.get("dependencies.auth")
    if auth_dependencies is not None:
        auth_dependencies.config.settings.AUTH_V1_ENABLED = value
    if _RUNTIME_MAIN is not None:
        visited: set[int] = set()

        def _sync_dependant(dependant) -> None:
            for dependency in getattr(dependant, "dependencies", []):
                _sync_dependant(dependency)
            call = getattr(dependant, "call", None)
            if call is None or id(call) in visited:
                return
            visited.add(id(call))
            globals_dict = getattr(call, "__globals__", {})
            config_module = globals_dict.get("config")
            settings = getattr(config_module, "settings", None)
            if settings is not None and hasattr(settings, "AUTH_V1_ENABLED"):
                settings.AUTH_V1_ENABLED = value

        for route in getattr(_RUNTIME_MAIN.app, "routes", []):
            dependant = getattr(route, "dependant", None)
            if dependant is not None:
                _sync_dependant(dependant)


def _create_user(runtime, *, email: str, password: str, role: str, status: str = "active"):
    database = runtime["database"]
    auth_models = runtime["auth_models"]
    auth_service = runtime["auth_service"]
    db = database.SessionLocal()
    try:
        user = auth_models.User(
            email=email,
            email_normalized=auth_service.normalize_email(email),
            password_hash=auth_service.hash_password(password),
            display_name="User",
            role=role,
            status=status,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    finally:
        db.close()


def _login(client, *, email: str, password: str) -> None:
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200


def _seed_api_config(runtime):
    database = runtime["database"]
    db = database.SessionLocal()
    try:
        row = database.ApiConfig(
            api_name="openai",
            encrypted_api_key="enc-key",
            key_hint="abcd",
            extra_config={"region": "us"},
            status="ok",
            usage_info="ready",
        )
        db.add(row)
        db.commit()
    finally:
        db.close()


def _seed_org(runtime, *, org_id: str = "org-1", name: str = "Org One", country: str = "PH"):
    database = runtime["database"]
    db = database.SessionLocal()
    try:
        org = database.OrganizationProfile(id=org_id, name=name, country=country)
        db.add(org)
        db.commit()
        return org
    finally:
        db.close()


def test_01_unauthenticated_agent_run_returns_401(runtime):
    client = runtime["client"]
    _set_auth_enabled(True)

    response = client.post("/api/agent/run")

    assert response.status_code == 401
    assert _error_code(response) == "AUTH_REQUIRED"


@pytest.mark.parametrize("role", ["analyst", "viewer"])
def test_02_analyst_and_viewer_agent_run_return_403(runtime, role):
    client = runtime["client"]
    _set_auth_enabled(True)
    _create_user(runtime, email=f"{role}@example.com", password="Password123456!", role=role)

    _login(client, email=f"{role}@example.com", password="Password123456!")
    response = client.post(
        "/api/agent/run",
        headers={"x-role": "super_admin", "x-session-id": "forged", "x-user-id": "forged"},
    )

    assert response.status_code == 403
    assert _error_code(response) == "ROLE_FORBIDDEN"


@pytest.mark.parametrize("role", ["admin", "super_admin"])
def test_03_admin_and_super_admin_agent_run_can_enter_business_logic(runtime, monkeypatch, role):
    client = runtime["client"]
    _set_auth_enabled(True)
    _create_user(runtime, email=f"{role}@example.com", password="Password123456!", role=role)

    import agent.loop as agent_loop

    monkeypatch.setattr(agent_loop, "run_agent_cycle", lambda force=True: {"tasks_created": 2})

    _login(client, email=f"{role}@example.com", password="Password123456!")
    response = client.post("/api/agent/run")

    assert response.status_code == 200
    assert response.json()["started"] is True


def test_04_configs_keys_unauthenticated_returns_401(runtime):
    client = runtime["client"]
    _set_auth_enabled(True)
    _seed_api_config(runtime)

    response = client.get("/api/configs/keys")

    assert response.status_code == 401
    assert _error_code(response) == "AUTH_REQUIRED"


def test_05_configs_keys_admin_returns_403(runtime):
    client = runtime["client"]
    _set_auth_enabled(True)
    _seed_api_config(runtime)
    _create_user(runtime, email="admin@example.com", password="Password123456!", role="admin")

    _login(client, email="admin@example.com", password="Password123456!")
    response = client.get("/api/configs/keys")

    assert response.status_code == 403
    assert _error_code(response) == "ROLE_FORBIDDEN"


def test_06_configs_keys_super_admin_returns_200(runtime):
    client = runtime["client"]
    _set_auth_enabled(True)
    _seed_api_config(runtime)
    _create_user(runtime, email="root@example.com", password="Password123456!", role="super_admin")

    _login(client, email="root@example.com", password="Password123456!")
    response = client.get("/api/configs/keys")

    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["api_name"] == "openai"
    assert "encrypted_api_key" not in str(payload)


def test_07_dashboard_write_unauthenticated_returns_401(runtime):
    client = runtime["client"]
    _set_auth_enabled(True)
    _seed_org(runtime)

    response = client.post(
        "/api/dashboard/manual-update",
        json={"org_id": "org-1", "field": "official_website", "value": "https://example.com"},
    )

    assert response.status_code == 401
    assert _error_code(response) == "AUTH_REQUIRED"


@pytest.mark.parametrize("role", ["analyst", "viewer"])
def test_08_dashboard_write_analyst_viewer_return_403(runtime, role):
    client = runtime["client"]
    _set_auth_enabled(True)
    _seed_org(runtime)
    _create_user(runtime, email=f"{role}@example.com", password="Password123456!", role=role)

    _login(client, email=f"{role}@example.com", password="Password123456!")
    response = client.post(
        "/api/dashboard/manual-update",
        json={"org_id": "org-1", "field": "official_website", "value": "https://example.com"},
    )

    assert response.status_code == 403
    assert _error_code(response) == "ROLE_FORBIDDEN"


@pytest.mark.parametrize("role", ["admin", "super_admin"])
def test_09_dashboard_write_admin_and_super_admin_return_200(runtime, role):
    client = runtime["client"]
    _set_auth_enabled(True)
    _seed_org(runtime)
    _create_user(runtime, email=f"{role}@example.com", password="Password123456!", role=role)

    _login(client, email=f"{role}@example.com", password="Password123456!")
    response = client.post(
        "/api/dashboard/manual-update",
        json={"org_id": "org-1", "field": "official_website", "value": "https://example.com"},
    )

    assert response.status_code == 200
    assert response.json()["success"] is True


def test_10_dashboard_read_endpoint_requires_auth(runtime):
    client = runtime["client"]
    _set_auth_enabled(True)

    response = client.get("/api/dashboard/coverage")

    assert response.status_code == 401
    assert _error_code(response) == "AUTH_REQUIRED"


def test_11_feedback_stats_require_admin(runtime):
    client = runtime["client"]
    _set_auth_enabled(True)
    _create_user(runtime, email="viewer@example.com", password="Password123456!", role="viewer")

    _login(client, email="viewer@example.com", password="Password123456!")
    response = client.get("/api/feedback/stats")

    assert response.status_code == 403
    assert _error_code(response) == "ROLE_FORBIDDEN"


def test_12_feedback_stats_admin_passes(runtime):
    client = runtime["client"]
    _set_auth_enabled(True)
    _create_user(runtime, email="admin@example.com", password="Password123456!", role="admin")

    _login(client, email="admin@example.com", password="Password123456!")
    response = client.get("/api/feedback/stats")

    assert response.status_code == 200
    assert "total_feedback" in response.json()
