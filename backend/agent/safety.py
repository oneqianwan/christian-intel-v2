"""
Agent安全层：额度控制、防重复、熔断
"""

import os
import sys
from datetime import datetime, timedelta
from typing import List

from sqlalchemy import func, text

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.planner import ActionPlan
from models.database import Mission, get_db


class SafetyGuard:
    API_DAILY_LIMITS = {"newsapi": 100, "scrapingbee": 30, "youtube": 1000}
    MAX_TASKS_PER_CYCLE = 10
    MIN_RECOLLECT_HOURS = 24

    def __init__(self):
        self._db_gen = get_db()
        self.db = next(self._db_gen)

    def __del__(self):
        try:
            self._db_gen.close()
        except Exception:
            pass

    def pre_run_check(self) -> bool:
        try:
            self.db.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

    def filter_plans(self, plans: List[ActionPlan]) -> List[ActionPlan]:
        if not plans:
            return []

        safe = []
        seen_keyword_surge = set()
        for plan in plans:
            if plan.action == "auto_collect" and self._is_recently_collected(plan.target):
                print(f"  [Safety] 跳过: {plan.target} 24h内已采集")
                continue

            if plan.action == "auto_collect" and plan.params.get("country") == "全球":
                if not self._check_api_quota("newsapi"):
                    print("  [Safety] NewsAPI额度不足")
                    continue

            if (
                plan.action == "notify_user"
                and plan.params.get("notification_type") == "keyword_surge"
            ):
                category = plan.target
                if (
                    category in seen_keyword_surge
                    or self._is_keyword_surge_notified_recently(category)
                ):
                    print(f"  [Safety] keyword_surge {category} 24h内已通知，跳过")
                    continue
                seen_keyword_surge.add(category)

            safe.append(plan)
            if len(safe) >= self.MAX_TASKS_PER_CYCLE:
                print(f"  [Safety] 达上限 {self.MAX_TASKS_PER_CYCLE}")
                break

        return safe

    def _is_recently_collected(self, target: str) -> bool:
        recent = datetime.utcnow() - timedelta(hours=self.MIN_RECOLLECT_HOURS)
        count = (
            self.db.query(func.count(Mission.id))
            .filter(
                Mission.country == target,
                Mission.composite_task_id.isnot(None),
                Mission.created_at >= recent,
            )
            .scalar()
        )
        return (count or 0) > 0

    def _check_api_quota(self, api_name: str) -> bool:
        if api_name not in self.API_DAILY_LIMITS:
            return True

        limit = self.API_DAILY_LIMITS[api_name]
        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        count = (
            self.db.query(func.count(Mission.id))
            .filter(
                Mission.composite_task_id.isnot(None),
                Mission.created_at >= today,
            )
            .scalar()
        )
        return (count or 0) * 3 < limit * 0.8

    def _is_keyword_surge_notified_recently(self, category: str) -> bool:
        """检查某类别 keyword_surge 是否在24h内已通知过。"""
        recent = datetime.utcnow() - timedelta(hours=24)
        count = self.db.execute(
            text(
                """
                SELECT COUNT(*)
                FROM agent_tasks
                WHERE task_type = 'keyword_surge_notification'
                  AND target = :category
                  AND created_at >= :recent
                """
            ),
            {"category": category, "recent": recent},
        ).scalar()
        return (count or 0) > 0
