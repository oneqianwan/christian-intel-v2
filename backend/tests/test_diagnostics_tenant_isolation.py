from __future__ import annotations

import pytest

from account_lifecycle_testkit import create_user, error_code, login, runtime, set_production_auth_defaults
from production_auth_testkit import reset_runtime_state
from tenant_testkit import create_membership, create_tenant, ensure_default_tenant, unique_tenant_slug


@pytest.fixture(autouse=True)
def _reset_runtime(runtime):
    reset_runtime_state(runtime)
    set_production_auth_defaults(runtime)
    ensure_default_tenant(runtime)
    yield


def _set_user_default_tenant(runtime, *, user, tenant) -> None:
    db = runtime["database"].SessionLocal()
    try:
        row = db.query(runtime["auth_models"].User).filter(runtime["auth_models"].User.id == user.id).one()
        row.default_tenant_id = str(tenant.id)
        db.add(row)
        db.commit()
    finally:
        db.close()


def _create_tenant_user(runtime, *, tenant, email: str, password: str, role: str = "viewer", tenant_role: str = "viewer"):
    user = create_user(runtime, email=email, password=password, role=role, display_name=email.split("@", 1)[0])
    _set_user_default_tenant(runtime, user=user, tenant=tenant)
    create_membership(runtime, tenant=tenant, user=user, role=tenant_role, status="active")
    return user


def _seed_request_trace(runtime, *, trace_id: str, request_id: str, tenant_id: str | None, event_type: str, event_data: dict):
    db = runtime["database"].SessionLocal()
    try:
        trace = runtime["database"].RequestTrace(
            id=trace_id,
            request_id=request_id,
            tenant_id=tenant_id,
            event_type=event_type,
            event_data=event_data,
        )
        db.add(trace)
        db.commit()
        db.refresh(trace)
        return trace
    finally:
        db.close()


def test_diagnostics_request_traces_are_tenant_scoped_and_platform_path_is_super_admin_only(runtime):
    client = runtime["client"]
    default_tenant = ensure_default_tenant(runtime)
    tenant_a = create_tenant(runtime, name="Tenant A", slug=unique_tenant_slug("diag-a"))
    tenant_b = create_tenant(runtime, name="Tenant B", slug=unique_tenant_slug("diag-b"))
    _create_tenant_user(
        runtime,
        tenant=tenant_a,
        email="diag-admin-a@example.com",
        password="Password123456!",
        tenant_role="tenant_admin",
    )
    _create_tenant_user(
        runtime,
        tenant=tenant_b,
        email="diag-admin-b@example.com",
        password="Password123456!",
        tenant_role="tenant_admin",
    )
    _seed_request_trace(
        runtime,
        trace_id="trace-a-1",
        request_id="request-a",
        tenant_id=str(tenant_a.id),
        event_type="route_decided",
        event_data={"route": "tenant-a-route"},
    )
    _seed_request_trace(
        runtime,
        trace_id="trace-b-1",
        request_id="request-b",
        tenant_id=str(tenant_b.id),
        event_type="route_decided",
        event_data={"route": "tenant-b-route"},
    )
    _seed_request_trace(
        runtime,
        trace_id="trace-platform-1",
        request_id="request-platform",
        tenant_id=None,
        event_type="system_event",
        event_data={"status": "ok"},
    )

    unauthenticated = client.get("/api/diagnostics/request/request-a")
    assert unauthenticated.status_code == 401
    assert error_code(unauthenticated) == "AUTH_REQUIRED"

    login(client, email="diag-admin-a@example.com", password="Password123456!")
    own_tenant = client.get("/api/diagnostics/request/request-a", headers={"X-Tenant-ID": tenant_a.public_id})
    foreign_trace = client.get("/api/diagnostics/request/request-b", headers={"X-Tenant-ID": tenant_a.public_id})
    cross_tenant_header = client.get("/api/diagnostics/request/request-b", headers={"X-Tenant-ID": tenant_b.public_id})
    null_tenant_trace = client.get("/api/diagnostics/request/request-platform", headers={"X-Tenant-ID": tenant_a.public_id})
    assert own_tenant.status_code == 200
    assert own_tenant.json()["found"] is True
    assert own_tenant.json()["trace_count"] == 1
    assert foreign_trace.status_code == 200
    assert foreign_trace.json()["found"] is False
    assert cross_tenant_header.status_code == 403
    assert error_code(cross_tenant_header) == "TENANT_MEMBERSHIP_REQUIRED"
    assert null_tenant_trace.status_code == 200
    assert null_tenant_trace.json()["found"] is False

    client.cookies.clear()
    login(client, email="diag-admin-b@example.com", password="Password123456!")
    own_tenant_b = client.get("/api/diagnostics/request/request-b", headers={"X-Tenant-ID": tenant_b.public_id})
    foreign_trace_b = client.get("/api/diagnostics/request/request-a", headers={"X-Tenant-ID": tenant_b.public_id})
    assert own_tenant_b.status_code == 200
    assert own_tenant_b.json()["found"] is True
    assert foreign_trace_b.status_code == 200
    assert foreign_trace_b.json()["found"] is False

    super_admin = create_user(
        runtime,
        email="diag-root@example.com",
        password="Password123456!",
        role="super_admin",
        display_name="Super Admin",
    )
    _set_user_default_tenant(runtime, user=super_admin, tenant=default_tenant)

    client.cookies.clear()
    login(client, email="diag-root@example.com", password="Password123456!")
    platform_only = client.get("/api/diagnostics/request/request-platform")
    no_context_tenant_trace = client.get("/api/diagnostics/request/request-a")
    explicit_tenant_trace = client.get("/api/diagnostics/request/request-a", headers={"X-Tenant-ID": tenant_a.public_id})
    assert platform_only.status_code == 200
    assert platform_only.json()["found"] is True
    assert no_context_tenant_trace.status_code == 200
    assert no_context_tenant_trace.json()["found"] is False
    assert explicit_tenant_trace.status_code == 200
    assert explicit_tenant_trace.json()["found"] is True

    db = runtime["database"].SessionLocal()
    try:
        trace_a = db.query(runtime["database"].RequestTrace).filter_by(id="trace-a-1").one()
        trace_b = db.query(runtime["database"].RequestTrace).filter_by(id="trace-b-1").one()
        assert trace_a.tenant_id == str(tenant_a.id)
        assert trace_b.tenant_id == str(tenant_b.id)
    finally:
        db.close()


def test_diagnostics_redacts_sensitive_payloads_and_health_stays_clean(runtime):
    client = runtime["client"]
    tenant = create_tenant(runtime, name="Tenant Diagnostics", slug=unique_tenant_slug("diag-secret"))
    _create_tenant_user(runtime, tenant=tenant, email="diag-secret@example.com", password="Password123456!")
    _seed_request_trace(
        runtime,
        trace_id="trace-secret-1",
        request_id="request-secret",
        tenant_id=str(tenant.id),
        event_type="delivery_emitted",
        event_data={
            "status": "ok",
            "password": "Password123456!",
            "request_body": {"token": "tok_live_123"},
            "nested": {"session": "sess_live_456", "note": "secret-key"},
        },
    )

    login(client, email="diag-secret@example.com", password="Password123456!")
    response = client.get("/api/diagnostics/request/request-secret", headers={"X-Tenant-ID": tenant.public_id})
    health = client.get("/api/health")

    assert response.status_code == 200
    payload = response.json()
    serialized = str(payload).lower()
    assert payload["found"] is True
    assert "password" not in payload["events"][0]["data"]
    assert "request_body" not in payload["events"][0]["data"]
    assert "Password123456!".lower() not in serialized
    assert "tok_live_123".lower() not in serialized
    assert "sess_live_456".lower() not in serialized
    assert "secret-key".lower() not in serialized
    assert health.status_code == 200
    assert "tok_live_123".lower() not in str(health.json()).lower()

