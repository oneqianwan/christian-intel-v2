from __future__ import annotations

import importlib
import json
import os
import sys
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


MODULES_TO_PURGE = [
    "config",
    "main",
    "models",
    "models.database",
    "models.auth",
    "models.schemas",
    "routers",
    "routers.org_detail",
    "services",
    "services.contact_intelligence",
]


def _purge_modules() -> None:
    for module_name in MODULES_TO_PURGE:
        sys.modules.pop(module_name, None)


@pytest.fixture()
def isolated_runtime(tmp_path: Path):
    test_db_path = tmp_path / f"org_detail_contacts_{uuid.uuid4().hex}.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{test_db_path.as_posix()}"
    os.environ["AUTH_CORS_ALLOW_ORIGINS"] = "http://127.0.0.1:4173"
    _purge_modules()

    database = importlib.import_module("models.database")
    importlib.import_module("models.auth")
    main = importlib.import_module("main")
    database.init_db()

    client_ctx = TestClient(main.app)
    client = client_ctx.__enter__()

    yield {
        "database": database,
        "client": client,
        "db_path": test_db_path,
    }

    client_ctx.__exit__(None, None, None)
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
    twitter_url: str | None = None,
    telegram_username: str | None = "victoryph",
    social_accounts_json: str | None = json.dumps({"facebook": "https://facebook.com/victoryph"}),
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
            source_url="https://victory.org.ph/contact",
            source_name="unit_test_seed",
            confidence=0.8,
        )
        db.add(org)
        db.commit()
        db.refresh(org)
        return org
    finally:
        db.close()


def test_org_detail_contacts_api_returns_contact_payload(isolated_runtime):
    runtime = isolated_runtime
    client = runtime["client"]
    _seed_org(runtime, org_id="org-victory", name="Victory Philippines")

    response = client.get("/api/dashboard/org/org-victory/contacts")
    assert response.status_code == 200

    payload = response.json()
    assert payload["found"] is True
    assert payload["organization"]["id"] == "org-victory"
    assert payload["organization"]["name"] == "Victory Philippines"
    assert payload["summary"]["website_count"] == 1
    assert payload["summary"]["email_count"] == 1
    assert payload["summary"]["phone_count"] == 1
    assert payload["summary"]["social_count"] == 3
    assert any(contact["type"] == "website" for contact in payload["contacts"])
    assert any(contact["type"] == "email" for contact in payload["contacts"])
    assert any(contact["type"] == "phone" for contact in payload["contacts"])
    assert any(contact["type"] == "social_profile" for contact in payload["contacts"])
    assert "field_level_source_not_available" in payload["warnings"]
    assert all(contact["is_verified"] is False for contact in payload["contacts"])


def test_org_detail_contacts_api_returns_empty_payload_without_fabrication(isolated_runtime):
    runtime = isolated_runtime
    client = runtime["client"]
    _seed_org(
        runtime,
        org_id="org-empty",
        name="Empty Org",
        official_website=None,
        contact_email=None,
        phone_public=None,
        facebook_url=None,
        youtube_url=None,
        twitter_url=None,
        telegram_username=None,
        social_accounts_json=None,
    )

    response = client.get("/api/dashboard/org/org-empty/contacts")
    assert response.status_code == 200

    payload = response.json()
    assert payload["found"] is True
    assert payload["contacts"] == []
    assert payload["summary"]["contact_count"] == 0
    assert "contact_missing" in payload["warnings"]


def test_org_detail_contacts_api_returns_404_for_missing_org(isolated_runtime):
    runtime = isolated_runtime
    client = runtime["client"]

    response = client.get("/api/dashboard/org/org-missing/contacts")
    assert response.status_code == 404
    assert response.json()["detail"] == "Organization not found"
