from __future__ import annotations

from datetime import datetime

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


def _seed_feedback(
    runtime,
    *,
    tenant_id: str | None,
    user_id: str | None,
    feedback_type: str,
    content: str,
    related_investor: str | None = None,
):
    db = runtime["database"].SessionLocal()
    try:
        row = runtime["database"].UserFeedback(
            session_id=f"user:{user_id or 'legacy'}",
            tenant_id=tenant_id,
            user_id=user_id,
            feedback_type=feedback_type,
            content=content,
            related_investor=related_investor,
            created_at=datetime.utcnow(),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row
    finally:
        db.close()


def test_feedback_create_list_and_stats_are_tenant_scoped(runtime):
    client = runtime["client"]
    tenant_a = create_tenant(runtime, name="Tenant A", slug=unique_tenant_slug("feedback-a"))
    tenant_b = create_tenant(runtime, name="Tenant B", slug=unique_tenant_slug("feedback-b"))
    _create_tenant_user(
        runtime,
        tenant=tenant_a,
        email="feedback-admin-a@example.com",
        password="Password123456!",
        tenant_role="tenant_admin",
    )
    _create_tenant_user(
        runtime,
        tenant=tenant_b,
        email="feedback-admin-b@example.com",
        password="Password123456!",
        tenant_role="tenant_admin",
    )

    login(client, email="feedback-admin-a@example.com", password="Password123456!")
    create_a = client.post(
        "/api/feedback",
        headers={"X-Tenant-ID": tenant_a.public_id},
        json={
            "feedback_type": "match_useful",
            "content": "tenant-a-useful",
            "related_investor": "Investor A",
            "tenant_id": tenant_b.public_id,
        },
    )
    assert create_a.status_code == 200
    assert create_a.json()["status"] == "recorded"

    list_a = client.get("/api/feedback", headers={"X-Tenant-ID": tenant_a.public_id})
    stats_a = client.get("/api/feedback/stats", headers={"X-Tenant-ID": tenant_a.public_id})
    assert list_a.status_code == 200
    assert len(list_a.json()) == 1
    assert list_a.json()[0]["content"] == "tenant-a-useful"
    assert stats_a.status_code == 200
    assert stats_a.json()["scope"] == "tenant"
    assert stats_a.json()["total_feedback"] == 1
    assert stats_a.json()["useful_matches"] == 1

    client.cookies.clear()
    login(client, email="feedback-admin-b@example.com", password="Password123456!")
    create_b = client.post(
        "/api/feedback",
        headers={"X-Tenant-ID": tenant_b.public_id},
        json={
            "feedback_type": "match_not_useful",
            "content": "tenant-b-not-useful",
            "related_investor": "Investor B",
        },
    )
    assert create_b.status_code == 200

    list_b = client.get("/api/feedback", headers={"X-Tenant-ID": tenant_b.public_id})
    stats_b = client.get("/api/feedback/stats", headers={"X-Tenant-ID": tenant_b.public_id})
    assert list_b.status_code == 200
    assert len(list_b.json()) == 1
    assert list_b.json()[0]["content"] == "tenant-b-not-useful"
    assert stats_b.status_code == 200
    assert stats_b.json()["total_feedback"] == 1
    assert stats_b.json()["not_useful_matches"] == 1

    db = runtime["database"].SessionLocal()
    try:
        rows = db.query(runtime["database"].UserFeedback).order_by(runtime["database"].UserFeedback.id.asc()).all()
        assert len(rows) == 2
        assert {row.tenant_id for row in rows} == {str(tenant_a.id), str(tenant_b.id)}
    finally:
        db.close()


def test_feedback_tenant_admin_boundary_null_tenant_fail_closed_and_no_secret_leakage(runtime):
    client = runtime["client"]
    tenant_a = create_tenant(runtime, name="Tenant A", slug=unique_tenant_slug("feedback-a"))
    tenant_b = create_tenant(runtime, name="Tenant B", slug=unique_tenant_slug("feedback-b"))
    admin_a = _create_tenant_user(
        runtime,
        tenant=tenant_a,
        email="feedback-boundary-a@example.com",
        password="Password123456!",
        tenant_role="tenant_admin",
    )
    _create_tenant_user(
        runtime,
        tenant=tenant_b,
        email="feedback-boundary-b@example.com",
        password="Password123456!",
        tenant_role="viewer",
    )
    create_membership(runtime, tenant=tenant_b, user=admin_a, role="viewer", status="active")
    _seed_feedback(
        runtime,
        tenant_id=str(tenant_a.id),
        user_id=str(admin_a.id),
        feedback_type="match_useful",
        content="tenant-a-visible",
        related_investor="Investor A",
    )
    _seed_feedback(
        runtime,
        tenant_id=None,
        user_id=str(admin_a.id),
        feedback_type="match_useful",
        content="legacy-null-tenant",
        related_investor="Legacy Investor",
    )

    login(client, email="feedback-boundary-a@example.com", password="Password123456!")
    own_list = client.get("/api/feedback", headers={"X-Tenant-ID": tenant_a.public_id})
    foreign_list = client.get("/api/feedback", headers={"X-Tenant-ID": tenant_b.public_id})
    own_stats = client.get("/api/feedback/stats", headers={"X-Tenant-ID": tenant_a.public_id})

    assert own_list.status_code == 200
    assert [item["content"] for item in own_list.json()] == ["tenant-a-visible"]
    assert own_stats.status_code == 200
    assert own_stats.json()["total_feedback"] == 1
    assert foreign_list.status_code == 403
    assert error_code(foreign_list) == "ROLE_FORBIDDEN"

    serialized = str(own_list.json()).lower() + str(own_stats.json()).lower()
    assert "password" not in serialized
    assert "token" not in serialized
    assert "secret" not in serialized
    assert "session_id" not in serialized


def test_feedback_super_admin_explicit_tenant_access_and_global_stats(runtime):
    client = runtime["client"]
    default_tenant = ensure_default_tenant(runtime)
    tenant_a = create_tenant(runtime, name="Tenant A", slug=unique_tenant_slug("feedback-a"))
    tenant_b = create_tenant(runtime, name="Tenant B", slug=unique_tenant_slug("feedback-b"))
    user_a = _create_tenant_user(
        runtime,
        tenant=tenant_a,
        email="feedback-super-a@example.com",
        password="Password123456!",
        tenant_role="tenant_admin",
    )
    user_b = _create_tenant_user(
        runtime,
        tenant=tenant_b,
        email="feedback-super-b@example.com",
        password="Password123456!",
        tenant_role="tenant_admin",
    )
    _seed_feedback(
        runtime,
        tenant_id=str(tenant_a.id),
        user_id=str(user_a.id),
        feedback_type="match_useful",
        content="tenant-a-feedback",
        related_investor="Investor A",
    )
    _seed_feedback(
        runtime,
        tenant_id=str(tenant_b.id),
        user_id=str(user_b.id),
        feedback_type="match_not_useful",
        content="tenant-b-feedback",
        related_investor="Investor B",
    )

    super_admin = create_user(
        runtime,
        email="feedback-root@example.com",
        password="Password123456!",
        role="super_admin",
        display_name="Super Admin",
    )
    _set_user_default_tenant(runtime, user=super_admin, tenant=default_tenant)

    login(client, email="feedback-root@example.com", password="Password123456!")
    no_context_list = client.get("/api/feedback")
    tenant_a_list = client.get("/api/feedback", headers={"X-Tenant-ID": tenant_a.public_id})
    global_stats = client.get("/api/feedback/stats")
    tenant_b_stats = client.get("/api/feedback/stats", headers={"X-Tenant-ID": tenant_b.public_id})

    assert no_context_list.status_code == 200
    assert no_context_list.json() == []
    assert tenant_a_list.status_code == 200
    assert [item["content"] for item in tenant_a_list.json()] == ["tenant-a-feedback"]
    assert global_stats.status_code == 200
    assert global_stats.json()["scope"] == "global"
    assert global_stats.json()["total_feedback"] == 2
    assert tenant_b_stats.status_code == 200
    assert tenant_b_stats.json()["scope"] == "tenant"
    assert tenant_b_stats.json()["total_feedback"] == 1
    assert tenant_b_stats.json()["not_useful_matches"] == 1


def test_feedback_unauthenticated_and_unauthorized_requests_are_blocked(runtime):
    client = runtime["client"]
    tenant = create_tenant(runtime, name="Tenant Viewer", slug=unique_tenant_slug("feedback-viewer"))
    _create_tenant_user(
        runtime,
        tenant=tenant,
        email="feedback-viewer@example.com",
        password="Password123456!",
        tenant_role="viewer",
    )

    unauth_list = client.get("/api/feedback")
    unauth_stats = client.get("/api/feedback/stats")
    assert unauth_list.status_code == 401
    assert error_code(unauth_list) == "AUTH_REQUIRED"
    assert unauth_stats.status_code == 401
    assert error_code(unauth_stats) == "AUTH_REQUIRED"

    login(client, email="feedback-viewer@example.com", password="Password123456!")
    viewer_list = client.get("/api/feedback", headers={"X-Tenant-ID": tenant.public_id})
    viewer_stats = client.get("/api/feedback/stats", headers={"X-Tenant-ID": tenant.public_id})
    assert viewer_list.status_code == 403
    assert error_code(viewer_list) == "ROLE_FORBIDDEN"
    assert viewer_stats.status_code == 403
    assert error_code(viewer_stats) == "ROLE_FORBIDDEN"
