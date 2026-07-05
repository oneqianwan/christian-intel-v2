from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass(frozen=True)
class ReflectionIssue:
    issue_type: str
    severity: str
    description: str
    related_fact_ids: List[str] = field(default_factory=list)
    related_evidence_ids: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "issue_type": self.issue_type,
            "severity": self.severity,
            "description": self.description,
            "related_fact_ids": list(self.related_fact_ids or []),
            "related_evidence_ids": list(self.related_evidence_ids or []),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ReflectionIssue":
        payload = data or {}
        return cls(
            issue_type=str(payload.get("issue_type") or ""),
            severity=str(payload.get("severity") or ""),
            description=str(payload.get("description") or ""),
            related_fact_ids=[str(item) for item in (payload.get("related_fact_ids") or []) if str(item or "").strip()],
            related_evidence_ids=[str(item) for item in (payload.get("related_evidence_ids") or []) if str(item or "").strip()],
        )


@dataclass(frozen=True)
class ReflectionResult:
    coverage_score: float
    evidence_score: float
    reasoning_score: float
    consistency_score: float
    overall_score: float
    issues: List[ReflectionIssue] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "coverage_score": float(self.coverage_score),
            "evidence_score": float(self.evidence_score),
            "reasoning_score": float(self.reasoning_score),
            "consistency_score": float(self.consistency_score),
            "overall_score": float(self.overall_score),
            "issues": [item.to_dict() for item in (self.issues or [])],
            "suggestions": list(self.suggestions or []),
            "metadata": dict(self.metadata or {}),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ReflectionResult":
        payload = data or {}
        return cls(
            coverage_score=float(payload.get("coverage_score") or 0.0),
            evidence_score=float(payload.get("evidence_score") or 0.0),
            reasoning_score=float(payload.get("reasoning_score") or 0.0),
            consistency_score=float(payload.get("consistency_score") or 0.0),
            overall_score=float(payload.get("overall_score") or 0.0),
            issues=[ReflectionIssue.from_dict(item) for item in (payload.get("issues") or []) if isinstance(item, dict)],
            suggestions=[str(item) for item in (payload.get("suggestions") or []) if str(item or "").strip()],
            metadata=dict(payload.get("metadata") or {}),
        )
