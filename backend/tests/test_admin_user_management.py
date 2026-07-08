from __future__ import annotations

from fastapi.testclient import TestClient

import pytest

from test_auth_api import runtime


@pytest.fixture(autouse=True)
def reset_db(runtime):
    database = runtime["database"]
    auth_models = runtime["auth_models"]
    client = runtime["client"]
    auth_service = runtime["auth_service"]

    db = database.SessionLocal()
    try:
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


def _error_code(response) -> str | None:
    payload = response.json()
    detail = payload.get("detail")
    if isinstance(detail, dict):
        return detail.get("error_code")
    return payload.get("error_code")


def _set_auth_enabled(enabled: bool) -> None:
    import config as config_module

    config_module.settings.AUTH_V1_ENABLED = bool(enabled)


def _create_user(
    runtime,
    *,
    email: str,
    password: str,
    role: str,
    status: str = "active",
    display_name: str = "User",
):
    database = runtime["database"]
    auth_models = runtime["auth_models"]
    auth_service = runtime["auth_service"]
    db = database.SessionLocal()
    try:
        user = auth_models.User(
            email=email,
            email_normalized=auth_service.normalize_email(email),
            password_hash=auth_service.hash_password(password),
            display_name=display_name,
            role=role,
            status=status,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    finally:
        db.close()


def _login(client: TestClient, *, email: str, password: str) -> None:
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200


def _create_session_token(runtime, *, user) -> str:
    database = runtime["database"]
    auth_service = runtime["auth_service"]
    db = database.SessionLocal()
    try:
        _, raw_token = auth_service.create_auth_session(db, user=user)
        return raw_token
    finally:
        db.close()


def _set_cookie(runtime, client: TestClient, raw_token: str) -> None:
    config = runtime["config"]
    client.cookies.set(
        config.settings.AUTH_COOKIE_NAME,
        raw_token,
        path=config.settings.AUTH_COOKIE_PATH,
    )


def test_01_super_admin_list_users_passes_and_filters(runtime):
    client = runtime["client"]
    _set_auth_enabled(True)
    _create_user(runtime, email="root@example.com", password="Password123456!", role="super_admin")
    _create_user(runtime, email="analyst@example.com", password="Password123456!", role="analyst")
    _create_user(runtime, email="viewer@example.com", password="Password123456!", role="viewer", status="disabled")

    _login(client, email="root@example.com", password="Password123456!")
    response = client.get("/api/admin/users", params={"role": "analyst", "email": "analyst", "limit": 10, "offset": 0})

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["email"] == "analyst@example.com"
    assert "password_hash" not in str(payload).lower()
    assert "token_hash" not in str(payload).lower()


def test_02_admin_list_users_passes(runtime):
    client = runtime["client"]
    _set_auth_enabled(True)
    _create_user(runtime, email="admin@example.com", password="Password123456!", role="admin")
    _create_user(runtime, email="viewer@example.com", password="Password123456!", role="viewer")

    _login(client, email="admin@example.com", password="Password123456!")
    response = client.get("/api/admin/users")

    assert response.status_code == 200
    assert response.json()["total"] == 2


@pytest.mark.parametrize(
    ("role", "path", "method"),
    [
        ("analyst", "/api/admin/users", "get"),
        ("viewer", "/api/admin/users", "get"),
        ("analyst", "/api/admin/users/placeholder/role", "patch"),
        ("viewer", "/api/admin/users/placeholder/status", "patch"),
        ("analyst", "/api/admin/users/placeholder/sessions/revoke", "post"),
    ],
)
def test_03_analyst_viewer_denied_across_admin_endpoints(runtime, role, path, method):
    client = runtime["client"]
    _set_auth_enabled(True)
    actor = _create_user(runtime, email=f"{role}@example.com", password="Password123456!", role=role)
    target = _create_user(runtime, email="target@example.com", password="Password123456!", role="viewer")

    _login(client, email=f"{role}@example.com", password="Password123456!")

    resolved_path = path.replace("placeholder", str(target.public_id))
    if method == "get":
        response = client.get(resolved_path)
    elif method == "patch" and resolved_path.endswith("/role"):
        response = client.patch(resolved_path, json={"role": "admin"})
    elif method == "patch":
        response = client.patch(resolved_path, json={"status": "disabled"})
    else:
        response = client.post(resolved_path)

    assert actor.role == role
    assert response.status_code == 403
    assert _error_code(response) == "ROLE_FORBIDDEN"


def test_04_unauthenticated_list_users_returns_401(runtime):
    client = runtime["client"]
    _set_auth_enabled(True)

    response = client.get("/api/admin/users")

    assert response.status_code == 401
    assert _error_code(response) == "AUTH_REQUIRED"


def test_05_get_user_detail_by_public_id_passes(runtime):
    client = runtime["client"]
    _set_auth_enabled(True)
    _create_user(runtime, email="admin@example.com", password="Password123456!", role="admin")
    target = _create_user(runtime, email="viewer@example.com", password="Password123456!", role="viewer")

    _login(client, email="admin@example.com", password="Password123456!")
    response = client.get(f"/api/admin/users/{target.public_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["public_id"] == str(target.public_id)
    assert payload["email"] == "viewer@example.com"
    assert "password_hash" not in payload


def test_06_missing_user_returns_404(runtime):
    client = runtime["client"]
    _set_auth_enabled(True)
    _create_user(runtime, email="admin@example.com", password="Password123456!", role="admin")

    _login(client, email="admin@example.com", password="Password123456!")
    response = client.get("/api/admin/users/missing-public-id")

    assert response.status_code == 404
    assert _error_code(response) == "USER_NOT_FOUND"


def test_07_super_admin_can_change_role(runtime):
    client = runtime["client"]
    database = runtime["database"]
    auth_models = runtime["auth_models"]
    _set_auth_enabled(True)
    _create_user(runtime, email="root@example.com", password="Password123456!", role="super_admin")
    target = _create_user(runtime, email="viewer@example.com", password="Password123456!", role="viewer")

    _login(client, email="root@example.com", password="Password123456!")
    response = client.patch(f"/api/admin/users/{target.public_id}/role", json={"role": "admin"})

    assert response.status_code == 200
    assert response.json()["role"] == "admin"

    db = database.SessionLocal()
    try:
        updated = db.query(auth_models.User).filter(auth_models.User.id == target.id).one()
        assert updated.role == "admin"
    finally:
        db.close()


def test_08_admin_cannot_change_role(runtime):
    client = runtime["client"]
    _set_auth_enabled(True)
    _create_user(runtime, email="admin@example.com", password="Password123456!", role="admin")
    target = _create_user(runtime, email="viewer@example.com", password="Password123456!", role="viewer")

    _login(client, email="admin@example.com", password="Password123456!")
    response = client.patch(f"/api/admin/users/{target.public_id}/role", json={"role": "analyst"})

    assert response.status_code == 403
    assert _error_code(response) == "ROLE_FORBIDDEN"


def test_09_self_demotion_rejected(runtime):
    client = runtime["client"]
    _set_auth_enabled(True)
    actor = _create_user(runtime, email="root@example.com", password="Password123456!", role="super_admin")
    _create_user(runtime, email="other@example.com", password="Password123456!", role="super_admin")

    _login(client, email="root@example.com", password="Password123456!")
    response = client.patch(f"/api/admin/users/{actor.public_id}/role", json={"role": "admin"})

    assert response.status_code == 403
    assert _error_code(response) == "SELF_DEMOTION_FORBIDDEN"


def test_10_unknown_role_rejected(runtime):
    client = runtime["client"]
    _set_auth_enabled(True)
    _create_user(runtime, email="root@example.com", password="Password123456!", role="super_admin")
    target = _create_user(runtime, email="viewer@example.com", password="Password123456!", role="viewer")

    _login(client, email="root@example.com", password="Password123456!")
    response = client.patch(f"/api/admin/users/{target.public_id}/role", json={"role": "owner"})

    assert response.status_code == 422


def test_11_super_admin_can_change_status(runtime):
    client = runtime["client"]
    database = runtime["database"]
    auth_models = runtime["auth_models"]
    _set_auth_enabled(True)
    _create_user(runtime, email="root@example.com", password="Password123456!", role="super_admin")
    target = _create_user(runtime, email="admin@example.com", password="Password123456!", role="admin", status="active")

    _login(client, email="root@example.com", password="Password123456!")
    response = client.patch(f"/api/admin/users/{target.public_id}/status", json={"status": "disabled"})

    assert response.status_code == 200
    assert response.json()["status"] == "disabled"

    db = database.SessionLocal()
    try:
        updated = db.query(auth_models.User).filter(auth_models.User.id == target.id).one()
        assert updated.status == "disabled"
    finally:
        db.close()


def test_12_admin_can_change_analyst_viewer_status(runtime):
    client = runtime["client"]
    _set_auth_enabled(True)
    _create_user(runtime, email="admin@example.com", password="Password123456!", role="admin")
    analyst = _create_user(runtime, email="analyst@example.com", password="Password123456!", role="analyst")
    viewer = _create_user(runtime, email="viewer@example.com", password="Password123456!", role="viewer")

    _login(client, email="admin@example.com", password="Password123456!")
    analyst_response = client.patch(f"/api/admin/users/{analyst.public_id}/status", json={"status": "disabled"})
    viewer_response = client.patch(f"/api/admin/users/{viewer.public_id}/status", json={"status": "pending"})

    assert analyst_response.status_code == 200
    assert analyst_response.json()["status"] == "disabled"
    assert viewer_response.status_code == 200
    assert viewer_response.json()["status"] == "pending"


def test_13_admin_cannot_change_admin_or_super_admin_status(runtime):
    client = runtime["client"]
    _set_auth_enabled(True)
    _create_user(runtime, email="admin@example.com", password="Password123456!", role="admin")
    other_admin = _create_user(runtime, email="other-admin@example.com", password="Password123456!", role="admin")
    super_admin = _create_user(runtime, email="root@example.com", password="Password123456!", role="super_admin")

    _login(client, email="admin@example.com", password="Password123456!")
    admin_response = client.patch(f"/api/admin/users/{other_admin.public_id}/status", json={"status": "disabled"})
    super_response = client.patch(f"/api/admin/users/{super_admin.public_id}/status", json={"status": "disabled"})

    assert admin_response.status_code == 403
    assert _error_code(admin_response) == "ROLE_FORBIDDEN"
    assert super_response.status_code == 403
    assert _error_code(super_response) == "ROLE_FORBIDDEN"


def test_14_self_disable_rejected(runtime):
    client = runtime["client"]
    _set_auth_enabled(True)
    actor = _create_user(runtime, email="root@example.com", password="Password123456!", role="super_admin")
    _create_user(runtime, email="other@example.com", password="Password123456!", role="super_admin")

    _login(client, email="root@example.com", password="Password123456!")
    response = client.patch(f"/api/admin/users/{actor.public_id}/status", json={"status": "disabled"})

    assert response.status_code == 403
    assert _error_code(response) == "SELF_DISABLE_FORBIDDEN"


def test_15_last_super_admin_disable_rejected(runtime):
    client = runtime["client"]
    _set_auth_enabled(True)
    _create_user(runtime, email="root@example.com", password="Password123456!", role="super_admin")

    _login(client, email="root@example.com", password="Password123456!")
    actor = client.get("/api/auth/me").json()["user"]
    response = client.patch(f"/api/admin/users/{actor['public_id']}/status", json={"status": "disabled"})

    assert response.status_code == 403
    assert _error_code(response) in {"SELF_DISABLE_FORBIDDEN", "LAST_SUPER_ADMIN_PROTECTED"}


def test_16_unknown_status_rejected(runtime):
    client = runtime["client"]
    _set_auth_enabled(True)
    _create_user(runtime, email="root@example.com", password="Password123456!", role="super_admin")
    target = _create_user(runtime, email="viewer@example.com", password="Password123456!", role="viewer")

    _login(client, email="root@example.com", password="Password123456!")
    response = client.patch(f"/api/admin/users/{target.public_id}/status", json={"status": "archived"})

    assert response.status_code == 422


def test_17_revoke_target_sessions_works(runtime):
    client = runtime["client"]
    _set_auth_enabled(True)
    _create_user(runtime, email="admin@example.com", password="Password123456!", role="admin")
    target = _create_user(runtime, email="viewer@example.com", password="Password123456!", role="viewer")
    target_token = _create_session_token(runtime, user=target)

    _login(client, email="admin@example.com", password="Password123456!")
    response = client.post(f"/api/admin/users/{target.public_id}/sessions/revoke")

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert response.json()["revoked_count"] >= 1
    assert "token" not in str(response.json()).lower()

    with TestClient(runtime["main"].app) as target_client:
        _set_cookie(runtime, target_client, target_token)
        me_response = target_client.get("/api/auth/me")

    assert me_response.status_code == 401
    assert _error_code(me_response) == "SESSION_REVOKED"


def test_18_admin_cannot_revoke_admin_or_super_admin_sessions(runtime):
    client = runtime["client"]
    _set_auth_enabled(True)
    _create_user(runtime, email="admin@example.com", password="Password123456!", role="admin")
    other_admin = _create_user(runtime, email="other-admin@example.com", password="Password123456!", role="admin")
    super_admin = _create_user(runtime, email="root@example.com", password="Password123456!", role="super_admin")

    _login(client, email="admin@example.com", password="Password123456!")
    admin_response = client.post(f"/api/admin/users/{other_admin.public_id}/sessions/revoke")
    super_response = client.post(f"/api/admin/users/{super_admin.public_id}/sessions/revoke")

    assert admin_response.status_code == 403
    assert _error_code(admin_response) == "ROLE_FORBIDDEN"
    assert super_response.status_code == 403
    assert _error_code(super_response) == "ROLE_FORBIDDEN"


def test_19_self_session_revoke_rejected(runtime):
    client = runtime["client"]
    _set_auth_enabled(True)
    actor = _create_user(runtime, email="root@example.com", password="Password123456!", role="super_admin")
    _create_user(runtime, email="viewer@example.com", password="Password123456!", role="viewer")

    _login(client, email="root@example.com", password="Password123456!")
    response = client.post(f"/api/admin/users/{actor.public_id}/sessions/revoke")

    assert response.status_code == 403
    assert _error_code(response) == "SELF_SESSION_REVOKE_FORBIDDEN"


def test_20_header_and_body_role_spoofing_rejected(runtime):
    client = runtime["client"]
    _set_auth_enabled(True)
    _create_user(runtime, email="viewer@example.com", password="Password123456!", role="viewer")
    target = _create_user(runtime, email="target@example.com", password="Password123456!", role="viewer")

    _login(client, email="viewer@example.com", password="Password123456!")
    response = client.patch(
        f"/api/admin/users/{target.public_id}/role",
        headers={"x-user-id": "forged-user", "x-session-id": "forged-session", "x-role": "super_admin"},
        json={"role": "admin"},
    )

    assert response.status_code == 403
    assert _error_code(response) == "ROLE_FORBIDDEN"


def test_21_auth_disabled_admin_api_fails_closed(runtime):
    client = runtime["client"]
    _set_auth_enabled(False)
    _create_user(runtime, email="root@example.com", password="Password123456!", role="super_admin")

    response = client.get("/api/admin/users")

    assert response.status_code == 503
    assert _error_code(response) == "AUTH_DISABLED"
