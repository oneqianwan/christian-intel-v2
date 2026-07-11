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
    "models",
    "models.database",
    "models.auth",
    "models.watch_alert",
    "services",
    "services.query_parser",
]


def _purge_modules() -> None:
    for module_name in MODULES_TO_PURGE:
        sys.modules.pop(module_name, None)


@pytest.fixture()
def parser_runtime(tmp_path: Path):
    test_db_path = tmp_path / f"query_parser_contact_{uuid.uuid4().hex}.db"
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


def test_chinese_contact_query_is_parsed(parser_runtime):
    parser = parser_runtime["query_parser"].QueryParser()
    try:
        parsed = parser.parse("Victory Philippines 怎么联系？", conversation_id="contact-zh")
    finally:
        parser.close()

    assert parsed["intent"] == "organization_contact_lookup"
    assert parsed["organization_name"] == "Victory Philippines"
    assert parsed["response_contract"] == "contact_lookup"
    assert parsed["requested_contacts"] == ["website", "email", "phone", "social"]


def test_english_contact_query_is_parsed_with_requested_field(parser_runtime):
    parser = parser_runtime["query_parser"].QueryParser()
    try:
        parsed = parser.parse("What is Victory Philippines website?", conversation_id="contact-en")
    finally:
        parser.close()

    assert parsed["intent"] == "organization_contact_lookup"
    assert parsed["organization_name"] == "Victory Philippines"
    assert parsed["response_contract"] == "contact_lookup"
    assert parsed["requested_contacts"] == ["website"]


def test_english_contact_information_query_defaults_to_all_contact_types(parser_runtime):
    parser = parser_runtime["query_parser"].QueryParser()
    try:
        parsed = parser.parse(
            "What is the contact information for Victory Philippines?",
            conversation_id="contact-en-all",
        )
    finally:
        parser.close()

    assert parsed["intent"] == "organization_contact_lookup"
    assert parsed["organization_name"] == "Victory Philippines"
    assert parsed["response_contract"] == "contact_lookup"
    assert parsed["requested_contacts"] == ["website", "email", "phone", "social"]


def test_english_phone_contact_query_is_parsed(parser_runtime):
    parser = parser_runtime["query_parser"].QueryParser()
    try:
        parsed = parser.parse("Does Victory Philippines have a phone number?", conversation_id="contact-phone")
    finally:
        parser.close()

    assert parsed["intent"] == "organization_contact_lookup"
    assert parsed["organization_name"] == "Victory Philippines"
    assert parsed["requested_contacts"] == ["phone"]


def test_contact_query_parser_parses_social_request(parser_runtime):
    parser = parser_runtime["query_parser"].QueryParser()
    try:
        parsed = parser.parse("Show me Victory Philippines social links", conversation_id="contact-social")
    finally:
        parser.close()

    assert parsed["intent"] == "organization_contact_lookup"
    assert parsed["organization_name"] == "Victory Philippines"
    assert parsed["requested_contacts"] == ["social"]


def test_chinese_contact_query_parses_email_request(parser_runtime):
    parser = parser_runtime["query_parser"].QueryParser()
    try:
        parsed = parser.parse("给我 Victory Philippines 的邮箱", conversation_id="contact-zh-email")
    finally:
        parser.close()

    assert parsed["intent"] == "organization_contact_lookup"
    assert parsed["organization_name"] == "Victory Philippines"
    assert parsed["requested_contacts"] == ["email"]


def test_chinese_contact_query_parses_social_request(parser_runtime):
    parser = parser_runtime["query_parser"].QueryParser()
    try:
        parsed = parser.parse("Victory Philippines 的社媒账号有哪些？", conversation_id="contact-zh-social")
    finally:
        parser.close()

    assert parsed["intent"] == "organization_contact_lookup"
    assert parsed["organization_name"] == "Victory Philippines"
    assert parsed["requested_contacts"] == ["social"]


def test_contact_query_parser_does_not_misclassify_score_query(parser_runtime):
    parser = parser_runtime["query_parser"].QueryParser()
    try:
        parsed = parser.parse("Victory Philippines 的评分是多少？", conversation_id="contact-score")
    finally:
        parser.close()

    assert parsed["intent"] == "organization_score_lookup"


def test_contact_query_parser_does_not_misclassify_graph_query(parser_runtime):
    parser = parser_runtime["query_parser"].QueryParser()
    try:
        parsed = parser.parse("Victory Philippines 有哪些合作方？", conversation_id="contact-graph")
    finally:
        parser.close()

    assert parsed["intent"] == "organization_relationship_graph_lookup"
