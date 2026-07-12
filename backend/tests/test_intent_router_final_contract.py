from __future__ import annotations

import importlib
import os
import socket
import sys
import uuid
from pathlib import Path

import httpx
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
    test_db_path = tmp_path / f"intent_router_contract_{uuid.uuid4().hex}.db"
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


def test_intent_result_contract_contains_confidence_candidates_and_reason_codes(parser_runtime, monkeypatch):
    monkeypatch.setattr(
        socket,
        "create_connection",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("real network must not be used")),
    )
    monkeypatch.setattr(
        httpx,
        "request",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("httpx.request must not be used")),
    )

    parser = parser_runtime["query_parser"].QueryParser()
    try:
        result = parser.parse_intent_final("Give me an evidence brief for Victory Philippines")
    finally:
        parser.close()

    assert result["intent"] == "organization_partnership_evidence_brief_lookup"
    assert result["intent_group"] == "evidence_brief"
    assert 0.0 <= result["confidence"] <= 1.0
    assert result["ambiguous"] is False
    assert len(result["candidate_intents"]) >= 1
    assert result["candidate_intents"][0]["intent"] == "organization_partnership_evidence_brief_lookup"
    assert result["candidate_intents"][0]["matched_signals"]
    assert result["organization_name"] == "Victory Philippines"
    assert result["reason_codes"]
    assert result["matched_keywords"]
    assert result["routing_decision"] == "direct"
    assert result["safe_default_intent"] == "organization_partnership_evidence_brief_lookup"


def test_missing_organization_name_returns_missing_parameters(parser_runtime):
    parser = parser_runtime["query_parser"].QueryParser()
    try:
        result = parser.parse_intent_final("推荐合作对象有哪些？")
    finally:
        parser.close()

    assert result["intent"] == "organization_partnership_recommendation_lookup"
    assert result["organization_name"] is None
    assert result["missing_parameters"] == ["organization_name"]
    assert result["routing_decision"] == "ask_clarification"
    assert "organization_name_missing" in result["warnings"]


def test_context_reference_requires_previous_organization(parser_runtime):
    parser = parser_runtime["query_parser"].QueryParser()
    try:
        result = parser.parse_intent_final("这个机构怎么联系？")
    finally:
        parser.close()

    assert result["organization_name"] is None
    assert result["missing_parameters"] == ["organization_context"]
    assert result["routing_decision"] == "ask_clarification"
    assert "context_reference_requires_previous_organization" in result["warnings"]
