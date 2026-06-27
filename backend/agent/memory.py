"""
Agent记忆层：记录任务状态和操作日志
"""

import os
import sys

from sqlalchemy import text

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models.database import get_db


class Memory:
    def __init__(self):
        self._db_gen = get_db()
        self.db = next(self._db_gen)
        self._ensure_tables()

    def __del__(self):
        try:
            self._db_gen.close()
        except Exception:
            pass

    def _ensure_tables(self):
        self.db.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS agent_logs (
                    id SERIAL PRIMARY KEY,
                    level VARCHAR(20) DEFAULT 'info',
                    module VARCHAR(50),
                    message TEXT NOT NULL,
                    detail JSONB,
                    created_at TIMESTAMP DEFAULT NOW()
                )
                """
            )
        )
        self.db.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS agent_tasks (
                    id SERIAL PRIMARY KEY,
                    task_type VARCHAR(50) NOT NULL,
                    status VARCHAR(20) DEFAULT 'pending',
                    target VARCHAR(100),
                    reason TEXT,
                    plan JSONB,
                    result JSONB,
                    created_at TIMESTAMP DEFAULT NOW(),
                    started_at TIMESTAMP,
                    completed_at TIMESTAMP
                )
                """
            )
        )
        self.db.commit()

    def log(self, module: str, message: str, detail: dict = None, level: str = "info"):
        try:
            self.db.execute(
                text(
                    """
                    INSERT INTO agent_logs (level, module, message, detail, created_at)
                    VALUES (:level, :module, :message, CAST(:detail AS JSONB), NOW())
                    """
                ),
                {
                    "level": level,
                    "module": module,
                    "message": message,
                    "detail": self._json_value(detail),
                },
            )
            self.db.commit()
        except Exception as exc:
            print(f"[Memory] 日志失败: {exc}")
            self.db.rollback()

    def create_task(self, task_type: str, target: str, reason: str, plan: dict = None) -> int:
        try:
            result = self.db.execute(
                text(
                    """
                    INSERT INTO agent_tasks (task_type, target, reason, plan, created_at)
                    VALUES (:type, :target, :reason, CAST(:plan AS JSONB), NOW())
                    RETURNING id
                    """
                ),
                {
                    "type": task_type,
                    "target": target,
                    "reason": reason,
                    "plan": self._json_value(plan),
                },
            )
            task_id = result.scalar()
            self.db.commit()
            return int(task_id or 0)
        except Exception as exc:
            print(f"[Memory] 任务创建失败: {exc}")
            self.db.rollback()
            return 0

    def update_task(self, task_id: int, status: str, result: dict = None):
        try:
            if status == "running":
                self.db.execute(
                    text(
                        """
                        UPDATE agent_tasks
                        SET status = :status, started_at = NOW()
                        WHERE id = :id
                        """
                    ),
                    {"status": status, "id": task_id},
                )
            elif status in ("done", "failed"):
                self.db.execute(
                    text(
                        """
                        UPDATE agent_tasks
                        SET status = :status,
                            result = CAST(:result AS JSONB),
                            completed_at = NOW()
                        WHERE id = :id
                        """
                    ),
                    {
                        "status": status,
                        "result": self._json_value(result),
                        "id": task_id,
                    },
                )
            self.db.commit()
        except Exception as exc:
            print(f"[Memory] 任务更新失败: {exc}")
            self.db.rollback()

    def get_recent_logs(self, module: str = None, limit: int = 20) -> list:
        if module:
            result = self.db.execute(
                text(
                    """
                    SELECT level, module, message, detail, created_at
                    FROM agent_logs
                    WHERE module = :module
                    ORDER BY created_at DESC
                    LIMIT :limit
                    """
                ),
                {"module": module, "limit": limit},
            )
        else:
            result = self.db.execute(
                text(
                    """
                    SELECT level, module, message, detail, created_at
                    FROM agent_logs
                    ORDER BY created_at DESC
                    LIMIT :limit
                    """
                ),
                {"limit": limit},
            )
        return [dict(row._mapping) for row in result]

    def _json_value(self, value):
        if value is None:
            return "{}"
        import json

        return json.dumps(value, ensure_ascii=False, default=str)
