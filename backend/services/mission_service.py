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
