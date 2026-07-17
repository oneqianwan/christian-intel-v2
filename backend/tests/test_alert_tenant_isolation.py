from __future__ import annotations

from datetime import datetime

import pytest

from account_lifecycle_testkit import create_user, error_code, login, runtime, set_production_auth_defaults
from production_auth_testkit import reset_runtime_state
from tenant_testkit import create_tenant, ensure_default_tenant, unique_tenant_slug, create_membership


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


def _seed_public_org(runtime, *, org_id: str, name: str):
    db = runtime["database"].SessionLocal()
    try:
        row = runtime["database"].OrganizationProfile(
            id=org_id,
            name=name,
            country="PH",
            official_website="https://example.org",
            people_score=64,
            digital_score=28,
            intel_score=65,
        )
        db.add(row)
        db.commit()
    finally:
        db.close()


def _seed_source(runtime, *, source_id: str):
    db = runtime["database"].SessionLocal()
    try:
        row = runtime["database"].Source(
            id=source_id,
            name="Manual Source",
            url=f"https://example.com/{source_id}",
            type="website",
            country="PH",
        )
        db.add(row)
        db.commit()
    finally:
        db.close()


def _seed_intelligence_item(runtime, *, item_id: str, source_id: str, entity_name: str, source_url: str):
    db = runtime["database"].SessionLocal()
    try:
        row = runtime["database"].IntelligenceItem(
            id=item_id,
            source_id=source_id,
            title=item_id,
            content=item_id,
            entity_name=entity_name,
            entity_type="organization",
            category="news",
            source_url=source_url,
        )
        db.add(row)
        db.commit()
    finally:
        db.close()


def _create_watch_target(client, *, tenant_public_id: str, entity_id: str):
    response = client.post(
        "/api/watch-targets",
        headers={"X-Tenant-ID": tenant_public_id},
        json={"entity_id": entity_id, "entity_type": "organization", "frequency": "daily"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _run_watch(client, *, tenant_public_id: str, watch_target_id: str):
    response = client.post(f"/api/watch-targets/{watch_target_id}/run", headers={"X-Tenant-ID": tenant_public_id})
    assert response.status_code == 200, response.text
    return response


def _seed_legacy_alert_chain(
    runtime,
    *,
    watch_target_id: str,
    tenant_id: str,
    owner_user_id: str,
    entity_id: str,
):
    db = runtime["database"].SessionLocal()
    try:
        watch_target = runtime["database"].WatchTarget(
            id=watch_target_id,
            tenant_id=tenant_id,
            user_id=owner_user_id,
            owner_user_id=owner_user_id,
            entity_id=entity_id,
            entity_type="organization",
            status="active",
            frequency="daily",
        )
        db.add(watch_target)
        db.flush()
        signal = runtime["database"].Signal(
            id=f"signal-{watch_target_id}",
            tenant_id=None,
            watch_target_id=watch_target.id,
            owner_user_id=owner_user_id,
            entity_id=entity_id,
            signal_type="new_news",
            title="legacy-signal",
            summary="legacy-signal",
            severity="low",
            dedup_key=f"legacy-{watch_target_id}",
            detected_at=datetime.utcnow(),
        )
        db.add(signal)
        db.flush()
        alert = runtime["database"].Alert(
            id=f"alert-{watch_target_id}",
            tenant_id=None,
            user_id=owner_user_id,
            owner_user_id=owner_user_id,
            watch_target_id=watch_target.id,
            signal_id=signal.id,
            title="legacy-alert",
            summary="legacy-alert",
            severity="low",
            status="unread",
        )
        db.add(alert)
        db.commit()
        return signal.id, alert.id
    finally:
        db.close()


def test_signal_alert_rule_and_alert_are_tenant_bound_and_alert_routes_are_scoped(runtime):
    client = runtime["client"]
    default_tenant = ensure_default_tenant(runtime)
    tenant_a = create_tenant(runtime, name="Tenant A", slug=unique_tenant_slug("alert-a"))
    tenant_b = create_tenant(runtime, name="Tenant B", slug=unique_tenant_slug("alert-b"))
    _create_tenant_user(runtime, tenant=tenant_a, email="alert-a@example.com", password="Password123456!")
    _create_tenant_user(runtime, tenant=tenant_b, email="alert-b@example.com", password="Password123456!")
    _seed_public_org(runtime, org_id="org-alert-shared", name="Victory Philippines")
    _seed_source(runtime, source_id="source-alert-shared")

    login(client, email="alert-a@example.com", password="Password123456!")
    watch_a_id = _create_watch_target(client, tenant_public_id=tenant_a.public_id, entity_id="org-alert-shared")
    _run_watch(client, tenant_public_id=tenant_a.public_id, watch_target_id=watch_a_id)

    client.cookies.clear()
    login(client, email="alert-b@example.com", password="Password123456!")
    watch_b_id = _create_watch_target(client, tenant_public_id=tenant_b.public_id, entity_id="org-alert-shared")
    _run_watch(client, tenant_public_id=tenant_b.public_id, watch_target_id=watch_b_id)

    _seed_intelligence_item(
        runtime,
        item_id="intel-alert-shared",
        source_id="source-alert-shared",
        entity_name="Victory Philippines",
        source_url="https://example.com/news/shared",
    )

    client.cookies.clear()
    login(client, email="alert-a@example.com", password="Password123456!")
    rerun_a = _run_watch(client, tenant_public_id=tenant_a.public_id, watch_target_id=watch_a_id)
    assert rerun_a.json()["signals_created"] == 1
    alerts_a = client.get("/api/alerts", headers={"X-Tenant-ID": tenant_a.public_id})
    assert alerts_a.status_code == 200
    assert alerts_a.json()["total"] == 1
    alert_a_id = alerts_a.json()["items"][0]["id"]
    get_a = client.get(f"/api/alerts/{alert_a_id}", headers={"X-Tenant-ID": tenant_a.public_id})
    assert get_a.status_code == 200
    read_a = client.patch(f"/api/alerts/{alert_a_id}/read", headers={"X-Tenant-ID": tenant_a.public_id})
    assert read_a.status_code == 200
    assert read_a.json()["status"] == "read"

    client.cookies.clear()
    login(client, email="alert-b@example.com", password="Password123456!")
    rerun_b = _run_watch(client, tenant_public_id=tenant_b.public_id, watch_target_id=watch_b_id)
    assert rerun_b.json()["signals_created"] == 1
    alerts_b = client.get("/api/alerts", headers={"X-Tenant-ID": tenant_b.public_id})
    unread_b = client.get("/api/alerts/unread-count", headers={"X-Tenant-ID": tenant_b.public_id})
    get_cross = client.get(f"/api/alerts/{alert_a_id}", headers={"X-Tenant-ID": tenant_b.public_id})
    patch_cross = client.patch(f"/api/alerts/{alert_a_id}/read", headers={"X-Tenant-ID": tenant_b.public_id})
    delete_cross = client.delete(f"/api/alerts/{alert_a_id}", headers={"X-Tenant-ID": tenant_b.public_id})
    assert alerts_b.status_code == 200
    assert alerts_b.json()["total"] == 1
    assert unread_b.status_code == 200
    assert unread_b.json()["unread_count"] == 1
    assert get_cross.status_code == 404
    assert error_code(get_cross) == "ALERT_NOT_FOUND"
    assert patch_cross.status_code == 404
    assert error_code(patch_cross) == "ALERT_NOT_FOUND"
    assert delete_cross.status_code == 404
    assert error_code(delete_cross) == "ALERT_NOT_FOUND"

    super_admin = create_user(
        runtime,
        email="alert-super-admin@example.com",
        password="Password123456!",
        role="super_admin",
        display_name="Super Admin",
    )
    _set_user_default_tenant(runtime, user=super_admin, tenant=default_tenant)

    client.cookies.clear()
    login(client, email="alert-super-admin@example.com", password="Password123456!")
    no_context = client.get(f"/api/alerts/{alert_a_id}")
    explicit_context = client.get(f"/api/alerts/{alert_a_id}", headers={"X-Tenant-ID": tenant_a.public_id})
    assert no_context.status_code == 404
    assert error_code(no_context) == "ALERT_NOT_FOUND"
    assert explicit_context.status_code == 200
    assert explicit_context.json()["id"] == alert_a_id

    db = runtime["database"].SessionLocal()
    try:
        watch_a = db.query(runtime["database"].WatchTarget).filter_by(id=watch_a_id).one()
        watch_b = db.query(runtime["database"].WatchTarget).filter_by(id=watch_b_id).one()
        signals_a = db.query(runtime["database"].Signal).filter_by(watch_target_id=watch_a_id).all()
        signals_b = db.query(runtime["database"].Signal).filter_by(watch_target_id=watch_b_id).all()
        alerts_rows_a = db.query(runtime["database"].Alert).filter_by(watch_target_id=watch_a_id).all()
        alerts_rows_b = db.query(runtime["database"].Alert).filter_by(watch_target_id=watch_b_id).all()
        rules_a = db.query(runtime["database"].AlertRule).filter_by(user_id=str(watch_a.owner_user_id), tenant_id=str(tenant_a.id)).all()
        rules_b = db.query(runtime["database"].AlertRule).filter_by(user_id=str(watch_b.owner_user_id), tenant_id=str(tenant_b.id)).all()
        assert any(str(signal.tenant_id) == str(tenant_a.id) for signal in signals_a)
        assert any(str(signal.tenant_id) == str(tenant_b.id) for signal in signals_b)
        assert all(str(alert.tenant_id) == str(tenant_a.id) for alert in alerts_rows_a)
        assert all(str(alert.tenant_id) == str(tenant_b.id) for alert in alerts_rows_b)
        assert len(rules_a) >= 1
        assert len(rules_b) >= 1
    finally:
        db.close()


def test_null_tenant_alerts_fail_closed_and_super_admin_requires_explicit_tenant_context(runtime):
    client = runtime["client"]
    default_tenant = ensure_default_tenant(runtime)
    tenant = create_tenant(runtime, name="Tenant A", slug=unique_tenant_slug("alert-null"))
    owner = _create_tenant_user(runtime, tenant=tenant, email="alert-null@example.com", password="Password123456!")
    _seed_public_org(runtime, org_id="org-alert-null", name="Null Tenant Org")
    signal_id, alert_id = _seed_legacy_alert_chain(
        runtime,
        watch_target_id="watch-alert-null",
        tenant_id=str(tenant.id),
        owner_user_id=str(owner.id),
        entity_id="org-alert-null",
    )

    login(client, email="alert-null@example.com", password="Password123456!")
    alerts_response = client.get("/api/alerts", headers={"X-Tenant-ID": tenant.public_id})
    alert_response = client.get(f"/api/alerts/{alert_id}", headers={"X-Tenant-ID": tenant.public_id})
    signals_response = client.get("/api/watch-targets/watch-alert-null/signals", headers={"X-Tenant-ID": tenant.public_id})
    assert alerts_response.status_code == 200
    assert alerts_response.json()["total"] == 0
    assert alert_response.status_code == 404
    assert error_code(alert_response) == "ALERT_NOT_FOUND"
    assert signals_response.status_code == 200
    assert signals_response.json()["total"] == 0

    super_admin = create_user(
        runtime,
        email="alert-root@example.com",
        password="Password123456!",
        role="super_admin",
        display_name="Super Admin",
    )
    _set_user_default_tenant(runtime, user=super_admin, tenant=default_tenant)

    client.cookies.clear()
    login(client, email="alert-root@example.com", password="Password123456!")
    no_context = client.get(f"/api/alerts/{alert_id}")
    explicit_context = client.get(f"/api/alerts/{alert_id}", headers={"X-Tenant-ID": tenant.public_id})
    assert no_context.status_code == 404
    assert error_code(no_context) == "ALERT_NOT_FOUND"
    assert explicit_context.status_code == 404
    assert error_code(explicit_context) == "ALERT_NOT_FOUND"
    assert signal_id.startswith("signal-")


def test_alert_payloads_do_not_leak_secrets(runtime):
    client = runtime["client"]
    tenant = create_tenant(runtime, name="Tenant Shield", slug=unique_tenant_slug("alert-secret"))
    _create_tenant_user(runtime, tenant=tenant, email="alert-secret@example.com", password="Password123456!")
    _seed_public_org(runtime, org_id="org-alert-secret", name="Shield Org")
    _seed_source(runtime, source_id="source-alert-secret")

    login(client, email="alert-secret@example.com", password="Password123456!")
    watch_id = _create_watch_target(client, tenant_public_id=tenant.public_id, entity_id="org-alert-secret")
    _run_watch(client, tenant_public_id=tenant.public_id, watch_target_id=watch_id)
    _seed_intelligence_item(
        runtime,
        item_id="intel-alert-secret",
        source_id="source-alert-secret",
        entity_name="Secret Org",
        source_url="https://example.com/news/secret",
    )
    _run_watch(client, tenant_public_id=tenant.public_id, watch_target_id=watch_id)

    alerts_response = client.get("/api/alerts", headers={"X-Tenant-ID": tenant.public_id})
    assert alerts_response.status_code == 200
    serialized = str(alerts_response.json()).lower()
    assert "password123456" not in serialized
    assert "auth_token" not in serialized
    assert "session_cookie" not in serialized
    assert "secret_key" not in serialized
