"""采集控制接口。"""

import json
import threading
from datetime import datetime
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from dependencies.rate_limit import enforce_rate_limit_for_request

try:
    from backend.services.agent import get_agent
    from backend.models.database import JobRun, Mission, SessionLocal
    from backend.services.mission_service import MISSION_PAYLOAD_PREFIX, create_collection_mission
except ImportError:
    from services.agent import get_agent
    from models.database import JobRun, Mission, SessionLocal
    from services.mission_service import MISSION_PAYLOAD_PREFIX, create_collection_mission

router = APIRouter(prefix="/api/collection", tags=["collection"])

_collection_tasks: Dict[str, "CollectionTask"] = {}
_collection_tasks_lock = threading.Lock()


class CollectionTask(BaseModel):
    task_id: str
    mission_id: str
    created_at: str = ""


class StartCollectionRequest(BaseModel):
    keywords: List[str] = Field(default_factory=list)
    country: Optional[str] = None
    source: str = "newsapi"  # newsapi, rss, webpage
    limit_per_keyword: int = 30


class StartCollectionResponse(BaseModel):
    task_id: str
    status: str
    message: str


class TaskStatusResponse(BaseModel):
    task: Optional[dict] = None
    recent_tasks: List[dict] = Field(default_factory=list)


def _task_to_dict(task: CollectionTask) -> dict:
    if hasattr(task, "model_dump"):
        return task.model_dump()
    return task.dict()


def _build_collection_adapter(
    *,
    task_id: str,
    mission_id: str,
    created_at: Optional[str] = None,
) -> CollectionTask:
    return CollectionTask(
        task_id=task_id,
        mission_id=mission_id,
        created_at=created_at or datetime.utcnow().isoformat(),
    )


def _parse_collection_payload(mission: Mission) -> dict:
    query = mission.query or ""
    if not query.startswith(MISSION_PAYLOAD_PREFIX):
        return {}
    try:
        payload = json.loads(query[len(MISSION_PAYLOAD_PREFIX):])
    except Exception:
        return {}
    metadata = payload.get("metadata") or {}
    entry = (metadata.get("entry") or "").strip()
    if not entry.startswith("api.collection"):
        return {}
    return payload


def _status_from_mission(mission_status: str) -> str:
    return {
        "queued": "pending",
        "running": "running",
        "done": "completed",
        "failed": "failed",
        "cancelled": "failed",
    }.get(mission_status, "pending")


def _build_task_from_mission(mission: Mission, adapter: Optional[CollectionTask] = None) -> Optional[dict]:
    payload = _parse_collection_payload(mission)
    if not payload:
        return None

    keywords = list(payload.get("keywords") or [])
    source = (payload.get("source") or "").strip().lower() or "newsapi"
    limit_per_keyword = max(1, min(int(payload.get("limit_per_keyword") or 30), 100))
    db = SessionLocal()
    try:
        jobs = db.query(JobRun).filter(JobRun.mission_id == mission.id).all()
    finally:
        db.close()

    collected = sum(max(job.result_count or 0, 0) for job in jobs)
    failed = sum(1 for job in jobs if job.status == "failed")
    error_message = next((job.error_message for job in jobs if job.error_message), None)

    started_at = None
    if mission.status != "queued":
        started_at = mission.updated_at.isoformat() if mission.updated_at else mission.created_at.isoformat()
    finished_at = None
    if mission.status in {"done", "failed", "cancelled"}:
        finished_at = mission.updated_at.isoformat() if mission.updated_at else mission.created_at.isoformat()

    return {
        "id": adapter.task_id if adapter else mission.id,
        "status": _status_from_mission(mission.status),
        "task_type": source,
        "keywords": keywords,
        "country": mission.country,
        "source": source,
        "total_expected": len(keywords) * limit_per_keyword,
        "collected": collected,
        "failed": failed,
        "deduped": max(len(keywords) * limit_per_keyword - collected - failed, 0),
        "created_at": adapter.created_at if adapter else (mission.created_at.isoformat() if mission.created_at else datetime.utcnow().isoformat()),
        "started_at": started_at,
        "finished_at": finished_at,
        "error_message": error_message,
        "mission_id": mission.id,
    }


def _get_collection_mission(task_id: str) -> tuple[Optional[Mission], Optional[CollectionTask]]:
    adapter = None
    with _collection_tasks_lock:
        adapter = _collection_tasks.get(task_id)
    mission_id = adapter.mission_id if adapter else task_id
    db = SessionLocal()
    try:
        mission = db.query(Mission).filter(Mission.id == mission_id).first()
        if not mission or not _parse_collection_payload(mission):
            return None, adapter
        return mission, adapter
    finally:
        db.close()


def _get_recent_task_dicts(limit: int = 10) -> List[dict]:
    db = SessionLocal()
    try:
        missions = (
            db.query(Mission)
            .order_by(Mission.created_at.desc())
            .limit(max(limit * 5, 20))
            .all()
        )
    finally:
        db.close()

    tasks: List[dict] = []
    with _collection_tasks_lock:
        adapters = {adapter.mission_id: adapter for adapter in _collection_tasks.values()}
    for mission in missions:
        adapter = adapters.get(mission.id)
        task = _build_task_from_mission(mission, adapter)
        if not task:
            continue
        tasks.append(task)
        if len(tasks) >= limit:
            break
    return tasks


def _count_recent_collection_missions() -> int:
    db = SessionLocal()
    try:
        missions = db.query(Mission).order_by(Mission.created_at.desc()).limit(500).all()
    finally:
        db.close()
    return sum(1 for mission in missions if _parse_collection_payload(mission))


@router.post("/start", response_model=StartCollectionResponse)
async def start_collection(payload: StartCollectionRequest, request: Request):
    """启动采集任务"""
    enforce_rate_limit_for_request(request, rule_name="public_high_cost")
    keywords = [(item or "").strip() for item in payload.keywords if (item or "").strip()]
    if not keywords:
        raise HTTPException(status_code=400, detail="keywords is required")

    source = (payload.source or "newsapi").strip().lower()
    if source not in {"newsapi", "rss", "webpage"}:
        raise HTTPException(status_code=400, detail="unsupported source")

    limit_per_keyword = max(1, min(int(payload.limit_per_keyword or 30), 100))
    mission = create_collection_mission(
        query=f"Collection Start | {source} | {', '.join(keywords)}",
        country=payload.country or "全球",
        source=source,
        keywords=keywords,
        limit_per_keyword=limit_per_keyword,
        metadata={
            "entry": "api.collection.start",
            "task_type": source,
        },
    )
    mission_id = mission.id if mission else None
    if not mission_id:
        raise HTTPException(status_code=409, detail="Mission creation skipped")

    adapter = _build_collection_adapter(
        task_id=mission_id,
        mission_id=mission_id,
    )

    with _collection_tasks_lock:
        _collection_tasks[mission_id] = adapter

    mission, adapter = _get_collection_mission(mission_id)
    task = _build_task_from_mission(mission, adapter) if mission else None

    return StartCollectionResponse(
        task_id=mission_id,
        status=(task or {}).get("status", "pending"),
        message=f"已启动{source}采集任务，关键词: {', '.join(keywords)}",
    )


@router.get("/status/{task_id}", response_model=TaskStatusResponse)
async def get_collection_status(task_id: str):
    """查询采集任务状态"""
    mission, adapter = _get_collection_mission(task_id)
    if not mission:
        raise HTTPException(status_code=404, detail="Task not found")
    task = _build_task_from_mission(mission, adapter)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    return TaskStatusResponse(
        task=task,
        recent_tasks=_get_recent_task_dicts(limit=10),
    )


@router.get("/recent")
async def get_recent_tasks(limit: int = 10):
    """获取最近任务列表"""
    limit = max(1, min(limit, 50))
    tasks = _get_recent_task_dicts(limit=limit)
    agent = get_agent()
    return {
        "tasks": tasks,
        "total": _count_recent_collection_missions(),
        "agent": agent.get_stats(),
    }


@router.get("/presets")
async def get_presets():
    """获取定向预设关键词"""
    try:
        from backend.data.preset_keywords import PRESET_KEYWORDS
    except ImportError:
        from data.preset_keywords import PRESET_KEYWORDS

    return {
        "presets": [
            {
                "label": preset["label"],
                "keywords": preset["keywords"],
                "country": preset.get("country"),
            }
            for preset in PRESET_KEYWORDS
        ],
        "total": len(PRESET_KEYWORDS),
    }


def _execute_collection(
    task_id: str,
    keywords: List[str],
    country: Optional[str],
    source: str,
    limit_per_keyword: int,
):
    """兼容保留：只创建 Mission，并登记一个 CollectionTask 适配记录。"""
    mission = create_collection_mission(
        query=f"Collection Compat | {source} | {', '.join(keywords)}",
        country=country or "全球",
        source=source,
        keywords=keywords,
        limit_per_keyword=limit_per_keyword,
        metadata={
            "entry": "api.collection.compat_execute",
            "legacy_task_id": task_id,
        },
    )
    mission_id = mission.id if mission else None
    if not mission_id:
        print(f"[Collection] Mission未创建，跳过兼容登记: task_id={task_id}")
        return
    adapter = _build_collection_adapter(
        task_id=task_id,
        mission_id=mission_id,
    )
    with _collection_tasks_lock:
        _collection_tasks[task_id] = adapter
    print(f"[Collection] 兼容入口已委托给 Mission: task_id={task_id}, mission_id={mission_id}")
