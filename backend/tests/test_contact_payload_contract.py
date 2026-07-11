from __future__ import annotations

import importlib
import json
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
    "services.contact_intelligence",
]


def _purge_modules() -> None:
    for module_name in MODULES_TO_PURGE:
        sys.modules.pop(module_name, None)


@pytest.fixture()
def isolated_runtime(tmp_path: Path):
    test_db_path = tmp_path / f"contact_payload_{uuid.uuid4().hex}.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{test_db_path.as_posix()}"
    _purge_modules()

    database = importlib.import_module("models.database")
    importlib.import_module("models.auth")
    importlib.import_module("models.watch_alert")
    contact_intelligence = importlib.import_module("services.contact_intelligence")
    database.init_db()

    yield {
        "database": database,
        "contact_intelligence": contact_intelligence,
        "db_path": test_db_path,
    }

    database.engine.dispose()
    _purge_modules()
    if test_db_path.exists():
        test_db_path.unlink()


def _seed_org(
    runtime,
    *,
    org_id: str,
    name: str,
    official_website: str | None = "https://victory.org.ph",
    contact_email: str | None = "info@victory.org.ph",
    phone_public: str | None = "+63 2 1234 5678",
    facebook_url: str | None = "https://facebook.com/victoryph",
    youtube_url: str | None = "https://youtube.com/@victoryph",
    twitter_url: str | None = "https://twitter.com/victoryph",
    telegram_username: str | None = "victoryph",
    social_accounts_json: str | None = None,
    social_accounts: dict | None = None,
    source_url: str | None = "https://victory.org.ph/contact",
    source_name: str | None = "unit_test_seed",
    confidence: float | None = 0.83,
):
    database = runtime["database"]
    db = database.SessionLocal()
    try:
        org = database.OrganizationProfile(
            id=org_id,
            name=name,
            country="Philippines",
            official_website=official_website,
            contact_email=contact_email,
            phone_public=phone_public,
            facebook_url=facebook_url,
            youtube_url=youtube_url,
            twitter_url=twitter_url,
            telegram_username=telegram_username,
            social_accounts_json=social_accounts_json,
            social_accounts=social_accounts,
            source_url=source_url,
            source_name=source_name,
            confidence=confidence,
            has_contact=True,
        )
        db.add(org)
        db.commit()
        db.refresh(org)
        return org
    finally:
        db.close()


def test_build_organization_contact_payload_returns_contract_and_dedupes(isolated_runtime):
    runtime = isolated_runtime
    database = runtime["database"]
    contact_intelligence = runtime["contact_intelligence"]
    _seed_org(
        runtime,
        org_id="org-victory",
        name="Victory Philippines",
        social_accounts_json=json.dumps(
            {
                "facebook": "https://facebook.com/victoryph",
                "youtube": "youtube.com/@victoryph",
            }
        ),
        social_accounts={"telegram": "victoryph"},
    )

    db = database.SessionLocal()
    try:
        payload = contact_intelligence.build_organization_contact_payload(db=db, org_id="org-victory")
    finally:
        db.close()

    assert payload["found"] is True
    assert payload["organization"]["id"] == "org-victory"
    assert payload["organization"]["name"] == "Victory Philippines"
    assert payload["organization"]["organization_confidence"] == 0.83

    contacts = payload["contacts"]
    assert payload["summary"]["contact_count"] == len(contacts)
    assert payload["summary"]["website_count"] == 1
    assert payload["summary"]["email_count"] == 1
    assert payload["summary"]["phone_count"] == 1
    assert payload["summary"]["social_count"] == 4
    assert payload["summary"]["verified_count"] == 0
    assert payload["summary"]["outreach_candidate_count"] == 2
    assert payload["summary"]["missing_source_count"] == len(contacts)

    website = next(contact for contact in contacts if contact["type"] == "website")
    email = next(contact for contact in contacts if contact["type"] == "email")
    phone = next(contact for contact in contacts if contact["type"] == "phone")
    telegram = next(contact for contact in contacts if contact.get("platform") == "telegram")
    facebook_contacts = [contact for contact in contacts if contact.get("platform") == "facebook"]

    assert website["label"] == "Official website"
    assert website["normalized_value"] == "https://victory.org.ph"
    assert email["label"] == "Public email"
    assert email["normalized_value"] == "info@victory.org.ph"
    assert phone["label"] == "Public phone"
    assert "1234" in phone["normalized_value"]
    assert telegram["normalized_value"] == "https://t.me/victoryph"
    assert len(facebook_contacts) == 1

    for contact in contacts:
        assert contact["source_url"] == "https://victory.org.ph/contact"
        assert contact["source_name"] == "unit_test_seed"
        assert contact["confidence"] is None
        assert contact["is_verified"] is False
        assert contact["verification_status"] == "unverified"
        assert "field_level_source_missing" in contact["warnings"]
        assert "field_level_confidence_missing" in contact["warnings"]
        assert "field_level_verification_missing" in contact["warnings"]

    assert "field_level_source_not_available" in payload["warnings"]
    assert "field_level_confidence_not_available" in payload["warnings"]
    assert "field_level_verification_not_available" in payload["warnings"]
    assert len({(contact["type"], contact.get("platform"), contact["normalized_value"]) for contact in contacts}) == len(contacts)


def test_build_organization_contact_payload_filters_invalid_values_and_reports_empty_state(isolated_runtime):
    runtime = isolated_runtime
    database = runtime["database"]
    contact_intelligence = runtime["contact_intelligence"]
    _seed_org(
        runtime,
        org_id="org-invalid",
        name="Invalid Contacts Org",
        official_website="not-a-valid-url",
        contact_email="invalid-email",
        phone_public="abcd",
        facebook_url="bad social value",
        youtube_url=None,
        twitter_url=None,
        telegram_username="no spaces allowed here",
        social_accounts_json=json.dumps({"linkedin": "not valid"}),
        social_accounts=None,
        source_url=None,
        source_name=None,
        confidence=0.91,
    )

    db = database.SessionLocal()
    try:
        payload = contact_intelligence.build_organization_contact_payload(db=db, org_id="org-invalid")
    finally:
        db.close()

    assert payload["found"] is True
    assert payload["contacts"] == []
    assert payload["summary"]["contact_count"] == 0
    assert "invalid_email_format" in payload["warnings"]
    assert "invalid_phone_format" in payload["warnings"]
    assert "invalid_url_format" in payload["warnings"]
    assert "contact_missing" in payload["warnings"]
    assert payload["organization"]["organization_confidence"] == 0.91


def test_build_organization_contact_payload_returns_not_found_without_fabrication(isolated_runtime):
    runtime = isolated_runtime
    database = runtime["database"]
    contact_intelligence = runtime["contact_intelligence"]

    db = database.SessionLocal()
    try:
        payload = contact_intelligence.build_organization_contact_payload(db=db, org_id="org-missing")
    finally:
        db.close()

    assert payload["found"] is False
    assert payload["organization"] is None
    assert payload["contacts"] == []
    assert payload["summary"]["contact_count"] == 0
    assert payload["warnings"] == ["not_found"]
