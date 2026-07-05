from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass(frozen=True)
class RepairAction:
    action_type: str
    priority: int
    target: str
    reason: str
    confidence: float
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_type": self.action_type,
            "priority": int(self.priority),
            "target": self.target,
            "reason": self.reason,
            "confidence": float(self.confidence),
            "metadata": dict(self.metadata or {}),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RepairAction":
        payload = data or {}
        return cls(
            action_type=str(payload.get("action_type") or ""),
            priority=int(payload.get("priority") or 0),
            target=str(payload.get("target") or ""),
            reason=str(payload.get("reason") or ""),
            confidence=float(payload.get("confidence") or 0.0),
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass(frozen=True)
class RepairPlan:
    actions: List[RepairAction] = field(default_factory=list)
    overall_priority: int = 0
    estimated_cost: float = 0.0
    estimated_latency: float = 0.0
    repair_score: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "actions": [item.to_dict() for item in (self.actions or [])],
            "overall_priority": int(self.overall_priority),
            "estimated_cost": float(self.estimated_cost),
            "estimated_latency": float(self.estimated_latency),
            "repair_score": float(self.repair_score),
            "metadata": dict(self.metadata or {}),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RepairPlan":
        payload = data or {}
        return cls(
            actions=[RepairAction.from_dict(item) for item in (payload.get("actions") or []) if isinstance(item, dict)],
            overall_priority=int(payload.get("overall_priority") or 0),
            estimated_cost=float(payload.get("estimated_cost") or 0.0),
            estimated_latency=float(payload.get("estimated_latency") or 0.0),
            repair_score=float(payload.get("repair_score") or 0.0),
            metadata=dict(payload.get("metadata") or {}),
        )
