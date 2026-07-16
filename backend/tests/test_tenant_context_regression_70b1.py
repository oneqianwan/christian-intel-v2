from __future__ import annotations

import pytest

from account_lifecycle_testkit import create_user, error_code, login, runtime, set_production_auth_defaults, set_test_mode
from production_auth_testkit import reset_runtime_state
from tenant_testkit import create_tenant, ensure_default_tenant, unique_tenant_slug


@pytest.fixture(autouse=True)
def _reset_runtime(runtime):
    reset_runtime_state(runtime)
    set_production_auth_defaults(runtime)
    ensure_default_tenant(runtime)
    yield


def test_b1_models_still_exist(runtime):
    auth_models = runtime["auth_models"]
    assert hasattr(auth_models, "Tenant")
    assert hasattr(auth_models, "TenantMembership")
    assert hasattr(auth_models.User, "default_tenant_id")


def test_admin_create_user_tenant_aware_still_works(runtime):
    client = runtime["client"]
    tenant = create_tenant(runtime, name="Tenant Alpha", slug=unique_tenant_slug("tenant-alpha"))
    create_user(runtime, email="root@example.com", password="Password123456!", role="super_admin")
    login(client, email="root@example.com", password="Password123456!")

    created = client.post(
        "/api/admin/users",
        json={
            "email": "invitee@example.com",
            "display_name": "Invitee",
            "role": "viewer",
            "status": "pending",
            "tenant_id": tenant.public_id,
        },
    )
    assert created.status_code == 200
    assert created.json()["user"]["default_tenant_id"] == tenant.public_id


def test_setup_and_password_reset_regressions_still_hold(runtime):
    client = runtime["client"]
    tenant = create_tenant(runtime, name="Tenant Alpha", slug=unique_tenant_slug("tenant-alpha"))
    create_user(runtime, email="root@example.com", password="Password123456!", role="super_admin")
    login(client, email="root@example.com", password="Password123456!")

    created = client.post(
        "/api/admin/users",
        json={
            "email": "invitee@example.com",
            "display_name": "Invitee",
            "role": "viewer",
            "status": "pending",
            "tenant_id": tenant.public_id,
        },
    )
    assert created.status_code == 200
    setup_token = created.json()["setup_token"]

    setup = client.post(
        "/api/auth/setup-password",
        json={
            "token": setup_token,
            "new_password": "NewPassword123456!",
            "confirm_password": "NewPassword123456!",
        },
    )
    assert setup.status_code == 200
    assert client.post("/api/auth/login", json={"email": "invitee@example.com", "password": "NewPassword123456!"}).status_code == 200

    set_test_mode(runtime)
    reset_request = client.post("/api/auth/password-reset/request", json={"email": "invitee@example.com"})
    assert reset_request.status_code == 200
    reset_token = reset_request.json()["reset_token"]
    assert reset_token

    confirm = client.post(
        "/api/auth/password-reset/confirm",
        json={
            "token": reset_token,
            "new_password": "AnotherPassword123456!",
            "confirm_password": "AnotherPassword123456!",
        },
    )
    assert confirm.status_code == 200


def test_public_saas_still_no_and_tenant_isolation_still_blocked(runtime):
    readiness_module = __import__("services.production_readiness", fromlist=["ProductionReadinessChecker"])
    checker = readiness_module.ProductionReadinessChecker()
    report = checker.build_report()
    imports = checker._collect_imports()
    controlled_beta_auth_ready = checker._is_controlled_beta_auth_ready(
        settings=imports.get("settings"),
        environment=report["environment"],
    )

    assert report["commercial_readiness"]["public_saas_ready"] is False
    assert controlled_beta_auth_ready is True
    assert report["tenant_readiness"]["tenant_isolation_readiness"] == "blocked"
    assert "production_authentication_not_fully_validated" not in set(
        report["commercial_readiness"]["reason_public_saas_not_ready"]
    )


def test_unauthenticated_admin_route_still_requires_auth(runtime):
    response = runtime["client"].post(
        "/api/admin/users",
        json={"email": "new@example.com", "display_name": "New", "role": "viewer", "status": "pending"},
    )
    assert response.status_code == 401
    assert error_code(response) == "AUTH_REQUIRED"
