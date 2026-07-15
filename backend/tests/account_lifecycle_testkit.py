from __future__ import annotations

from production_auth_testkit import reset_runtime_state, runtime


def set_production_auth_defaults(runtime) -> None:
    settings = runtime["config"].settings
    settings.APP_ENV = "production"
    settings.DEPLOYMENT_ENV = "production"
    settings.AUTH_V1_ENABLED = True
    settings.AUTH_COOKIE_REQUIRED = True
    settings.AUTH_COOKIE_SECURE = False
    settings.AUTH_COOKIE_SAMESITE = "lax"
    settings.CHAT_USER_OWNERSHIP_ENABLED = True
    settings.WATCH_ALERT_USER_OWNERSHIP_ENABLED = True
    settings.BOOKMARKS_USER_OWNERSHIP_ENABLED = True
    settings.FEEDBACK_USER_OWNERSHIP_ENABLED = True
    settings.ALLOW_PUBLIC_CORE_APIS = False
    settings.ALLOW_LEGACY_SESSION_ID = False
    settings.ALLOW_ANONYMOUS_FEEDBACK = False
    settings.WATCH_ALERT_V1_ENABLED = True
    settings.WATCH_ALERT_NOTIFICATIONS_ENABLED = True
    settings.WATCH_ALERT_SCHEDULER_ENABLED = True


def error_code(response) -> str | None:
    payload = response.json()
    detail = payload.get("detail")
    if isinstance(detail, dict):
        return detail.get("error_code")
    return payload.get("error_code")


def create_user(
    runtime,
    *,
    email: str,
    password: str,
    role: str = "viewer",
    status: str = "active",
    display_name: str = "User",
):
    database = runtime["database"]
    auth_models = runtime["auth_models"]
    auth_service = runtime["auth_service"]
    db = database.SessionLocal()
    try:
        user = auth_models.User(
            email=auth_service.normalize_email(email),
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


def login(client, *, email: str, password: str):
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return response


def set_test_mode(runtime) -> None:
    settings = runtime["config"].settings
    settings.APP_ENV = "test"
    settings.DEPLOYMENT_ENV = "test"
