from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass(frozen=True)
class Evidence:
    evidence_id: str
    source_id: str
    source_type: str
    url: str
    title: str
    snippet: str
    raw_content: str
    confidence: float
    relevance: float
    created_at: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "source_id": self.source_id,
            "source_type": self.source_type,
            "url": self.url,
            "title": self.title,
            "snippet": self.snippet,
            "raw_content": self.raw_content,
            "confidence": float(self.confidence),
            "relevance": float(self.relevance),
            "created_at": self.created_at,
            "metadata": dict(self.metadata or {}),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Evidence":
        payload = data or {}
        return cls(
            evidence_id=str(payload.get("evidence_id") or payload.get("id") or ""),
            source_id=str(payload.get("source_id") or ""),
            source_type=str(payload.get("source_type") or payload.get("type") or ""),
            url=str(payload.get("url") or ""),
            title=str(payload.get("title") or ""),
            snippet=str(payload.get("snippet") or ""),
            raw_content=str(payload.get("raw_content") or payload.get("content") or ""),
            confidence=float(payload.get("confidence") or 0.0),
            relevance=float(payload.get("relevance") or 0.0),
            created_at=str(payload.get("created_at") or payload.get("updated_at") or payload.get("published_at") or ""),
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass(frozen=True)
class Fact:
    fact_id: str
    subject: str
    predicate: str
    object: str
    evidence_ids: List[str] = field(default_factory=list)
    confidence: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fact_id": self.fact_id,
            "subject": self.subject,
            "predicate": self.predicate,
            "object": self.object,
            "evidence_ids": list(self.evidence_ids or []),
            "confidence": float(self.confidence),
            "metadata": dict(self.metadata or {}),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Fact":
        payload = data or {}
        return cls(
            fact_id=str(payload.get("fact_id") or payload.get("id") or ""),
            subject=str(payload.get("subject") or ""),
            predicate=str(payload.get("predicate") or payload.get("field") or ""),
            object=str(payload.get("object") or payload.get("value") or ""),
            evidence_ids=[str(item) for item in (payload.get("evidence_ids") or []) if str(item or "").strip()],
            confidence=float(payload.get("confidence") or 0.0),
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass(frozen=True)
class Source:
    source_id: str
    source_type: str
    authority: float
    domain: str
    retrieved_at: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_type": self.source_type,
            "authority": float(self.authority),
            "domain": self.domain,
            "retrieved_at": self.retrieved_at,
            "metadata": dict(self.metadata or {}),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Source":
        payload = data or {}
        return cls(
            source_id=str(payload.get("source_id") or ""),
            source_type=str(payload.get("source_type") or ""),
            authority=float(payload.get("authority") or 0.0),
            domain=str(payload.get("domain") or ""),
            retrieved_at=str(payload.get("retrieved_at") or payload.get("updated_at") or payload.get("published_at") or ""),
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass(frozen=True)
class EvidenceBundle:
    evidences: List[Evidence] = field(default_factory=list)
    facts: List[Fact] = field(default_factory=list)
    sources: List[Source] = field(default_factory=list)
    conflicts: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "evidences": [item.to_dict() for item in (self.evidences or [])],
            "facts": [item.to_dict() for item in (self.facts or [])],
            "sources": [item.to_dict() for item in (self.sources or [])],
            "conflicts": [dict(item or {}) for item in (self.conflicts or []) if isinstance(item, dict)],
            "metadata": dict(self.metadata or {}),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EvidenceBundle":
        payload = data or {}
        return cls(
            evidences=[Evidence.from_dict(item) for item in (payload.get("evidences") or []) if isinstance(item, dict)],
            facts=[Fact.from_dict(item) for item in (payload.get("facts") or []) if isinstance(item, dict)],
            sources=[Source.from_dict(item) for item in (payload.get("sources") or []) if isinstance(item, dict)],
            conflicts=[dict(item or {}) for item in (payload.get("conflicts") or []) if isinstance(item, dict)],
            metadata=dict(payload.get("metadata") or {}),
        )
