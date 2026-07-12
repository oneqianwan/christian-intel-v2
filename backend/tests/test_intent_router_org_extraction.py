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
    "services.intent_router_final",
    "services.query_parser",
]


def _purge_modules() -> None:
    for module_name in MODULES_TO_PURGE:
        sys.modules.pop(module_name, None)


@pytest.fixture()
def parser_runtime(tmp_path: Path):
    test_db_path = tmp_path / f"intent_router_org_extract_{uuid.uuid4().hex}.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{test_db_path.as_posix()}"
    _purge_modules()

    database = importlib.import_module("models.database")
    importlib.import_module("models.auth")
    importlib.import_module("models.watch_alert")
    query_parser = importlib.import_module("services.query_parser")
    database.init_db()

    yield {
        "database": database,
        "query_parser": query_parser,
        "db_path": test_db_path,
    }

    database.engine.dispose()
    _purge_modules()
    if test_db_path.exists():
        test_db_path.unlink()


def test_chinese_organization_name_extraction(parser_runtime):
    parser = parser_runtime["query_parser"].QueryParser()
    try:
        result = parser.parse_intent_final("给我 Victory Philippines 的联系方式")
    finally:
        parser.close()

    assert result["organization_name"] == "Victory Philippines"


def test_english_organization_name_extraction(parser_runtime):
    parser = parser_runtime["query_parser"].QueryParser()
    try:
        result = parser.parse_intent_final("What are the next steps for Victory Philippines?")
    finally:
        parser.close()

    assert result["organization_name"] == "Victory Philippines"


def test_target_organization_extraction(parser_runtime):
    parser = parser_runtime["query_parser"].QueryParser()
    try:
        zh_result = parser.parse_intent_final("给我 Victory Philippines 联系 Alpha Church 的行动计划")
        en_result = parser.parse_intent_final("Create an action plan for Victory Philippines to contact Alpha Church")
    finally:
        parser.close()

    assert zh_result["organization_name"] == "Victory Philippines"
    assert zh_result["target_organization_name"] == "Alpha Church"
    assert en_result["organization_name"] == "Victory Philippines"
    assert en_result["target_organization_name"] == "Alpha Church"


def test_context_reference_returns_warning_and_missing_parameter(parser_runtime):
    parser = parser_runtime["query_parser"].QueryParser()
    try:
        zh_result = parser.parse_intent_final("刚才那个机构的证据简报")
        en_result = parser.parse_intent_final("Contact info for this organization")
    finally:
        parser.close()

    assert zh_result["organization_name"] is None
    assert "context_reference_requires_previous_organization" in zh_result["warnings"]
    assert zh_result["missing_parameters"] == ["organization_context"]

    assert en_result["organization_name"] is None
    assert "context_reference_requires_previous_organization" in en_result["warnings"]
    assert en_result["missing_parameters"] == ["organization_context"]


def test_missing_org_returns_missing_parameters(parser_runtime):
    parser = parser_runtime["query_parser"].QueryParser()
    try:
        result = parser.parse_intent_final("Create an action plan")
    finally:
        parser.close()

    assert result["intent"] == "organization_partnership_action_plan_lookup"
    assert result["organization_name"] is None
    assert result["missing_parameters"] == ["organization_name"]
