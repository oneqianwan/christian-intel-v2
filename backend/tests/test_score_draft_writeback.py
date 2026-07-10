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
    "config",
    "main",
    "models",
    "models.database",
    "models.auth",
    "models.schemas",
    "routers",
    "routers.auth",
    "routers.chat",
    "routers.conversations",
    "dependencies",
    "dependencies.auth",
    "dependencies.chat_auth",
    "services",
    "services.auth_service",
    "services.brain",
    "services.brain_planner",
    "services.chat_ownership",
    "services.mission_service",
    "services.score_draft_service",
]


def _purge_modules() -> None:
    for module_name in MODULES_TO_PURGE:
        sys.modules.pop(module_name, None)


@pytest.fixture()
def isolated_runtime(tmp_path: Path):
    test_db_path = tmp_path / f"score_writeback_{uuid.uuid4().hex}.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{test_db_path.as_posix()}"
    _purge_modules()

    config = importlib.import_module("config")
    database = importlib.import_module("models.database")
    mission_service = importlib.import_module("services.mission_service")
    score_draft_service = importlib.import_module("services.score_draft_service")
    brain_module = importlib.import_module("services.brain")

    database.init_db()

    yield {
        "config": config,
        "database": database,
        "mission_service": mission_service,
        "score_draft_service": score_draft_service,
        "brain_module": brain_module,
        "db_path": test_db_path,
    }

    database.engine.dispose()
    _purge_modules()
    if test_db_path.exists():
        test_db_path.unlink()


def _seed_org(runtime, *, org_id: str, name: str, people_score=None, digital_score=None, intel_score=None):
    database = runtime["database"]
    db = database.SessionLocal()
    try:
        db.query(database.OrganizationProfile).filter(database.OrganizationProfile.name == name).delete()
        org = database.OrganizationProfile(
            id=org_id,
            name=name,
            country="Philippines",
            source_name="unit_test",
            official_website="https://example.com",
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


def _seed_completed_mission(runtime, *, mission_id: str, organization_name: str, score_draft: dict, status: str = "done"):
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
            "request_id": "req-writeback",
        },
        "collection_result": {
            "sources_checked": ["rss", "website"],
            "raw_items_count": 2,
            "collection_summary": "mock collection result",
        },
        "score_draft": score_draft,
    }
    db = database.SessionLocal()
    try:
        db.query(database.Mission).filter(database.Mission.id == mission_id).delete()
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


def _make_valid_score_draft(*, organization_name: str, mission_id: str, people_score=72, digital_score=65, intel_score=58):
    return {
        "organization_name": organization_name,
        "mission_id": mission_id,
        "score_draft": True,
        "writeback": False,
        "data_source": "collection_result",
        "people_score": people_score,
        "digital_score": digital_score,
        "intel_score": intel_score,
        "scoring_ready": True,
        "evidence_summary": "evidence ok",
        "requested_scores": ["people_score", "digital_score", "intel_score"],
        "scorer_versions": {"people": "mock", "digital": "mock", "intel": "mock"},
    }


def test_valid_completed_mission_score_draft_writes_back_to_profile(isolated_runtime):
    runtime = isolated_runtime
    database = runtime["database"]
    service = runtime["score_draft_service"]

    org_name = "Unknown Church"
    _seed_org(runtime, org_id="org-unknown", name=org_name)
    draft = _make_valid_score_draft(organization_name=org_name, mission_id="mission-writeback-1")
    _seed_completed_mission(runtime, mission_id="mission-writeback-1", organization_name=org_name, score_draft=draft, status="done")

    db = database.SessionLocal()
    try:
        result = service.writeback_score_draft(
            mission_id="mission-writeback-1",
            score_draft=draft,
            approved=True,
            writeback_reason="unit_test",
            db=db,
        )
        assert result["writeback"] is True
        assert result["status"] == "completed"
        assert result["organization_name"] == org_name
        assert result["scores_written"]["people_score"] == 72
        assert result["scores_written"]["digital_score"] == 65
        assert result["scores_written"]["intel_score"] == 58

        org = db.query(database.OrganizationProfile).filter(database.OrganizationProfile.name == org_name).first()
        assert org is not None
        assert org.people_score == 72
        assert org.digital_score == 65
        assert org.intel_score == 58
    finally:
        db.close()


def test_writeback_then_brain_score_lookup_reads_new_scores(isolated_runtime, monkeypatch):
    runtime = isolated_runtime
    database = runtime["database"]
    service = runtime["score_draft_service"]
    brain_module = runtime["brain_module"]

    org_name = "Unknown Church"
    _seed_org(runtime, org_id="org-unknown-2", name=org_name)
    draft = _make_valid_score_draft(organization_name=org_name, mission_id="mission-writeback-2")
    _seed_completed_mission(runtime, mission_id="mission-writeback-2", organization_name=org_name, score_draft=draft, status="done")

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

    db = database.SessionLocal()
    try:
        result = service.writeback_score_draft(
            mission_id="mission-writeback-2",
            score_draft=draft,
            approved=True,
            writeback_reason="unit_test",
            db=db,
        )
        assert result["writeback"] is True
    finally:
        db.close()

    brain = brain_module.Brain()
    lookup = brain._resolve_score_lookup_if_applicable(
        user_message="Unknown Church 的评分是多少？",
        conversation_id="phase57d-readback",
        route="simple",
    )
    assert lookup is not None
    assert "People Score: 72" in lookup["answer"]
    assert "Digital Score: 65" in lookup["answer"]
    assert "Intel Score: 58" in lookup["answer"]


def test_writeback_rejects_when_not_approved(isolated_runtime):
    runtime = isolated_runtime
    database = runtime["database"]
    service = runtime["score_draft_service"]

    org_name = "Unknown Church"
    _seed_org(runtime, org_id="org-unknown-3", name=org_name)
    draft = _make_valid_score_draft(organization_name=org_name, mission_id="mission-writeback-3")
    _seed_completed_mission(runtime, mission_id="mission-writeback-3", organization_name=org_name, score_draft=draft, status="done")

    db = database.SessionLocal()
    try:
        result = service.writeback_score_draft(
            mission_id="mission-writeback-3",
            score_draft=draft,
            approved=False,
            writeback_reason="unit_test",
            db=db,
        )
        assert result["writeback"] is False
        assert result["reason"] == "not_approved"
        org = db.query(database.OrganizationProfile).filter(database.OrganizationProfile.name == org_name).first()
        assert org is not None
        assert (org.people_score or 0) == 0
    finally:
        db.close()


def test_writeback_rejects_invalid_score_range(isolated_runtime):
    runtime = isolated_runtime
    database = runtime["database"]
    service = runtime["score_draft_service"]

    org_name = "Unknown Church"
    _seed_org(runtime, org_id="org-unknown-4", name=org_name)
    draft = _make_valid_score_draft(organization_name=org_name, mission_id="mission-writeback-4", people_score=999)
    _seed_completed_mission(runtime, mission_id="mission-writeback-4", organization_name=org_name, score_draft=draft, status="done")

    db = database.SessionLocal()
    try:
        result = service.writeback_score_draft(
            mission_id="mission-writeback-4",
            score_draft=draft,
            approved=True,
            writeback_reason="unit_test",
            db=db,
        )
        assert result["writeback"] is False
        assert result["reason"] == "invalid_score_range"
    finally:
        db.close()


def test_writeback_rejects_missing_evidence_summary(isolated_runtime):
    runtime = isolated_runtime
    database = runtime["database"]
    service = runtime["score_draft_service"]

    org_name = "Unknown Church"
    _seed_org(runtime, org_id="org-unknown-5", name=org_name)
    draft = _make_valid_score_draft(organization_name=org_name, mission_id="mission-writeback-5")
    draft["evidence_summary"] = ""
    _seed_completed_mission(runtime, mission_id="mission-writeback-5", organization_name=org_name, score_draft=draft, status="done")

    db = database.SessionLocal()
    try:
        result = service.writeback_score_draft(
            mission_id="mission-writeback-5",
            score_draft=draft,
            approved=True,
            writeback_reason="unit_test",
            db=db,
        )
        assert result["writeback"] is False
        assert result["reason"] == "missing_evidence"
    finally:
        db.close()


def test_writeback_rejects_non_completed_mission(isolated_runtime):
    runtime = isolated_runtime
    database = runtime["database"]
    service = runtime["score_draft_service"]

    org_name = "Unknown Church"
    _seed_org(runtime, org_id="org-unknown-6", name=org_name)
    draft = _make_valid_score_draft(organization_name=org_name, mission_id="mission-writeback-6")
    _seed_completed_mission(runtime, mission_id="mission-writeback-6", organization_name=org_name, score_draft=draft, status="queued")

    db = database.SessionLocal()
    try:
        result = service.writeback_score_draft(
            mission_id="mission-writeback-6",
            score_draft=draft,
            approved=True,
            writeback_reason="unit_test",
            db=db,
        )
        assert result["writeback"] is False
        assert result["reason"] == "mission_not_completed"
    finally:
        db.close()


def test_writeback_preserves_existing_scores_by_default(isolated_runtime):
    runtime = isolated_runtime
    database = runtime["database"]
    service = runtime["score_draft_service"]

    org_name = "Unknown Church"
    _seed_org(runtime, org_id="org-unknown-7", name=org_name, people_score=10, digital_score=11, intel_score=12)
    draft = _make_valid_score_draft(organization_name=org_name, mission_id="mission-writeback-7", people_score=72, digital_score=65, intel_score=58)
    _seed_completed_mission(runtime, mission_id="mission-writeback-7", organization_name=org_name, score_draft=draft, status="done")

    db = database.SessionLocal()
    try:
        result = service.writeback_score_draft(
            mission_id="mission-writeback-7",
            score_draft=draft,
            approved=True,
            writeback_reason="unit_test",
            preserve_existing=True,
            overwrite=False,
            db=db,
        )
        assert result["writeback"] is False
        assert result["reason"] == "existing_score_preserved"
        org = db.query(database.OrganizationProfile).filter(database.OrganizationProfile.name == org_name).first()
        assert org is not None
        assert org.people_score == 10
        assert org.digital_score == 11
        assert org.intel_score == 12
    finally:
        db.close()


def test_writeback_can_overwrite_only_when_explicit(isolated_runtime):
    runtime = isolated_runtime
    database = runtime["database"]
    service = runtime["score_draft_service"]

    org_name = "Unknown Church"
    _seed_org(runtime, org_id="org-unknown-8", name=org_name, people_score=10, digital_score=11, intel_score=12)
    draft = _make_valid_score_draft(organization_name=org_name, mission_id="mission-writeback-8", people_score=72, digital_score=65, intel_score=58)
    _seed_completed_mission(runtime, mission_id="mission-writeback-8", organization_name=org_name, score_draft=draft, status="done")

    db = database.SessionLocal()
    try:
        result = service.writeback_score_draft(
            mission_id="mission-writeback-8",
            score_draft=draft,
            approved=True,
            writeback_reason="unit_test_overwrite",
            preserve_existing=True,
            overwrite=True,
            db=db,
        )
        assert result["writeback"] is True
        assert result["overwrite"] is True
        org = db.query(database.OrganizationProfile).filter(database.OrganizationProfile.name == org_name).first()
        assert org is not None
        assert org.people_score == 72
        assert org.digital_score == 65
        assert org.intel_score == 58
    finally:
        db.close()


def test_writeback_does_not_call_llm(isolated_runtime, monkeypatch):
    runtime = isolated_runtime
    database = runtime["database"]
    service = runtime["score_draft_service"]
    brain_module = runtime["brain_module"]

    org_name = "Unknown Church"
    _seed_org(runtime, org_id="org-unknown-9", name=org_name)
    draft = _make_valid_score_draft(organization_name=org_name, mission_id="mission-writeback-9")
    _seed_completed_mission(runtime, mission_id="mission-writeback-9", organization_name=org_name, score_draft=draft, status="done")

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

    db = database.SessionLocal()
    try:
        result = service.writeback_score_draft(
            mission_id="mission-writeback-9",
            score_draft=draft,
            approved=True,
            writeback_reason="unit_test",
            db=db,
        )
        assert result["writeback"] is True
    finally:
        db.close()


def test_writeback_records_mission_id_data_source_reason(isolated_runtime):
    runtime = isolated_runtime
    database = runtime["database"]
    service = runtime["score_draft_service"]

    org_name = "Unknown Church"
    _seed_org(runtime, org_id="org-unknown-10", name=org_name)
    draft = _make_valid_score_draft(organization_name=org_name, mission_id="mission-writeback-10")
    _seed_completed_mission(runtime, mission_id="mission-writeback-10", organization_name=org_name, score_draft=draft, status="done")

    db = database.SessionLocal()
    try:
        result = service.writeback_score_draft(
            mission_id="mission-writeback-10",
            score_draft=draft,
            approved=True,
            writeback_reason="reason-123",
            db=db,
        )
        assert result["writeback"] is True
        assert result["mission_id"] == "mission-writeback-10"
        assert result["data_source"] == "collection_result"
        assert result["writeback_reason"] == "reason-123"

        org = db.query(database.OrganizationProfile).filter(database.OrganizationProfile.name == org_name).first()
        assert org is not None
        assert org.data_sources_json
        trail = json.loads(org.data_sources_json)
        assert isinstance(trail, list)
        last = trail[-1]
        assert last["mission_id"] == "mission-writeback-10"
        assert last["data_source"] == "collection_result"
        assert last["reason"] == "reason-123"
    finally:
        db.close()
