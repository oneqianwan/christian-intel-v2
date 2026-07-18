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


def _seed_task(runtime, *, task_id: int, tenant_id: str | None, title: str, description: str = "legacy"):
    db = runtime["database"].SessionLocal()
    try:
        task = runtime["database"].Task(
            id=task_id,
            tenant_id=tenant_id,
            title=title,
            description=description,
            priority="medium",
            status="pending",
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        return task
    finally:
        db.close()


def test_tasks_are_tenant_scoped_and_cross_tenant_access_is_blocked(runtime):
    client = runtime["client"]
    tenant_a = create_tenant(runtime, name="Tenant A", slug=unique_tenant_slug("task-a"))
    tenant_b = create_tenant(runtime, name="Tenant B", slug=unique_tenant_slug("task-b"))
    _create_tenant_user(runtime, tenant=tenant_a, email="task-a@example.com", password="Password123456!")
    _create_tenant_user(runtime, tenant=tenant_b, email="task-b@example.com", password="Password123456!")

    unauthenticated = client.get("/api/tasks")
    assert unauthenticated.status_code == 401
    assert error_code(unauthenticated) == "AUTH_REQUIRED"

    login(client, email="task-a@example.com", password="Password123456!")
    create_a = client.post(
        "/api/tasks",
        headers={"X-Tenant-ID": tenant_a.public_id},
        json={"title": "Tenant A Task", "description": "owned by tenant a", "tenant_id": tenant_b.public_id},
    )
    assert create_a.status_code == 200
    task_a_id = create_a.json()["task_id"]

    get_a = client.get(f"/api/tasks/{task_a_id}", headers={"X-Tenant-ID": tenant_a.public_id})
    assert get_a.status_code == 200
    assert get_a.json()["title"] == "Tenant A Task"

    client.cookies.clear()
    login(client, email="task-b@example.com", password="Password123456!")
    create_b = client.post(
        "/api/tasks",
        headers={"X-Tenant-ID": tenant_b.public_id},
        json={"title": "Tenant B Task", "description": "owned by tenant b"},
    )
    assert create_b.status_code == 200
    task_b_id = create_b.json()["task_id"]

    list_b = client.get("/api/tasks", headers={"X-Tenant-ID": tenant_b.public_id})
    get_cross = client.get(f"/api/tasks/{task_a_id}", headers={"X-Tenant-ID": tenant_b.public_id})
    patch_cross = client.patch(
        f"/api/tasks/{task_a_id}",
        headers={"X-Tenant-ID": tenant_b.public_id},
        json={"status": "done"},
    )
    delete_cross = client.delete(f"/api/tasks/{task_a_id}", headers={"X-Tenant-ID": tenant_b.public_id})
    assert list_b.status_code == 200
    assert [item["id"] for item in list_b.json()["tasks"]] == [task_b_id]
    assert get_cross.status_code == 404
    assert error_code(get_cross) == "TASK_NOT_FOUND"
    assert patch_cross.status_code == 404
    assert error_code(patch_cross) == "TASK_NOT_FOUND"
    assert delete_cross.status_code == 404
    assert error_code(delete_cross) == "TASK_NOT_FOUND"

    client.cookies.clear()
    login(client, email="task-a@example.com", password="Password123456!")
    list_a = client.get("/api/tasks", headers={"X-Tenant-ID": tenant_a.public_id})
    delete_a = client.delete(f"/api/tasks/{task_a_id}", headers={"X-Tenant-ID": tenant_a.public_id})
    assert list_a.status_code == 200
    assert [item["id"] for item in list_a.json()["tasks"]] == [task_a_id]
    assert delete_a.status_code == 204

    client.cookies.clear()
    login(client, email="task-b@example.com", password="Password123456!")
    list_b_after = client.get("/api/tasks", headers={"X-Tenant-ID": tenant_b.public_id})
    assert [item["id"] for item in list_b_after.json()["tasks"]] == [task_b_id]

    db = runtime["database"].SessionLocal()
    try:
        task_b = db.query(runtime["database"].Task).filter_by(id=task_b_id).one()
        assert task_b.tenant_id == str(tenant_b.id)
        assert db.query(runtime["database"].Task).filter_by(id=task_a_id).first() is None
    finally:
        db.close()


def test_null_tenant_tasks_are_hidden_and_super_admin_requires_explicit_tenant_context(runtime):
    client = runtime["client"]
    default_tenant = ensure_default_tenant(runtime)
    tenant = create_tenant(runtime, name="Tenant Scoped", slug=unique_tenant_slug("task-null"))
    _create_tenant_user(runtime, tenant=tenant, email="task-owner@example.com", password="Password123456!")
    _seed_task(runtime, task_id=101, tenant_id=None, title="Legacy Null Task")
    _seed_task(runtime, task_id=102, tenant_id=str(tenant.id), title="Tenant Owned Task")

    login(client, email="task-owner@example.com", password="Password123456!")
    list_response = client.get("/api/tasks", headers={"X-Tenant-ID": tenant.public_id})
    get_response = client.get("/api/tasks/101", headers={"X-Tenant-ID": tenant.public_id})
    patch_response = client.patch("/api/tasks/101", headers={"X-Tenant-ID": tenant.public_id}, json={"status": "done"})
    delete_response = client.delete("/api/tasks/101", headers={"X-Tenant-ID": tenant.public_id})
    assert list_response.status_code == 200
    assert [item["id"] for item in list_response.json()["tasks"]] == [102]
    assert get_response.status_code == 404
    assert error_code(get_response) == "TASK_NOT_FOUND"
    assert patch_response.status_code == 404
    assert error_code(patch_response) == "TASK_NOT_FOUND"
    assert delete_response.status_code == 404
    assert error_code(delete_response) == "TASK_NOT_FOUND"

    super_admin = create_user(
        runtime,
        email="task-root@example.com",
        password="Password123456!",
        role="super_admin",
        display_name="Super Admin",
    )
    _set_user_default_tenant(runtime, user=super_admin, tenant=default_tenant)

    client.cookies.clear()
    login(client, email="task-root@example.com", password="Password123456!")
    no_context = client.get("/api/tasks/102")
    explicit_context = client.get("/api/tasks/102", headers={"X-Tenant-ID": tenant.public_id})
    assert no_context.status_code == 404
    assert error_code(no_context) == "TASK_NOT_FOUND"
    assert explicit_context.status_code == 200
    assert explicit_context.json()["id"] == 102


def test_disabled_tenant_and_disabled_membership_are_blocked_for_tasks(runtime):
    client = runtime["client"]
    default_tenant = ensure_default_tenant(runtime)
    disabled_tenant = create_tenant(runtime, name="Tenant Disabled", slug=unique_tenant_slug("task-disabled"), status="disabled")
    inactive_membership_tenant = create_tenant(runtime, name="Tenant Membership", slug=unique_tenant_slug("task-membership"))
    user = _create_tenant_user(runtime, tenant=default_tenant, email="task-blocked@example.com", password="Password123456!")
    create_membership(runtime, tenant=disabled_tenant, user=user, role="viewer", status="active")
    create_membership(runtime, tenant=inactive_membership_tenant, user=user, role="viewer", status="disabled")

    login(client, email="task-blocked@example.com", password="Password123456!")
    disabled_tenant_response = client.get("/api/tasks", headers={"X-Tenant-ID": disabled_tenant.public_id})
    disabled_membership_response = client.get("/api/tasks", headers={"X-Tenant-ID": inactive_membership_tenant.public_id})

    assert disabled_tenant_response.status_code == 403
    assert error_code(disabled_tenant_response) == "TENANT_DISABLED"
    assert disabled_membership_response.status_code == 403
    assert error_code(disabled_membership_response) == "TENANT_MEMBERSHIP_INACTIVE"

