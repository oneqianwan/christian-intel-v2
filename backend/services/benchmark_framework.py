from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from services.core_models import AnswerContext, Conflict, Evidence, Fact, Requirement


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _clamp(score: float, minimum: float = 0.0, maximum: float = 100.0) -> float:
    return round(max(minimum, min(maximum, _to_float(score, 0.0))), 2)


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _normalize_list(values: List[Any]) -> List[str]:
    out: List[str] = []
    seen = set()
    for value in values or []:
        text = _normalize_text(value)
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


@dataclass(frozen=True)
class BenchmarkCase:
    id: str
    name: str
    description: str
    question: str
    expected_entities: List[str] = field(default_factory=list)
    expected_fields: List[str] = field(default_factory=list)
    expected_sources: List[str] = field(default_factory=list)
    expected_answer_keywords: List[str] = field(default_factory=list)
    expected_citations: int = 0
    minimum_coverage: float = 0.0
    minimum_confidence: float = 0.0
    allow_partial: bool = True
    category: str = ""
    difficulty: str = "medium"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "question": self.question,
            "expected_entities": list(self.expected_entities or []),
            "expected_fields": list(self.expected_fields or []),
            "expected_sources": list(self.expected_sources or []),
            "expected_answer_keywords": list(self.expected_answer_keywords or []),
            "expected_citations": int(self.expected_citations or 0),
            "minimum_coverage": float(self.minimum_coverage or 0.0),
            "minimum_confidence": float(self.minimum_confidence or 0.0),
            "allow_partial": bool(self.allow_partial),
            "category": self.category,
            "difficulty": self.difficulty,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BenchmarkCase":
        payload = data or {}
        return cls(
            id=str(payload.get("id") or ""),
            name=str(payload.get("name") or ""),
            description=str(payload.get("description") or ""),
            question=str(payload.get("question") or ""),
            expected_entities=list(payload.get("expected_entities") or []),
            expected_fields=list(payload.get("expected_fields") or []),
            expected_sources=list(payload.get("expected_sources") or []),
            expected_answer_keywords=list(payload.get("expected_answer_keywords") or []),
            expected_citations=int(payload.get("expected_citations") or 0),
            minimum_coverage=float(payload.get("minimum_coverage") or 0.0),
            minimum_confidence=float(payload.get("minimum_confidence") or 0.0),
            allow_partial=bool(payload.get("allow_partial", True)),
            category=str(payload.get("category") or ""),
            difficulty=str(payload.get("difficulty") or "medium"),
        )


@dataclass(frozen=True)
class BenchmarkResult:
    case_id: str
    pipeline: str
    latency_ms: float
    tool_count: int
    tool_names: List[str] = field(default_factory=list)
    coverage_score: float = 0.0
    citation_score: float = 0.0
    conflict_score: float = 0.0
    reasoning_score: float = 0.0
    answer_score: float = 0.0
    memory_hit: bool = False
    cache_hit: bool = False
    verification_pass: bool = False
    task_count: int = 0
    task_coverage: float = 0.0
    task_graph_depth: float = 0.0
    task_parallelism: float = 0.0
    task_merge_rate: float = 0.0
    success: bool = False
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "case_id": self.case_id,
            "pipeline": self.pipeline,
            "latency_ms": float(self.latency_ms or 0.0),
            "tool_count": int(self.tool_count or 0),
            "tool_names": list(self.tool_names or []),
            "coverage_score": float(self.coverage_score or 0.0),
            "citation_score": float(self.citation_score or 0.0),
            "conflict_score": float(self.conflict_score or 0.0),
            "reasoning_score": float(self.reasoning_score or 0.0),
            "answer_score": float(self.answer_score or 0.0),
            "memory_hit": bool(self.memory_hit),
            "cache_hit": bool(self.cache_hit),
            "verification_pass": bool(self.verification_pass),
            "task_count": int(self.task_count or 0),
            "task_coverage": float(self.task_coverage or 0.0),
            "task_graph_depth": float(self.task_graph_depth or 0.0),
            "task_parallelism": float(self.task_parallelism or 0.0),
            "task_merge_rate": float(self.task_merge_rate or 0.0),
            "success": bool(self.success),
            "errors": list(self.errors or []),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BenchmarkResult":
        payload = data or {}
        return cls(
            case_id=str(payload.get("case_id") or ""),
            pipeline=str(payload.get("pipeline") or ""),
            latency_ms=float(payload.get("latency_ms") or 0.0),
            tool_count=int(payload.get("tool_count") or 0),
            tool_names=list(payload.get("tool_names") or []),
            coverage_score=float(payload.get("coverage_score") or 0.0),
            citation_score=float(payload.get("citation_score") or 0.0),
            conflict_score=float(payload.get("conflict_score") or 0.0),
            reasoning_score=float(payload.get("reasoning_score") or 0.0),
            answer_score=float(payload.get("answer_score") or 0.0),
            memory_hit=bool(payload.get("memory_hit")),
            cache_hit=bool(payload.get("cache_hit")),
            verification_pass=bool(payload.get("verification_pass")),
            task_count=int(payload.get("task_count") or 0),
            task_coverage=float(payload.get("task_coverage") or 0.0),
            task_graph_depth=float(payload.get("task_graph_depth") or 0.0),
            task_parallelism=float(payload.get("task_parallelism") or 0.0),
            task_merge_rate=float(payload.get("task_merge_rate") or 0.0),
            success=bool(payload.get("success")),
            errors=list(payload.get("errors") or []),
        )


@dataclass(frozen=True)
class BenchmarkSuite:
    name: str
    cases: List[BenchmarkCase] = field(default_factory=list)
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "cases": [item.to_dict() for item in (self.cases or [])],
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BenchmarkSuite":
        payload = data or {}
        return cls(
            name=str(payload.get("name") or ""),
            cases=[BenchmarkCase.from_dict(item) for item in (payload.get("cases") or []) if isinstance(item, dict)],
            description=str(payload.get("description") or ""),
        )


def ensure_requirement(value: Any, fallback_fields: List[str] | None = None) -> Requirement:
    if isinstance(value, Requirement):
        return value
    if isinstance(value, dict):
        return Requirement.from_dict(value)
    return Requirement(
        required_fields=list(fallback_fields or []),
        required_sources=[],
        minimum_sources=1,
        minimum_confidence=0.0,
        coverage_threshold=0.0,
        allow_partial=True,
    )


def ensure_answer_context(value: Any, fallback_fields: List[str] | None = None) -> AnswerContext:
    if isinstance(value, AnswerContext):
        return value
    if isinstance(value, dict):
        return AnswerContext.from_dict(value)
    requirement = ensure_requirement(None, fallback_fields=fallback_fields)
    return AnswerContext(
        question="",
        requirement=requirement,
        sections=[],
        facts=[],
        conflicts=[],
        missing=[],
        citation_map={},
        evidence=[],
    )


def ensure_fact_list(value: Any) -> List[Fact]:
    if not isinstance(value, list):
        return []
    return [Fact.from_dict(item) if isinstance(item, dict) else item for item in value if isinstance(item, (Fact, dict))]


def ensure_conflict_list(value: Any) -> List[Conflict]:
    if not isinstance(value, list):
        return []
    return [Conflict.from_dict(item) if isinstance(item, dict) else item for item in value if isinstance(item, (Conflict, dict))]


def ensure_evidence_list(value: Any) -> List[Evidence]:
    if not isinstance(value, list):
        return []
    return [Evidence.from_dict(item) if isinstance(item, dict) else item for item in value if isinstance(item, (Evidence, dict))]


def compute_coverage_score(case: BenchmarkCase, answer_context: AnswerContext, verification: Dict[str, Any] | None = None) -> float:
    verification = dict(verification or {})
    requirement = ensure_requirement(answer_context.requirement, fallback_fields=case.expected_fields)
    required_fields = _normalize_list(requirement.required_fields or case.expected_fields)
    if not required_fields:
        return 100.0
    fact_fields = {_normalize_text(item.field) for item in ensure_fact_list(answer_context.facts)}
    explicitly_missing = {_normalize_text(item) for item in list(answer_context.missing or []) + list(verification.get("missing_fields") or [])}
    hits = 0
    for field_name in required_fields:
        if field_name in fact_fields and field_name not in explicitly_missing:
            hits += 1
    return _clamp((hits / max(len(required_fields), 1)) * 100.0)


def compute_citation_score(case: BenchmarkCase, answer_context: AnswerContext) -> float:
    facts = ensure_fact_list(answer_context.facts)
    evidence = ensure_evidence_list(answer_context.evidence)
    citation_map = dict(answer_context.citation_map or {})
    evidence_ids = {item.id for item in evidence if str(item.id or "").strip()}
    if not facts:
        if case.expected_citations <= 0:
            return 100.0 if evidence else 0.0
        return _clamp((len(evidence_ids) / max(case.expected_citations, 1)) * 100.0)
    complete = 0
    for fact in facts:
        linked = list(fact.evidence_ids or []) or list(citation_map.get(fact.id) or [])
        if linked and any(item in evidence_ids for item in linked):
            complete += 1
    completeness = complete / max(len(facts), 1)
    expected_ratio = 1.0
    if case.expected_citations > 0:
        expected_ratio = min(len(evidence_ids) / max(case.expected_citations, 1), 1.0)
    return _clamp(((completeness * 0.7) + (expected_ratio * 0.3)) * 100.0)


def compute_conflict_score(answer_context: AnswerContext) -> float:
    conflicts = ensure_conflict_list(answer_context.conflicts)
    if not conflicts:
        return 100.0
    explained = 0
    for conflict in conflicts:
        if (conflict.sources or []) and (conflict.evidence_ids or []):
            explained += 1
    penalty = min(len(conflicts) * 18.0, 70.0)
    explanation_bonus = (explained / max(len(conflicts), 1)) * 20.0
    return _clamp(100.0 - penalty + explanation_bonus)


def compute_reasoning_score(case: BenchmarkCase, answer_context: AnswerContext) -> float:
    sections = list(answer_context.sections or [])
    facts = ensure_fact_list(answer_context.facts)
    requirement = ensure_requirement(answer_context.requirement, fallback_fields=case.expected_fields)
    required_fields = _normalize_list(requirement.required_fields or case.expected_fields)
    fact_fields = {_normalize_text(item.field) for item in facts}
    field_match_ratio = 1.0 if not required_fields else len(fact_fields & set(required_fields)) / max(len(required_fields), 1)
    section_ratio = 1.0 if facts and not sections else min(len(sections) / max(len(required_fields), 1), 1.0)
    citation_ready_facts = 0
    for fact in facts:
        if fact.evidence_ids:
            citation_ready_facts += 1
    citation_ratio = 1.0 if not facts else citation_ready_facts / max(len(facts), 1)
    entity_ratio = 1.0
    if case.expected_entities:
        answer_text = _normalize_text(answer_context.question + " " + " ".join(item.value for item in facts))
        matched_entities = 0
        for entity in _normalize_list(case.expected_entities):
            if entity in answer_text:
                matched_entities += 1
        entity_ratio = matched_entities / max(len(case.expected_entities), 1)
    return _clamp(((field_match_ratio * 0.4) + (section_ratio * 0.2) + (citation_ratio * 0.2) + (entity_ratio * 0.2)) * 100.0)


def compute_answer_score(
    case: BenchmarkCase,
    *,
    answer: str,
    coverage_score: float,
    citation_score: float,
    conflict_score: float,
    reasoning_score: float,
    verification_pass: bool,
) -> float:
    base_score = (
        coverage_score * 0.3
        + citation_score * 0.25
        + conflict_score * 0.2
        + reasoning_score * 0.25
    )
    keywords = _normalize_list(case.expected_answer_keywords)
    keyword_ratio = 1.0
    if keywords:
        answer_text = _normalize_text(answer)
        matched = 0
        for keyword in keywords:
            if keyword in answer_text:
                matched += 1
        keyword_ratio = matched / max(len(keywords), 1)
    verification_bonus = 5.0 if verification_pass else 0.0
    return _clamp(base_score * (0.85 + keyword_ratio * 0.15) + verification_bonus)


def extract_average_confidence(answer_context: AnswerContext) -> float:
    fact_scores = [_to_float(item.confidence) for item in ensure_fact_list(answer_context.facts) if _to_float(item.confidence) > 0]
    evidence_scores = [_to_float(item.confidence) for item in ensure_evidence_list(answer_context.evidence) if _to_float(item.confidence) > 0]
    scores = fact_scores or evidence_scores
    if not scores:
        return 0.0
    return round(sum(scores) / len(scores), 3)


def compute_task_graph_metrics(task_graph: Any) -> Dict[str, float]:
    if task_graph is None:
        return {
            "task_count": 0.0,
            "task_coverage": 0.0,
            "task_graph_depth": 0.0,
            "task_parallelism": 0.0,
            "task_merge_rate": 0.0,
        }
    payload = task_graph.to_dict() if hasattr(task_graph, "to_dict") else dict(task_graph or {})
    tasks = list(payload.get("tasks") or [])
    metadata = dict(payload.get("metadata") or {})
    required_count = 0
    completed_like = 0
    for item in tasks:
        if not isinstance(item, dict):
            continue
        if bool(item.get("required", True)):
            required_count += 1
        if str(item.get("status") or "").strip().lower() in {"done", "completed", "pending"}:
            completed_like += 1
    coverage = (completed_like / max(required_count, 1)) * 100.0 if required_count else 0.0
    return {
        "task_count": float(len(tasks)),
        "task_coverage": _clamp(coverage),
        "task_graph_depth": _to_float(metadata.get("graph_depth"), 0.0),
        "task_parallelism": _to_float(metadata.get("parallelism"), 0.0),
        "task_merge_rate": _to_float(metadata.get("merge_rate"), 0.0),
    }


def benchmark_success(
    case: BenchmarkCase,
    *,
    answer_score: float,
    coverage_score: float,
    average_confidence: float,
    verification_pass: bool,
    errors: List[str] | None = None,
) -> bool:
    if errors:
        return False
    if coverage_score < _to_float(case.minimum_coverage, 0.0) * 100.0:
        return False
    if average_confidence < _to_float(case.minimum_confidence, 0.0):
        return False
    if not case.allow_partial and not verification_pass:
        return False
    return answer_score >= 60.0
