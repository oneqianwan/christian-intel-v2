from __future__ import annotations

import importlib
import os
import sys
import uuid
from pathlib import Path


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


def _build_parser(tmp_path: Path):
    test_db_path = tmp_path / f"query_parser_graph_{uuid.uuid4().hex}.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{test_db_path.as_posix()}"
    _purge_modules()
    database = importlib.import_module("models.database")
    importlib.import_module("models.auth")
    importlib.import_module("models.watch_alert")
    query_parser_module = importlib.import_module("services.query_parser")
    database.init_db()
    parser = query_parser_module.QueryParser()
    return database, parser, test_db_path


def test_chinese_relationship_graph_query_is_parsed(tmp_path: Path):
    database, parser, test_db_path = _build_parser(tmp_path)
    try:
        parsed = parser.parse("说明 Victory Philippines 的关系网络", conversation_id="graph-zh")
        assert parsed is not None
        assert parsed["intent"] == "organization_relationship_graph_lookup"
        assert parsed["organization_name"] == "Victory Philippines"
        assert parsed["response_contract"] == "relationship_graph"
        assert parsed["depth"] == 1
        assert parsed["include_unverified"] is False
    finally:
        parser.close()
        database.engine.dispose()
        _purge_modules()
        if test_db_path.exists():
            test_db_path.unlink()


def test_english_relationship_graph_query_is_parsed(tmp_path: Path):
    database, parser, test_db_path = _build_parser(tmp_path)
    try:
        parsed = parser.parse("Show me the relationship graph of Victory Philippines", conversation_id="graph-en")
        assert parsed is not None
        assert parsed["intent"] == "organization_relationship_graph_lookup"
        assert parsed["organization_name"] == "Victory Philippines"
        assert parsed["response_contract"] == "relationship_graph"
        assert parsed["depth"] == 1
        assert parsed["include_unverified"] is False
    finally:
        parser.close()
        database.engine.dispose()
        _purge_modules()
        if test_db_path.exists():
            test_db_path.unlink()


def test_relationship_graph_parser_does_not_misclassify_score_query(tmp_path: Path):
    database, parser, test_db_path = _build_parser(tmp_path)
    try:
        parsed = parser.parse("Victory Philippines 的评分是多少？", conversation_id="score")
        assert parsed is not None
        assert parsed["intent"] == "organization_score_lookup"
        assert parsed["response_contract"] == "score_lookup"
    finally:
        parser.close()
        database.engine.dispose()
        _purge_modules()
        if test_db_path.exists():
            test_db_path.unlink()


def test_relationship_graph_parser_does_not_misclassify_contact_query(tmp_path: Path):
    database, parser, test_db_path = _build_parser(tmp_path)
    try:
        db = database.SessionLocal()
        try:
            db.add(
                database.OrganizationProfile(
                    id="org-victory-contact",
                    name="Victory Philippines",
                    country="Philippines",
                    source_name="manual_seed",
                    official_website="https://victory.org.ph",
                    contact_email="hello@victory.org.ph",
                    phone_public="+63-2-0000-0000",
                    leader_name="Leader",
                    leader_title="Pastor",
                )
            )
            db.commit()
        finally:
            db.close()
        parsed = parser.parse("Victory Philippines 的联系方式是什么？", conversation_id="contact")
        assert parsed is not None
        answer = str(parsed.get("answer") or parsed.get("response") or "")
        assert parsed.get("direct_answer") is True
        assert "Victory Philippines" in answer
        assert "relationship_graph" not in answer
    finally:
        parser.close()
        database.engine.dispose()
        _purge_modules()
        if test_db_path.exists():
            test_db_path.unlink()
