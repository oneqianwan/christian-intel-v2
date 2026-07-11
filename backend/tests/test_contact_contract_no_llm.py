from __future__ import annotations

import importlib
import os
import socket
import sys
import uuid
from pathlib import Path

import pytest
import requests
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
    "services.brain",
    "services.contact_intelligence",
]


def _purge_modules() -> None:
    for module_name in MODULES_TO_PURGE:
        sys.modules.pop(module_name, None)


@pytest.fixture()
def isolated_runtime(tmp_path: Path):
    test_db_path = tmp_path / f"contact_contract_no_llm_{uuid.uuid4().hex}.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{test_db_path.as_posix()}"
    os.environ["AUTH_CORS_ALLOW_ORIGINS"] = "http://127.0.0.1:4173"
    _purge_modules()

    database = importlib.import_module("models.database")
    importlib.import_module("models.auth")
    brain_module = importlib.import_module("services.brain")
    contact_intelligence = importlib.import_module("services.contact_intelligence")
    main = importlib.import_module("main")
    database.init_db()

    client_ctx = TestClient(main.app)
    client = client_ctx.__enter__()

    yield {
        "database": database,
        "brain_module": brain_module,
        "contact_intelligence": contact_intelligence,
        "client": client,
        "db_path": test_db_path,
    }

    client_ctx.__exit__(None, None, None)
    database.engine.dispose()
    _purge_modules()
    if test_db_path.exists():
        test_db_path.unlink()


def _seed_org(runtime, *, org_id: str, name: str):
    database = runtime["database"]
    db = database.SessionLocal()
    try:
        org = database.OrganizationProfile(
            id=org_id,
            name=name,
            country="Philippines",
            official_website="https://victory.org.ph",
            contact_email="info@victory.org.ph",
            phone_public="+63 2 1234 5678",
            facebook_url="https://facebook.com/victoryph",
            source_url="https://victory.org.ph/contact",
            source_name="unit_test_seed",
            confidence=0.82,
        )
        db.add(org)
        db.commit()
        db.refresh(org)
        return org
    finally:
        db.close()


def test_contact_service_and_api_do_not_call_llm_or_real_network(isolated_runtime, monkeypatch):
    runtime = isolated_runtime
    database = runtime["database"]
    brain_module = runtime["brain_module"]
    contact_intelligence = runtime["contact_intelligence"]
    client = runtime["client"]

    _seed_org(runtime, org_id="org-victory", name="Victory Philippines")

    monkeypatch.setattr(
        brain_module.Brain,
        "_call_llm",
        lambda *_args, **_kwargs: pytest.fail("_call_llm must not be used by contact payload service or contact API"),
    )
    monkeypatch.setattr(
        brain_module.Brain,
        "_call_llm_stream",
        lambda *_args, **_kwargs: pytest.fail("_call_llm_stream must not be used by contact payload service or contact API"),
    )
    monkeypatch.setattr(
        socket,
        "create_connection",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("real network must not be used")),
    )
    monkeypatch.setattr(
        requests.sessions.Session,
        "request",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("HTTP request must not be used")),
    )

    db = database.SessionLocal()
    try:
        payload = contact_intelligence.build_organization_contact_payload(db=db, org_id="org-victory")
    finally:
        db.close()

    assert payload["found"] is True
    assert payload["summary"]["contact_count"] >= 3

    response = client.get("/api/dashboard/org/org-victory/contacts")
    assert response.status_code == 200
    assert response.json()["summary"]["contact_count"] >= 3
