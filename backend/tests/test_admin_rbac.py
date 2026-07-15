from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi import Body, Depends, FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from test_auth_api import _reset_auth_settings, runtime


_RUNTIME_CONFIG = None


class RoleProbeRequest(BaseModel):
    role: str | None = None


@pytest.fixture(autouse=True)
def reset_db(runtime):
    global _RUNTIME_CONFIG
    database = runtime["database"]
    auth_models = runtime["auth_models"]
    client = runtime["client"]
    auth_service = runtime["auth_service"]
    _RUNTIME_CONFIG = runtime["config"]

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


def _create_user(runtime, *, email: str, password: str, role: str = "viewer", status: str = "active"):
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


def _create_session_token(runtime, *, user):
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


def _build_rbac_app(runtime) -> FastAPI:
    from dependencies.auth import (
        get_current_user,
        require_admin,
        require_role,
        require_super_admin,
    )

    app = FastAPI()

    @app.get("/rbac/admin")
    def admin_probe(user=Depends(require_admin)):
        return {"role": str(user.role)}

    @app.get("/rbac/super-admin")
    def super_admin_probe(user=Depends(require_super_admin)):
        return {"role": str(user.role)}

    @app.get("/rbac/analyst")
    def analyst_probe(user=Depends(require_role("analyst"))):
        return {"role": str(user.role)}

    @app.get("/rbac/viewer")
    def viewer_probe(user=Depends(require_role("viewer"))):
        return {"role": str(user.role)}

    @app.post("/rbac/body-role")
    def body_role_probe(
        payload: RoleProbeRequest = Body(...),
        user=Depends(require_admin),
    ):
        return {"effective_role": str(user.role), "body_role": payload.role}

    return app


def test_01_super_admin_passes_require_super_admin(runtime):
    _set_auth_enabled(True)
    user = _create_user(runtime, email="root@example.com", password="Password123456!", role="super_admin")
    app = _build_rbac_app(runtime)

    with TestClient(app) as client:
        _set_cookie(runtime, client, _create_session_token(runtime, user=user))
        response = client.get("/rbac/super-admin")

    assert response.status_code == 200
    assert response.json()["role"] == "super_admin"


def test_02_admin_rejected_by_require_super_admin(runtime):
    _set_auth_enabled(True)
    user = _create_user(runtime, email="admin@example.com", password="Password123456!", role="admin")
    app = _build_rbac_app(runtime)

    with TestClient(app) as client:
        _set_cookie(runtime, client, _create_session_token(runtime, user=user))
        response = client.get("/rbac/super-admin")

    assert response.status_code == 403
    assert _error_code(response) == "ROLE_FORBIDDEN"


def test_03_super_admin_passes_require_admin(runtime):
    _set_auth_enabled(True)
    user = _create_user(runtime, email="root@example.com", password="Password123456!", role="super_admin")
    app = _build_rbac_app(runtime)

    with TestClient(app) as client:
        _set_cookie(runtime, client, _create_session_token(runtime, user=user))
        response = client.get("/rbac/admin")

    assert response.status_code == 200
    assert response.json()["role"] == "super_admin"


def test_04_admin_passes_require_admin(runtime):
    _set_auth_enabled(True)
    user = _create_user(runtime, email="admin@example.com", password="Password123456!", role="admin")
    app = _build_rbac_app(runtime)

    with TestClient(app) as client:
        _set_cookie(runtime, client, _create_session_token(runtime, user=user))
        response = client.get("/rbac/admin")

    assert response.status_code == 200
    assert response.json()["role"] == "admin"


def test_05_analyst_rejected_by_require_admin(runtime):
    _set_auth_enabled(True)
    user = _create_user(runtime, email="analyst@example.com", password="Password123456!", role="analyst")
    app = _build_rbac_app(runtime)

    with TestClient(app) as client:
        _set_cookie(runtime, client, _create_session_token(runtime, user=user))
        response = client.get("/rbac/admin")

    assert response.status_code == 403
    assert _error_code(response) == "ROLE_FORBIDDEN"


def test_06_viewer_rejected_by_require_admin(runtime):
    _set_auth_enabled(True)
    user = _create_user(runtime, email="viewer@example.com", password="Password123456!", role="viewer")
    app = _build_rbac_app(runtime)

    with TestClient(app) as client:
        _set_cookie(runtime, client, _create_session_token(runtime, user=user))
        response = client.get("/rbac/admin")

    assert response.status_code == 403
    assert _error_code(response) == "ROLE_FORBIDDEN"


def test_07_unauthenticated_returns_401(runtime):
    _set_auth_enabled(True)
    app = _build_rbac_app(runtime)

    with TestClient(app) as client:
        response = client.get("/rbac/admin")

    assert response.status_code == 401
    assert _error_code(response) == "AUTH_REQUIRED"


def test_08_invalid_session_returns_401(runtime):
    _set_auth_enabled(True)
    app = _build_rbac_app(runtime)

    with TestClient(app) as client:
        _set_cookie(runtime, client, "not-a-real-token")
        response = client.get("/rbac/admin")

    assert response.status_code == 401
    assert _error_code(response) == "INVALID_SESSION"


def test_09_disabled_user_rejected(runtime):
    _set_auth_enabled(True)
    user = _create_user(runtime, email="disabled@example.com", password="Password123456!", role="admin", status="disabled")
    app = _build_rbac_app(runtime)

    with TestClient(app) as client:
        _set_cookie(runtime, client, _create_session_token(runtime, user=user))
        response = client.get("/rbac/admin")

    assert response.status_code == 403
    assert _error_code(response) == "ACCOUNT_DISABLED"


def test_10_unknown_role_denied(runtime):
    _set_auth_enabled(True)
    from dependencies.auth import get_current_user

    app = _build_rbac_app(runtime)
    app.dependency_overrides[get_current_user] = lambda: type("FakeUser", (), {"role": "mystery"})()

    with TestClient(app) as client:
        response = client.get("/rbac/admin")

    assert response.status_code == 403
    assert _error_code(response) == "ROLE_FORBIDDEN"


def test_11_header_role_spoofing_is_ignored(runtime):
    _set_auth_enabled(True)
    user = _create_user(runtime, email="viewer@example.com", password="Password123456!", role="viewer")
    app = _build_rbac_app(runtime)

    with TestClient(app) as client:
        _set_cookie(runtime, client, _create_session_token(runtime, user=user))
        response = client.get(
            "/rbac/admin",
            headers={"x-user-id": "forged-user", "x-session-id": "forged-session", "x-role": "super_admin"},
        )

    assert response.status_code == 403
    assert _error_code(response) == "ROLE_FORBIDDEN"


def test_12_body_role_spoofing_is_ignored(runtime):
    _set_auth_enabled(True)
    user = _create_user(runtime, email="viewer@example.com", password="Password123456!", role="viewer")
    app = _build_rbac_app(runtime)

    with TestClient(app) as client:
        _set_cookie(runtime, client, _create_session_token(runtime, user=user))
        response = client.post(
            "/rbac/body-role",
            headers={"x-user-id": "forged-user"},
            json={"role": "super_admin"},
        )

    assert response.status_code == 403
    assert _error_code(response) == "ROLE_FORBIDDEN"


def test_13_require_role_analyst_is_exact(runtime):
    _set_auth_enabled(True)
    analyst = _create_user(runtime, email="analyst@example.com", password="Password123456!", role="analyst")
    admin = _create_user(runtime, email="admin@example.com", password="Password123456!", role="admin")
    app = _build_rbac_app(runtime)

    with TestClient(app) as client:
        _set_cookie(runtime, client, _create_session_token(runtime, user=analyst))
        analyst_response = client.get("/rbac/analyst")
        client.cookies.clear()
        _set_cookie(runtime, client, _create_session_token(runtime, user=admin))
        admin_response = client.get("/rbac/analyst")

    assert analyst_response.status_code == 200
    assert analyst_response.json()["role"] == "analyst"
    assert admin_response.status_code == 403
    assert _error_code(admin_response) == "ROLE_FORBIDDEN"


def test_14_require_role_viewer_is_exact(runtime):
    _set_auth_enabled(True)
    viewer = _create_user(runtime, email="viewer@example.com", password="Password123456!", role="viewer")
    super_admin = _create_user(runtime, email="root@example.com", password="Password123456!", role="super_admin")
    app = _build_rbac_app(runtime)

    with TestClient(app) as client:
        _set_cookie(runtime, client, _create_session_token(runtime, user=viewer))
        viewer_response = client.get("/rbac/viewer")
        client.cookies.clear()
        _set_cookie(runtime, client, _create_session_token(runtime, user=super_admin))
        super_admin_response = client.get("/rbac/viewer")

    assert viewer_response.status_code == 200
    assert viewer_response.json()["role"] == "viewer"
    assert super_admin_response.status_code == 403
    assert _error_code(super_admin_response) == "ROLE_FORBIDDEN"


def test_15_auth_disabled_rejects_rbac_dependency(runtime):
    _set_auth_enabled(False)
    user = _create_user(runtime, email="admin@example.com", password="Password123456!", role="admin")
    app = _build_rbac_app(runtime)

    with TestClient(app) as client:
        _set_cookie(runtime, client, _create_session_token(runtime, user=user))
        response = client.get("/rbac/admin")

    assert response.status_code == 503
    assert _error_code(response) == "AUTH_DISABLED"


def test_16_role_hierarchy_helper_is_explicit_and_denies_unknown():
    from dependencies.auth import role_at_least

    assert role_at_least("super_admin", "admin") is True
    assert role_at_least("admin", "viewer") is True
    assert role_at_least("viewer", "analyst") is False
    assert role_at_least("mystery", "viewer") is False
    assert role_at_least(None, "viewer") is False


def test_17_revoked_session_returns_401(runtime):
    _set_auth_enabled(True)
    user = _create_user(runtime, email="admin@example.com", password="Password123456!", role="admin")
    raw_token = _create_session_token(runtime, user=user)
    database = runtime["database"]
    auth_models = runtime["auth_models"]
    auth_service = runtime["auth_service"]
    app = _build_rbac_app(runtime)

    db = database.SessionLocal()
    try:
        session = (
            db.query(auth_models.AuthSession)
            .filter(auth_models.AuthSession.token_hash == auth_service.hash_session_token(raw_token))
            .one()
        )
        session.status = "revoked"
        session.revoked_at = datetime.utcnow()
        db.add(session)
        db.commit()
    finally:
        db.close()

    with TestClient(app) as client:
        _set_cookie(runtime, client, raw_token)
        response = client.get("/rbac/admin")

    assert response.status_code == 401
    assert _error_code(response) == "SESSION_REVOKED"


def test_18_expired_session_returns_401(runtime):
    _set_auth_enabled(True)
    user = _create_user(runtime, email="admin@example.com", password="Password123456!", role="admin")
    raw_token = _create_session_token(runtime, user=user)
    database = runtime["database"]
    auth_models = runtime["auth_models"]
    auth_service = runtime["auth_service"]
    app = _build_rbac_app(runtime)

    db = database.SessionLocal()
    try:
        session = (
            db.query(auth_models.AuthSession)
            .filter(auth_models.AuthSession.token_hash == auth_service.hash_session_token(raw_token))
            .one()
        )
        session.expires_at = datetime.utcnow() - timedelta(seconds=1)
        db.add(session)
        db.commit()
    finally:
        db.close()

    with TestClient(app) as client:
        _set_cookie(runtime, client, raw_token)
        response = client.get("/rbac/admin")

    assert response.status_code == 401
    assert _error_code(response) == "SESSION_EXPIRED"
