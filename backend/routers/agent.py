"""
Agent管理接口：手动触发、状态查询、日志查看
"""

import os
import sys
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.memory import Memory
from models.database import get_db


router = APIRouter(prefix="/api/agent", tags=["agent"])


class AgentTriggerResponse(BaseModel):
    started: bool
    cycle_id: str
    message: str


@router.post("/run", response_model=AgentTriggerResponse)
async def trigger_agent():
    """手动触发一次Agent循环（管理员用）"""
    try:
        from agent.loop import run_agent_cycle

        result = run_agent_cycle(force=True)
        return AgentTriggerResponse(
            started=True,
            cycle_id=f"manual-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}",
            message=f"Agent执行完成: 创建 {result.get('tasks_created', 0)} 个任务",
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/status")
async def agent_status():
    """查询Agent当前状态"""
    db_gen = get_db()
    db = next(db_gen)
    try:
        last_run = None
        last_run_file = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "agent", ".agent_last_run")
        )
        if os.path.exists(last_run_file):
            with open(last_run_file, "r", encoding="utf-8") as file_obj:
                last_run = file_obj.read().strip() or None

        apis = db.execute(
            text("SELECT api_name, status FROM api_configs ORDER BY api_name")
        ).fetchall()

        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        today_count = db.execute(
            text(
                """
                SELECT COUNT(*) FROM missions
                WHERE composite_task_id IS NOT NULL AND created_at >= :today
                """
            ),
            {"today": today},
        ).scalar()

        pending = db.execute(
            text(
                """
                SELECT COUNT(*) FROM missions
                WHERE status = 'queued' AND composite_task_id IS NOT NULL
                """
            )
        ).scalar()

        return {
            "last_run": last_run,
            "next_run": "冷却6小时或Worker触发",
            "today_tasks": today_count or 0,
            "pending_auto_tasks": pending or 0,
            "apis": {api_name: status for api_name, status in apis},
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        try:
            db_gen.close()
        except Exception:
            pass


@router.get("/logs")
async def agent_logs(limit: int = 20, module: str | None = None):
    """查询Agent日志"""
    try:
        memory = Memory()
        logs = memory.get_recent_logs(module=module, limit=limit)
        return {"total": len(logs), "logs": logs}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
