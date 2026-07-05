from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass(frozen=True)
class AnswerFact:
    fact_id: str
    subject: str
    predicate: str
    object: str
    confidence: float
    evidence_ids: List[str] = field(default_factory=list)
    priority: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fact_id": self.fact_id,
            "subject": self.subject,
            "predicate": self.predicate,
            "object": self.object,
            "confidence": float(self.confidence),
            "evidence_ids": list(self.evidence_ids or []),
            "priority": float(self.priority),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AnswerFact":
        payload = data or {}
        return cls(
            fact_id=str(payload.get("fact_id") or ""),
            subject=str(payload.get("subject") or ""),
            predicate=str(payload.get("predicate") or ""),
            object=str(payload.get("object") or ""),
            confidence=float(payload.get("confidence") or 0.0),
            evidence_ids=[str(item) for item in (payload.get("evidence_ids") or []) if str(item or "").strip()],
            priority=float(payload.get("priority") or 0.0),
        )


@dataclass(frozen=True)
class AnswerSection:
    section_id: str
    title: str
    facts: List[AnswerFact] = field(default_factory=list)
    citations: List[Dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "section_id": self.section_id,
            "title": self.title,
            "facts": [item.to_dict() for item in (self.facts or [])],
            "citations": [dict(item or {}) for item in (self.citations or []) if isinstance(item, dict)],
            "confidence": float(self.confidence),
            "metadata": dict(self.metadata or {}),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AnswerSection":
        payload = data or {}
        return cls(
            section_id=str(payload.get("section_id") or ""),
            title=str(payload.get("title") or ""),
            facts=[AnswerFact.from_dict(item) for item in (payload.get("facts") or []) if isinstance(item, dict)],
            citations=[dict(item or {}) for item in (payload.get("citations") or []) if isinstance(item, dict)],
            confidence=float(payload.get("confidence") or 0.0),
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass(frozen=True)
class AnswerContext:
    facts: List[AnswerFact] = field(default_factory=list)
    sections: List[AnswerSection] = field(default_factory=list)
    citations: List[Dict[str, Any]] = field(default_factory=list)
    conflicts: List[Dict[str, Any]] = field(default_factory=list)
    summary: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "facts": [item.to_dict() for item in (self.facts or [])],
            "sections": [item.to_dict() for item in (self.sections or [])],
            "citations": [dict(item or {}) for item in (self.citations or []) if isinstance(item, dict)],
            "conflicts": [dict(item or {}) for item in (self.conflicts or []) if isinstance(item, dict)],
            "summary": self.summary,
            "metadata": dict(self.metadata or {}),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AnswerContext":
        payload = data or {}
        return cls(
            facts=[AnswerFact.from_dict(item) for item in (payload.get("facts") or []) if isinstance(item, dict)],
            sections=[AnswerSection.from_dict(item) for item in (payload.get("sections") or []) if isinstance(item, dict)],
            citations=[dict(item or {}) for item in (payload.get("citations") or []) if isinstance(item, dict)],
            conflicts=[dict(item or {}) for item in (payload.get("conflicts") or []) if isinstance(item, dict)],
            summary=str(payload.get("summary") or ""),
            metadata=dict(payload.get("metadata") or {}),
        )
