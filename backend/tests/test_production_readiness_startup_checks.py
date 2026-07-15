from __future__ import annotations

import importlib
import json
import os
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


MODULES_TO_PURGE = [
    "config",
    "models",
    "models.database",
    "models.auth",
    "models.watch_alert",
    "services",
    "services.audit_trail",
    "services.observability",
    "services.response_contract",
    "services.production_readiness",
    "services.brain",
    "services.query_parser",
    "services.intent_router_final",
    "services.organization_resolver",
    "services.brain_orchestrator",
]


def _purge_modules() -> None:
    for module_name in MODULES_TO_PURGE:
        sys.modules.pop(module_name, None)


@pytest.fixture()
def startup_runtime(tmp_path: Path, monkeypatch):
    test_db_path = tmp_path / f"production_readiness_startup_{uuid.uuid4().hex}.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{test_db_path.as_posix()}")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")
    monkeypatch.delenv("DEBUG", raising=False)
    monkeypatch.delenv("FLASK_DEBUG", raising=False)
    monkeypatch.delenv("PYTHON_ENV", raising=False)
    _purge_modules()

    database = importlib.import_module("models.database")
    importlib.import_module("models.auth")
    importlib.import_module("models.watch_alert")
    config_module = importlib.import_module("config")
    brain_module = importlib.import_module("services.brain")
    importlib.import_module("services.query_parser")
    importlib.import_module("services.intent_router_final")
    importlib.import_module("services.organization_resolver")
    importlib.import_module("services.brain_orchestrator")
    importlib.import_module("services.response_contract")
    importlib.import_module("services.observability")
    importlib.import_module("services.audit_trail")
    readiness_module = importlib.import_module("services.production_readiness")
    database.init_db()

    yield {
        "database": database,
        "brain_module": brain_module,
        "config_module": config_module,
        "readiness_module": readiness_module,
    }

    database.engine.dispose()
    _purge_modules()
    if test_db_path.exists():
        test_db_path.unlink()


def test_startup_imports_are_available_and_llm_key_is_not_required(startup_runtime):
    checker = startup_runtime["readiness_module"].ProductionReadinessChecker()
    report = checker.build_report()

    assert startup_runtime["brain_module"].Brain is not None
    assert startup_runtime["config_module"].Settings().PROVIDER_CONFIG.provider == "deepseek"
    assert report["environment"]["backend_import_ok"] is True
    assert report["environment"]["database_config_ok"] is True
    assert report["environment"]["required_env_present"] is True
    assert report["environment"]["dangerous_debug_mode"] is False
    assert report["environment"]["account_token_storage_ok"] is True
    assert report["core_brain"]["intent_router_ok"] is True
    assert report["core_brain"]["organization_resolver_ok"] is True
    assert report["core_brain"]["brain_orchestrator_ok"] is True
    assert report["core_brain"]["response_contract_ok"] is True
    assert report["core_brain"]["observability_ok"] is True


def test_startup_report_omits_secret_values(startup_runtime, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "do-not-print-this-secret")
    checker = startup_runtime["readiness_module"].ProductionReadinessChecker()
    report = checker.build_report()
    serialized = json.dumps(report, ensure_ascii=False)

    assert "do-not-print-this-secret" not in serialized
    assert report["status"] in {"ready", "degraded", "blocked"}


def test_startup_report_detects_missing_account_tokens_table(startup_runtime):
    database = startup_runtime["database"]
    checker = startup_runtime["readiness_module"].ProductionReadinessChecker()

    with database.engine.begin() as conn:
        conn.execute(text("DROP TABLE account_tokens"))

    report = checker.build_report()

    assert report["environment"]["account_token_storage_ok"] is False
    assert "account_token_storage_missing" in report["errors"]
    assert report["status"] == "blocked"
