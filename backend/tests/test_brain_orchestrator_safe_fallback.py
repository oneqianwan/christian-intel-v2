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
    test_db_path = tmp_path / f"brain_orchestrator_fallback_{uuid.uuid4().hex}.db"
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


def test_missing_organization_asks_for_clarification(orchestrator_runtime):
    orchestrator = orchestrator_runtime.BrainOrchestrator()
    result = orchestrator.orchestrate("推荐合作对象有哪些？")

    assert result["route_status"] == "ask_clarification"
    assert result["requires_clarification"] is True
    assert "organization_name" in result["missing_parameters"]
    assert "Victory Philippines" in (result["clarification_prompt"] or "")
    assert result["policy"]["allow_llm"] is False


def test_context_reference_asks_for_clarification(orchestrator_runtime):
    orchestrator = orchestrator_runtime.BrainOrchestrator()
    result = orchestrator.orchestrate("这个机构怎么联系？")

    assert result["route_status"] == "ask_clarification"
    assert result["requires_clarification"] is True
    assert result["organization_name"] is None
    assert result["organization_resolution"]["context_reference"] is True
    assert "context_reference_requires_previous_organization" in result["warnings"]


def test_ambiguous_organization_does_not_route_to_ready(orchestrator_runtime):
    orchestrator = orchestrator_runtime.BrainOrchestrator()
    result = orchestrator.orchestrate(
        "Victory 怎么联系？",
        known_organizations=[
            {"id": "org-victory-ph", "name": "Victory Philippines"},
            {"id": "org-victory-church", "name": "Victory Church"},
            {"id": "org-victory-outreach", "name": "Victory Outreach"},
        ],
    )

    assert result["route_status"] == "ambiguous"
    assert result["ambiguous"] is True
    assert result["dispatch"]["method"] is None
    assert len(result["candidate_organizations"]) >= 2
    assert "请选择" in (result["clarification_prompt"] or "")


def test_unsupported_query_stays_local_and_safe(orchestrator_runtime):
    orchestrator = orchestrator_runtime.BrainOrchestrator()
    result = orchestrator.orchestrate("随便帮我看看")

    assert result["route_status"] in {"unsupported", "ask_clarification"}
    assert result["dispatch"]["method"] is None
    assert result["policy"]["allow_llm"] is False
    assert result["policy"]["allow_network"] is False


def test_missing_target_does_not_block_non_target_lookup(orchestrator_runtime):
    orchestrator = orchestrator_runtime.BrainOrchestrator()
    result = orchestrator.orchestrate("Victory Philippines 怎么联系？")

    assert result["route_status"] == "ready"
    assert result["selected_module"] == "contact_intelligence"
    assert result["target_organization_name"] is None


def test_no_fabricated_organization_id(orchestrator_runtime):
    orchestrator = orchestrator_runtime.BrainOrchestrator()
    result = orchestrator.orchestrate("Contact info for Victory Philippines")

    org_resolution = result["organization_resolution"]
    assert org_resolution["organization_id"] is None
    assert org_resolution["candidates"][0]["organization_id"] is None
