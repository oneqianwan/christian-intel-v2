"""
Agent规划层：根据感知结果生成行动计划
"""

import os
import sys
from dataclasses import dataclass, field
from typing import List

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.perception import PerceptionResult


@dataclass
class ActionPlan:
    action: str
    target: str
    priority: int
    params: dict = field(default_factory=dict)
    reason: str = ""


class Planner:
    SEVERITY_PRIORITY = {"high": 1, "medium": 3, "low": 5}
    ACTION_MAP = {
        "gap": "auto_collect",
        "api_health": "mark_api_error",
        "source_stale": "auto_collect",
        "user_query_gap": "auto_collect_and_notify",
        "keyword_surge": "notify_user",
    }

    def create_plans(self, perceptions: List[PerceptionResult]) -> List[ActionPlan]:
        if not perceptions:
            return []

        perceptions.sort(key=lambda p: self.SEVERITY_PRIORITY.get(p.severity, 5))
        plans = []
        seen = set()

        for perception in perceptions:
            if perception.target in seen and perception.type == "source_stale":
                continue

            action = self.ACTION_MAP.get(perception.type, "notify_user")
            priority = (
                0
                if perception.type == "user_query_gap"
                else 1
                if perception.type == "keyword_surge"
                else self.SEVERITY_PRIORITY.get(perception.severity, 5)
            )
            params = self._build_params(perception)
            plans.append(
                ActionPlan(
                    action,
                    perception.target,
                    priority,
                    params,
                    f"{perception.type}: {perception.target} ({perception.severity})",
                )
            )
            seen.add(perception.target)

        plans.sort(key=lambda plan: plan.priority)
        print(f"[Planner] {len(plans)} 个计划")
        for plan in plans:
            print(f"  P{plan.priority}: {plan.action} -> {plan.target}")
        return plans

    def _build_params(self, perception: PerceptionResult) -> dict:
        if perception.type == "gap":
            return {
                "country": perception.target,
                "reason": (
                    f"缺口: {perception.detail.get('current', 0)}/"
                    f"{perception.detail.get('threshold', 0)}"
                ),
                "count": perception.detail.get("gap", 10),
            }
        if perception.type == "api_health":
            return {
                "api_name": perception.target,
                "reason": f"API异常: {perception.detail}",
            }
        if perception.type == "source_stale":
            return {
                "source_name": perception.target,
                "reason": (
                    "来源陈旧: "
                    f"{perception.detail.get('last_update', 'unknown')}"
                ),
            }
        if perception.type == "user_query_gap":
            return {
                "country": perception.detail.get("country") or "全球",
                "entity": perception.detail.get("entity", ""),
                "user_query": perception.detail.get("user_query", ""),
                "conversation_id": perception.detail.get("conversation_id", ""),
                "reason": f"用户查询缺口: {perception.detail.get('user_query', '')[:50]}",
                "notification_type": "gap_filled",
                "original_query": perception.detail.get("user_query", ""),
            }
        if perception.type == "keyword_surge":
            sample_titles = perception.detail.get("sample_titles", [])[:3]
            return {
                "notification_type": "keyword_surge",
                "category": perception.target,
                "message": (
                    f"🚨 **突发关键词预警：{perception.target}**\n\n"
                    f"过去24小时检测到 **{perception.detail.get('24h_count', 0)}** 条相关情报，"
                    f"是过去7天日均（{perception.detail.get('daily_avg_7d', 0)}条）的 "
                    f"**{perception.detail.get('multiplier', 0)}倍**。\n\n"
                    "相关情报：\n"
                    + "\n".join([f"- {title}" for title in sample_titles])
                ),
                "severity": perception.severity,
            }
        return {"detail": perception.detail}
