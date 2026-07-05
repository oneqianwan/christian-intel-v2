from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List

from services.e2e_dataset import EvaluationCase, get_default_e2e_dataset
from services.feature_flags import feature_flag_enabled
from services.e2e_metrics import (
    EvaluationResult,
    aggregate_results,
    compare_result_sets,
    compute_answer_accuracy,
    compute_citation_precision,
    compute_entity_recall,
    compute_fact_recall,
    compute_reasoning_quality,
    extract_answer_context_payload,
    extract_answer_text,
    extract_reasoning_payload,
    extract_repair_flags,
    extract_token_usage,
    extract_tool_names,
    extract_verification_payload,
)
from services.trace_center import TraceCenter


class EndToEndEvaluator:
    def __init__(
        self,
        agent: Any,
        *,
        dataset: List[EvaluationCase] | None = None,
        trace_center: TraceCenter | None = None,
    ):
        self.agent = agent
        self.dataset = list(dataset or get_default_e2e_dataset())
        self.trace_center = trace_center or TraceCenter(enabled=True)
        self.last_trace: Dict[str, Any] = {}

    def run_case(self, case: EvaluationCase) -> EvaluationResult:
        if not self._enabled():
            return EvaluationResult(
                answer_accuracy=0.0,
                entity_recall=0.0,
                fact_recall=0.0,
                citation_precision=0.0,
                reasoning_quality=0.0,
                latency=0.0,
                tool_count=0,
                token_usage=0,
                repair_triggered=False,
                repair_success=False,
                metadata={"case_id": case.case_id, "category": case.category, "disabled": True, "score": 0.0},
            )
        self._start_trace(case.question, pipeline="EndToEndEvaluator")
        started = time.perf_counter()
        errors: List[str] = []
        response: Dict[str, Any] = {}
        try:
            response = self._run_agent(case)
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
        latency = round((time.perf_counter() - started) * 1000, 2)
        answer = extract_answer_text(response)
        answer_context = extract_answer_context_payload(response)
        verification = extract_verification_payload(response)
        reasoning_context = extract_reasoning_payload(response)
        runtime_trace = self._extract_runtime_trace()
        tool_names = extract_tool_names(runtime_trace)
        token_usage = extract_token_usage(response, runtime_trace)
        repair_flags = extract_repair_flags(verification)
        result = EvaluationResult(
            answer_accuracy=compute_answer_accuracy(case, answer, answer_context, verification),
            entity_recall=compute_entity_recall(case, answer, answer_context),
            fact_recall=compute_fact_recall(case, answer_context),
            citation_precision=compute_citation_precision(case, answer_context),
            reasoning_quality=compute_reasoning_quality(case, answer_context, reasoning_context),
            latency=latency,
            tool_count=len(tool_names),
            token_usage=token_usage,
            repair_triggered=bool(repair_flags.get("repair_triggered")),
            repair_success=bool(repair_flags.get("repair_success")),
            metadata={
                "case_id": case.case_id,
                "category": case.category,
                "difficulty": case.difficulty,
                "pipeline": str(runtime_trace.get("pipeline") or ""),
                "tool_names": tool_names,
                "errors": errors,
            },
        )
        result_dict = result.to_dict()
        result_dict["metadata"] = {
            **dict(result_dict.get("metadata") or {}),
            "score": self.compute_score(result),
        }
        final_result = EvaluationResult.from_dict(result_dict)
        self.last_trace = self._finish_trace(
            summary={"case_id": case.case_id, "score": self.compute_score(final_result), "latency": latency},
            pipeline="EndToEndEvaluator",
        )
        return final_result

    def run_dataset(self, dataset: List[EvaluationCase] | None = None) -> Dict[str, Any]:
        active_dataset = list(dataset or self.dataset)
        results = [self.run_case(case) for case in active_dataset]
        return self.export_report(results, dataset=active_dataset)

    def compare_versions(
        self,
        baseline_results: List[EvaluationResult | Dict[str, Any]],
        current_results: List[EvaluationResult | Dict[str, Any]],
    ) -> Dict[str, Any]:
        return compare_result_sets(baseline_results, current_results)

    def export_report(
        self,
        results: List[EvaluationResult | Dict[str, Any]],
        *,
        dataset: List[EvaluationCase] | None = None,
        comparison: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        active_dataset = list(dataset or self.dataset)
        normalized = [item if isinstance(item, EvaluationResult) else EvaluationResult.from_dict(item) for item in (results or [])]
        summary = aggregate_results(normalized)
        rows = []
        for item in normalized:
            payload = item.to_dict()
            metadata = dict(payload.get("metadata") or {})
            rows.append(
                {
                    "case_id": str(metadata.get("case_id") or ""),
                    "category": str(metadata.get("category") or ""),
                    "difficulty": str(metadata.get("difficulty") or ""),
                    "answer_accuracy": payload.get("answer_accuracy"),
                    "entity_recall": payload.get("entity_recall"),
                    "fact_recall": payload.get("fact_recall"),
                    "citation_precision": payload.get("citation_precision"),
                    "reasoning_quality": payload.get("reasoning_quality"),
                    "latency": payload.get("latency"),
                    "tool_count": payload.get("tool_count"),
                    "token_usage": payload.get("token_usage"),
                    "repair_triggered": payload.get("repair_triggered"),
                    "repair_success": payload.get("repair_success"),
                    "score": metadata.get("score", 0.0),
                    "errors": list(metadata.get("errors") or []),
                }
            )
        rows.sort(key=lambda item: float(item.get("score") or 0.0))
        worst_cases = rows[:10]
        top_improvement = sorted(
            list((comparison or {}).get("case_deltas") or []),
            key=lambda item: float(item.get("score_delta") or 0.0),
            reverse=True,
        )[:10]
        top_regression = sorted(
            list((comparison or {}).get("case_deltas") or []),
            key=lambda item: float(item.get("score_delta") or 0.0),
        )[:10]
        markdown_lines = [
            "# End-to-End Evaluation Report",
            "",
            f"- Total Cases: {summary.get('total_cases', 0)}",
            f"- Accuracy: {summary.get('average_accuracy', 0.0)}",
            f"- Fact Recall: {summary.get('average_fact_recall', 0.0)}",
            f"- Citation Precision: {summary.get('average_citation_precision', 0.0)}",
            f"- Entity Recall: {summary.get('average_entity_recall', 0.0)}",
            f"- Reasoning Quality: {summary.get('average_reasoning_quality', 0.0)}",
            f"- Average Latency: {summary.get('average_latency', 0.0)} ms",
            f"- Average Tool Count: {summary.get('average_tool_count', 0.0)}",
            f"- Average Token Usage: {summary.get('average_token_usage', 0.0)}",
            f"- Repair Trigger Rate: {summary.get('repair_trigger_rate', 0.0)}%",
            f"- Repair Success Rate: {summary.get('repair_success_rate', 0.0)}%",
            f"- Overall Score: {summary.get('overall_score', 0.0)}",
            "",
            "## Worst Cases",
        ]
        for item in worst_cases:
            markdown_lines.append(
                f"- {item['case_id']} | {item['category']} | score={item['score']} | accuracy={item['answer_accuracy']} | citation={item['citation_precision']}"
            )
        markdown_lines.append("")
        markdown_lines.append("## Top Improvement")
        for item in top_improvement:
            markdown_lines.append(f"- {item.get('case_id')} | score_delta={item.get('score_delta')} | accuracy_delta={item.get('accuracy_delta')}")
        markdown_lines.append("")
        markdown_lines.append("## Top Regression")
        for item in top_regression:
            markdown_lines.append(f"- {item.get('case_id')} | score_delta={item.get('score_delta')} | accuracy_delta={item.get('accuracy_delta')}")
        markdown_lines.append("")
        markdown_lines.append("## Summary")
        markdown_lines.append(
            f"- Dataset Categories: {', '.join(sorted({case.category for case in active_dataset if str(case.category or '').strip()}))}"
        )
        return {
            "dataset": [item.to_dict() for item in active_dataset],
            "summary": summary,
            "results": rows,
            "comparison": dict(comparison or {}),
            "top_improvement": top_improvement,
            "top_regression": top_regression,
            "worst_cases": worst_cases,
            "json": {
                "summary": summary,
                "comparison": dict(comparison or {}),
                "results": rows,
                "top_improvement": top_improvement,
                "top_regression": top_regression,
                "worst_cases": worst_cases,
            },
            "markdown": "\n".join(markdown_lines).strip(),
        }

    def compute_score(self, result: EvaluationResult | Dict[str, Any]) -> float:
        item = result if isinstance(result, EvaluationResult) else EvaluationResult.from_dict(result or {})
        return round(
            item.answer_accuracy * 0.3
            + item.entity_recall * 0.15
            + item.fact_recall * 0.2
            + item.citation_precision * 0.15
            + item.reasoning_quality * 0.2,
            2,
        )

    def _enabled(self) -> bool:
        return feature_flag_enabled("E2E_EVALUATION_ENABLED")

    def _run_agent(self, case: EvaluationCase) -> Dict[str, Any]:
        conversation_id = f"e2e-{case.case_id}-{uuid.uuid4().hex[:8]}"
        history: List[dict] = []
        if hasattr(self.agent, "think") and callable(getattr(self.agent, "think")):
            return dict(self.agent.think(case.question, conversation_id, history) or {})
        if callable(self.agent):
            return dict(self.agent(case.question, conversation_id, history) or {})
        raise TypeError("agent must expose think() or be callable")

    def _extract_runtime_trace(self) -> Dict[str, Any]:
        if hasattr(self.agent, "_last_trace_session"):
            trace = getattr(self.agent, "_last_trace_session") or {}
            if isinstance(trace, dict):
                return dict(trace)
        return {}

    def _start_trace(self, question: str, *, pipeline: str) -> None:
        self.trace_center.start_session(question, pipeline=pipeline)

    def _finish_trace(self, *, summary: Dict[str, Any], pipeline: str) -> Dict[str, Any]:
        session = self.trace_center.finish_session(summary=summary, pipeline=pipeline)
        if session is None:
            return {}
        return session.to_dict()
