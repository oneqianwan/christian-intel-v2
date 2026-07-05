from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass(frozen=True)
class HealthCheck:
    status: str
    score: float
    checks: List[Dict[str, Any]] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "score": float(self.score or 0.0),
            "checks": list(self.checks or []),
            "summary": dict(self.summary or {}),
        }

    @classmethod
    def evaluate(cls, dashboard: Dict[str, Any]) -> "HealthCheck":
        sections = dict(dashboard or {})
        tool = dict(sections.get("tool_statistics") or {})
        memory = dict(sections.get("memory_statistics") or {})
        knowledge = dict(sections.get("knowledge_statistics") or {})
        loop = dict(sections.get("loop_statistics") or {})
        score = float((sections.get("runtime_score") or {}).get("overall_runtime_score") or 0.0)

        checks: List[Dict[str, Any]] = []
        loop_avg = float(loop.get("average_loop") or 0.0)
        if loop_avg > 3.0:
            checks.append({"name": "Loop Average", "status": "Critical", "value": loop_avg, "reason": "Loop > 3"})

        tool_error_rate = float(tool.get("failure_rate_pct") or 0.0)
        if tool_error_rate > 30.0:
            checks.append({"name": "Tool Error Rate", "status": "Warning", "value": tool_error_rate, "reason": "Tool Error >30%"})

        memory_hit_rate = float(memory.get("hit_rate_pct") or 0.0)
        if memory_hit_rate < 20.0 and (int(memory.get("cache_hit") or 0) + int(memory.get("cache_miss") or 0)) > 0:
            checks.append({"name": "Memory Hit Rate", "status": "Warning", "value": memory_hit_rate, "reason": "Memory Hit <20%"})

        knowledge_merge_fail = int(knowledge.get("merge_fail_count") or 0)
        if knowledge_merge_fail > 0:
            checks.append({"name": "Knowledge Merge", "status": "Critical", "value": knowledge_merge_fail, "reason": "Knowledge Merge Fail"})

        status = "Healthy"
        if any(item.get("status") == "Critical" for item in checks):
            status = "Critical"
        elif any(item.get("status") == "Warning" for item in checks):
            status = "Warning"

        return cls(
            status=status,
            score=score,
            checks=checks,
            summary={
                "critical_count": len([item for item in checks if item.get("status") == "Critical"]),
                "warning_count": len([item for item in checks if item.get("status") == "Warning"]),
            },
        )
