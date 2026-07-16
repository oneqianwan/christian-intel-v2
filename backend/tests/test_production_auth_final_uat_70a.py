from __future__ import annotations

import sqlite3

from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from account_lifecycle_testkit import create_user, error_code, login, runtime, set_production_auth_defaults, set_test_mode
from production_auth_testkit import reset_runtime_state
from test_auth_migration import _run_migration
from test_production_readiness_core_uat import _block_llm_and_network, seeded_runtime
from test_production_readiness_startup_checks import startup_runtime


@pytest.fixture(autouse=True)
def _reset_runtime(runtime):
    reset_runtime_state(runtime)
    set_production_auth_defaults(runtime)
    yield


def test_final_uat_core_api_protection_and_defaults(runtime):
    client = runtime["client"]
    settings = runtime["config"].settings
    database = runtime["database"]

    assert settings.ALLOW_PUBLIC_CORE_APIS is False
    assert settings.CHAT_USER_OWNERSHIP_ENABLED is True
    assert settings.WATCH_ALERT_USER_OWNERSHIP_ENABLED is True
    assert settings.BOOKMARKS_USER_OWNERSHIP_ENABLED is True
    assert settings.FEEDBACK_USER_OWNERSHIP_ENABLED is True

    protected_calls = [
        ("post", "/api/chat/simple", {"json": {"message": "hello"}}),
        ("post", "/api/chat/stream", {"json": {"message": "hello"}}),
        ("get", "/api/conversations", {}),
        ("get", "/api/export/html", {"params": {"query": "victory", "country": "菲律宾"}}),
        ("get", "/api/export/pdf", {"params": {"query": "victory", "country": "菲律宾"}}),
        ("get", "/api/dashboard/overview", {}),
        ("get", "/api/dashboard/scores", {}),
        ("get", "/api/diagnostics/request/request-1", {}),
    ]

    for method, path, kwargs in protected_calls:
        response = getattr(client, method)(path, **kwargs)
        assert response.status_code == 401
        assert error_code(response) == "AUTH_REQUIRED"

    watch_response = client.post(
        "/api/watch-targets",
        headers={"x-session-id": "legacy-user"},
        json={"entity_id": "org-1", "entity_type": "organization", "frequency": "daily"},
    )
    bookmark_response = client.post("/api/bookmarks", params={"item_id": "bookmark-item", "note": "legacy"})
    feedback_response = client.post(
        "/api/feedback",
        headers={"x-session-id": "legacy-session"},
        json={"feedback_type": "match_useful", "content": "legacy"},
    )

    assert watch_response.status_code == 401
    assert error_code(watch_response) == "AUTH_REQUIRED"
    assert bookmark_response.status_code == 401
    assert error_code(bookmark_response) == "AUTH_REQUIRED"
    assert feedback_response.status_code == 401
    assert error_code(feedback_response) == "AUTH_REQUIRED"

    db = database.SessionLocal()
    try:
        assert db.query(database.Bookmark).count() == 0
        assert db.query(database.UserFeedback).count() == 0
    finally:
        db.close()


def test_final_uat_admin_rbac_and_account_provisioning(runtime):
    app = runtime["main"].app
    admin_client_ctx = TestClient(app)
    super_client_ctx = TestClient(app)
    admin_client = admin_client_ctx.__enter__()
    super_client = super_client_ctx.__enter__()
    database = runtime["database"]
    auth_models = runtime["auth_models"]

    try:
        unauthenticated = runtime["client"].get("/api/admin/users")
        assert unauthenticated.status_code == 401
        assert error_code(unauthenticated) == "AUTH_REQUIRED"

        create_user(runtime, email="viewer@example.com", password="Password123456!", role="viewer")
        login(runtime["client"], email="viewer@example.com", password="Password123456!")
        forbidden_list = runtime["client"].get("/api/admin/users")
        forbidden_create = runtime["client"].post(
            "/api/admin/users",
            json={"email": "blocked@example.com", "display_name": "Blocked", "role": "viewer", "status": "pending"},
        )
        assert forbidden_list.status_code == 403
        assert error_code(forbidden_list) == "ROLE_FORBIDDEN"
        assert forbidden_create.status_code == 403
        assert error_code(forbidden_create) == "ROLE_FORBIDDEN"

        create_user(runtime, email="admin@example.com", password="Password123456!", role="admin")
        create_user(runtime, email="root@example.com", password="Password123456!", role="super_admin")
        login(admin_client, email="admin@example.com", password="Password123456!")
        login(super_client, email="root@example.com", password="Password123456!")

        created = admin_client.post(
            "/api/admin/users",
            json={
                "email": " MixedCase@Example.com ",
                "display_name": "Provisioned User",
                "role": "viewer",
                "status": "pending",
            },
        )
        assert created.status_code == 200
        payload = created.json()
        assert payload["user"]["email"] == "mixedcase@example.com"
        assert payload["setup_token"]

        duplicate = admin_client.post(
            "/api/admin/users",
            json={
                "email": "mixedcase@example.com",
                "display_name": "Duplicate",
                "role": "viewer",
                "status": "pending",
            },
        )
        assert duplicate.status_code == 409
        assert error_code(duplicate) == "EMAIL_ALREADY_EXISTS"

        no_super_admin = admin_client.post(
            "/api/admin/users",
            json={
                "email": "root2@example.com",
                "display_name": "Root Two",
                "role": "super_admin",
                "status": "pending",
            },
        )
        assert no_super_admin.status_code == 403
        assert error_code(no_super_admin) == "ROLE_FORBIDDEN"

        db = database.SessionLocal()
        try:
            provisioned_user = (
                db.query(auth_models.User).filter(auth_models.User.email_normalized == "mixedcase@example.com").one()
            )
            token_row = (
                db.query(auth_models.AccountToken).filter(auth_models.AccountToken.user_id == provisioned_user.id).one()
            )
            assert provisioned_user.password_hash.startswith("$argon2id$")
            assert payload["setup_token"] not in provisioned_user.password_hash
            assert token_row.token_hash
            assert payload["setup_token"] not in token_row.token_hash
            admin_user = db.query(auth_models.User).filter(auth_models.User.email_normalized == "admin@example.com").one()
        finally:
            db.close()

        disable_response = super_client.patch(
            f"/api/admin/users/{admin_user.public_id}/status",
            json={"status": "disabled"},
        )
        assert disable_response.status_code == 200
        assert disable_response.json()["status"] == "disabled"

        blocked_admin = admin_client.get("/api/admin/users")
        assert blocked_admin.status_code == 401
        assert error_code(blocked_admin) == "SESSION_REVOKED"

        runtime["config"].settings.AUTH_V1_ENABLED = False
        fail_closed_admin = runtime["client"].get("/api/admin/users")
        fail_closed_chat = runtime["client"].post("/api/chat/simple", json={"message": "hello"})
        assert fail_closed_admin.status_code == 503
        assert error_code(fail_closed_admin) == "AUTH_DISABLED"
        assert fail_closed_chat.status_code == 503
        assert error_code(fail_closed_chat) == "AUTH_DISABLED"
    finally:
        admin_client_ctx.__exit__(None, None, None)
        super_client_ctx.__exit__(None, None, None)


def test_final_uat_setup_password_password_reset_and_session_security(runtime):
    client = runtime["client"]
    database = runtime["database"]
    auth_models = runtime["auth_models"]

    create_user(runtime, email="admin@example.com", password="Password123456!", role="admin")
    login(client, email="admin@example.com", password="Password123456!")

    invited = client.post(
        "/api/admin/users",
        json={
            "email": "invitee@example.com",
            "display_name": "Invitee",
            "role": "viewer",
            "status": "pending",
        },
    )
    assert invited.status_code == 200
    invite_payload = invited.json()
    invite_token = invite_payload["setup_token"]

    db = database.SessionLocal()
    try:
        invited_user = db.query(auth_models.User).filter(auth_models.User.email_normalized == "invitee@example.com").one()
        setup_token_row = (
            db.query(auth_models.AccountToken)
            .filter(
                auth_models.AccountToken.user_id == invited_user.id,
                auth_models.AccountToken.purpose == "setup_password",
            )
            .one()
        )
        assert setup_token_row.expires_at is not None
        assert invite_token not in setup_token_row.token_hash
        setup_token_row.expires_at = datetime.utcnow() - timedelta(seconds=5)
        db.add(setup_token_row)
        db.commit()
    finally:
        db.close()

    expired_setup = client.post(
        "/api/auth/setup-password",
        json={
            "token": invite_token,
            "new_password": "NewPassword123456!",
            "confirm_password": "NewPassword123456!",
        },
    )
    assert expired_setup.status_code == 400
    assert error_code(expired_setup) == "TOKEN_EXPIRED"

    reinvite = client.post(
        "/api/admin/users",
        json={
            "email": "invitee2@example.com",
            "display_name": "Invitee Two",
            "role": "viewer",
            "status": "pending",
        },
    )
    assert reinvite.status_code == 200
    fresh_setup_token = reinvite.json()["setup_token"]

    weak_password = client.post(
        "/api/auth/setup-password",
        json={"token": fresh_setup_token, "new_password": "short", "confirm_password": "short"},
    )
    assert weak_password.status_code == 422
    assert error_code(weak_password) == "PASSWORD_TOO_SHORT"

    setup_success = client.post(
        "/api/auth/setup-password",
        json={
            "token": fresh_setup_token,
            "new_password": "NewPassword123456!",
            "confirm_password": "NewPassword123456!",
        },
    )
    assert setup_success.status_code == 200
    assert setup_success.json()["success"] is True
    assert fresh_setup_token not in str(setup_success.json())

    reused_setup = client.post(
        "/api/auth/setup-password",
        json={
            "token": fresh_setup_token,
            "new_password": "AnotherPassword123456!",
            "confirm_password": "AnotherPassword123456!",
        },
    )
    assert reused_setup.status_code == 400
    assert error_code(reused_setup) == "TOKEN_INVALID"

    login_response = client.post(
        "/api/auth/login",
        json={"email": "invitee2@example.com", "password": "NewPassword123456!"},
    )
    assert login_response.status_code == 200
    set_cookie = login_response.headers.get("set-cookie", "")
    assert "HttpOnly" in set_cookie
    assert "SameSite=" in set_cookie
    assert f"Max-Age={runtime['config'].settings.AUTH_SESSION_TTL_SECONDS}" in set_cookie
    old_session_token = set_cookie.split(";", 1)[0].split("=", 1)[1]

    logout = client.post("/api/auth/logout")
    assert logout.status_code == 200
    follow_up_after_logout = client.get("/api/auth/me")
    assert follow_up_after_logout.status_code == 401
    assert error_code(follow_up_after_logout) == "AUTH_REQUIRED"

    second_login = client.post(
        "/api/auth/login",
        json={"email": "invitee2@example.com", "password": "NewPassword123456!"},
    )
    assert second_login.status_code == 200
    logout_all = client.post("/api/auth/logout-all")
    assert logout_all.status_code == 200
    follow_up_after_logout_all = client.get("/api/auth/me")
    assert follow_up_after_logout_all.status_code == 401
    assert error_code(follow_up_after_logout_all) in {"AUTH_REQUIRED", "SESSION_REVOKED"}

    create_user(runtime, email="disabled@example.com", password="Password123456!", role="viewer", status="disabled")
    disabled_login = client.post("/api/auth/login", json={"email": "disabled@example.com", "password": "Password123456!"})
    assert disabled_login.status_code == 403
    assert error_code(disabled_login) == "ACCOUNT_DISABLED"

    existing_reset_public = client.post("/api/auth/password-reset/request", json={"email": "invitee2@example.com"})
    missing_reset_public = client.post("/api/auth/password-reset/request", json={"email": "missing@example.com"})
    assert existing_reset_public.status_code == 200
    assert missing_reset_public.status_code == 200
    assert existing_reset_public.json()["message"] == missing_reset_public.json()["message"]

    set_test_mode(runtime)
    reset_with_token = client.post("/api/auth/password-reset/request", json={"email": "invitee2@example.com"})
    assert reset_with_token.status_code == 200
    reset_token = reset_with_token.json()["reset_token"]
    assert reset_token

    db = database.SessionLocal()
    try:
        reset_user = db.query(auth_models.User).filter(auth_models.User.email_normalized == "invitee2@example.com").one()
        reset_token_row = (
            db.query(auth_models.AccountToken)
            .filter(
                auth_models.AccountToken.user_id == reset_user.id,
                auth_models.AccountToken.purpose == "password_reset",
            )
            .order_by(auth_models.AccountToken.created_at.desc())
            .first()
        )
        assert reset_token_row is not None
        assert reset_token not in reset_token_row.token_hash
        assert reset_token_row.expires_at is not None
        disabled_user = db.query(auth_models.User).filter(auth_models.User.email_normalized == "disabled@example.com").one()
        assert disabled_user.password_hash.startswith("$argon2id$")
    finally:
        db.close()

    client.cookies.clear()
    client.cookies.set(
        runtime["config"].settings.AUTH_COOKIE_NAME,
        old_session_token,
        path=runtime["config"].settings.AUTH_COOKIE_PATH,
    )
    reset_confirm = client.post(
        "/api/auth/password-reset/confirm",
        json={
            "token": reset_token,
            "new_password": "ResetPassword123456!",
            "confirm_password": "ResetPassword123456!",
        },
    )
    assert reset_confirm.status_code == 200
    assert reset_confirm.json()["success"] is True
    assert reset_token not in str(reset_confirm.json())

    reused_reset = client.post(
        "/api/auth/password-reset/confirm",
        json={
            "token": reset_token,
            "new_password": "AnotherResetPassword123456!",
            "confirm_password": "AnotherResetPassword123456!",
        },
    )
    assert reused_reset.status_code == 400
    assert error_code(reused_reset) == "TOKEN_INVALID"

    old_password_blocked = client.post(
        "/api/auth/login",
        json={"email": "invitee2@example.com", "password": "NewPassword123456!"},
    )
    assert old_password_blocked.status_code == 401
    assert error_code(old_password_blocked) == "INVALID_CREDENTIALS"

    current_session_blocked = client.get("/api/auth/me")
    assert current_session_blocked.status_code == 401
    assert error_code(current_session_blocked) in {"AUTH_REQUIRED", "SESSION_REVOKED"}

    new_password_login = client.post(
        "/api/auth/login",
        json={"email": "invitee2@example.com", "password": "ResetPassword123456!"},
    )
    assert new_password_login.status_code == 200

    disabled_reset = client.post("/api/auth/password-reset/request", json={"email": "disabled@example.com"})
    assert disabled_reset.status_code == 200
    assert disabled_reset.json()["reset_token"] is None

    for _ in range(3):
        invalid = client.post("/api/auth/login", json={"email": "unknown@example.com", "password": "wrong-password"})
        assert invalid.status_code == 401
        assert error_code(invalid) == "INVALID_CREDENTIALS"
    limited = client.post("/api/auth/login", json={"email": "unknown@example.com", "password": "wrong-password"})
    assert limited.status_code == 429
    assert error_code(limited) == "LOGIN_RATE_LIMITED"


def test_final_uat_migration_readiness_and_public_saas_status(startup_runtime, tmp_path: Path):
    checker = startup_runtime["readiness_module"].ProductionReadinessChecker()
    database = startup_runtime["database"]
    report = checker.build_report()

    assert report["status"] == "ready"
    assert report["environment"]["account_token_storage_ok"] is True
    assert report["commercial_readiness"]["public_saas_ready"] is False
    reasons = set(report["commercial_readiness"]["reason_public_saas_not_ready"])
    assert "multi_tenant_isolation_not_fully_validated" in reasons
    assert "billing_not_implemented" in reasons
    assert "rate_limit_not_fully_validated" in reasons
    assert "monitoring_alerting_not_fully_validated" in reasons
    assert "backup_recovery_not_fully_validated" in reasons
    assert "deployment_health_checks_not_fully_validated" in reasons

    with database.engine.begin() as conn:
        conn.execute(text("DROP TABLE account_tokens"))
    missing_report = checker.build_report()
    assert missing_report["status"] == "blocked"
    assert missing_report["environment"]["account_token_storage_ok"] is False
    assert "account_token_storage_missing" in missing_report["errors"]

    db_path = tmp_path / "final_uat_auth_migration.db"
    proc = _run_migration(["--database", str(db_path), "--apply", "--verify"], cwd=Path(__file__).resolve().parents[1])
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "VERIFY_OK=true" in proc.stdout

    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.cursor()
        tables = {row[0] for row in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "account_tokens" in tables
        columns = {row[1] for row in cur.execute("PRAGMA table_info(account_tokens)")}
        assert {
            "id",
            "public_id",
            "user_id",
            "token_hash",
            "purpose",
            "status",
            "expires_at",
            "used_at",
            "created_at",
            "created_by_user_id",
        }.issubset(columns)
    finally:
        conn.close()


def test_final_uat_authenticated_core_intelligence_regression(seeded_runtime, monkeypatch):
    brain_module = seeded_runtime["brain_module"]
    checker = seeded_runtime["readiness_module"].ProductionReadinessChecker()
    _block_llm_and_network(monkeypatch, brain_module)
    brain = brain_module.Brain()

    contracts = [
        brain.think("Victory Philippines 评分是多少？", conversation_id="uat-score")["response_contract"],
        brain.think("Victory Philippines 的关系图谱", conversation_id="uat-graph")["response_contract"],
        brain.think("Victory Philippines 怎么联系？", conversation_id="uat-contact")["response_contract"],
        brain.think("Victory Philippines 推荐合作对象有哪些？", conversation_id="uat-recommendation")["response_contract"],
        brain.think("What are the next steps for Harbor Church?", conversation_id="uat-action-plan")["response_contract"],
        brain.think("Give me an evidence brief for Harbor Church.", conversation_id="uat-evidence-brief")["response_contract"],
        brain.think("推荐合作对象有哪些？", conversation_id="uat-fallback")["response_contract"],
    ]
    report = checker.build_report(contracts=contracts)

    payload_types = {contract["payload_type"] for contract in contracts}
    assert "score_snapshot" in payload_types
    assert "relationship_graph" in payload_types
    assert "contact_intelligence" in payload_types
    assert "partnership_recommendation" in payload_types
    assert "partnership_action_plan" in payload_types
    assert "partnership_evidence_brief" in payload_types

    for contract in contracts:
        assert contract["response_contract_version"] == "6.0D"
        assert contract["observability"]["audit_summary"]["audit_version"] == "6.0E"
        assert contract["audit"]["no_llm"] is True
        assert contract["audit"]["no_network"] is True
        assert contract["audit"]["no_fabrication"] is True
        assert contract["source"] != "llm"

    assert report["status"] == "ready"
    assert report["core_brain"]["response_contract_ok"] is True
    assert report["core_brain"]["observability_ok"] is True
    assert report["safety"]["no_llm_for_structured_lookup"] is True
    assert report["safety"]["no_network_for_structured_lookup"] is True
    assert report["safety"]["no_fabrication"] is True
    assert report["safety"]["safe_fallback_enabled"] is True
