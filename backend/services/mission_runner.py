import multiprocessing as mp
import os
import sys
import uuid
import json
import asyncio
from datetime import datetime, timedelta
from queue import Empty

import redis
from sqlalchemy import or_

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models.database import SessionLocal, Mission, JobRun, Source, IntelligenceItem, Message
from services.rss_scanner import fetch_rss
from services.analysis import compare_entities
from services.llm_client import get_llm_client

SOURCE_TIMEOUT_SECONDS = 30
SUCCESS_STATUSES = {"success", "no_change"}
COMPOSITE_REDIS_TTL_SECONDS = 3600


def _create_job_run(db, mission_id: str, job_type: str, source_id: str) -> JobRun:
    job = JobRun(
        id=str(uuid.uuid4()),
        mission_id=mission_id,
        job_type=job_type,
        source_id=source_id,
        status="running",
        started_at=datetime.utcnow(),
    )
    db.add(job)
    db.commit()
    return job


def _finalize_job_run(db, job: JobRun, result: dict):
    status = result.get("status")
    job.status = "done" if status in SUCCESS_STATUSES else "failed"
    job.finished_at = datetime.utcnow()
    job.result_count = result.get("new_items", 0)
    if result.get("error"):
        job.error_message = str(result["error"])[:500]
    db.commit()


def _load_composite_meta(composite_id: str) -> dict:
    if not composite_id:
        return {}

    redis_client = _get_composite_redis_client()
    if not redis_client:
        return {}

    try:
        raw = redis_client.get(f"composite:{composite_id}")
        return json.loads(raw) if raw else {}
    except Exception:
        return {}


def _resolve_mission_source_scope(db, mission: Mission) -> set[str] | None:
    target_entity = (getattr(mission, "target_entity", "") or "").strip().lower()
    if not target_entity:
        return None

    filtered = (
        db.query(Source)
        .filter(
            Source.country == mission.country,
            Source.is_active == True,
        )
        .all()
    )
    filtered = [source for source in filtered if target_entity in (source.name or "").lower()]
    return {source.id for source in filtered} if filtered else None


def _filter_sources_for_mission(sources: list[Source], allowed_source_ids: set[str] | None) -> list[Source]:
    if not allowed_source_ids:
        return sources
    return [source for source in sources if source.id in allowed_source_ids]


def _resolve_primary_status_source(db, mission: Mission, allowed_source_ids: set[str] | None) -> str | None:
    scoped_sources = (
        db.query(Source)
        .filter(
            Source.country == mission.country,
            Source.is_active == True,
        )
        .all()
    )
    scoped_sources = _filter_sources_for_mission(scoped_sources, allowed_source_ids)
    if not scoped_sources:
        return None

    type_priority = {
        "website": 0,
        "news_page": 1,
        "youtube_channel": 2,
        "rss": 3,
        "rss_global": 4,
        "telegram_channel": 5,
    }
    scoped_sources.sort(key=lambda source: (type_priority.get(source.type, 99), source.name or ""))
    return scoped_sources[0].name


def notify_dialog_status_update(mission: Mission, message: str, source_name: str | None = None):
    """将后台任务步骤状态追加到关联会话。"""
    if not mission.composite_task_id:
        return

    composite_meta = _load_composite_meta(mission.composite_task_id)
    conversation_id = composite_meta.get("conversation_id")
    if not conversation_id:
        return

    db = SessionLocal()
    try:
        target_entity = (getattr(mission, "target_entity", "") or "").strip().lower()
        normalized_source_name = (source_name or "").strip()
        if target_entity and normalized_source_name and target_entity not in normalized_source_name.lower():
            return

        recent_duplicate = (
            db.query(Message)
            .filter(
                Message.conversation_id == conversation_id,
                Message.delivery_type == "status_update",
                Message.content == message,
                Message.created_at >= datetime.utcnow() - timedelta(seconds=30),
            )
            .first()
        )
        if recent_duplicate:
            return

        status_msg = Message(
            id=str(uuid.uuid4()),
            conversation_id=conversation_id,
            role="assistant",
            content=message,
            sources=[],
            delivery_type="status_update",
            status="completed",
            created_at=datetime.utcnow(),
        )
        db.add(status_msg)
        db.commit()
    except Exception as exc:
        print(f"[STATUS_UPDATE] 追加状态消息失败: {str(exc)[:200]}")
    finally:
        db.close()


def _execute_source_scan(source_id: str, source_type: str, result_queue):
    db = SessionLocal()
    try:
        source = db.query(Source).filter(Source.id == source_id).first()
        if not source:
            result_queue.put(
                {"status": "failed", "error": f"来源不存在: {source_id}", "new_items": 0}
            )
            return

        if source_type in {"rss", "rss_global"}:
            result = fetch_rss(source, db)
        elif source_type == "news_page":
            from services.news_page_scraper import scrape_news_page

            result = scrape_news_page(source, db)
        elif source_type == "website":
            from services.deep_scraper import deep_scrape_organization

            result = deep_scrape_organization(source, db)
        elif source_type == "youtube_channel":
            from services.youtube_collector import collect_youtube_channel

            result = collect_youtube_channel(source, db)
        elif source_type == "telegram_channel":
            from services.telegram_collector import collect_telegram_channel

            result = collect_telegram_channel(source, db)
        else:
            from services.page_scraper import scrape_page

            result = scrape_page(source, db)

        result_queue.put(result or {"status": "success", "new_items": 0})
    except Exception as exc:
        result_queue.put(
            {
                "status": "failed",
                "error": f"{source_type} 扫描异常: {str(exc)[:300]}",
                "new_items": 0,
            }
        )
    finally:
        db.close()


def run_with_timeout(source: Source, timeout_sec: int = SOURCE_TIMEOUT_SECONDS) -> dict:
    ctx = mp.get_context("spawn")
    result_queue = ctx.Queue()
    process = ctx.Process(
        target=_execute_source_scan,
        args=(source.id, source.type, result_queue),
    )
    process.start()
    process.join(timeout=timeout_sec)

    if process.is_alive():
        process.terminate()
        process.join(5)
        print(f"[TIMEOUT] 来源扫描超时: {source.name} ({source.type})")
        return {
            "status": "timeout",
            "source": source.name,
            "error": f"来源扫描超过 {timeout_sec} 秒",
            "new_items": 0,
        }

    try:
        return result_queue.get_nowait()
    except Empty:
        if process.exitcode not in (0, None):
            return {
                "status": "failed",
                "source": source.name,
                "error": f"子进程异常退出，exit_code={process.exitcode}",
                "new_items": 0,
            }
        return {"status": "failed", "source": source.name, "error": "未返回结果", "new_items": 0}


def _run_source_group(db, mission: Mission, sources, job_type: str, primary_status_source: str | None = None):
    for source in sources:
        should_notify = not primary_status_source or source.name == primary_status_source
        if should_notify:
            notify_dialog_status_update(
                mission,
                f"📡 正在从 {source.name} 采集情报...",
                source_name=source.name,
            )
        job = _create_job_run(db, mission.id, job_type, source.id)
        result = run_with_timeout(source)
        _finalize_job_run(db, job, result)
        if should_notify:
            notify_dialog_status_update(
                mission,
                f"✅ {source.name} 采集完成，获得 {result.get('new_items', 0)} 条情报",
                source_name=source.name,
            )
        print(f"  {source.name}: {result}")


def _get_composite_redis_client():
    try:
        return redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)
    except Exception:
        return None


def _build_comparison_items(entity_results: dict, country: str | None) -> list[dict]:
    comparison_items = []
    for entity, items in entity_results.items():
        if not items:
            comparison_items.append(
                {
                    "name": entity,
                    "type": "entity",
                    "country": country or "",
                    "category": "compare_analysis",
                    "data": {
                        "recent_item_count": 0,
                        "time_window_days": 30,
                        "note": "近30天未检索到相关情报",
                    },
                    "source_name": "系统检索",
                    "source_url": "",
                }
            )
            continue

        for item in items:
            comparison_items.append(
                {
                    "name": entity,
                    "type": "entity",
                    "country": country or "",
                    "category": "compare_analysis",
                    "data": {
                        "title": item["title"],
                        "date": item["date"],
                        "recent_item_count": len(items),
                        "time_window_days": 30,
                    },
                    "source_name": item["source"],
                    "source_url": item["url"],
                }
            )
    return comparison_items


def trigger_comparison(entity_a: str, entity_b: str, country: str | None, composite_id: str, db):
    result = compare_entities(db, [entity_a, entity_b])
    comparison_items = _build_comparison_items(result["entity_results"], country)
    content = result["content"]

    try:
        llm_content = asyncio.run(
            get_llm_client().analyze_comparison(
                f"对比 {entity_a} 和 {entity_b} 在{country or '目标地区'}的近期动态",
                comparison_items,
            )
        )
        if llm_content:
            content = llm_content
    except Exception as exc:
        print(f"[COMPOSITE] LLM 对比分析失败: {str(exc)[:100]}")

    existing = db.query(IntelligenceItem).filter(
        IntelligenceItem.category == "comparison",
        IntelligenceItem.source_url == f"composite:{composite_id}",
    ).first()
    if existing:
        print(f"[COMPOSITE] 对比分析已存在，跳过重复写入: {existing.id}")
        return existing

    source = (
        db.query(Source)
        .filter(Source.country == (country or "菲律宾"), Source.is_active == True)
        .order_by(Source.created_at.asc())
        .first()
    )
    if not source:
        source = db.query(Source).filter(Source.is_active == True).order_by(Source.created_at.asc()).first()
    if not source:
        raise RuntimeError("没有可用于保存对比分析的来源")

    comparison_item = IntelligenceItem(
        id=str(uuid.uuid4()),
        source_id=source.id,
        title=f"对比分析: {entity_a} vs {entity_b}",
        content=content,
        entity_name=f"{entity_a} vs {entity_b}",
        entity_type="comparison",
        country=country,
        category="comparison",
        source_url=f"composite:{composite_id}",
        source_name="系统对比分析",
        published_at=datetime.utcnow(),
        ingested_at=datetime.utcnow(),
        confidence=0.85,
    )
    db.add(comparison_item)
    db.commit()
    print(f"[COMPOSITE] 对比分析已保存: {comparison_item.id}")
    synthetic_mission = Mission(id=str(uuid.uuid4()), query="", country=country or "", composite_task_id=composite_id)
    notify_dialog_status_update(synthetic_mission, "📊 对比分析已生成")
    return comparison_item


def check_composite_completion(mission_id: str, db):
    current = db.query(Mission).filter(Mission.id == mission_id).first()
    if not current or not current.composite_task_id:
        return

    composite_id = current.composite_task_id
    group_missions = db.query(Mission).filter(Mission.composite_task_id == composite_id).all()
    all_done = all(m.status in {"done", "failed"} for m in group_missions)
    if not all_done:
        return

    redis_client = _get_composite_redis_client()
    lock_key = f"composite_lock:{composite_id}"
    if redis_client:
        lock_acquired = redis_client.set(lock_key, "1", ex=300, nx=True)
        if not lock_acquired:
            print(f"[COMPOSITE] 复合任务 {composite_id} 已在处理，跳过重复触发")
            return

    print(f"[COMPOSITE] 复合任务 {composite_id} 全部完成，触发对比分析")
    synthetic_mission = Mission(id=str(uuid.uuid4()), query="", country=current.country, composite_task_id=composite_id)
    notify_dialog_status_update(synthetic_mission, "🎯 所有采集任务已完成，正在生成对比分析...")

    try:
        meta = {}
        if redis_client:
            meta_raw = redis_client.get(f"composite:{composite_id}")
            if meta_raw:
                meta = json.loads(meta_raw)

        entities = meta.get("entities") or []
        country = meta.get("country") or current.country
        if len(entities) >= 2:
            trigger_comparison(entities[0], entities[1], country, composite_id, db)

        for mission in group_missions:
            mission.composite_status = "completed"
        db.commit()
    except Exception as exc:
        for mission in group_missions:
            mission.composite_status = "failed"
        db.commit()
        print(f"[COMPOSITE] 触发对比失败: {str(exc)[:200]}")
    finally:
        if redis_client:
            redis_client.expire(f"composite:{composite_id}", COMPOSITE_REDIS_TTL_SECONDS)


def run_mission(mission_id: str):
    """RQ Worker 执行的实际任务"""
    db = SessionLocal()
    try:
        mission = db.query(Mission).filter(Mission.id == mission_id).first()
        if not mission:
            print(f"Mission {mission_id} not found")
            return

        mission.status = "running"
        if mission.composite_task_id:
            mission.composite_status = "running"
        mission.updated_at = datetime.utcnow()
        db.commit()
        print(f"开始执行采集任务: {mission.query} (priority={mission.priority})")
        allowed_source_ids = _resolve_mission_source_scope(db, mission)
        primary_status_source = _resolve_primary_status_source(db, mission, allowed_source_ids)

        rss_sources = db.query(Source).filter(
            Source.type.in_(["rss", "rss_global"]),
            Source.country == mission.country,
            Source.is_active == True,
        ).all()
        rss_sources = _filter_sources_for_mission(rss_sources, allowed_source_ids)
        _run_source_group(db, mission, rss_sources, "rss_scan", primary_status_source)

        web_sources = db.query(Source).filter(
            Source.type.in_(["website", "news_page"]),
            Source.country == mission.country,
            Source.is_active == True,
        ).all()
        web_sources = _filter_sources_for_mission(web_sources, allowed_source_ids)
        _run_source_group(db, mission, web_sources, "page_extract", primary_status_source)

        yt_sources = db.query(Source).filter(
            Source.type == "youtube_channel",
            Source.country == mission.country,
            Source.is_active == True,
        ).all()
        yt_sources = _filter_sources_for_mission(yt_sources, allowed_source_ids)
        _run_source_group(db, mission, yt_sources, "youtube_collect", primary_status_source)

        tg_sources = db.query(Source).filter(
            Source.type == "telegram_channel",
            Source.country == mission.country,
            Source.is_active == True,
        ).all()
        tg_sources = _filter_sources_for_mission(tg_sources, allowed_source_ids)
        _run_source_group(db, mission, tg_sources, "telegram_collect", primary_status_source)

        mission.status = "done"
        mission.updated_at = datetime.utcnow()
        db.commit()
        check_composite_completion(mission.id, db)
        print(f"采集任务完成: {mission_id}")
    except Exception as exc:
        if "mission" in locals() and mission:
            mission.status = "failed"
            if mission.composite_task_id:
                mission.composite_status = "failed"
            mission.updated_at = datetime.utcnow()
            db.commit()
            check_composite_completion(mission.id, db)
        print(f"采集任务失败: {mission_id}, error={str(exc)[:500]}")
        raise
    finally:
        db.close()
