import json
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from models.database import Mission, OrganizationProfile, SessionLocal
from services import mission_service


SCORE_DRAFT_MISSION_TYPE = mission_service.SCORE_COLLECTION_MISSION_TYPE


def _load_mission_by_id(session: Session, mission_id: str) -> Optional[Mission]:
    return session.query(Mission).filter(Mission.id == mission_id).first()


def _get_payload(mission: Mission) -> dict[str, Any]:
    query = str(getattr(mission, "query", "") or "")
    if not query.startswith(mission_service.MISSION_PAYLOAD_PREFIX):
        return {}
    try:
        parsed = json.loads(query[len(mission_service.MISSION_PAYLOAD_PREFIX) :])
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _store_payload(mission: Mission, payload: dict[str, Any]) -> bool:
    if not isinstance(payload, dict):
        return False
    query = str(getattr(mission, "query", "") or "")
    if not query.startswith(mission_service.MISSION_PAYLOAD_PREFIX):
        return False
    setattr(
        mission,
        "query",
        mission_service.MISSION_PAYLOAD_PREFIX
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
    )
    return True


def _score_draft_runner_adapter(*, scorer_input: dict[str, Any]) -> dict[str, Any]:
    return {
        "people_score": None,
        "digital_score": None,
        "intel_score": None,
        "scoring_ready": False,
        "scorer_versions": {
            "people": "unknown",
            "digital": "unknown",
            "intel": "unknown",
        },
    }


def create_score_draft_from_collection_result(
    *,
    mission_id: Optional[str] = None,
    mission: Optional[Mission] = None,
    db: Optional[Session] = None,
) -> dict[str, Any]:
    owns_session = db is None
    session = db or SessionLocal()
    try:
        target_mission = mission or (_load_mission_by_id(session, mission_id) if mission_id else None)
        if target_mission is None:
            return {"status": "skipped", "reason": "mission_not_found", "mission_id": mission_id}

        payload = _get_payload(target_mission)
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        mission_type = str(metadata.get("mission_type") or "").strip()
        if mission_type != SCORE_DRAFT_MISSION_TYPE:
            return {
                "status": "skipped",
                "reason": "unsupported_mission_type",
                "mission_id": str(getattr(target_mission, "id", "") or ""),
                "mission_type": mission_type or "unknown",
            }

        collection_result = payload.get("collection_result") if isinstance(payload.get("collection_result"), dict) else None
        normalized_status = str(getattr(target_mission, "status", "") or "").strip().lower()
        if normalized_status not in {"done", "completed"} or not collection_result:
            return {
                "status": "not_ready",
                "reason": "insufficient_collection_result",
                "mission_id": str(getattr(target_mission, "id", "") or ""),
                "organization_name": str(metadata.get("organization_name") or "") or str(payload.get("query") or ""),
            }

        organization_name = (
            str(metadata.get("organization_name") or "").strip()
            or str(getattr(target_mission, "target_entity", "") or "").strip()
            or str(payload.get("query") or "").strip()
        )
        requested_scores = list(metadata.get("requested_scores") or [])

        scorer_input = {
            "organization_name": organization_name,
            "mission_id": str(getattr(target_mission, "id", "") or ""),
            "requested_scores": requested_scores,
            "collection_result": collection_result,
        }
        scored = _score_draft_runner_adapter(scorer_input=scorer_input) or {}
        people_score = scored.get("people_score")
        digital_score = scored.get("digital_score")
        intel_score = scored.get("intel_score")
        scoring_ready = bool(scored.get("scoring_ready")) and all(
            isinstance(value, (int, float)) for value in [people_score, digital_score, intel_score]
        )
        evidence_summary = (
            str(collection_result.get("collection_summary") or "").strip()
            or f"Collection raw_items_count={int(collection_result.get('raw_items_count') or 0)}"
        )

        draft = {
            "status": "completed",
            "organization_name": organization_name,
            "mission_id": str(getattr(target_mission, "id", "") or ""),
            "score_draft": True,
            "writeback": False,
            "data_source": "collection_result",
            "people_score": people_score,
            "digital_score": digital_score,
            "intel_score": intel_score,
            "scoring_ready": scoring_ready,
            "evidence_summary": evidence_summary,
            "requested_scores": requested_scores,
            "scorer_versions": scored.get("scorer_versions")
            if isinstance(scored.get("scorer_versions"), dict)
            else {"people": "unknown", "digital": "unknown", "intel": "unknown"},
        }

        stored_payload = {**payload, "score_draft": {k: v for k, v in draft.items() if k != "status"}}
        if _store_payload(target_mission, stored_payload):
            setattr(target_mission, "updated_at", datetime.utcnow())
            session.commit()

        return draft
    finally:
        if owns_session:
            session.close()


def _normalize_score_number(value: Any) -> tuple[bool, Optional[int]]:
    if value is None:
        return True, None
    if isinstance(value, bool):
        return False, None
    try:
        number = float(value)
    except Exception:
        return False, None
    if number < 0 or number > 100:
        return False, None
    return True, int(round(number))


def _profile_has_existing_scores(profile: OrganizationProfile) -> bool:
    people_existing = bool(getattr(profile, "people_score_calculated_at", None)) or bool((profile.people_score or 0) > 0)
    digital_existing = bool(getattr(profile, "digital_score_calculated_at", None)) or bool((profile.digital_score or 0) > 0)
    intel_existing = bool(getattr(profile, "intel_score_calculated_at", None)) or bool((profile.intel_score or 0) > 0)
    return people_existing or digital_existing or intel_existing


def _resolve_unique_organization_profile(session: Session, organization_name: str) -> tuple[Optional[OrganizationProfile], str]:
    from sqlalchemy import func, or_

    normalized = (organization_name or "").strip()
    if not normalized:
        return None, "organization_not_found"
    lowered = normalized.lower()
    matches = (
        session.query(OrganizationProfile)
        .filter(
            or_(
                func.lower(OrganizationProfile.name) == lowered,
                func.lower(OrganizationProfile.name_local) == lowered,
                func.lower(OrganizationProfile.official_name) == lowered,
                func.lower(OrganizationProfile.short_name) == lowered,
                func.lower(OrganizationProfile.english_name) == lowered,
            )
        )
        .all()
    )
    if not matches:
        return None, "organization_not_found"
    if len(matches) != 1:
        return None, "ambiguous_organization"
    return matches[0], ""


def _append_writeback_trail(profile: OrganizationProfile, entry: dict[str, Any]) -> None:
    raw = getattr(profile, "data_sources_json", None)
    trail: list[dict[str, Any]] = []
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                trail = [item for item in parsed if isinstance(item, dict)]
        except Exception:
            trail = []
    trail.append(entry)
    profile.data_sources_json = json.dumps(trail[-20:], ensure_ascii=False, separators=(",", ":"))


def writeback_score_draft(
    *,
    mission_id: Optional[str] = None,
    mission: Optional[Mission] = None,
    score_draft: Optional[dict[str, Any]] = None,
    approved: bool = False,
    preserve_existing: bool = True,
    overwrite: bool = False,
    writeback_reason: Optional[str] = None,
    writeback_source: str = "score_draft_service",
    db: Optional[Session] = None,
) -> dict[str, Any]:
    owns_session = db is None
    session = db or SessionLocal()
    target_mission: Optional[Mission] = None
    organization_name = ""
    resolved_mission_id = None
    try:
        target_mission = mission or (_load_mission_by_id(session, mission_id) if mission_id else None)
        if target_mission is None:
            return {"writeback": False, "status": "rejected", "reason": "mission_not_found"}

        resolved_mission_id = str(getattr(target_mission, "id", "") or "")
        payload = _get_payload(target_mission)
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        mission_type = str(metadata.get("mission_type") or "").strip()
        if mission_type != SCORE_DRAFT_MISSION_TYPE:
            return {
                "writeback": False,
                "status": "rejected",
                "reason": "unsupported_mission_type",
                "mission_id": resolved_mission_id,
            }

        normalized_status = str(getattr(target_mission, "status", "") or "").strip().lower()
        if normalized_status not in {"done", "completed"}:
            return {
                "writeback": False,
                "status": "rejected",
                "reason": "mission_not_completed",
                "mission_id": resolved_mission_id,
            }

        collection_result = payload.get("collection_result") if isinstance(payload.get("collection_result"), dict) else None
        if not collection_result:
            return {
                "writeback": False,
                "status": "rejected",
                "reason": "insufficient_collection_result",
                "mission_id": resolved_mission_id,
            }

        stored_draft = payload.get("score_draft") if isinstance(payload.get("score_draft"), dict) else None
        effective_draft = score_draft if isinstance(score_draft, dict) else stored_draft
        if not isinstance(effective_draft, dict):
            return {
                "writeback": False,
                "status": "rejected",
                "reason": "missing_score_draft",
                "mission_id": resolved_mission_id,
            }

        if not approved:
            return {
                "writeback": False,
                "status": "rejected",
                "reason": "not_approved",
                "mission_id": resolved_mission_id,
            }

        if bool(effective_draft.get("writeback")) is not False:
            return {
                "writeback": False,
                "status": "rejected",
                "reason": "already_written",
                "mission_id": resolved_mission_id,
            }

        if str(effective_draft.get("data_source") or "").strip() != "collection_result":
            return {
                "writeback": False,
                "status": "rejected",
                "reason": "invalid_data_source",
                "mission_id": resolved_mission_id,
            }

        organization_name = (
            str(effective_draft.get("organization_name") or "").strip()
            or str(metadata.get("organization_name") or "").strip()
            or str(getattr(target_mission, "target_entity", "") or "").strip()
            or str(payload.get("query") or "").strip()
        )
        if not organization_name:
            return {
                "writeback": False,
                "status": "rejected",
                "reason": "organization_not_found",
                "mission_id": resolved_mission_id,
            }

        evidence_summary = str(effective_draft.get("evidence_summary") or "").strip()
        if not evidence_summary:
            return {
                "writeback": False,
                "status": "rejected",
                "reason": "missing_evidence",
                "mission_id": resolved_mission_id,
                "organization_name": organization_name,
            }

        requested_scores = effective_draft.get("requested_scores")
        if not isinstance(requested_scores, list):
            requested_scores = []
        required = {"people_score", "digital_score", "intel_score"}
        if not required.issubset(set(str(item) for item in requested_scores)):
            return {
                "writeback": False,
                "status": "rejected",
                "reason": "missing_requested_scores",
                "mission_id": resolved_mission_id,
                "organization_name": organization_name,
            }

        ok_people, people_score = _normalize_score_number(effective_draft.get("people_score"))
        ok_digital, digital_score = _normalize_score_number(effective_draft.get("digital_score"))
        ok_intel, intel_score = _normalize_score_number(effective_draft.get("intel_score"))
        if not (ok_people and ok_digital and ok_intel):
            return {
                "writeback": False,
                "status": "rejected",
                "reason": "invalid_score_range",
                "mission_id": resolved_mission_id,
                "organization_name": organization_name,
            }

        profile, resolve_reason = _resolve_unique_organization_profile(session, organization_name)
        if profile is None:
            return {
                "writeback": False,
                "status": "rejected",
                "reason": resolve_reason or "organization_not_found",
                "mission_id": resolved_mission_id,
                "organization_name": organization_name,
            }

        if preserve_existing and not overwrite and _profile_has_existing_scores(profile):
            session.rollback()
            return {
                "writeback": False,
                "status": "rejected",
                "reason": "existing_score_preserved",
                "mission_id": resolved_mission_id,
                "organization_name": organization_name,
            }

        now = datetime.utcnow()
        scores_written: dict[str, Any] = {}
        if people_score is not None:
            profile.people_score = int(people_score)
            profile.people_score_calculated_at = now
            scores_written["people_score"] = int(people_score)
        if digital_score is not None:
            profile.digital_score = int(digital_score)
            profile.digital_score_calculated_at = now
            scores_written["digital_score"] = int(digital_score)
        if intel_score is not None:
            profile.intel_score = int(intel_score)
            profile.intel_score_calculated_at = now
            scores_written["intel_score"] = int(intel_score)
        if not scores_written:
            session.rollback()
            return {
                "writeback": False,
                "status": "rejected",
                "reason": "insufficient_scores",
                "mission_id": resolved_mission_id,
                "organization_name": organization_name,
            }

        _append_writeback_trail(
            profile,
            {
                "source": "score_writeback",
                "writeback_source": writeback_source,
                "mission_id": resolved_mission_id,
                "data_source": "collection_result",
                "reason": str(writeback_reason or "").strip(),
                "overwrite": bool(overwrite),
                "at": now.isoformat(),
            },
        )

        profile.updated_at = now
        session.commit()
        return {
            "writeback": True,
            "status": "completed",
            "organization_name": organization_name,
            "organization_profile_id": str(getattr(profile, "id", "") or ""),
            "mission_id": resolved_mission_id,
            "scores_written": scores_written,
            "writeback_source": writeback_source,
            "writeback_reason": str(writeback_reason or "").strip(),
            "data_source": "collection_result",
            "overwrite": bool(overwrite),
        }
    except Exception:
        session.rollback()
        return {
            "writeback": False,
            "status": "rejected",
            "reason": "writeback_failed",
            "mission_id": resolved_mission_id,
            "organization_name": organization_name,
        }
    finally:
        if owns_session:
            session.close()
