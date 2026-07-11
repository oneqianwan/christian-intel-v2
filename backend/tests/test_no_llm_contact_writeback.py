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
    "services.contact_intelligence",
    "services.org_profile_scraper",
    "services.llm_contact_extractor",
    "crawlers.website_deep_crawler",
]


def _purge_modules() -> None:
    for module_name in MODULES_TO_PURGE:
        sys.modules.pop(module_name, None)


@pytest.fixture()
def isolated_runtime(tmp_path: Path):
    test_db_path = tmp_path / f"no_llm_contact_writeback_{uuid.uuid4().hex}.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{test_db_path.as_posix()}"
    _purge_modules()

    database = importlib.import_module("models.database")
    importlib.import_module("models.auth")
    importlib.import_module("models.watch_alert")
    contact_intelligence = importlib.import_module("services.contact_intelligence")
    org_profile_scraper = importlib.import_module("services.org_profile_scraper")
    llm_contact_extractor = importlib.import_module("services.llm_contact_extractor")
    website_deep_crawler = importlib.import_module("crawlers.website_deep_crawler")
    database.init_db()

    yield {
        "database": database,
        "contact_intelligence": contact_intelligence,
        "org_profile_scraper": org_profile_scraper,
        "llm_contact_extractor": llm_contact_extractor,
        "website_deep_crawler": website_deep_crawler,
        "db_path": test_db_path,
    }

    database.engine.dispose()
    _purge_modules()
    if test_db_path.exists():
        test_db_path.unlink()


def _seed_org(runtime, *, org_id: str, name: str, source_url: str | None = "https://victory.org.ph/about", contact_email: str | None = None):
    database = runtime["database"]
    db = database.SessionLocal()
    try:
        org = database.OrganizationProfile(
            id=org_id,
            name=name,
            country="Philippines",
            official_website="https://victory.org.ph",
            source_url=source_url,
            source_name="unit_test_seed",
            contact_email=contact_email,
        )
        db.add(org)
        db.commit()
        db.refresh(org)
        return org
    finally:
        db.close()


def test_llm_suggested_candidates_do_not_write_direct_fields(isolated_runtime, monkeypatch):
    runtime = isolated_runtime
    database = runtime["database"]
    contact_intelligence = runtime["contact_intelligence"]
    llm_contact_extractor = runtime["llm_contact_extractor"]

    _seed_org(runtime, org_id="org-victory-llm", name="Victory Philippines")

    monkeypatch.setattr(
        llm_contact_extractor,
        "extract_contacts_with_llm",
        lambda *_args, **_kwargs: pytest.fail("LLM contact extractor must not be called by writeback protection test"),
    )

    db = database.SessionLocal()
    try:
        org = db.query(database.OrganizationProfile).filter(database.OrganizationProfile.id == "org-victory-llm").first()
        result = contact_intelligence.apply_validated_contact_candidates_to_org(
            org,
            [
                {
                    "type": "email",
                    "value": "ceo@victory.org.ph",
                    "source_url": "https://victory.org.ph/about",
                    "source_name": "llm",
                    "extraction_method": "llm_suggested",
                    "source_context": "generic_page",
                },
                {
                    "type": "phone",
                    "value": "+63 2 9999 8888",
                    "source_url": "https://victory.org.ph/about",
                    "source_name": "llm",
                    "extraction_method": "llm_suggested",
                    "source_context": "generic_page",
                },
                {
                    "type": "social_profile",
                    "platform": "facebook",
                    "value": "https://facebook.com/victoryph",
                    "source_url": "https://victory.org.ph/about",
                    "source_name": "llm",
                    "extraction_method": "llm_suggested",
                    "source_context": "generic_page",
                },
            ],
            change_source="unit_test_writeback",
            changed_by="pytest",
            db=db,
        )
        db.commit()
        db.refresh(org)
    finally:
        db.close()

    assert result["updated_fields"] == []
    assert org.contact_email is None
    assert org.phone_public is None
    assert org.facebook_url is None


def test_low_confidence_generic_candidate_does_not_overwrite_existing_but_contact_page_can(isolated_runtime):
    runtime = isolated_runtime
    database = runtime["database"]
    contact_intelligence = runtime["contact_intelligence"]

    _seed_org(
        runtime,
        org_id="org-victory-overwrite",
        name="Victory Philippines",
        source_url="https://victory.org.ph/about",
        contact_email="old@victory.org.ph",
    )

    db = database.SessionLocal()
    try:
        org = db.query(database.OrganizationProfile).filter(database.OrganizationProfile.id == "org-victory-overwrite").first()

        generic_result = contact_intelligence.apply_validated_contact_candidates_to_org(
            org,
            [
                {
                    "type": "email",
                    "value": "generic@victory.org.ph",
                    "source_url": "https://victory.org.ph/about",
                    "source_name": "crawler",
                    "extraction_method": "regex",
                    "source_context": "generic_page",
                }
            ],
            change_source="unit_test_generic",
            changed_by="pytest",
            db=db,
        )
        db.commit()
        assert generic_result["updated_fields"] == []
        assert org.contact_email == "old@victory.org.ph"

        contact_result = contact_intelligence.apply_validated_contact_candidates_to_org(
            org,
            [
                {
                    "type": "email",
                    "value": "info@victory.org.ph",
                    "source_url": "https://victory.org.ph/contact",
                    "source_name": "crawler",
                    "extraction_method": "regex",
                    "source_context": "contact_page",
                }
            ],
            change_source="unit_test_contact_page",
            changed_by="pytest",
            db=db,
        )
        db.commit()
        db.refresh(org)
    finally:
        db.close()

    assert contact_result["updated_fields"] == ["contact_email"]
    assert org.contact_email == "info@victory.org.ph"

    db = database.SessionLocal()
    try:
        history_rows = (
            db.query(database.FieldChangeHistory)
            .filter(
                database.FieldChangeHistory.organization_id == "org-victory-overwrite",
                database.FieldChangeHistory.field_name == "contact_email",
            )
            .all()
        )
    finally:
        db.close()

    assert any("method=regex" in row.change_source for row in history_rows)
    assert any("context=contact_page" in row.change_source for row in history_rows)


def test_writeback_paths_ignore_raw_llm_contact_fields_and_only_accept_validated_rule_candidates(isolated_runtime, monkeypatch):
    runtime = isolated_runtime
    database = runtime["database"]
    org_profile_scraper = runtime["org_profile_scraper"]
    website_deep_crawler = runtime["website_deep_crawler"]
    llm_contact_extractor = runtime["llm_contact_extractor"]

    _seed_org(runtime, org_id="org-victory-save", name="Victory Philippines")

    monkeypatch.setattr(
        llm_contact_extractor,
        "extract_contacts_with_llm",
        lambda *_args, **_kwargs: pytest.fail("extract_contacts_with_llm must not be called"),
    )
    monkeypatch.setattr(
        website_deep_crawler,
        "call_llm",
        lambda *_args, **_kwargs: pytest.fail("call_llm must not be called"),
    )

    db = database.SessionLocal()
    try:
        website_deep_crawler.save_deep_data(
            "org-victory-save",
            "Victory Philippines",
            "https://victory.org.ph/about",
            {
                "description": "Example",
                "contact_email": "llm-guess@victory.org.ph",
                "contact_phone": "+63 2 7777 8888",
                "social_accounts": {"facebook": "https://facebook.com/llmguess"},
                "key_activities": [],
            },
            "This about page has no explicit contact information.",
            db,
        )
        org = db.query(database.OrganizationProfile).filter(database.OrganizationProfile.id == "org-victory-save").first()
        assert org.contact_email is None
        assert org.phone_public is None
        assert org.facebook_url is None

        result = org_profile_scraper.store_organization_profile(
            db,
            {"name": "Victory Philippines Store", "country": "Philippines", "website": "https://victory.org.ph", "leader_title_hint": []},
            {
                "status": "success",
                "data": {
                    "official_website": "https://victory.org.ph",
                    "contact_email": "llm-direct@victory.org.ph",
                    "phone_public": "+63 2 3333 4444",
                    "facebook_url": "https://facebook.com/llmdirect",
                    "contact_candidates": [
                        {
                            "type": "email",
                            "value": "llm-direct@victory.org.ph",
                            "source_url": "https://victory.org.ph/about",
                            "source_name": "llm",
                            "extraction_method": "llm_suggested",
                            "source_context": "generic_page",
                        }
                    ],
                },
            },
        )
        created = db.query(database.OrganizationProfile).filter(database.OrganizationProfile.id == result["id"]).first()
    finally:
        db.close()

    assert created.contact_email is None
    assert created.phone_public is None
    assert created.facebook_url is None
