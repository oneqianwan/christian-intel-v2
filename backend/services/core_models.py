from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional


class QuestionType(str, Enum):
    PROFILE = "PROFILE"
    NEWS = "NEWS"
    TIMELINE = "TIMELINE"
    COMPARISON = "COMPARISON"
    RANKING = "RANKING"
    RELATIONSHIP = "RELATIONSHIP"
    GRAPH = "GRAPH"
    CONTACT = "CONTACT"
    INVESTMENT = "INVESTMENT"
    COUNTRY = "COUNTRY"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class QuestionContext:
    question: str
    question_type: QuestionType
    language: str
    country: str
    entities: List[Dict[str, Any]]
    time_range: Optional[Dict[str, str]]
    comparison: bool
    ranking: bool
    relationship: bool
    conversation_id: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "question": self.question,
            "question_type": self.question_type.value,
            "language": self.language,
            "country": self.country,
            "entities": list(self.entities or []),
            "time_range": dict(self.time_range) if self.time_range else None,
            "comparison": bool(self.comparison),
            "ranking": bool(self.ranking),
            "relationship": bool(self.relationship),
            "conversation_id": self.conversation_id,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "QuestionContext":
        payload = data or {}
        qt_value = str(payload.get("question_type") or "UNKNOWN")
        qt = QuestionType(qt_value) if qt_value in getattr(QuestionType, "_value2member_map_", {}) else QuestionType.UNKNOWN
        return cls(
            question=str(payload.get("question") or ""),
            question_type=qt,
            language=str(payload.get("language") or ""),
            country=str(payload.get("country") or ""),
            entities=list(payload.get("entities") or []),
            time_range=dict(payload.get("time_range") or {}) if payload.get("time_range") else None,
            comparison=bool(payload.get("comparison")),
            ranking=bool(payload.get("ranking")),
            relationship=bool(payload.get("relationship")),
            conversation_id=str(payload.get("conversation_id") or ""),
        )


@dataclass(frozen=True)
class Requirement:
    required_fields: List[str]
    required_sources: List[str]
    minimum_sources: int
    minimum_confidence: float
    coverage_threshold: float
    allow_partial: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "required_fields": list(self.required_fields or []),
            "required_sources": list(self.required_sources or []),
            "minimum_sources": int(self.minimum_sources),
            "minimum_confidence": float(self.minimum_confidence),
            "coverage_threshold": float(self.coverage_threshold),
            "allow_partial": bool(self.allow_partial),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Requirement":
        payload = data or {}
        return cls(
            required_fields=list(payload.get("required_fields") or []),
            required_sources=list(payload.get("required_sources") or []),
            minimum_sources=int(payload.get("minimum_sources") or 1),
            minimum_confidence=float(payload.get("minimum_confidence") or 0.0),
            coverage_threshold=float(payload.get("coverage_threshold") or 0.0),
            allow_partial=bool(payload.get("allow_partial", True)),
        )


@dataclass(frozen=True)
class Evidence:
    id: str
    title: str
    snippet: str
    url: str
    source_name: str
    authority: float
    confidence: float
    published_at: str
    updated_at: str
    type: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "snippet": self.snippet,
            "url": self.url,
            "source_name": self.source_name,
            "authority": float(self.authority),
            "confidence": float(self.confidence),
            "published_at": self.published_at,
            "updated_at": self.updated_at,
            "type": self.type,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Evidence":
        payload = data or {}
        return cls(
            id=str(payload.get("id") or ""),
            title=str(payload.get("title") or ""),
            snippet=str(payload.get("snippet") or ""),
            url=str(payload.get("url") or ""),
            source_name=str(payload.get("source_name") or ""),
            authority=float(payload.get("authority") or 0.0),
            confidence=float(payload.get("confidence") or 0.0),
            published_at=str(payload.get("published_at") or ""),
            updated_at=str(payload.get("updated_at") or ""),
            type=str(payload.get("type") or ""),
        )


@dataclass(frozen=True)
class Fact:
    id: str
    field: str
    value: str
    confidence: float
    evidence_ids: List[str]
    sources: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "field": self.field,
            "value": self.value,
            "confidence": float(self.confidence),
            "evidence_ids": list(self.evidence_ids or []),
            "sources": list(self.sources or []),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Fact":
        payload = data or {}
        return cls(
            id=str(payload.get("id") or ""),
            field=str(payload.get("field") or ""),
            value=str(payload.get("value") or ""),
            confidence=float(payload.get("confidence") or 0.0),
            evidence_ids=list(payload.get("evidence_ids") or []),
            sources=list(payload.get("sources") or []),
        )


@dataclass(frozen=True)
class Conflict:
    field: str
    values: List[str]
    sources: List[str]
    evidence_ids: List[str]
    severity: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "field": self.field,
            "values": list(self.values or []),
            "sources": list(self.sources or []),
            "evidence_ids": list(self.evidence_ids or []),
            "severity": self.severity,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Conflict":
        payload = data or {}
        return cls(
            field=str(payload.get("field") or ""),
            values=list(payload.get("values") or []),
            sources=list(payload.get("sources") or []),
            evidence_ids=list(payload.get("evidence_ids") or []),
            severity=str(payload.get("severity") or ""),
        )


@dataclass(frozen=True)
class Section:
    title: str
    purpose: str
    fact_ids: List[str]
    citation_ids: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "purpose": self.purpose,
            "fact_ids": list(self.fact_ids or []),
            "citation_ids": list(self.citation_ids or []),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Section":
        payload = data or {}
        return cls(
            title=str(payload.get("title") or ""),
            purpose=str(payload.get("purpose") or ""),
            fact_ids=list(payload.get("fact_ids") or []),
            citation_ids=list(payload.get("citation_ids") or []),
        )


@dataclass(frozen=True)
class AnswerContext:
    question: str
    requirement: Requirement
    sections: List[Section]
    facts: List[Fact]
    conflicts: List[Conflict]
    missing: List[str]
    citation_map: Dict[str, List[str]]
    evidence: List[Evidence]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "question": self.question,
            "requirement": self.requirement.to_dict(),
            "sections": [s.to_dict() for s in (self.sections or [])],
            "facts": [f.to_dict() for f in (self.facts or [])],
            "conflicts": [c.to_dict() for c in (self.conflicts or [])],
            "missing": list(self.missing or []),
            "citation_map": {k: list(v or []) for k, v in (self.citation_map or {}).items()},
            "evidence": [e.to_dict() for e in (self.evidence or [])],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AnswerContext":
        payload = data or {}
        return cls(
            question=str(payload.get("question") or ""),
            requirement=Requirement.from_dict(payload.get("requirement") or {}),
            sections=[Section.from_dict(x) for x in (payload.get("sections") or []) if isinstance(x, dict)],
            facts=[Fact.from_dict(x) for x in (payload.get("facts") or []) if isinstance(x, dict)],
            conflicts=[Conflict.from_dict(x) for x in (payload.get("conflicts") or []) if isinstance(x, dict)],
            missing=list(payload.get("missing") or []),
            citation_map={str(k): list(v or []) for k, v in (payload.get("citation_map") or {}).items()},
            evidence=[Evidence.from_dict(x) for x in (payload.get("evidence") or []) if isinstance(x, dict)],
        )


@dataclass(frozen=True)
class MemoryContext:
    current_entity: str
    current_country: str
    current_topic: str
    current_requirement: Optional[Requirement]
    cached_evidence_ids: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "current_entity": self.current_entity,
            "current_country": self.current_country,
            "current_topic": self.current_topic,
            "current_requirement": self.current_requirement.to_dict() if self.current_requirement else None,
            "cached_evidence_ids": list(self.cached_evidence_ids or []),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MemoryContext":
        payload = data or {}
        req = payload.get("current_requirement")
        return cls(
            current_entity=str(payload.get("current_entity") or ""),
            current_country=str(payload.get("current_country") or ""),
            current_topic=str(payload.get("current_topic") or ""),
            current_requirement=Requirement.from_dict(req) if isinstance(req, dict) else None,
            cached_evidence_ids=list(payload.get("cached_evidence_ids") or []),
        )
