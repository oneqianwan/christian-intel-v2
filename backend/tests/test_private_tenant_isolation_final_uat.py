from __future__ import annotations

from datetime import datetime

import importlib

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


def _seed_public_org(runtime, *, org_id: str, name: str = "Victory Philippines"):
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
        return row
    finally:
        db.close()


def _seed_public_item(runtime, *, item_id: str, title: str = "Victory Philippines"):
    db = runtime["database"].SessionLocal()
    try:
        source = runtime["database"].Source(
            id=f"source-{item_id}",
            name="Global Source",
            url=f"https://example.com/{item_id}",
            type="website",
            country="PH",
            scope="global",
        )
        item = runtime["database"].IntelligenceItem(
            id=item_id,
            source_id=source.id,
            title=title,
            entity_name=title,
            entity_type="organization",
            country="PH",
            category="public_intelligence",
            source_url=f"https://example.com/{item_id}",
            source_name=source.name,
            scope="global",
        )
        db.add(source)
        db.add(item)
        db.commit()
        return item_id
    finally:
        db.close()


def _seed_conversation(runtime, *, conversation_id: str, tenant_id: str | None, owner_user_id: str | None, title: str = "Seed"):
    db = runtime["database"].SessionLocal()
    try:
        conversation = runtime["database"].Conversation(
            id=conversation_id,
            title=title,
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
        )
        db.add(conversation)
        db.commit()
        db.refresh(conversation)
        return conversation
    finally:
        db.close()


def _seed_message(runtime, *, message_id: str, conversation_id: str, tenant_id: str | None, role: str, content: str):
    db = runtime["database"].SessionLocal()
    try:
        message = runtime["database"].Message(
            id=message_id,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            role=role,
            content=content,
            sources=[],
        )
        db.add(message)
        db.commit()
        db.refresh(message)
        return message
    finally:
        db.close()


def _seed_bookmark(runtime, *, bookmark_id: str, tenant_id: str | None, user_id: str | None, item_id: str, note: str = "legacy"):
    db = runtime["database"].SessionLocal()
    try:
        bookmark = runtime["database"].Bookmark(
            id=bookmark_id,
            tenant_id=tenant_id,
            user_id=user_id,
            intelligence_item_id=item_id,
            note=note,
        )
        db.add(bookmark)
        db.commit()
        db.refresh(bookmark)
        return bookmark
    finally:
        db.close()


def _seed_feedback(
    runtime,
    *,
    tenant_id: str | None,
    user_id: str | None,
    feedback_type: str,
    content: str,
):
    db = runtime["database"].SessionLocal()
    try:
        row = runtime["database"].UserFeedback(
            session_id=f"user:{user_id or 'legacy'}",
            tenant_id=tenant_id,
            user_id=user_id,
            feedback_type=feedback_type,
            content=content,
            created_at=datetime.utcnow(),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row
    finally:
        db.close()


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


def _seed_watch_target(
    runtime,
    *,
    watch_target_id: str,
    tenant_id: str | None,
    user_id: str,
    owner_user_id: str | None,
    entity_id: str,
):
    db = runtime["database"].SessionLocal()
    try:
        row = runtime["database"].WatchTarget(
            id=watch_target_id,
            tenant_id=tenant_id,
            user_id=user_id,
            owner_user_id=owner_user_id,
            entity_id=entity_id,
            entity_type="organization",
            status="active",
            frequency="daily",
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row
    finally:
        db.close()


def _seed_alert_chain(
    runtime,
    *,
    watch_target_id: str,
    tenant_id: str | None,
    owner_user_id: str,
    entity_id: str,
    suffix: str,
):
    db = runtime["database"].SessionLocal()
    try:
        signal = runtime["database"].Signal(
            id=f"signal-{suffix}",
            tenant_id=tenant_id,
            watch_target_id=watch_target_id,
            owner_user_id=owner_user_id,
            entity_id=entity_id,
            signal_type="new_news",
            title=f"signal-{suffix}",
            summary=f"signal-{suffix}",
            severity="low",
            dedup_key=f"dedup-{suffix}",
            detected_at=datetime.utcnow(),
        )
        db.add(signal)
        db.flush()
        alert = runtime["database"].Alert(
            id=f"alert-{suffix}",
            tenant_id=tenant_id,
            user_id=owner_user_id,
            owner_user_id=owner_user_id,
            watch_target_id=watch_target_id,
            signal_id=signal.id,
            title=f"alert-{suffix}",
            summary=f"alert-{suffix}",
            severity="low",
            status="unread",
        )
        db.add(alert)
        db.commit()
        return signal.id, alert.id
    finally:
        db.close()


def test_final_uat_blocks_cross_tenant_reads_across_private_data(runtime, monkeypatch):
    client = runtime["client"]
    chat_router = importlib.import_module("routers.chat")
    monkeypatch.setattr(chat_router, "think", lambda *_args, **_kwargs: {"answer": "ok", "evidence": []})

    tenant_a = create_tenant(runtime, name="Tenant A", slug=unique_tenant_slug("final-a"))
    tenant_b = create_tenant(runtime, name="Tenant B", slug=unique_tenant_slug("final-b"))
    user_a = _create_tenant_user(
        runtime,
        tenant=tenant_a,
        email="final-a@example.com",
        password="Password123456!",
        tenant_role="tenant_admin",
    )
    user_b = _create_tenant_user(
        runtime,
        tenant=tenant_b,
        email="final-b@example.com",
        password="Password123456!",
        tenant_role="tenant_admin",
    )
    item_id = _seed_public_item(runtime, item_id="item-final-shared")
    _seed_public_org(runtime, org_id="org-final-shared")

    login(client, email="final-a@example.com", password="Password123456!")
    conversation_a = client.post("/api/conversations", headers={"X-Tenant-ID": tenant_a.public_id}, json={"title": "A"})
    assert conversation_a.status_code == 200
    conversation_a_id = conversation_a.json()["id"]
    message_a = client.post(
        "/api/chat/simple",
        headers={"X-Tenant-ID": tenant_a.public_id},
        json={"message": "hello a", "conversation_id": conversation_a_id},
    )
    assert message_a.status_code == 200
    bookmark_a = client.post(
        "/api/bookmarks",
        params={"item_id": item_id, "note": "bookmark-a"},
        headers={"X-Tenant-ID": tenant_a.public_id},
    )
    assert bookmark_a.status_code == 200
    feedback_a = client.post(
        "/api/feedback",
        headers={"X-Tenant-ID": tenant_a.public_id},
        json={"feedback_type": "match_useful", "content": "tenant-a-feedback"},
    )
    assert feedback_a.status_code == 200
    watch_a = client.post(
        "/api/watch-targets",
        headers={"X-Tenant-ID": tenant_a.public_id},
        json={"entity_id": "org-final-shared", "entity_type": "organization", "frequency": "daily"},
    )
    assert watch_a.status_code == 201
    watch_a_id = watch_a.json()["id"]
    task_a = client.post(
        "/api/tasks",
        headers={"X-Tenant-ID": tenant_a.public_id},
        json={"title": "Task A", "description": "tenant a"},
    )
    assert task_a.status_code == 200

    client.cookies.clear()
    login(client, email="final-b@example.com", password="Password123456!")
    conversation_b = client.post("/api/conversations", headers={"X-Tenant-ID": tenant_b.public_id}, json={"title": "B"})
    assert conversation_b.status_code == 200
    conversation_b_id = conversation_b.json()["id"]
    message_b = client.post(
        "/api/chat/simple",
        headers={"X-Tenant-ID": tenant_b.public_id},
        json={"message": "hello b", "conversation_id": conversation_b_id},
    )
    assert message_b.status_code == 200
    bookmark_b = client.post(
        "/api/bookmarks",
        params={"item_id": item_id, "note": "bookmark-b"},
        headers={"X-Tenant-ID": tenant_b.public_id},
    )
    assert bookmark_b.status_code == 200
    bookmark_b_id = bookmark_b.json()["bookmark_id"]
    feedback_b = client.post(
        "/api/feedback",
        headers={"X-Tenant-ID": tenant_b.public_id},
        json={"feedback_type": "match_not_useful", "content": "tenant-b-feedback"},
    )
    assert feedback_b.status_code == 200
    watch_b = client.post(
        "/api/watch-targets",
        headers={"X-Tenant-ID": tenant_b.public_id},
        json={"entity_id": "org-final-shared", "entity_type": "organization", "frequency": "weekly"},
    )
    assert watch_b.status_code == 201
    watch_b_id = watch_b.json()["id"]
    task_b = client.post(
        "/api/tasks",
        headers={"X-Tenant-ID": tenant_b.public_id},
        json={"title": "Task B", "description": "tenant b"},
    )
    assert task_b.status_code == 200
    task_b_id = task_b.json()["task_id"]

    _seed_request_trace(
        runtime,
        trace_id="trace-final-a",
        request_id="request-final-a",
        tenant_id=str(tenant_a.id),
        event_type="route_decided",
        event_data={"route": "tenant-a"},
    )
    _seed_request_trace(
        runtime,
        trace_id="trace-final-b",
        request_id="request-final-b",
        tenant_id=str(tenant_b.id),
        event_type="route_decided",
        event_data={"route": "tenant-b"},
    )
    signal_b_id, alert_b_id = _seed_alert_chain(
        runtime,
        watch_target_id=watch_b_id,
        tenant_id=str(tenant_b.id),
        owner_user_id=str(user_b.id),
        entity_id="org-final-shared",
        suffix="tenant-b",
    )
    assert signal_b_id.startswith("signal-")

    client.cookies.clear()
    login(client, email="final-a@example.com", password="Password123456!")
    cross_conversation = client.get(f"/api/conversations/{conversation_b_id}", headers={"X-Tenant-ID": tenant_a.public_id})
    cross_messages = client.get(
        f"/api/conversations/{conversation_b_id}/messages",
        headers={"X-Tenant-ID": tenant_a.public_id},
    )
    cross_bookmark = client.get(f"/api/bookmarks/{bookmark_b_id}", headers={"X-Tenant-ID": tenant_a.public_id})
    cross_bookmark_delete = client.delete(f"/api/bookmarks/{bookmark_b_id}", headers={"X-Tenant-ID": tenant_a.public_id})
    own_feedback = client.get("/api/feedback", headers={"X-Tenant-ID": tenant_a.public_id})
    cross_feedback = client.get("/api/feedback", headers={"X-Tenant-ID": tenant_b.public_id})
    own_feedback_stats = client.get("/api/feedback/stats", headers={"X-Tenant-ID": tenant_a.public_id})
    cross_watch = client.get(f"/api/watch-targets/{watch_b_id}", headers={"X-Tenant-ID": tenant_a.public_id})
    cross_watch_patch = client.patch(
        f"/api/watch-targets/{watch_b_id}",
        headers={"X-Tenant-ID": tenant_a.public_id},
        json={"status": "paused"},
    )
    cross_watch_delete = client.delete(f"/api/watch-targets/{watch_b_id}", headers={"X-Tenant-ID": tenant_a.public_id})
    cross_signals = client.get(
        f"/api/watch-targets/{watch_b_id}/signals",
        headers={"X-Tenant-ID": tenant_a.public_id},
    )
    cross_alert = client.get(f"/api/alerts/{alert_b_id}", headers={"X-Tenant-ID": tenant_a.public_id})
    cross_trace = client.get("/api/diagnostics/request/request-final-b", headers={"X-Tenant-ID": tenant_a.public_id})
    cross_task = client.get(f"/api/tasks/{task_b_id}", headers={"X-Tenant-ID": tenant_a.public_id})
    cross_task_patch = client.patch(
        f"/api/tasks/{task_b_id}",
        headers={"X-Tenant-ID": tenant_a.public_id},
        json={"status": "done"},
    )
    cross_task_delete = client.delete(f"/api/tasks/{task_b_id}", headers={"X-Tenant-ID": tenant_a.public_id})

    assert cross_conversation.status_code == 404
    assert error_code(cross_conversation) == "CONVERSATION_NOT_FOUND"
    assert cross_messages.status_code == 404
    assert error_code(cross_messages) == "CONVERSATION_NOT_FOUND"
    assert cross_bookmark.status_code == 404
    assert error_code(cross_bookmark) == "BOOKMARK_NOT_FOUND"
    assert cross_bookmark_delete.status_code == 404
    assert error_code(cross_bookmark_delete) == "BOOKMARK_NOT_FOUND"
    assert own_feedback.status_code == 200
    assert [item["content"] for item in own_feedback.json()] == ["tenant-a-feedback"]
    assert cross_feedback.status_code == 403
    assert error_code(cross_feedback) == "TENANT_MEMBERSHIP_REQUIRED"
    assert own_feedback_stats.status_code == 200
    assert own_feedback_stats.json()["total_feedback"] == 1
    assert own_feedback_stats.json()["useful_matches"] == 1
    assert own_feedback_stats.json()["not_useful_matches"] == 0
    assert cross_watch.status_code == 404
    assert error_code(cross_watch) == "WATCH_TARGET_NOT_FOUND"
    assert cross_watch_patch.status_code == 404
    assert error_code(cross_watch_patch) == "WATCH_TARGET_NOT_FOUND"
    assert cross_watch_delete.status_code == 404
    assert error_code(cross_watch_delete) == "WATCH_TARGET_NOT_FOUND"
    assert cross_signals.status_code == 404
    assert error_code(cross_signals) == "WATCH_TARGET_NOT_FOUND"
    assert cross_alert.status_code == 404
    assert error_code(cross_alert) == "ALERT_NOT_FOUND"
    assert cross_trace.status_code == 200
    assert cross_trace.json()["found"] is False
    assert cross_task.status_code == 404
    assert error_code(cross_task) == "TASK_NOT_FOUND"
    assert cross_task_patch.status_code == 404
    assert error_code(cross_task_patch) == "TASK_NOT_FOUND"
    assert cross_task_delete.status_code == 404
    assert error_code(cross_task_delete) == "TASK_NOT_FOUND"


def test_final_uat_null_tenant_private_rows_fail_closed_and_platform_diagnostics_are_super_admin_only(runtime):
    client = runtime["client"]
    default_tenant = ensure_default_tenant(runtime)
    tenant = create_tenant(runtime, name="Tenant Scoped", slug=unique_tenant_slug("final-null"))
    owner = _create_tenant_user(
        runtime,
        tenant=tenant,
        email="final-null@example.com",
        password="Password123456!",
        tenant_role="tenant_admin",
    )
    item_id = _seed_public_item(runtime, item_id="item-final-null")
    _seed_public_org(runtime, org_id="org-final-null", name="Legacy Org")
    _seed_public_org(runtime, org_id="org-final-owned", name="Owned Org")

    _seed_conversation(
        runtime,
        conversation_id="final-null-conversation",
        tenant_id=None,
        owner_user_id=str(owner.id),
        title="legacy",
    )
    _seed_conversation(
        runtime,
        conversation_id="final-owned-conversation",
        tenant_id=str(tenant.id),
        owner_user_id=str(owner.id),
        title="owned",
    )
    _seed_message(
        runtime,
        message_id="final-null-message",
        conversation_id="final-owned-conversation",
        tenant_id=None,
        role="user",
        content="legacy message",
    )
    _seed_bookmark(
        runtime,
        bookmark_id="final-null-bookmark",
        tenant_id=None,
        user_id=str(owner.id),
        item_id=item_id,
    )
    _seed_bookmark(
        runtime,
        bookmark_id="final-owned-bookmark",
        tenant_id=str(tenant.id),
        user_id=str(owner.id),
        item_id=item_id,
        note="owned",
    )
    _seed_feedback(
        runtime,
        tenant_id=None,
        user_id=str(owner.id),
        feedback_type="match_useful",
        content="legacy feedback",
    )
    _seed_feedback(
        runtime,
        tenant_id=str(tenant.id),
        user_id=str(owner.id),
        feedback_type="match_useful",
        content="owned feedback",
    )
    _seed_watch_target(
        runtime,
        watch_target_id="final-null-watch",
        tenant_id=None,
        user_id=str(owner.id),
        owner_user_id=str(owner.id),
        entity_id="org-final-null",
    )
    _seed_watch_target(
        runtime,
        watch_target_id="final-owned-watch",
        tenant_id=str(tenant.id),
        user_id=str(owner.id),
        owner_user_id=str(owner.id),
        entity_id="org-final-owned",
    )
    _seed_alert_chain(
        runtime,
        watch_target_id="final-owned-watch",
        tenant_id=None,
        owner_user_id=str(owner.id),
        entity_id="org-final-owned",
        suffix="final-null",
    )
    _seed_request_trace(
        runtime,
        trace_id="trace-final-null",
        request_id="request-final-null",
        tenant_id=None,
        event_type="system_event",
        event_data={"status": "legacy"},
    )
    _seed_request_trace(
        runtime,
        trace_id="trace-final-owned",
        request_id="request-final-owned",
        tenant_id=str(tenant.id),
        event_type="route_decided",
        event_data={"route": "owned"},
    )
    _seed_task(runtime, task_id=901, tenant_id=None, title="legacy task")
    _seed_task(runtime, task_id=902, tenant_id=str(tenant.id), title="owned task")

    login(client, email="final-null@example.com", password="Password123456!")
    conversation_list = client.get("/api/conversations", headers={"X-Tenant-ID": tenant.public_id})
    conversation_get = client.get("/api/conversations/final-null-conversation", headers={"X-Tenant-ID": tenant.public_id})
    messages = client.get("/api/conversations/final-owned-conversation/messages", headers={"X-Tenant-ID": tenant.public_id})
    bookmark_list = client.get("/api/bookmarks", headers={"X-Tenant-ID": tenant.public_id})
    bookmark_get = client.get("/api/bookmarks/final-null-bookmark", headers={"X-Tenant-ID": tenant.public_id})
    feedback_list = client.get("/api/feedback", headers={"X-Tenant-ID": tenant.public_id})
    feedback_stats = client.get("/api/feedback/stats", headers={"X-Tenant-ID": tenant.public_id})
    watch_list = client.get("/api/watch-targets", headers={"X-Tenant-ID": tenant.public_id})
    watch_get = client.get("/api/watch-targets/final-null-watch", headers={"X-Tenant-ID": tenant.public_id})
    signals = client.get("/api/watch-targets/final-owned-watch/signals", headers={"X-Tenant-ID": tenant.public_id})
    alerts = client.get("/api/alerts", headers={"X-Tenant-ID": tenant.public_id})
    null_trace = client.get("/api/diagnostics/request/request-final-null", headers={"X-Tenant-ID": tenant.public_id})
    tenant_trace = client.get("/api/diagnostics/request/request-final-owned", headers={"X-Tenant-ID": tenant.public_id})
    tasks = client.get("/api/tasks", headers={"X-Tenant-ID": tenant.public_id})
    null_task = client.get("/api/tasks/901", headers={"X-Tenant-ID": tenant.public_id})

    assert conversation_list.status_code == 200
    assert [item["id"] for item in conversation_list.json()] == ["final-owned-conversation"]
    assert conversation_get.status_code == 404
    assert error_code(conversation_get) == "CONVERSATION_NOT_FOUND"
    assert messages.status_code == 200
    assert messages.json() == []
    assert bookmark_list.status_code == 200
    assert [item["bookmark_id"] for item in bookmark_list.json()] == ["final-owned-bookmark"]
    assert bookmark_get.status_code == 404
    assert error_code(bookmark_get) == "BOOKMARK_NOT_FOUND"
    assert feedback_list.status_code == 200
    assert [item["content"] for item in feedback_list.json()] == ["owned feedback"]
    assert feedback_stats.status_code == 200
    assert feedback_stats.json()["total_feedback"] == 1
    assert watch_list.status_code == 200
    assert [item["id"] for item in watch_list.json()["items"]] == ["final-owned-watch"]
    assert watch_get.status_code == 404
    assert error_code(watch_get) == "WATCH_TARGET_NOT_FOUND"
    assert signals.status_code == 200
    assert signals.json()["total"] == 0
    assert alerts.status_code == 200
    assert alerts.json()["total"] == 0
    assert null_trace.status_code == 200
    assert null_trace.json()["found"] is False
    assert tenant_trace.status_code == 200
    assert tenant_trace.json()["found"] is True
    assert tasks.status_code == 200
    assert [item["id"] for item in tasks.json()["tasks"]] == [902]
    assert null_task.status_code == 404
    assert error_code(null_task) == "TASK_NOT_FOUND"

    super_admin = create_user(
        runtime,
        email="final-root@example.com",
        password="Password123456!",
        role="super_admin",
        display_name="Super Admin",
    )
    _set_user_default_tenant(runtime, user=super_admin, tenant=default_tenant)

    client.cookies.clear()
    login(client, email="final-root@example.com", password="Password123456!")
    platform_trace = client.get("/api/diagnostics/request/request-final-null")
    assert platform_trace.status_code == 200
    assert platform_trace.json()["found"] is True


def test_final_uat_blocks_disabled_tenant_and_disabled_membership(runtime):
    client = runtime["client"]
    default_tenant = ensure_default_tenant(runtime)
    disabled_tenant = create_tenant(runtime, name="Tenant Disabled", slug=unique_tenant_slug("final-disabled"), status="disabled")
    inactive_membership_tenant = create_tenant(
        runtime,
        name="Tenant Membership",
        slug=unique_tenant_slug("final-membership"),
    )
    _seed_public_org(runtime, org_id="org-final-disabled")
    user = _create_tenant_user(runtime, tenant=default_tenant, email="final-blocked@example.com", password="Password123456!")
    create_membership(runtime, tenant=disabled_tenant, user=user, role="viewer", status="active")
    create_membership(runtime, tenant=inactive_membership_tenant, user=user, role="viewer", status="disabled")

    login(client, email="final-blocked@example.com", password="Password123456!")
    disabled_conversations = client.get("/api/conversations", headers={"X-Tenant-ID": disabled_tenant.public_id})
    disabled_tasks = client.get("/api/tasks", headers={"X-Tenant-ID": disabled_tenant.public_id})
    disabled_watch_targets = client.get("/api/watch-targets", headers={"X-Tenant-ID": disabled_tenant.public_id})
    inactive_conversations = client.get("/api/conversations", headers={"X-Tenant-ID": inactive_membership_tenant.public_id})
    inactive_tasks = client.get("/api/tasks", headers={"X-Tenant-ID": inactive_membership_tenant.public_id})
    inactive_watch_targets = client.get("/api/watch-targets", headers={"X-Tenant-ID": inactive_membership_tenant.public_id})

    assert disabled_conversations.status_code == 403
    assert error_code(disabled_conversations) == "TENANT_DISABLED"
    assert disabled_tasks.status_code == 403
    assert error_code(disabled_tasks) == "TENANT_DISABLED"
    assert disabled_watch_targets.status_code == 403
    assert error_code(disabled_watch_targets) == "TENANT_DISABLED"
    assert inactive_conversations.status_code == 403
    assert error_code(inactive_conversations) == "TENANT_MEMBERSHIP_INACTIVE"
    assert inactive_tasks.status_code == 403
    assert error_code(inactive_tasks) == "TENANT_MEMBERSHIP_INACTIVE"
    assert inactive_watch_targets.status_code == 403
    assert error_code(inactive_watch_targets) == "TENANT_MEMBERSHIP_INACTIVE"
