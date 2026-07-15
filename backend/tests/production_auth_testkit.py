from __future__ import annotations

import importlib
import os
import sys
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect as sa_inspect


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

MODULE_PREFIXES_TO_PURGE = (
    "config",
    "main",
    "models",
    "routers",
    "dependencies",
    "services.auth_service",
    "services.account_lifecycle",
    "services.chat_ownership",
)


def _purge_modules() -> None:
    for module_name in list(sys.modules):
        if any(module_name == prefix or module_name.startswith(f"{prefix}.") for prefix in MODULE_PREFIXES_TO_PURGE):
            sys.modules.pop(module_name, None)


def reset_runtime_state(runtime) -> None:
    database = runtime["database"]
    auth_models = runtime["auth_models"]
    auth_service = runtime["auth_service"]
    client = runtime["client"]
    settings = runtime["config"].settings
    db = database.SessionLocal()
    try:
        existing_tables = set(sa_inspect(database.engine).get_table_names())
        for model in (
            database.RequestTrace,
            database.Message,
            database.Conversation,
            database.Bookmark,
            database.UserFeedback,
            database.UserProfile,
            database.Alert,
            database.Signal,
            database.WatchRun,
            database.WatchTarget,
            database.IntelligenceItem,
            database.Page,
            database.Source,
            database.OrganizationProfile,
            auth_models.AccountToken,
            auth_models.AuthSession,
            auth_models.User,
        ):
            if getattr(model, "__tablename__", None) in existing_tables:
                db.query(model).delete()
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

    settings.APP_ENV = "production"
    settings.DEPLOYMENT_ENV = "production"
    settings.AUTH_COOKIE_SECURE = False
    settings.AUTH_COOKIE_SAMESITE = "lax"


@pytest.fixture(scope="module")
def runtime(tmp_path_factory: pytest.TempPathFactory):
    test_db_dir = tmp_path_factory.mktemp(f"production_auth_{uuid.uuid4().hex}")
    test_db_path = test_db_dir / "runtime.db"
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))
    importlib.invalidate_caches()
    os.environ["DATABASE_URL"] = f"sqlite:///{test_db_path.as_posix()}"
    os.environ["AUTH_CORS_ALLOW_ORIGINS"] = "http://127.0.0.1:4173"
    os.environ["AUTH_PASSWORD_TIME_COST"] = "1"
    os.environ["AUTH_PASSWORD_MEMORY_COST_KIB"] = "8192"
    os.environ["AUTH_PASSWORD_PARALLELISM"] = "1"
    os.environ["AUTH_PASSWORD_HASH_LEN"] = "16"
    os.environ["AUTH_PASSWORD_SALT_LEN"] = "16"
    os.environ["AUTH_LOGIN_MAX_ATTEMPTS"] = "3"
    os.environ["AUTH_LOGIN_WINDOW_SECONDS"] = "60"
    _purge_modules()

    config = importlib.import_module("config")
    database = importlib.import_module("models.database")
    auth_models = importlib.import_module("models.auth")
    importlib.import_module("models.watch_alert")
    importlib.import_module("dependencies.auth")
    importlib.import_module("dependencies.chat_auth")
    importlib.import_module("dependencies.watch_alert_auth")
    auth_service = importlib.import_module("services.auth_service")
    main = importlib.import_module("main")

    database.init_db()
    client_ctx = TestClient(main.app)
    client = client_ctx.__enter__()
    runtime = {
        "config": config,
        "database": database,
        "auth_models": auth_models,
        "auth_service": auth_service,
        "main": main,
        "client": client,
    }
    reset_runtime_state(runtime)

    yield runtime

    client_ctx.__exit__(None, None, None)
    database.engine.dispose()
    _purge_modules()
    if test_db_path.exists():
        test_db_path.unlink()
