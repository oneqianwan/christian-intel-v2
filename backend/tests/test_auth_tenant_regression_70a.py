from __future__ import annotations

import pytest

from account_lifecycle_testkit import create_user, error_code, login, runtime, set_production_auth_defaults
from production_auth_testkit import reset_runtime_state
from tenant_testkit import ensure_default_tenant


@pytest.fixture(autouse=True)
def _reset_runtime(runtime):
    reset_runtime_state(runtime)
    set_production_auth_defaults(runtime)
    ensure_default_tenant(runtime)
    yield


def test_unauthenticated_core_auth_protection_unchanged(runtime):
    client = runtime["client"]

    for method, path, kwargs in [
        ("post", "/api/chat/simple", {"json": {"message": "hello"}}),
        ("post", "/api/chat/stream", {"json": {"message": "hello"}}),
        ("get", "/api/conversations", {}),
    ]:
        response = getattr(client, method)(path, **kwargs)
        assert response.status_code == 401
        assert error_code(response) == "AUTH_REQUIRED"


def test_admin_unauthorized_still_403(runtime):
    client = runtime["client"]
    create_user(runtime, email="viewer@example.com", password="Password123456!", role="viewer")
    login(client, email="viewer@example.com", password="Password123456!")

    response = client.get("/api/admin/users")
    assert response.status_code == 403
    assert error_code(response) == "ROLE_FORBIDDEN"


def test_admin_create_user_still_protected(runtime):
    client = runtime["client"]
    response = client.post(
        "/api/admin/users",
        json={"email": "new@example.com", "display_name": "New", "role": "viewer", "status": "pending"},
    )
    assert response.status_code == 401
    assert error_code(response) == "AUTH_REQUIRED"


def test_password_reset_prevents_enumeration(runtime):
    client = runtime["client"]
    create_user(runtime, email="user@example.com", password="Password123456!", role="viewer")

    existing = client.post("/api/auth/password-reset/request", json={"email": "user@example.com"})
    missing = client.post("/api/auth/password-reset/request", json={"email": "missing@example.com"})

    assert existing.status_code == 200
    assert missing.status_code == 200
    assert existing.json()["message"] == missing.json()["message"]


def test_logout_and_logout_all_still_work(runtime):
    client = runtime["client"]
    create_user(runtime, email="user@example.com", password="Password123456!", role="viewer")
    login(client, email="user@example.com", password="Password123456!")

    logout = client.post("/api/auth/logout")
    assert logout.status_code == 200
    assert client.get("/api/auth/me").status_code == 401

    login(client, email="user@example.com", password="Password123456!")
    logout_all = client.post("/api/auth/logout-all")
    assert logout_all.status_code == 200
    assert client.get("/api/auth/me").status_code == 401


def test_login_and_me_do_not_print_secret_and_public_saas_still_no(runtime):
    client = runtime["client"]
    create_user(runtime, email="user@example.com", password="Password123456!", role="viewer")
    response = client.post("/api/auth/login", json={"email": "user@example.com", "password": "Password123456!"})

    assert response.status_code == 200
    payload_text = str(response.json()).lower()
    assert "password" not in payload_text
    assert "token_hash" not in payload_text

    readiness_module = __import__("services.production_readiness", fromlist=["ProductionReadinessChecker"])
    report = readiness_module.ProductionReadinessChecker().build_report()
    assert report["commercial_readiness"]["public_saas_ready"] is False
    assert report["tenant_readiness"]["tenant_isolation_readiness"] == "partial"
