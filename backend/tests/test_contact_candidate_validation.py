from __future__ import annotations

import importlib
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _contact_module():
    return importlib.import_module("services.contact_intelligence")


def test_email_validation_accepts_mailto_and_marks_generic_webmaster():
    contact_intelligence = _contact_module()

    candidate = contact_intelligence.validate_contact_candidate(
        {
            "type": "email",
            "value": "mailto:webmaster@victory.org.ph?subject=Hello",
            "source_url": "https://victory.org.ph/contact",
            "source_name": "unit_test",
            "extraction_method": "regex",
            "source_context": "contact_page",
        }
    )

    assert candidate is not None
    assert candidate["normalized_value"] == "webmaster@victory.org.ph"
    assert "generic_email" in candidate["warnings"]
    assert candidate["verification_status"] == "unverified"
    assert candidate["is_verified"] is False


def test_email_validation_rejects_invalid_and_placeholder_emails():
    contact_intelligence = _contact_module()

    assert (
        contact_intelligence.validate_contact_candidate(
            {
                "type": "email",
                "value": "invalid-email",
                "source_url": "https://victory.org.ph/contact",
                "extraction_method": "regex",
            }
        )
        is None
    )
    assert (
        contact_intelligence.validate_contact_candidate(
            {
                "type": "email",
                "value": "example@example.com",
                "source_url": "https://victory.org.ph/contact",
                "extraction_method": "regex",
            }
        )
        is None
    )
    assert (
        contact_intelligence.validate_contact_candidate(
            {
                "type": "email",
                "value": "noreply@victory.org.ph",
                "source_url": "https://victory.org.ph/contact",
                "extraction_method": "regex",
            }
        )
        is None
    )


def test_phone_validation_accepts_valid_and_rejects_invalid_values():
    contact_intelligence = _contact_module()

    valid = contact_intelligence.validate_contact_candidate(
        {
            "type": "phone",
            "value": "+63 (2) 1234-5678",
            "source_url": "https://victory.org.ph/contact",
            "extraction_method": "regex",
            "source_context": "contact_page",
        }
    )
    invalid_date = contact_intelligence.validate_contact_candidate(
        {
            "type": "phone",
            "value": "2026-07-11",
            "source_url": "https://victory.org.ph/contact",
            "extraction_method": "regex",
        }
    )
    invalid_short = contact_intelligence.validate_contact_candidate(
        {
            "type": "phone",
            "value": "12345",
            "source_url": "https://victory.org.ph/contact",
            "extraction_method": "regex",
        }
    )

    assert valid is not None
    assert valid["normalized_value"] == "+63 2 1234 5678"
    assert invalid_date is None
    assert invalid_short is None


def test_social_url_validation_and_telegram_normalization():
    contact_intelligence = _contact_module()

    facebook = contact_intelligence.validate_contact_candidate(
        {
            "type": "social_profile",
            "platform": "facebook",
            "value": "https://facebook.com/victoryph",
            "source_url": "https://victory.org.ph/contact",
            "extraction_method": "link_parser",
        }
    )
    facebook_share = contact_intelligence.validate_contact_candidate(
        {
            "type": "social_profile",
            "platform": "facebook",
            "value": "https://facebook.com/sharer/sharer.php?u=https://victory.org.ph",
            "source_url": "https://victory.org.ph/contact",
            "extraction_method": "link_parser",
        }
    )
    telegram = contact_intelligence.validate_contact_candidate(
        {
            "type": "social_profile",
            "platform": "telegram",
            "value": "@victoryph",
            "source_url": "https://victory.org.ph/contact",
            "extraction_method": "regex",
        }
    )

    assert facebook is not None
    assert facebook["normalized_value"] == "https://facebook.com/victoryph"
    assert facebook_share is None
    assert telegram is not None
    assert telegram["normalized_value"] == "https://t.me/victoryph"
    assert telegram["value"] == "victoryph"


def test_duplicate_contacts_prefer_contact_page_over_generic_page():
    contact_intelligence = _contact_module()

    deduped = contact_intelligence.dedupe_contact_candidates(
        [
            {
                "type": "email",
                "value": "info@victory.org.ph",
                "source_url": "https://victory.org.ph/about",
                "source_name": "generic_page",
                "extraction_method": "regex",
                "source_context": "generic_page",
            },
            {
                "type": "email",
                "value": "info@victory.org.ph",
                "source_url": "https://victory.org.ph/contact",
                "source_name": "contact_page",
                "extraction_method": "regex",
                "source_context": "contact_page",
            },
        ],
        organization_url="https://victory.org.ph",
    )

    assert len(deduped) == 1
    assert deduped[0]["source_context"] == "contact_page"
    assert deduped[0]["source_url"] == "https://victory.org.ph/contact"


def test_llm_suggested_candidate_is_unverified_and_not_trusted():
    contact_intelligence = _contact_module()

    candidate = contact_intelligence.validate_contact_candidate(
        {
            "type": "email",
            "value": "contact@victory.org.ph",
            "source_url": "https://victory.org.ph/about",
            "source_name": "llm",
            "extraction_method": "llm_suggested",
            "source_context": "generic_page",
        }
    )

    assert candidate is not None
    assert candidate["verification_status"] == "unverified"
    assert candidate["is_verified"] is False
    assert candidate["trusted_for_writeback"] is False
    assert "llm_suggested" in candidate["warnings"]
    assert "review_needed" in candidate["warnings"]
