from __future__ import annotations

import importlib
import socket
import sys
from pathlib import Path

import pytest


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _contact_module():
    return importlib.import_module("services.contact_intelligence")


def _structured_crawler_module():
    return importlib.import_module("services.structured_crawler")


def _website_deep_crawler_module():
    return importlib.import_module("crawlers.website_deep_crawler")


def test_build_contact_candidates_from_crawl_result_only_keeps_validated_candidates():
    contact_intelligence = _contact_module()

    candidates = contact_intelligence.build_contact_candidates_from_crawl_result(
        {
            "emails": ["info@victory.org.ph", "example@example.com", "noreply@victory.org.ph"],
            "phones": ["+63 2 1234 5678", "2026-07-11"],
            "social_accounts": {
                "facebook": "https://facebook.com/victoryph",
                "youtube": "https://youtube.com/@victoryph",
                "telegram": "@victoryph",
                "twitter": "https://twitter.com/intent/tweet?text=bad",
            },
            "source_url": "https://victory.org.ph/contact",
            "source_name": "structured_crawler",
            "source_context": "contact_page",
        },
        organization_url="https://victory.org.ph",
        extraction_method="regex",
    )

    normalized_values = {candidate["normalized_value"] for candidate in candidates}
    assert "info@victory.org.ph" in normalized_values
    assert "+63 2 1234 5678" in normalized_values
    assert "https://facebook.com/victoryph" in normalized_values
    assert "https://youtube.com/@victoryph" in normalized_values
    assert "https://t.me/victoryph" in normalized_values
    assert "example@example.com" not in normalized_values
    assert "https://twitter.com/intent/tweet?text=bad" not in normalized_values

    for candidate in candidates:
        assert candidate["verification_status"] == "unverified"
        assert candidate["is_verified"] is False


def test_missing_source_url_produces_warning_and_no_candidate_returns_empty():
    contact_intelligence = _contact_module()

    missing_source = contact_intelligence.build_contact_candidates_from_crawl_result(
        {
            "contact_email": "info@victory.org.ph",
            "source_url": None,
            "source_name": "crawler_without_source",
        },
        organization_url="https://victory.org.ph",
        extraction_method="regex",
    )
    no_candidate = contact_intelligence.build_contact_candidates_from_crawl_result(
        {
            "emails": [],
            "phones": [],
            "social_accounts": {},
            "source_url": "https://victory.org.ph/about",
        },
        organization_url="https://victory.org.ph",
        extraction_method="regex",
    )

    assert len(missing_source) == 1
    assert "source_url_missing" in missing_source[0]["warnings"]
    assert missing_source[0]["trusted_for_writeback"] is False
    assert no_candidate == []


def test_contact_page_candidate_is_preferred_and_generic_page_email_stays_unverified():
    contact_intelligence = _contact_module()

    candidates = contact_intelligence.dedupe_contact_candidates(
        [
            {
                "type": "email",
                "value": "info@victory.org.ph",
                "source_url": "https://victory.org.ph/about",
                "source_name": "generic",
                "source_context": "generic_page",
                "extraction_method": "regex",
            },
            {
                "type": "email",
                "value": "info@victory.org.ph",
                "source_url": "https://victory.org.ph/contact",
                "source_name": "contact",
                "source_context": "contact_page",
                "extraction_method": "regex",
            },
        ],
        organization_url="https://victory.org.ph",
    )

    assert len(candidates) == 1
    assert candidates[0]["source_context"] == "contact_page"
    assert candidates[0]["verification_status"] == "unverified"
    assert candidates[0]["is_verified"] is False


def test_structured_crawler_to_db_updates_uses_validated_contact_candidates():
    structured_crawler = _structured_crawler_module()

    report = structured_crawler.DeepCrawlReport(
        org_id="org-victory",
        org_name="Victory Philippines",
        base_url="https://victory.org.ph",
        pages_crawled=[
            structured_crawler.CrawlResult(
                page_type="contact",
                url="https://victory.org.ph/contact",
                html="""
                <html>
                  <body>
                    Contact us at info@victory.org.ph or noreply@victory.org.ph.
                    Call +63 (2) 1234-5678 today.
                    <a href="https://facebook.com/victoryph">Facebook</a>
                    <a href="https://facebook.com/sharer/sharer.php?u=https://victory.org.ph">Share</a>
                  </body>
                </html>
                """,
                status_code=200,
                text_content="Contact us at info@victory.org.ph or noreply@victory.org.ph. Call +63 (2) 1234-5678 today.",
                extracted_info={},
            )
        ],
        has_errors=False,
        error_log=[],
    )

    updates = report.to_db_updates()

    assert updates["has_contact"] is True
    assert updates["contact_email"] == "info@victory.org.ph"
    assert updates["phone_public"] == "+63 2 1234 5678"
    assert updates["facebook_url"] == "https://facebook.com/victoryph"


def test_pure_contact_extraction_does_not_call_network_or_llm(monkeypatch):
    contact_intelligence = _contact_module()
    website_deep_crawler = _website_deep_crawler_module()

    monkeypatch.setattr(
        socket,
        "create_connection",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("real network must not be used")),
    )
    monkeypatch.setattr(
        website_deep_crawler,
        "call_llm",
        lambda *_args, **_kwargs: pytest.fail("real LLM must not be used"),
    )

    candidates = contact_intelligence.extract_contact_candidates_from_text(
        "Email info@victory.org.ph and follow https://facebook.com/victoryph",
        source_url="https://victory.org.ph/contact",
        source_name="unit_test",
        organization_url="https://victory.org.ph",
        source_context="contact_page",
    )

    assert len(candidates) == 2
