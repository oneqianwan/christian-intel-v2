"""
采集控制接口 — 一键启动采集任务，查询进度
"""

import asyncio
import threading
import uuid
from datetime import datetime
from typing import Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

try:
    from backend.services.agent import get_agent
    from backend.services.auto_extractor import batch_extract_from_intelligence_items
    from backend.services.api_collectors import NewsAPICollector
    from backend.services.rss_collector import collect_rss
    from backend.models.database import IntelligenceItem, SessionLocal
except ImportError:
    from services.agent import get_agent
    from services.auto_extractor import batch_extract_from_intelligence_items
    from services.api_collectors import NewsAPICollector
    from services.rss_collector import collect_rss
    from models.database import IntelligenceItem, SessionLocal

router = APIRouter(prefix="/api/collection", tags=["collection"])

_collection_tasks: Dict[str, "CollectionTask"] = {}
_collection_tasks_lock = threading.Lock()


class CollectionTask(BaseModel):
    id: str
    status: str  # pending, running, completed, failed
    task_type: str  # newsapi, rss, webpage
    keywords: List[str]
    country: Optional[str] = None
    source: str
    total_expected: int = 0
    collected: int = 0
    failed: int = 0
    deduped: int = 0
    created_at: str = ""
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    error_message: Optional[str] = None


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


def _get_recent_task_dicts(limit: int = 10) -> List[dict]:
    with _collection_tasks_lock:
        recent = sorted(
            _collection_tasks.values(),
            key=lambda item: item.created_at,
            reverse=True,
        )[:limit]
        return [_task_to_dict(task) for task in recent]


@router.post("/start", response_model=StartCollectionResponse)
async def start_collection(
    request: StartCollectionRequest,
    background_tasks: BackgroundTasks,
):
    """启动采集任务"""
    keywords = [(item or "").strip() for item in request.keywords if (item or "").strip()]
    if not keywords:
        raise HTTPException(status_code=400, detail="keywords is required")

    source = (request.source or "newsapi").strip().lower()
    if source not in {"newsapi", "rss", "webpage"}:
        raise HTTPException(status_code=400, detail="unsupported source")

    limit_per_keyword = max(1, min(int(request.limit_per_keyword or 30), 100))
    task_id = f"coll-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"

    task = CollectionTask(
        id=task_id,
        status="pending",
        task_type=source,
        keywords=keywords,
        country=request.country,
        source=source,
        total_expected=len(keywords) * limit_per_keyword,
        created_at=datetime.utcnow().isoformat(),
    )

    with _collection_tasks_lock:
        _collection_tasks[task_id] = task

    background_tasks.add_task(
        _execute_collection,
        task_id=task_id,
        keywords=keywords,
        country=request.country,
        source=source,
        limit_per_keyword=limit_per_keyword,
    )

    return StartCollectionResponse(
        task_id=task_id,
        status="pending",
        message=f"已启动{source}采集任务，关键词: {', '.join(keywords)}",
    )


@router.get("/status/{task_id}", response_model=TaskStatusResponse)
async def get_collection_status(task_id: str):
    """查询采集任务状态"""
    with _collection_tasks_lock:
        task = _collection_tasks.get(task_id)

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    return TaskStatusResponse(
        task=_task_to_dict(task),
        recent_tasks=_get_recent_task_dicts(limit=10),
    )


@router.get("/recent")
async def get_recent_tasks(limit: int = 10):
    """获取最近任务列表"""
    tasks = _get_recent_task_dicts(limit=max(1, min(limit, 50)))
    agent = get_agent()
    return {
        "tasks": tasks,
        "total": len(_collection_tasks),
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


def _update_task(task: CollectionTask, **kwargs) -> None:
    for key, value in kwargs.items():
        setattr(task, key, value)


def _execute_collection(
    task_id: str,
    keywords: List[str],
    country: Optional[str],
    source: str,
    limit_per_keyword: int,
):
    """在后台线程执行采集"""
    with _collection_tasks_lock:
        task = _collection_tasks.get(task_id)
    if not task:
        return

    _update_task(
        task,
        status="running",
        started_at=datetime.utcnow().isoformat(),
        error_message=None,
    )

    db = SessionLocal()
    try:
        total_collected = 0
        total_failed = 0
        total_deduped = 0

        if source == "newsapi":
            collector = NewsAPICollector(db)
            if not collector.api_key:
                raise RuntimeError("NEWSAPI_KEY 未配置，无法执行 NewsAPI 采集")

            for keyword in keywords:
                try:
                    count = collector._collect_keyword(
                        keyword,
                        label=keyword,
                        limit_per_keyword=limit_per_keyword,
                    )
                    total_collected += count
                    total_deduped += max(limit_per_keyword - count, 0)
                    _update_task(
                        task,
                        collected=total_collected,
                        failed=total_failed,
                        deduped=total_deduped,
                    )
                except Exception as exc:
                    total_failed += 1
                    _update_task(task, failed=total_failed)
                    print(f"[Collection] 关键词 '{keyword}' 采集失败: {exc}")

        elif source == "rss":
            before_count = db.query(IntelligenceItem).count()
            collect_rss(limit_per_source=limit_per_keyword)
            db.expire_all()
            after_count = db.query(IntelligenceItem).count()
            total_collected = max(after_count - before_count, 0)
            total_deduped = max(task.total_expected - total_collected, 0)
            _update_task(
                task,
                collected=total_collected,
                failed=0,
                deduped=total_deduped,
            )

        elif source == "webpage":
            try:
                from backend.crawlers.dynamic_crawler import DynamicCrawler
            except ImportError:
                from crawlers.dynamic_crawler import DynamicCrawler

            async def run_crawler() -> tuple[int, int]:
                crawler = DynamicCrawler()
                collected = 0
                failed = 0
                try:
                    await crawler.start()
                    for keyword in keywords:
                        search_url = f"https://www.google.com/search?q={keyword.replace(' ', '+')}"
                        try:
                            result = await crawler.fetch_page(search_url)
                            if result.get("success"):
                                collected += 1
                            else:
                                failed += 1
                        except Exception as exc:
                            failed += 1
                            print(f"[Collection] 网页采集 '{keyword}' 失败: {exc}")
                        _update_task(task, collected=collected, failed=failed)
                finally:
                    await crawler.stop()
                return collected, failed

            total_collected, total_failed = asyncio.run(run_crawler())
            total_deduped = max(task.total_expected - total_collected - total_failed, 0)

        final_status = "completed" if total_failed < len(keywords) else "failed"

        if final_status == "completed":
            try:
                print("[Collection] 任务完成，自动提取机构信息...")
                extract_stats = batch_extract_from_intelligence_items(limit=100)
                print(f"[Collection] 自动提取完成: {extract_stats}")
            except Exception as exc:
                print(f"[Collection] 自动提取失败: {exc}")

        _update_task(
            task,
            status=final_status,
            collected=total_collected,
            failed=total_failed,
            deduped=total_deduped,
            finished_at=datetime.utcnow().isoformat(),
        )
    except Exception as exc:
        _update_task(
            task,
            status="failed",
            error_message=str(exc),
            finished_at=datetime.utcnow().isoformat(),
        )
    finally:
        db.close()
