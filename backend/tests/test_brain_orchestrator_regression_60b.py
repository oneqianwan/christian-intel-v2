from __future__ import annotations

import importlib
import os
import sys
import uuid
from pathlib import Path

import pytest


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
    "services.query_parser",
    "services.intent_router_final",
    "services.organization_resolver",
    "services.brain_orchestrator",
]


def _purge_modules() -> None:
    for module_name in MODULES_TO_PURGE:
        sys.modules.pop(module_name, None)


@pytest.fixture()
def orchestrator_runtime(tmp_path: Path):
    test_db_path = tmp_path / f"brain_orchestrator_reg60b_{uuid.uuid4().hex}.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{test_db_path.as_posix()}"
    _purge_modules()

    database = importlib.import_module("models.database")
    importlib.import_module("models.auth")
    importlib.import_module("models.watch_alert")
    orchestrator_module = importlib.import_module("services.brain_orchestrator")
    database.init_db()

    yield orchestrator_module

    database.engine.dispose()
    _purge_modules()
    if test_db_path.exists():
        test_db_path.unlink()


def test_phase60b_capabilities_do_not_regress(orchestrator_runtime):
    orchestrator = orchestrator_runtime.BrainOrchestrator()
    known_organizations = [
        {"id": "org-victory", "name": "Victory Philippines", "canonical_name": "Victory Philippines"},
        {"id": "org-alpha", "name": "Alpha Church", "canonical_name": "Alpha Church"},
    ]
    alias_map = {
        "Victory PH": "Victory Philippines",
        "Alpha": "Alpha Church",
    }

    standard = orchestrator.orchestrate("Contact info for Victory Philippines", known_organizations=known_organizations, alias_map=alias_map)
    alias = orchestrator.orchestrate("Victory PH 怎么联系", known_organizations=known_organizations, alias_map=alias_map)
    normalized = orchestrator.orchestrate("victory-philippines contact info", known_organizations=known_organizations, alias_map=alias_map)
    target = orchestrator.orchestrate(
        "Create an action plan for Victory Philippines to contact Alpha Church",
        known_organizations=known_organizations,
        alias_map=alias_map,
    )
    context_ref = orchestrator.orchestrate("this organization 怎么联系")
    missing_org = orchestrator.orchestrate("推荐合作对象有哪些？")

    assert standard["organization_name"] == "Victory Philippines"
    assert alias["organization_resolution"]["canonical_name"] == "Victory Philippines"
    assert alias["organization_resolution"]["candidates"][0]["match_type"] == "alias"
    assert normalized["organization_name"] == "Victory Philippines"
    assert target["organization_name"] == "Victory Philippines"
    assert target["target_organization_name"] == "Alpha Church"
    assert context_ref["route_status"] == "ask_clarification"
    assert context_ref["organization_resolution"]["context_reference"] is True
    assert missing_org["route_status"] == "ask_clarification"
    assert "organization_name" in missing_org["missing_parameters"]
    assert standard["intent_result"]["organization_name"] == "Victory Philippines"
    assert target["intent_result"]["target_organization_name"] == "Alpha Church"
