from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from services.e2e_dataset import EvaluationCase


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _normalize_list(values: List[Any]) -> List[str]:
    out: List[str] = []
    seen = set()
    for item in values or []:
        text = _normalize_text(item)
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _clamp(value: float, minimum: float = 0.0, maximum: float = 100.0) -> float:
    return round(max(minimum, min(maximum, float(value or 0.0))), 2)


@dataclass(frozen=True)
class EvaluationResult:
    answer_accuracy: float
    entity_recall: float
    fact_recall: float
    citation_precision: float
    reasoning_quality: float
    latency: float
    tool_count: int
    token_usage: int
    repair_triggered: bool
    repair_success: bool
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "answer_accuracy": float(self.answer_accuracy or 0.0),
            "entity_recall": float(self.entity_recall or 0.0),
            "fact_recall": float(self.fact_recall or 0.0),
            "citation_precision": float(self.citation_precision or 0.0),
            "reasoning_quality": float(self.reasoning_quality or 0.0),
            "latency": float(self.latency or 0.0),
            "tool_count": int(self.tool_count or 0),
            "token_usage": int(self.token_usage or 0),
            "repair_triggered": bool(self.repair_triggered),
            "repair_success": bool(self.repair_success),
            "metadata": dict(self.metadata or {}),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EvaluationResult":
        payload = data or {}
        return cls(
            answer_accuracy=float(payload.get("answer_accuracy") or 0.0),
            entity_recall=float(payload.get("entity_recall") or 0.0),
            fact_recall=float(payload.get("fact_recall") or 0.0),
            citation_precision=float(payload.get("citation_precision") or 0.0),
            reasoning_quality=float(payload.get("reasoning_quality") or 0.0),
            latency=float(payload.get("latency") or 0.0),
            tool_count=int(payload.get("tool_count") or 0),
            token_usage=int(payload.get("token_usage") or 0),
            repair_triggered=bool(payload.get("repair_triggered")),
            repair_success=bool(payload.get("repair_success")),
            metadata=dict(payload.get("metadata") or {}),
        )


def extract_tool_names(trace: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    seen = set()
    for stage in list(trace.get("stages") or []):
        for event in list(stage.get("events") or []):
            metadata = dict(event.get("metadata") or {})
            tool_name = str(metadata.get("tool_name") or "").strip()
            if event.get("name") == "Tool Executed" and tool_name and tool_name not in seen:
                seen.add(tool_name)
                out.append(tool_name)
    return out


def extract_token_usage(response: Dict[str, Any], trace: Dict[str, Any]) -> int:
    usage = dict(response.get("usage") or {})
    total = int(usage.get("total_tokens") or 0)
    if total > 0:
        return total
    for stage in list(trace.get("stages") or []):
        for event in list(stage.get("events") or []):
            metadata = dict(event.get("metadata") or {})
            tokens = int(metadata.get("total_tokens") or metadata.get("token_usage") or 0)
            if tokens > 0:
                total += tokens
    return total


def extract_answer_text(response: Dict[str, Any]) -> str:
    return str(response.get("answer") or response.get("content") or "")


def extract_answer_context_payload(response: Dict[str, Any]) -> Dict[str, Any]:
    value = response.get("answer_context")
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "to_dict"):
        try:
            return dict(value.to_dict())
        except Exception:
            return {}
    return {}


def extract_verification_payload(response: Dict[str, Any]) -> Dict[str, Any]:
    return dict(response.get("verification") or {})


def extract_reasoning_payload(response: Dict[str, Any]) -> Dict[str, Any]:
    metadata = dict((extract_answer_context_payload(response).get("metadata") or {}))
    return dict(metadata.get("reasoning_context") or {})


def compute_answer_accuracy(case: EvaluationCase, answer: str, answer_context: Dict[str, Any], verification: Dict[str, Any]) -> float:
    answer_text = _normalize_text(answer)
    expected_tokens = _normalize_list(str(case.expected_answer or "").split())
    hit = 0
    for token in expected_tokens:
        if token in answer_text:
            hit += 1
    answer_ratio = 1.0 if not expected_tokens else hit / max(len(expected_tokens), 1)
    verification_bonus = 0.1 if bool(verification.get("answer_ready")) else 0.0
    fact_bonus = min(len(list(answer_context.get("facts") or [])) / max(len(case.expected_facts or []), 1), 1.0) * 0.2 if case.expected_facts else 0.0
    return _clamp((answer_ratio * 0.7 + fact_bonus + verification_bonus) * 100.0)


def compute_entity_recall(case: EvaluationCase, answer: str, answer_context: Dict[str, Any]) -> float:
    expected = _normalize_list(case.expected_entities)
    if not expected:
        return 100.0
    facts = [dict(item or {}) for item in (answer_context.get("facts") or []) if isinstance(item, dict)]
    fact_parts: List[str] = []
    for item in facts:
        fact_parts.extend(
            [
                str(item.get("subject") or ""),
                str(item.get("predicate") or ""),
                str(item.get("object") or ""),
                str(item.get("value") or ""),
            ]
        )
    fact_text = " ".join(fact_parts)
    haystack = _normalize_text(f"{answer} {fact_text}")
    matched = sum(1 for entity in expected if entity in haystack)
    return _clamp((matched / max(len(expected), 1)) * 100.0)


def compute_fact_recall(case: EvaluationCase, answer_context: Dict[str, Any]) -> float:
    expected = _normalize_list(case.expected_facts)
    if not expected:
        return 100.0
    facts = [dict(item or {}) for item in (answer_context.get("facts") or []) if isinstance(item, dict)]
    observed = set()
    for item in facts:
        observed.add(_normalize_text(item.get("field") or item.get("predicate") or ""))
        observed.add(_normalize_text(item.get("object") or item.get("value") or ""))
    matched = sum(1 for fact in expected if fact in observed)
    return _clamp((matched / max(len(expected), 1)) * 100.0)


def compute_citation_precision(case: EvaluationCase, answer_context: Dict[str, Any]) -> float:
    facts = [dict(item or {}) for item in (answer_context.get("facts") or []) if isinstance(item, dict)]
    evidence = [dict(item or {}) for item in (answer_context.get("evidence") or []) if isinstance(item, dict)]
    citation_map = dict(answer_context.get("citation_map") or {})
    if not evidence and case.expected_citations <= 0:
        return 100.0
    valid_evidence = {
        str(item.get("id") or item.get("evidence_id") or "")
        for item in evidence
        if str(item.get("id") or item.get("evidence_id") or "").strip()
    }
    cited = 0
    linked = 0
    for fact in facts:
        links = list(fact.get("evidence_ids") or []) or list(citation_map.get(str(fact.get("id") or fact.get("fact_id") or "")) or [])
        if links:
            linked += 1
            if any(str(item) in valid_evidence for item in links):
                cited += 1
    if linked <= 0:
        expected_ratio = min(len(valid_evidence) / max(case.expected_citations, 1), 1.0) if case.expected_citations > 0 else 0.0
        return _clamp(expected_ratio * 100.0)
    return _clamp((cited / max(linked, 1)) * 100.0)


def compute_reasoning_quality(case: EvaluationCase, answer_context: Dict[str, Any], reasoning_context: Dict[str, Any]) -> float:
    sections = [dict(item or {}) for item in (answer_context.get("sections") or []) if isinstance(item, dict)]
    reasoning_graph = dict(reasoning_context.get("reasoning_graph") or {})
    nodes = [dict(item or {}) for item in (reasoning_graph.get("nodes") or []) if isinstance(item, dict)]
    edges = [dict(item or {}) for item in (reasoning_graph.get("edges") or []) if isinstance(item, dict)]
    conclusions = [item for item in nodes if _normalize_text(item.get("node_type")) == "conclusion"]
    expected = _normalize_list(case.expected_reasoning)
    edge_relations = {_normalize_text(item.get("relation")) for item in edges}
    matched = sum(1 for item in expected if item in edge_relations or item in _normalize_text(" ".join(str(section.get("title") or "") for section in sections)))
    expected_ratio = 1.0 if not expected else matched / max(len(expected), 1)
    conclusion_ratio = 1.0 if conclusions else 0.0
    structure_ratio = 1.0 if sections else 0.0
    return _clamp((expected_ratio * 0.4 + conclusion_ratio * 0.3 + structure_ratio * 0.3) * 100.0)


def extract_repair_flags(verification: Dict[str, Any]) -> Dict[str, bool]:
    metadata = dict(verification.get("metadata") or {})
    repair_plan = dict(metadata.get("repair_plan") or {})
    repair_execution = dict(metadata.get("repair_execution") or {})
    return {
        "repair_triggered": bool(repair_plan),
        "repair_success": bool(repair_execution.get("repair_completed")),
    }


def aggregate_results(results: List[EvaluationResult | Dict[str, Any]]) -> Dict[str, Any]:
    normalized = [item if isinstance(item, EvaluationResult) else EvaluationResult.from_dict(item) for item in (results or [])]
    total = len(normalized)
    if total <= 0:
        return {
            "total_cases": 0,
            "average_accuracy": 0.0,
            "average_entity_recall": 0.0,
            "average_fact_recall": 0.0,
            "average_citation_precision": 0.0,
            "average_reasoning_quality": 0.0,
            "average_latency": 0.0,
            "average_tool_count": 0.0,
            "average_token_usage": 0.0,
            "repair_trigger_rate": 0.0,
            "repair_success_rate": 0.0,
            "overall_score": 0.0,
        }
    repair_triggered = sum(1 for item in normalized if item.repair_triggered)
    repair_success = sum(1 for item in normalized if item.repair_success)
    average_accuracy = round(sum(item.answer_accuracy for item in normalized) / total, 2)
    average_entity_recall = round(sum(item.entity_recall for item in normalized) / total, 2)
    average_fact_recall = round(sum(item.fact_recall for item in normalized) / total, 2)
    average_citation_precision = round(sum(item.citation_precision for item in normalized) / total, 2)
    average_reasoning_quality = round(sum(item.reasoning_quality for item in normalized) / total, 2)
    average_latency = round(sum(item.latency for item in normalized) / total, 2)
    average_tool_count = round(sum(item.tool_count for item in normalized) / total, 2)
    average_token_usage = round(sum(item.token_usage for item in normalized) / total, 2)
    repair_trigger_rate = round((repair_triggered / total) * 100.0, 2)
    repair_success_rate = round((repair_success / max(repair_triggered, 1)) * 100.0, 2) if repair_triggered else 0.0
    overall_score = _clamp(
        average_accuracy * 0.3
        + average_entity_recall * 0.15
        + average_fact_recall * 0.2
        + average_citation_precision * 0.15
        + average_reasoning_quality * 0.2
    )
    return {
        "total_cases": total,
        "average_accuracy": average_accuracy,
        "average_entity_recall": average_entity_recall,
        "average_fact_recall": average_fact_recall,
        "average_citation_precision": average_citation_precision,
        "average_reasoning_quality": average_reasoning_quality,
        "average_latency": average_latency,
        "average_tool_count": average_tool_count,
        "average_token_usage": average_token_usage,
        "repair_trigger_rate": repair_trigger_rate,
        "repair_success_rate": repair_success_rate,
        "overall_score": overall_score,
    }


def compare_result_sets(
    baseline_results: List[EvaluationResult | Dict[str, Any]],
    current_results: List[EvaluationResult | Dict[str, Any]],
) -> Dict[str, Any]:
    baseline = [item if isinstance(item, EvaluationResult) else EvaluationResult.from_dict(item) for item in (baseline_results or [])]
    current = [item if isinstance(item, EvaluationResult) else EvaluationResult.from_dict(item) for item in (current_results or [])]
    baseline_map = {str((item.metadata or {}).get("case_id") or f"baseline-{idx}"): item for idx, item in enumerate(baseline, start=1)}
    current_map = {str((item.metadata or {}).get("case_id") or f"current-{idx}"): item for idx, item in enumerate(current, start=1)}
    case_ids = sorted(set(baseline_map) | set(current_map))
    deltas: List[Dict[str, Any]] = []
    for case_id in case_ids:
        left = baseline_map.get(case_id)
        right = current_map.get(case_id)
        left_score = float((left.metadata or {}).get("score") or 0.0) if left is not None else 0.0
        right_score = float((right.metadata or {}).get("score") or 0.0) if right is not None else 0.0
        deltas.append(
            {
                "case_id": case_id,
                "accuracy_delta": round((right.answer_accuracy if right else 0.0) - (left.answer_accuracy if left else 0.0), 2),
                "citation_delta": round((right.citation_precision if right else 0.0) - (left.citation_precision if left else 0.0), 2),
                "runtime_delta": round((right.latency if right else 0.0) - (left.latency if left else 0.0), 2),
                "tool_delta": int((right.tool_count if right else 0) - (left.tool_count if left else 0)),
                "repair_delta": round((100.0 if (right.repair_success if right else False) else 0.0) - (100.0 if (left.repair_success if left else False) else 0.0), 2),
                "score_delta": round(right_score - left_score, 2),
            }
        )
    baseline_summary = aggregate_results(baseline)
    current_summary = aggregate_results(current)
    delta_summary = {
        "accuracy_delta": round(current_summary.get("average_accuracy", 0.0) - baseline_summary.get("average_accuracy", 0.0), 2),
        "citation_delta": round(current_summary.get("average_citation_precision", 0.0) - baseline_summary.get("average_citation_precision", 0.0), 2),
        "runtime_delta": round(current_summary.get("average_latency", 0.0) - baseline_summary.get("average_latency", 0.0), 2),
        "tool_delta": round(current_summary.get("average_tool_count", 0.0) - baseline_summary.get("average_tool_count", 0.0), 2),
        "repair_delta": round(current_summary.get("repair_success_rate", 0.0) - baseline_summary.get("repair_success_rate", 0.0), 2),
        "overall_score_delta": round(current_summary.get("overall_score", 0.0) - baseline_summary.get("overall_score", 0.0), 2),
    }
    return {
        "baseline": baseline_summary,
        "current": current_summary,
        "delta": delta_summary,
        "case_deltas": deltas,
    }
