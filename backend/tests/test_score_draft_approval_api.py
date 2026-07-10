from __future__ import annotations

import importlib
import json
import os
import socket
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
    "routers.auth",
    "routers.admin",
    "dependencies",
    "dependencies.auth",
    "queue_client",
    "services",
    "services.auth_service",
    "services.brain",
    "services.mission_service",
    "services.score_draft_service",
]


def _purge_modules() -> None:
    for module_name in MODULES_TO_PURGE:
        sys.modules.pop(module_name, None)


@pytest.fixture()
def isolated_runtime(tmp_path: Path):
    test_db_path = tmp_path / f"score_draft_approval_{uuid.uuid4().hex}.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{test_db_path.as_posix()}"
    os.environ["AUTH_CORS_ALLOW_ORIGINS"] = "http://127.0.0.1:4173"
    os.environ["AUTH_PASSWORD_TIME_COST"] = "1"
    os.environ["AUTH_PASSWORD_MEMORY_COST_KIB"] = "8192"
    os.environ["AUTH_PASSWORD_PARALLELISM"] = "1"
    os.environ["AUTH_PASSWORD_HASH_LEN"] = "16"
    os.environ["AUTH_PASSWORD_SALT_LEN"] = "16"
    os.environ["AUTH_LOGIN_MAX_ATTEMPTS"] = "3"
    os.environ["AUTH_LOGIN_WINDOW_SECONDS"] = "60"
    _purge_modules()

    config = importlib.import_module("config")
    database = importlib.import_module("models.database")
    auth_models = importlib.import_module("models.auth")
    auth_service = importlib.import_module("services.auth_service")
    mission_service = importlib.import_module("services.mission_service")
    score_draft_service = importlib.import_module("services.score_draft_service")
    brain_module = importlib.import_module("services.brain")
    main = importlib.import_module("main")

    config.settings.AUTH_V1_ENABLED = True
    database.init_db()

    client_ctx = TestClient(main.app)
    client = client_ctx.__enter__()

    yield {
        "config": config,
        "database": database,
        "auth_models": auth_models,
        "auth_service": auth_service,
        "mission_service": mission_service,
        "score_draft_service": score_draft_service,
        "brain_module": brain_module,
        "client": client,
        "db_path": test_db_path,
    }

    client_ctx.__exit__(None, None, None)
    database.engine.dispose()
    _purge_modules()
    if test_db_path.exists():
        test_db_path.unlink()


@pytest.fixture(autouse=True)
def reset_state(isolated_runtime):
    runtime = isolated_runtime
    database = runtime["database"]
    auth_models = runtime["auth_models"]
    client = runtime["client"]

    client.cookies.clear()
    db = database.SessionLocal()
    try:
        db.query(database.Mission).delete()
        db.query(database.OrganizationProfile).delete()
        db.query(auth_models.AuthSession).delete()
        db.query(auth_models.User).delete()
        db.commit()
    finally:
        db.close()


def _error_code(response) -> str | None:
    payload = response.json()
    detail = payload.get("detail")
    if isinstance(detail, dict):
        return detail.get("error_code")
    return payload.get("error_code")


def _create_user(
    runtime,
    *,
    email: str,
    password: str,
    role: str,
    status: str = "active",
    display_name: str = "User",
):
    database = runtime["database"]
    auth_models = runtime["auth_models"]
    auth_service = runtime["auth_service"]
    db = database.SessionLocal()
    try:
        user = auth_models.User(
            email=email,
            email_normalized=auth_service.normalize_email(email),
            password_hash=auth_service.hash_password(password),
            display_name=display_name,
            role=role,
            status=status,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    finally:
        db.close()


def _authenticate_client(runtime, *, user) -> str:
    database = runtime["database"]
    auth_service = runtime["auth_service"]
    client = runtime["client"]
    config = runtime["config"]
    db = database.SessionLocal()
    try:
        _, raw_token = auth_service.create_auth_session(db, user=user)
    finally:
        db.close()
    client.cookies.set(
        config.settings.AUTH_COOKIE_NAME,
        raw_token,
        path=config.settings.AUTH_COOKIE_PATH,
    )
    return raw_token


def _seed_org(runtime, *, org_id: str, name: str, people_score=None, digital_score=None, intel_score=None):
    database = runtime["database"]
    db = database.SessionLocal()
    try:
        org = database.OrganizationProfile(
            id=org_id,
            name=name,
            country="Philippines",
            source_name="unit_test",
            official_website=f"https://{name.lower().replace(' ', '-')}.example.com",
        )
        if people_score is not None:
            org.people_score = people_score
        if digital_score is not None:
            org.digital_score = digital_score
        if intel_score is not None:
            org.intel_score = intel_score
        db.add(org)
        db.commit()
        db.refresh(org)
        return org
    finally:
        db.close()


def _seed_mission(
    runtime,
    *,
    mission_id: str,
    organization_name: str,
    status: str = "done",
    collection_summary: str = "mock collection result",
):
    database = runtime["database"]
    mission_service = runtime["mission_service"]
    payload = {
        "query": organization_name,
        "metadata": {
            "mission_type": "organization_score_data_collection",
            "organization_name": organization_name,
            "reason": "score_lookup_db_miss",
            "requested_scores": ["people_score", "digital_score", "intel_score"],
            "collection_targets": ["rss", "website"],
            "created_by": "brain_score_lookup",
            "request_id": "req-approval-api",
        },
        "collection_result": {
            "sources_checked": ["rss", "website"],
            "raw_items_count": 2,
            "collection_summary": collection_summary,
            "raw_items": [
                {"title": "About page", "source_type": "website"},
                {"title": "Recent news", "source_type": "rss"},
            ],
        },
    }
    db = database.SessionLocal()
    try:
        mission = database.Mission(
            id=mission_id,
            query=mission_service.MISSION_PAYLOAD_PREFIX + json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            country="全球",
            target_entity=organization_name,
            status=status,
            priority=5,
        )
        db.add(mission)
        db.commit()
        db.refresh(mission)
        return mission
    finally:
        db.close()


def _get_org(runtime, *, name: str):
    database = runtime["database"]
    db = database.SessionLocal()
    try:
        return db.query(database.OrganizationProfile).filter(database.OrganizationProfile.name == name).first()
    finally:
        db.close()


def _approval_path(mission_id: str) -> str:
    return f"/api/admin/score-drafts/{mission_id}/approve"


def _approval_payload(*, approved: bool = True, overwrite: bool = False, reason: str = "admin_approved_after_review") -> dict:
    return {
        "approved": approved,
        "writeback_reason": reason,
        "overwrite": overwrite,
    }


def _mock_scores(monkeypatch, runtime, *, people_score=72, digital_score=65, intel_score=58):
    score_draft_service = runtime["score_draft_service"]
    monkeypatch.setattr(
        score_draft_service,
        "_score_draft_runner_adapter",
        lambda *, scorer_input: {
            "people_score": people_score,
            "digital_score": digital_score,
            "intel_score": intel_score,
            "scoring_ready": True,
            "scorer_versions": {"people": "mock", "digital": "mock", "intel": "mock"},
        },
    )


def test_admin_can_approve_completed_mission_and_write_back(isolated_runtime, monkeypatch):
    runtime = isolated_runtime
    client = runtime["client"]
    score_draft_service = runtime["score_draft_service"]

    admin = _create_user(runtime, email="admin@example.com", password="Password123456!", role="admin")
    _authenticate_client(runtime, user=admin)
    _seed_org(runtime, org_id="org-approval-1", name="Approval Church")
    _seed_mission(runtime, mission_id="mission-approval-1", organization_name="Approval Church")
    _mock_scores(monkeypatch, runtime)

    called = {"value": False}
    original_writeback = score_draft_service.writeback_score_draft

    def _writeback_wrapper(**kwargs):
        called["value"] = True
        return original_writeback(**kwargs)

    monkeypatch.setattr(score_draft_service, "writeback_score_draft", _writeback_wrapper)

    response = client.post(_approval_path("mission-approval-1"), json=_approval_payload())

    assert response.status_code == 200
    payload = response.json()
    assert payload == {
        "success": True,
        "writeback": True,
        "mission_id": "mission-approval-1",
        "organization_name": "Approval Church",
        "scores_written": {"people_score": 72, "digital_score": 65, "intel_score": 58},
        "writeback_source": "admin_score_draft_approval_api",
        "writeback_reason": "admin_approved_after_review",
        "data_source": "collection_result",
        "reason": None,
    }
    assert called["value"] is True

    org = _get_org(runtime, name="Approval Church")
    assert org is not None
    assert org.people_score == 72
    assert org.digital_score == 65
    assert org.intel_score == 58


def test_approved_false_rejects_without_writeback(isolated_runtime, monkeypatch):
    runtime = isolated_runtime
    client = runtime["client"]
    score_draft_service = runtime["score_draft_service"]

    admin = _create_user(runtime, email="admin@example.com", password="Password123456!", role="admin")
    _authenticate_client(runtime, user=admin)
    _seed_org(runtime, org_id="org-approval-2", name="Approval Church")
    _seed_mission(runtime, mission_id="mission-approval-2", organization_name="Approval Church")

    monkeypatch.setattr(
        score_draft_service,
        "writeback_score_draft",
        lambda **_kwargs: pytest.fail("writeback_score_draft must not be called when approved=false"),
    )

    response = client.post(_approval_path("mission-approval-2"), json=_approval_payload(approved=False))

    assert response.status_code == 200
    assert response.json() == {
        "success": False,
        "writeback": False,
        "mission_id": None,
        "organization_name": None,
        "scores_written": None,
        "writeback_source": None,
        "writeback_reason": None,
        "data_source": None,
        "reason": "not_approved",
    }


def test_overwrite_defaults_false_and_preserves_existing_scores(isolated_runtime, monkeypatch):
    runtime = isolated_runtime
    client = runtime["client"]

    admin = _create_user(runtime, email="admin@example.com", password="Password123456!", role="admin")
    _authenticate_client(runtime, user=admin)
    _seed_org(runtime, org_id="org-approval-3", name="Existing Church", people_score=10, digital_score=11, intel_score=12)
    _seed_mission(runtime, mission_id="mission-approval-3", organization_name="Existing Church")
    _mock_scores(monkeypatch, runtime)

    response = client.post(_approval_path("mission-approval-3"), json=_approval_payload())

    assert response.status_code == 200
    assert response.json()["reason"] == "existing_score_preserved"

    org = _get_org(runtime, name="Existing Church")
    assert org is not None
    assert org.people_score == 10
    assert org.digital_score == 11
    assert org.intel_score == 12


def test_overwrite_true_explicitly_allows_replacing_existing_scores(isolated_runtime, monkeypatch):
    runtime = isolated_runtime
    client = runtime["client"]

    admin = _create_user(runtime, email="admin@example.com", password="Password123456!", role="admin")
    _authenticate_client(runtime, user=admin)
    _seed_org(runtime, org_id="org-approval-4", name="Overwrite Church", people_score=10, digital_score=11, intel_score=12)
    _seed_mission(runtime, mission_id="mission-approval-4", organization_name="Overwrite Church")
    _mock_scores(monkeypatch, runtime, people_score=81, digital_score=77, intel_score=69)

    response = client.post(_approval_path("mission-approval-4"), json=_approval_payload(overwrite=True))

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["writeback"] is True
    assert payload["scores_written"] == {"people_score": 81, "digital_score": 77, "intel_score": 69}

    org = _get_org(runtime, name="Overwrite Church")
    assert org is not None
    assert org.people_score == 81
    assert org.digital_score == 77
    assert org.intel_score == 69


def test_mission_not_completed_is_rejected(isolated_runtime, monkeypatch):
    runtime = isolated_runtime
    client = runtime["client"]
    score_draft_service = runtime["score_draft_service"]

    admin = _create_user(runtime, email="admin@example.com", password="Password123456!", role="admin")
    _authenticate_client(runtime, user=admin)
    _seed_org(runtime, org_id="org-approval-5", name="Queued Church")
    _seed_mission(runtime, mission_id="mission-approval-5", organization_name="Queued Church", status="queued")

    monkeypatch.setattr(
        score_draft_service,
        "create_score_draft_from_collection_result",
        lambda **_kwargs: pytest.fail("score draft rebuild must not run for non-completed mission"),
    )

    response = client.post(_approval_path("mission-approval-5"), json=_approval_payload())

    assert response.status_code == 200
    assert response.json()["reason"] == "mission_not_completed"


def test_missing_evidence_is_rejected(isolated_runtime, monkeypatch):
    runtime = isolated_runtime
    client = runtime["client"]
    score_draft_service = runtime["score_draft_service"]

    admin = _create_user(runtime, email="admin@example.com", password="Password123456!", role="admin")
    _authenticate_client(runtime, user=admin)
    _seed_org(runtime, org_id="org-approval-6", name="Evidence Church")
    _seed_mission(runtime, mission_id="mission-approval-6", organization_name="Evidence Church")

    monkeypatch.setattr(
        score_draft_service,
        "create_score_draft_from_collection_result",
        lambda **_kwargs: {
            "organization_name": "Evidence Church",
            "mission_id": "mission-approval-6",
            "score_draft": True,
            "writeback": False,
            "data_source": "collection_result",
            "people_score": 72,
            "digital_score": 65,
            "intel_score": 58,
            "scoring_ready": True,
            "evidence_summary": "",
            "requested_scores": ["people_score", "digital_score", "intel_score"],
            "scorer_versions": {"people": "mock", "digital": "mock", "intel": "mock"},
        },
    )

    response = client.post(_approval_path("mission-approval-6"), json=_approval_payload())

    assert response.status_code == 200
    assert response.json()["reason"] == "missing_evidence"


def test_organization_not_found_is_rejected(isolated_runtime, monkeypatch):
    runtime = isolated_runtime
    client = runtime["client"]

    admin = _create_user(runtime, email="admin@example.com", password="Password123456!", role="admin")
    _authenticate_client(runtime, user=admin)
    _seed_mission(runtime, mission_id="mission-approval-7", organization_name="Missing Church")
    _mock_scores(monkeypatch, runtime)

    response = client.post(_approval_path("mission-approval-7"), json=_approval_payload())

    assert response.status_code == 200
    assert response.json()["reason"] == "organization_not_found"


def test_approval_api_does_not_call_llm_or_real_network(isolated_runtime, monkeypatch):
    runtime = isolated_runtime
    client = runtime["client"]
    brain_module = runtime["brain_module"]

    admin = _create_user(runtime, email="admin@example.com", password="Password123456!", role="admin")
    _authenticate_client(runtime, user=admin)
    _seed_org(runtime, org_id="org-approval-8", name="Safe Church")
    _seed_mission(runtime, mission_id="mission-approval-8", organization_name="Safe Church")
    _mock_scores(monkeypatch, runtime)

    monkeypatch.setattr(
        brain_module.Brain,
        "_call_llm",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("_call_llm must not be called")),
    )
    monkeypatch.setattr(
        brain_module.Brain,
        "_call_llm_stream",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("_call_llm_stream must not be called")),
    )
    monkeypatch.setattr(
        socket,
        "create_connection",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("real network must not be used")),
    )

    response = client.post(_approval_path("mission-approval-8"), json=_approval_payload())

    assert response.status_code == 200
    assert response.json()["success"] is True


def test_non_admin_and_unauthenticated_cannot_approve(isolated_runtime, monkeypatch):
    runtime = isolated_runtime
    client = runtime["client"]

    _seed_org(runtime, org_id="org-approval-9", name="Protected Church")
    _seed_mission(runtime, mission_id="mission-approval-9", organization_name="Protected Church")
    _mock_scores(monkeypatch, runtime)

    unauthenticated = client.post(_approval_path("mission-approval-9"), json=_approval_payload())
    assert unauthenticated.status_code == 401
    assert _error_code(unauthenticated) == "AUTH_REQUIRED"

    analyst = _create_user(runtime, email="analyst@example.com", password="Password123456!", role="analyst")
    _authenticate_client(runtime, user=analyst)
    forbidden = client.post(_approval_path("mission-approval-9"), json=_approval_payload())
    assert forbidden.status_code == 403
    assert _error_code(forbidden) == "ROLE_FORBIDDEN"


def test_victory_philippines_existing_scores_are_preserved_by_default(isolated_runtime, monkeypatch):
    runtime = isolated_runtime
    client = runtime["client"]

    admin = _create_user(runtime, email="admin@example.com", password="Password123456!", role="admin")
    _authenticate_client(runtime, user=admin)
    _seed_org(
        runtime,
        org_id="org-victory",
        name="Victory Philippines",
        people_score=64,
        digital_score=28,
        intel_score=65,
    )
    _seed_mission(runtime, mission_id="mission-approval-10", organization_name="Victory Philippines")
    _mock_scores(monkeypatch, runtime, people_score=90, digital_score=91, intel_score=92)

    response = client.post(_approval_path("mission-approval-10"), json=_approval_payload())

    assert response.status_code == 200
    assert response.json()["reason"] == "existing_score_preserved"

    org = _get_org(runtime, name="Victory Philippines")
    assert org is not None
    assert org.people_score == 64
    assert org.digital_score == 28
    assert org.intel_score == 65
