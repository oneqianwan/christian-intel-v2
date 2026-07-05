from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


def _coerce_str(value: Any) -> str:
    return str(value or "").strip()


def _coerce_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _coerce_str_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    items: List[str] = []
    seen = set()
    for item in value:
        text = _coerce_str(item)
        if not text or text in seen:
            continue
        seen.add(text)
        items.append(text)
    return items


def _coerce_dict(value: Any) -> Dict[str, Any]:
    return dict(value or {}) if isinstance(value, dict) else {}


@dataclass(frozen=True)
class InsightInput:
    question: str
    intent: str
    target_entities: List[str] = field(default_factory=list)
    target_scope: str = ""
    query_mode: str = ""
    tool_results: List[dict] = field(default_factory=list)
    evidence_bundle: Dict[str, Any] = field(default_factory=dict)
    knowledge_graph: Dict[str, Any] = field(default_factory=dict)
    answer_context: Dict[str, Any] = field(default_factory=dict)
    verification_result: Dict[str, Any] = field(default_factory=dict)
    score_fields: Dict[str, Any] = field(default_factory=dict)
    source_urls: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "question": self.question,
            "intent": self.intent,
            "target_entities": list(self.target_entities or []),
            "target_scope": self.target_scope,
            "query_mode": self.query_mode,
            "tool_results": [dict(item or {}) for item in (self.tool_results or []) if isinstance(item, dict)],
            "evidence_bundle": dict(self.evidence_bundle or {}),
            "knowledge_graph": dict(self.knowledge_graph or {}),
            "answer_context": dict(self.answer_context or {}),
            "verification_result": dict(self.verification_result or {}),
            "score_fields": dict(self.score_fields or {}),
            "source_urls": list(self.source_urls or []),
            "metadata": dict(self.metadata or {}),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "InsightInput":
        payload = data or {}
        return cls(
            question=_coerce_str(payload.get("question")),
            intent=_coerce_str(payload.get("intent")),
            target_entities=_coerce_str_list(payload.get("target_entities")),
            target_scope=_coerce_str(payload.get("target_scope")),
            query_mode=_coerce_str(payload.get("query_mode")),
            tool_results=[dict(item or {}) for item in (payload.get("tool_results") or []) if isinstance(item, dict)],
            evidence_bundle=_coerce_dict(payload.get("evidence_bundle")),
            knowledge_graph=_coerce_dict(payload.get("knowledge_graph")),
            answer_context=_coerce_dict(payload.get("answer_context")),
            verification_result=_coerce_dict(payload.get("verification_result")),
            score_fields=_coerce_dict(payload.get("score_fields")),
            source_urls=_coerce_str_list(payload.get("source_urls")),
            metadata=_coerce_dict(payload.get("metadata")),
        )


@dataclass(frozen=True)
class InsightFinding:
    id: str
    title: str
    summary: str
    confidence: float
    evidence_ids: List[str] = field(default_factory=list)
    source_urls: List[str] = field(default_factory=list)
    severity: str = "info"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "summary": self.summary,
            "confidence": float(self.confidence),
            "evidence_ids": list(self.evidence_ids or []),
            "source_urls": list(self.source_urls or []),
            "severity": self.severity,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "InsightFinding":
        payload = data or {}
        return cls(
            id=_coerce_str(payload.get("id")),
            title=_coerce_str(payload.get("title")),
            summary=_coerce_str(payload.get("summary")),
            confidence=_coerce_float(payload.get("confidence")),
            evidence_ids=_coerce_str_list(payload.get("evidence_ids")),
            source_urls=_coerce_str_list(payload.get("source_urls")),
            severity=_coerce_str(payload.get("severity")) or "info",
        )


@dataclass(frozen=True)
class InsightRisk:
    id: str
    title: str
    summary: str
    confidence: float
    evidence_ids: List[str] = field(default_factory=list)
    source_urls: List[str] = field(default_factory=list)
    severity: str = "medium"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "summary": self.summary,
            "confidence": float(self.confidence),
            "evidence_ids": list(self.evidence_ids or []),
            "source_urls": list(self.source_urls or []),
            "severity": self.severity,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "InsightRisk":
        payload = data or {}
        return cls(
            id=_coerce_str(payload.get("id")),
            title=_coerce_str(payload.get("title")),
            summary=_coerce_str(payload.get("summary")),
            confidence=_coerce_float(payload.get("confidence")),
            evidence_ids=_coerce_str_list(payload.get("evidence_ids")),
            source_urls=_coerce_str_list(payload.get("source_urls")),
            severity=_coerce_str(payload.get("severity")) or "medium",
        )


@dataclass(frozen=True)
class InsightOpportunity:
    id: str
    title: str
    summary: str
    confidence: float
    evidence_ids: List[str] = field(default_factory=list)
    source_urls: List[str] = field(default_factory=list)
    priority: str = "medium"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "summary": self.summary,
            "confidence": float(self.confidence),
            "evidence_ids": list(self.evidence_ids or []),
            "source_urls": list(self.source_urls or []),
            "priority": self.priority,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "InsightOpportunity":
        payload = data or {}
        return cls(
            id=_coerce_str(payload.get("id")),
            title=_coerce_str(payload.get("title")),
            summary=_coerce_str(payload.get("summary")),
            confidence=_coerce_float(payload.get("confidence")),
            evidence_ids=_coerce_str_list(payload.get("evidence_ids")),
            source_urls=_coerce_str_list(payload.get("source_urls")),
            priority=_coerce_str(payload.get("priority")) or "medium",
        )


@dataclass(frozen=True)
class InsightRecommendation:
    id: str
    title: str
    summary: str
    confidence: float
    evidence_ids: List[str] = field(default_factory=list)
    source_urls: List[str] = field(default_factory=list)
    priority: str = "medium"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "summary": self.summary,
            "confidence": float(self.confidence),
            "evidence_ids": list(self.evidence_ids or []),
            "source_urls": list(self.source_urls or []),
            "priority": self.priority,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "InsightRecommendation":
        payload = data or {}
        return cls(
            id=_coerce_str(payload.get("id")),
            title=_coerce_str(payload.get("title")),
            summary=_coerce_str(payload.get("summary")),
            confidence=_coerce_float(payload.get("confidence")),
            evidence_ids=_coerce_str_list(payload.get("evidence_ids")),
            source_urls=_coerce_str_list(payload.get("source_urls")),
            priority=_coerce_str(payload.get("priority")) or "medium",
        )


@dataclass(frozen=True)
class InsightSection:
    id: str
    title: str
    summary: str
    confidence: float
    evidence_ids: List[str] = field(default_factory=list)
    source_urls: List[str] = field(default_factory=list)
    priority: str = "medium"
    findings: List[InsightFinding] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "summary": self.summary,
            "confidence": float(self.confidence),
            "evidence_ids": list(self.evidence_ids or []),
            "source_urls": list(self.source_urls or []),
            "priority": self.priority,
            "findings": [item.to_dict() for item in (self.findings or [])],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "InsightSection":
        payload = data or {}
        return cls(
            id=_coerce_str(payload.get("id")),
            title=_coerce_str(payload.get("title")),
            summary=_coerce_str(payload.get("summary")),
            confidence=_coerce_float(payload.get("confidence")),
            evidence_ids=_coerce_str_list(payload.get("evidence_ids")),
            source_urls=_coerce_str_list(payload.get("source_urls")),
            priority=_coerce_str(payload.get("priority")) or "medium",
            findings=[InsightFinding.from_dict(item) for item in (payload.get("findings") or []) if isinstance(item, dict)],
        )


@dataclass(frozen=True)
class InsightResult:
    id: str
    title: str
    summary: str
    confidence: float
    target_entities: List[str] = field(default_factory=list)
    target_scope: str = ""
    query_mode: str = ""
    evidence_ids: List[str] = field(default_factory=list)
    source_urls: List[str] = field(default_factory=list)
    priority: str = "medium"
    executive_summary: InsightSection | None = None
    key_findings: List[InsightFinding] = field(default_factory=list)
    score_explanations: List[InsightFinding] = field(default_factory=list)
    risks: List[InsightRisk] = field(default_factory=list)
    opportunities: List[InsightOpportunity] = field(default_factory=list)
    evidence_backed_insights: List[InsightFinding] = field(default_factory=list)
    data_gaps: List[InsightFinding] = field(default_factory=list)
    recommended_next_questions: List[InsightRecommendation] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "summary": self.summary,
            "confidence": float(self.confidence),
            "target_entities": list(self.target_entities or []),
            "target_scope": self.target_scope,
            "query_mode": self.query_mode,
            "evidence_ids": list(self.evidence_ids or []),
            "source_urls": list(self.source_urls or []),
            "priority": self.priority,
            "executive_summary": self.executive_summary.to_dict() if self.executive_summary is not None else None,
            "key_findings": [item.to_dict() for item in (self.key_findings or [])],
            "score_explanations": [item.to_dict() for item in (self.score_explanations or [])],
            "risks": [item.to_dict() for item in (self.risks or [])],
            "opportunities": [item.to_dict() for item in (self.opportunities or [])],
            "evidence_backed_insights": [item.to_dict() for item in (self.evidence_backed_insights or [])],
            "data_gaps": [item.to_dict() for item in (self.data_gaps or [])],
            "recommended_next_questions": [item.to_dict() for item in (self.recommended_next_questions or [])],
            "metadata": dict(self.metadata or {}),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "InsightResult":
        payload = data or {}
        executive_summary_payload = payload.get("executive_summary")
        return cls(
            id=_coerce_str(payload.get("id")),
            title=_coerce_str(payload.get("title")),
            summary=_coerce_str(payload.get("summary")),
            confidence=_coerce_float(payload.get("confidence")),
            target_entities=_coerce_str_list(payload.get("target_entities")),
            target_scope=_coerce_str(payload.get("target_scope")),
            query_mode=_coerce_str(payload.get("query_mode")),
            evidence_ids=_coerce_str_list(payload.get("evidence_ids")),
            source_urls=_coerce_str_list(payload.get("source_urls")),
            priority=_coerce_str(payload.get("priority")) or "medium",
            executive_summary=InsightSection.from_dict(executive_summary_payload) if isinstance(executive_summary_payload, dict) else None,
            key_findings=[InsightFinding.from_dict(item) for item in (payload.get("key_findings") or []) if isinstance(item, dict)],
            score_explanations=[InsightFinding.from_dict(item) for item in (payload.get("score_explanations") or []) if isinstance(item, dict)],
            risks=[InsightRisk.from_dict(item) for item in (payload.get("risks") or []) if isinstance(item, dict)],
            opportunities=[InsightOpportunity.from_dict(item) for item in (payload.get("opportunities") or []) if isinstance(item, dict)],
            evidence_backed_insights=[InsightFinding.from_dict(item) for item in (payload.get("evidence_backed_insights") or []) if isinstance(item, dict)],
            data_gaps=[InsightFinding.from_dict(item) for item in (payload.get("data_gaps") or []) if isinstance(item, dict)],
            recommended_next_questions=[
                InsightRecommendation.from_dict(item)
                for item in (payload.get("recommended_next_questions") or [])
                if isinstance(item, dict)
            ],
            metadata=_coerce_dict(payload.get("metadata")),
        )
