import hashlib
import json
import uuid
from datetime import datetime
from typing import Any, Optional

import redis
from sqlalchemy.orm import Session

from models.database import Mission, SessionLocal
from queue_client import DEFAULT_COLLECTION_PRIORITY, REDIS_URL, enqueue_collection_mission

MISSION_PAYLOAD_PREFIX = "__mission_payload__:"
MISSION_CREATE_LOCK_TTL_SECONDS = 10
SCORE_COLLECTION_MISSION_TYPE = "organization_score_data_collection"
DEFAULT_SCORE_COLLECTION_TARGETS = ["rss", "website"]
MISSION_CREATE_LOCK_RELEASE_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
end
return 0
"""


def _build_query_payload(
    *,
    query: str,
    source: Optional[str] = None,
    keywords: Optional[list[str]] = None,
    limit_per_keyword: Optional[int] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> str:
    payload = {
        "query": query,
        "source": source,
        "keywords": keywords or [],
        "limit_per_keyword": limit_per_keyword,
        "metadata": metadata or {},
    }
    if not source and not payload["keywords"] and limit_per_keyword is None and not payload["metadata"]:
        return query
    return MISSION_PAYLOAD_PREFIX + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _get_mission_lock_redis_client():
    return redis.from_url(REDIS_URL, decode_responses=True)


def _parse_mission_payload(query: str) -> dict[str, Any]:
    if not query or not query.startswith(MISSION_PAYLOAD_PREFIX):
        return {}
    try:
        return json.loads(query[len(MISSION_PAYLOAD_PREFIX) :])
    except Exception:
        return {}


def _load_mission_by_id(session: Session, mission_id: str) -> Optional[Mission]:
    return session.query(Mission).filter(Mission.id == mission_id).first()


def _get_mission_metadata(mission: Mission) -> dict[str, Any]:
    payload = _parse_mission_payload(mission.query or "")
    metadata = payload.get("metadata") or {}
    if isinstance(metadata, dict):
        return metadata
    return {}


def _get_mission_payload(mission: Mission) -> dict[str, Any]:
    payload = _parse_mission_payload(mission.query or "")
    return payload if isinstance(payload, dict) else {}


def _normalize_collection_targets(payload: dict[str, Any], metadata: dict[str, Any]) -> list[str]:
    raw_targets = metadata.get("collection_targets") or payload.get("collection_targets") or []
    normalized: list[str] = []
    for value in raw_targets:
        item = str(value or "").strip().lower()
        if item in {"page", "website", "webpage", "news_page"}:
            item = "website"
        elif item in {"rss", "rss_global"}:
            item = "rss"
        elif item in {"youtube", "youtube_channel"}:
            item = "youtube"
        elif item in {"telegram", "telegram_channel"}:
            item = "telegram"
        if item and item not in normalized:
            normalized.append(item)
    return normalized or list(DEFAULT_SCORE_COLLECTION_TARGETS)


def _sanitize_dispatch_error(exc: Exception) -> str:
    message = str(exc or "").strip()[:300]
    lowered = message.lower()
    if any(token in lowered for token in ["password", "token", "api_key", "authorization"]):
        return "collector dispatch failed"
    return message or "collector dispatch failed"


def _dispatch_collection_runner_adapter(*, mission: Mission, payload: dict[str, Any]) -> Optional[dict[str, Any]]:
    from services.mission_runner import run_mission

    run_mission(mission.id)
    return None


def dispatch_collection_mission(
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
            return {
                "status": "skipped",
                "reason": "mission_not_found",
                "mission_id": mission_id,
            }

        payload = _get_mission_payload(target_mission)
        metadata = _get_mission_metadata(target_mission)
        mission_type = str(metadata.get("mission_type") or "").strip()
        if mission_type != SCORE_COLLECTION_MISSION_TYPE:
            return {
                "status": "skipped",
                "reason": "unsupported_mission_type",
                "mission_id": target_mission.id,
                "mission_type": mission_type or "unknown",
            }

        organization_name = (
            str(metadata.get("organization_name") or "").strip()
            or str(getattr(target_mission, "target_entity", "") or "").strip()
            or str(payload.get("query") or "").strip()
        )
        requested_scores = list(metadata.get("requested_scores") or [])
        collection_targets = _normalize_collection_targets(payload, metadata)

        target_mission.status = "running"
        target_mission.updated_at = datetime.utcnow()
        session.commit()

        try:
            adapter_result = _dispatch_collection_runner_adapter(mission=target_mission, payload=payload)
            session.refresh(target_mission)
            if adapter_result is None:
                adapter_status = "completed" if target_mission.status in {"done", "completed"} else "failed"
                adapter_result = {
                    "status": adapter_status,
                    "sources_checked": collection_targets,
                    "raw_items_count": 0,
                    "collection_summary": f"Mission runner finished with status={target_mission.status}",
                    "scoring_ready": False,
                }
            else:
                result_status = str(adapter_result.get("status") or "").strip().lower()
                target_mission.status = "done" if result_status in {"success", "no_change", "completed", "done"} else "failed"
                target_mission.updated_at = datetime.utcnow()
                session.commit()

            normalized_status = "completed" if target_mission.status in {"done", "completed"} else "failed"
            return {
                "mission_id": target_mission.id,
                "organization_name": organization_name,
                "mission_type": mission_type,
                "status": normalized_status,
                "sources_checked": list(adapter_result.get("sources_checked") or collection_targets),
                "raw_items_count": int(adapter_result.get("raw_items_count") or 0),
                "collection_summary": str(
                    adapter_result.get("collection_summary")
                    or f"Collection dispatch {normalized_status}"
                ),
                "requested_scores": requested_scores,
                "scoring_ready": False,
            }
        except Exception as exc:
            target_mission.status = "failed"
            target_mission.updated_at = datetime.utcnow()
            session.commit()
            return {
                "mission_id": target_mission.id,
                "organization_name": organization_name,
                "mission_type": mission_type,
                "status": "failed",
                "sources_checked": collection_targets,
                "raw_items_count": 0,
                "collection_summary": "Collection dispatch failed",
                "requested_scores": requested_scores,
                "scoring_ready": False,
                "error_message": _sanitize_dispatch_error(exc),
            }
    finally:
        if owns_session:
            session.close()


def _build_mission_create_lock_key(
    *,
    query_payload: str,
    country: str,
    target_entity: Optional[str],
) -> str:
    lock_source = json.dumps(
        {
            "query": query_payload,
            "country": country,
            "target_entity": target_entity,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    lock_hash = hashlib.sha256(lock_source.encode("utf-8")).hexdigest()
    return f"mission:create:{lock_hash}"


def _release_mission_create_lock(redis_client, lock_key: Optional[str], lock_token: Optional[str]) -> None:
    if not redis_client or not lock_key or not lock_token:
        return
    try:
        redis_client.eval(MISSION_CREATE_LOCK_RELEASE_SCRIPT, 1, lock_key, lock_token)
    except Exception:
        pass


def _find_existing_collection_mission(
    *,
    session: Session,
    query_payload: str,
    country: str,
    target_entity: Optional[str],
) -> Optional[Mission]:
    return (
        session.query(Mission)
        .filter(
            Mission.status.in_(["queued", "running"]),
            Mission.query == query_payload,
            Mission.country == country,
            Mission.target_entity == target_entity,
        )
        .order_by(Mission.created_at.desc())
        .first()
    )


def create_collection_mission(
    *,
    query: str,
    country: str = "菲律宾",
    priority: int = DEFAULT_COLLECTION_PRIORITY,
    target_entity: Optional[str] = None,
    composite_task_id: Optional[str] = None,
    composite_status: Optional[str] = None,
    source: Optional[str] = None,
    keywords: Optional[list[str]] = None,
    limit_per_keyword: Optional[int] = None,
    metadata: Optional[dict[str, Any]] = None,
    db: Optional[Session] = None,
) -> Optional[Mission]:
    owns_session = db is None
    session = db or SessionLocal()
    redis_client = None
    lock_key = None
    lock_token = None
    try:
        query_payload = _build_query_payload(
            query=query,
            source=source,
            keywords=keywords,
            limit_per_keyword=limit_per_keyword,
            metadata=metadata,
        )
        lock_key = _build_mission_create_lock_key(
            query_payload=query_payload,
            country=country,
            target_entity=target_entity,
        )
        lock_token = str(uuid.uuid4())
        redis_client = _get_mission_lock_redis_client()
        lock_acquired = redis_client.set(
            lock_key,
            lock_token,
            nx=True,
            ex=MISSION_CREATE_LOCK_TTL_SECONDS,
        )
        if not lock_acquired:
            return _find_existing_collection_mission(
                session=session,
                query_payload=query_payload,
                country=country,
                target_entity=target_entity,
            )

        existing_mission = _find_existing_collection_mission(
            session=session,
            query_payload=query_payload,
            country=country,
            target_entity=target_entity,
        )
        if existing_mission:
            return existing_mission

        mission = Mission(
            id=str(uuid.uuid4()),
            query=query_payload,
            country=country,
            target_entity=target_entity,
            composite_task_id=composite_task_id,
            composite_status=composite_status,
            status="queued",
            priority=priority or DEFAULT_COLLECTION_PRIORITY,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        session.add(mission)
        session.commit()
        session.refresh(mission)
        enqueue_collection_mission(mission.id, mission.priority)
        return mission
    finally:
        _release_mission_create_lock(redis_client, lock_key, lock_token)
        if owns_session:
            session.close()
