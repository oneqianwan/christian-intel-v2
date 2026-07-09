from __future__ import annotations

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.query_parser import QueryParser


def _parse_without_db(message: str):
    parser = QueryParser()
    try:
        parser._find_organization = lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("_find_organization should not be called in Phase 5.6A"))  # type: ignore[method-assign]
        return parser.parse(message)
    finally:
        parser.close()


def _assert_score_lookup(result, *, organization_name: str, requested_scores: list[str]) -> None:
    assert result is not None
    assert result["intent"] == "organization_score_lookup"
    assert result["organization_name"] == organization_name
    assert result["requested_scores"] == requested_scores
    assert result["response_contract"] == "score_lookup"
    assert result["data_found"] is False
    assert result["direct_answer"] is False
    assert result["requires_database_lookup"] is True


def test_score_query_chinese_all_scores():
    result = _parse_without_db("Victory Philippines 的评分是多少？")
    _assert_score_lookup(
        result,
        organization_name="Victory Philippines",
        requested_scores=["people_score", "digital_score", "intel_score"],
    )


def test_score_query_english_all_scores():
    result = _parse_without_db("Show me Victory Philippines scores")
    _assert_score_lookup(
        result,
        organization_name="Victory Philippines",
        requested_scores=["people_score", "digital_score", "intel_score"],
    )


def test_people_score_query():
    result = _parse_without_db("Victory Philippines people score?")
    _assert_score_lookup(
        result,
        organization_name="Victory Philippines",
        requested_scores=["people_score"],
    )


def test_digital_score_query():
    result = _parse_without_db("Victory Philippines digital score?")
    _assert_score_lookup(
        result,
        organization_name="Victory Philippines",
        requested_scores=["digital_score"],
    )


def test_intel_score_query():
    result = _parse_without_db("Victory Philippines intel score?")
    _assert_score_lookup(
        result,
        organization_name="Victory Philippines",
        requested_scores=["intel_score"],
    )


def test_mixed_language_score_query():
    result = _parse_without_db("请告诉我 Victory Philippines people score 是多少？")
    _assert_score_lookup(
        result,
        organization_name="Victory Philippines",
        requested_scores=["people_score"],
    )


def test_non_score_query_not_classified_as_score_lookup():
    examples = [
        "Tell me about Victory Philippines",
        "Victory Philippines latest news",
        "Victory Philippines website",
        "Victory Philippines pastors",
        "Victory Philippines locations",
    ]

    for message in examples:
        result = _parse_without_db(message)
        if result is None:
            continue
        assert result.get("intent") != "organization_score_lookup"


def test_organization_name_is_clean():
    result = _parse_without_db("请查询：Victory Philippines 的评分是多少？")
    _assert_score_lookup(
        result,
        organization_name="Victory Philippines",
        requested_scores=["people_score", "digital_score", "intel_score"],
    )


def test_composite_score_query():
    result = _parse_without_db("Victory Philippines overall score?")
    _assert_score_lookup(
        result,
        organization_name="Victory Philippines",
        requested_scores=["composite_score"],
    )
