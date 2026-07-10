import json
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from models.database import Mission, SessionLocal
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

