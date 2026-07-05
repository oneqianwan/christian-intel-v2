from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List

from services.benchmark_framework import (
    BenchmarkCase,
    BenchmarkResult,
    BenchmarkSuite,
    benchmark_success,
    compute_answer_score,
    compute_citation_score,
    compute_conflict_score,
    compute_coverage_score,
    compute_reasoning_score,
    ensure_answer_context,
    extract_average_confidence,
)
from services.e2e_dataset import EvaluationCase, get_default_e2e_dataset
from services.e2e_evaluator import EndToEndEvaluator
from services.e2e_metrics import EvaluationResult
from services.feature_flags import feature_flag_enabled
from services.default_benchmark_suite import get_default_benchmark_suite
from services.trace_center import TraceCenter


class BenchmarkRunner:
    def __init__(
        self,
        agent: Any,
        *,
        suite: BenchmarkSuite | None = None,
        trace_center: TraceCenter | None = None,
    ):
        self.agent = agent
        self.suite = suite or get_default_benchmark_suite()
        self.trace_center = trace_center or TraceCenter(enabled=True)
        self.last_trace: Dict[str, Any] = {}

    def run_e2e_dataset(self, dataset: List[EvaluationCase] | None = None) -> Dict[str, Any]:
        evaluator = self._get_e2e_evaluator(dataset=dataset)
        return evaluator.run_dataset(dataset=dataset)

    def compare_e2e_versions(
        self,
        baseline_results: List[EvaluationResult | Dict[str, Any]],
        current_results: List[EvaluationResult | Dict[str, Any]],
    ) -> Dict[str, Any]:
        evaluator = self._get_e2e_evaluator()
        comparison = evaluator.compare_versions(baseline_results, current_results)
        return evaluator.export_report(current_results, comparison=comparison)

    def run_case(self, case: BenchmarkCase) -> BenchmarkResult:
        if not self._enabled():
            return BenchmarkResult(
                case_id=case.id,
                pipeline="",
                latency_ms=0.0,
                tool_count=0,
                tool_names=[],
                coverage_score=0.0,
                citation_score=0.0,
                conflict_score=0.0,
                reasoning_score=0.0,
                answer_score=0.0,
                memory_hit=False,
                cache_hit=False,
                verification_pass=False,
                success=False,
                errors=["benchmark_framework_disabled"],
            )

        self._start_trace(case.question, pipeline="BenchmarkRunner")
        self._trace("BENCHMARK", "Benchmark Started", metadata={"case_id": case.id, "category": case.category})

        started = time.perf_counter()
        errors: List[str] = []
        response: Dict[str, Any] = {}
        try:
            response = self._run_agent(case)
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
        latency_ms = round((time.perf_counter() - started) * 1000, 2)

        answer_context = ensure_answer_context(response.get("answer_context"), fallback_fields=case.expected_fields)
        verification = dict(response.get("verification") or {})
        answer = str(response.get("answer") or "")
        runtime_trace = self._extract_runtime_trace()

        coverage_score = compute_coverage_score(case, answer_context, verification)
        citation_score = compute_citation_score(case, answer_context)
        conflict_score = compute_conflict_score(answer_context)
        reasoning_score = compute_reasoning_score(case, answer_context)
        verification_pass = self._verification_pass(verification)
        answer_score = compute_answer_score(
            case,
            answer=answer,
            coverage_score=coverage_score,
            citation_score=citation_score,
            conflict_score=conflict_score,
            reasoning_score=reasoning_score,
            verification_pass=verification_pass,
        )
        average_confidence = extract_average_confidence(answer_context)
        tool_names = self._extract_tool_names(runtime_trace)
        result = BenchmarkResult(
            case_id=case.id,
            pipeline=self._extract_pipeline(runtime_trace),
            latency_ms=latency_ms,
            tool_count=len(tool_names),
            tool_names=tool_names,
            coverage_score=coverage_score,
            citation_score=citation_score,
            conflict_score=conflict_score,
            reasoning_score=reasoning_score,
            answer_score=answer_score,
            memory_hit=self._memory_hit(runtime_trace),
            cache_hit=self._cache_hit(runtime_trace),
            verification_pass=verification_pass,
            success=benchmark_success(
                case,
                answer_score=answer_score,
                coverage_score=coverage_score,
                average_confidence=average_confidence,
                verification_pass=verification_pass,
                errors=errors,
            ),
            errors=errors,
        )

        self._trace(
            "BENCHMARK",
            "Benchmark Finished",
            metadata={
                "case_id": case.id,
                "pipeline": result.pipeline,
                "latency_ms": result.latency_ms,
                "answer_score": result.answer_score,
            },
        )
        self._trace(
            "BENCHMARK",
            "Benchmark Passed" if result.success else "Benchmark Failed",
            status="ok" if result.success else "failed",
            metadata={"case_id": case.id, "errors": list(result.errors or [])},
        )
        self.last_trace = self._finish_trace(
            summary={"case_id": case.id, "success": result.success, "answer_score": result.answer_score},
            pipeline=result.pipeline or "BenchmarkRunner",
        )
        return result

    def run_suite(self, suite: BenchmarkSuite | None = None) -> Dict[str, Any]:
        active_suite = suite or self.suite
        results: List[BenchmarkResult] = []
        for case in active_suite.cases or []:
            results.append(self.run_case(case))
        return self.export_report(results, suite=active_suite)

    def compare_results(
        self,
        baseline_results: List[BenchmarkResult | Dict[str, Any]],
        candidate_results: List[BenchmarkResult | Dict[str, Any]],
    ) -> Dict[str, Any]:
        self._start_trace("benchmark-compare", pipeline="BenchmarkCompare")
        baseline = {item.case_id: item for item in self._ensure_results(baseline_results)}
        candidate = {item.case_id: item for item in self._ensure_results(candidate_results)}
        compared_cases = sorted(set(baseline) | set(candidate))
        deltas: List[Dict[str, Any]] = []
        improved = 0
        regressed = 0
        unchanged = 0

        for case_id in compared_cases:
            left = baseline.get(case_id)
            right = candidate.get(case_id)
            left_score = left.answer_score if left is not None else 0.0
            right_score = right.answer_score if right is not None else 0.0
            delta = round(right_score - left_score, 2)
            status = "unchanged"
            if delta > 0:
                improved += 1
                status = "improved"
            elif delta < 0:
                regressed += 1
                status = "regressed"
            else:
                unchanged += 1
            deltas.append(
                {
                    "case_id": case_id,
                    "baseline_score": left_score,
                    "candidate_score": right_score,
                    "delta_score": delta,
                    "baseline_latency_ms": left.latency_ms if left is not None else 0.0,
                    "candidate_latency_ms": right.latency_ms if right is not None else 0.0,
                    "status": status,
                }
            )

        self._trace(
            "BENCHMARK",
            "Benchmark Compared",
            metadata={"compared_case_count": len(compared_cases), "improved": improved, "regressed": regressed, "unchanged": unchanged},
        )
        self.last_trace = self._finish_trace(
            summary={"compared_case_count": len(compared_cases), "improved": improved, "regressed": regressed},
            pipeline="BenchmarkCompare",
        )
        return {
            "compared_case_count": len(compared_cases),
            "improved": improved,
            "regressed": regressed,
            "unchanged": unchanged,
            "deltas": deltas,
            "trace": dict(self.last_trace or {}),
        }

    def export_report(
        self,
        results: List[BenchmarkResult | Dict[str, Any]],
        *,
        suite: BenchmarkSuite | None = None,
        comparison: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        active_suite = suite or self.suite
        normalized_results = self._ensure_results(results)
        total = len(normalized_results)
        passed = sum(1 for item in normalized_results if item.success)
        avg_latency = round(sum(item.latency_ms for item in normalized_results) / max(total, 1), 2)
        avg_coverage = round(sum(item.coverage_score for item in normalized_results) / max(total, 1), 2)
        avg_citation = round(sum(item.citation_score for item in normalized_results) / max(total, 1), 2)
        avg_conflict = round(sum(item.conflict_score for item in normalized_results) / max(total, 1), 2)
        avg_reasoning = round(sum(item.reasoning_score for item in normalized_results) / max(total, 1), 2)
        avg_answer = round(sum(item.answer_score for item in normalized_results) / max(total, 1), 2)
        memory_hits = sum(1 for item in normalized_results if item.memory_hit)
        cache_hits = sum(1 for item in normalized_results if item.cache_hit)
        verification_passes = sum(1 for item in normalized_results if item.verification_pass)

        rows = []
        for result in normalized_results:
            rows.append(
                {
                    "case_id": result.case_id,
                    "question": self._question_for_case(active_suite, result.case_id),
                    "pipeline": result.pipeline,
                    "latency_ms": result.latency_ms,
                    "coverage_score": result.coverage_score,
                    "reasoning_score": result.reasoning_score,
                    "citation_score": result.citation_score,
                    "conflict_score": result.conflict_score,
                    "tool_count": result.tool_count,
                    "tool_names": list(result.tool_names or []),
                    "memory_hit": result.memory_hit,
                    "cache_hit": result.cache_hit,
                    "verification_pass": result.verification_pass,
                    "final_score": result.answer_score,
                    "success": result.success,
                    "errors": list(result.errors or []),
                }
            )

        markdown_lines = [
            f"# Benchmark Report: {active_suite.name}",
            "",
            active_suite.description or "",
            "",
            f"- Total Cases: {total}",
            f"- Passed: {passed}",
            f"- Success Rate: {round((passed / max(total, 1)) * 100.0, 2)}%",
            f"- Average Latency: {avg_latency} ms",
            f"- Average Coverage: {avg_coverage}",
            f"- Average Reasoning: {avg_reasoning}",
            f"- Average Citation: {avg_citation}",
            f"- Average Conflict: {avg_conflict}",
            f"- Average Final Score: {avg_answer}",
            "",
            "| Case | Pipeline | Latency | Coverage | Reasoning | Citation | Conflict | Tool Count | Memory Hit | Cache Hit | Verification | Final Score |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- | ---: |",
        ]
        for row in rows:
            markdown_lines.append(
                f"| {row['case_id']} | {row['pipeline']} | {row['latency_ms']} | {row['coverage_score']} | {row['reasoning_score']} | {row['citation_score']} | {row['conflict_score']} | {row['tool_count']} | {'Yes' if row['memory_hit'] else 'No'} | {'Yes' if row['cache_hit'] else 'No'} | {'Pass' if row['verification_pass'] else 'Fail'} | {row['final_score']} |"
            )

        return {
            "suite": active_suite.to_dict(),
            "summary": {
                "total_cases": total,
                "passed_cases": passed,
                "success_rate": round((passed / max(total, 1)) * 100.0, 2),
                "average_latency_ms": avg_latency,
                "average_coverage_score": avg_coverage,
                "average_citation_score": avg_citation,
                "average_conflict_score": avg_conflict,
                "average_reasoning_score": avg_reasoning,
                "average_answer_score": avg_answer,
                "memory_hit_count": memory_hits,
                "cache_hit_count": cache_hits,
                "verification_pass_count": verification_passes,
            },
            "results": rows,
            "comparison": dict(comparison or {}),
            "markdown": "\n".join(markdown_lines).strip(),
        }

    def _enabled(self) -> bool:
        return feature_flag_enabled("BENCHMARK_FRAMEWORK_ENABLED")

    def _get_e2e_evaluator(self, dataset: List[EvaluationCase] | None = None) -> EndToEndEvaluator:
        return EndToEndEvaluator(
            self.agent,
            dataset=list(dataset or get_default_e2e_dataset()),
            trace_center=self.trace_center,
        )

    def _run_agent(self, case: BenchmarkCase) -> Dict[str, Any]:
        conversation_id = f"benchmark-{case.id}-{uuid.uuid4().hex[:8]}"
        history: List[dict] = []
        if hasattr(self.agent, "think") and callable(getattr(self.agent, "think")):
            result = self.agent.think(case.question, conversation_id, history)
            return dict(result or {})
        if callable(self.agent):
            result = self.agent(case.question, conversation_id, history)
            return dict(result or {})
        raise TypeError("agent must expose think() or be callable")

    def _extract_runtime_trace(self) -> Dict[str, Any]:
        if hasattr(self.agent, "_last_trace_session"):
            trace = getattr(self.agent, "_last_trace_session") or {}
            if isinstance(trace, dict):
                return dict(trace)
        return {}

    def _extract_pipeline(self, trace: Dict[str, Any]) -> str:
        return str(trace.get("pipeline") or "")

    def _extract_tool_names(self, trace: Dict[str, Any]) -> List[str]:
        tool_names: List[str] = []
        seen = set()
        for stage in list(trace.get("stages") or []):
            for event in list(stage.get("events") or []):
                metadata = dict(event.get("metadata") or {})
                tool_name = str(metadata.get("tool_name") or "").strip()
                if event.get("name") == "Tool Executed" and tool_name and tool_name not in seen:
                    seen.add(tool_name)
                    tool_names.append(tool_name)
        return tool_names

    def _memory_hit(self, trace: Dict[str, Any]) -> bool:
        for stage in list(trace.get("stages") or []):
            stage_name = str(stage.get("stage_name") or "")
            if stage_name.startswith("MEMORY"):
                return True
            for event in list(stage.get("events") or []):
                if event.get("name") in {"Memory Loaded", "Entity Restored", "Knowledge Snapshot Created"}:
                    return True
        return False

    def _cache_hit(self, trace: Dict[str, Any]) -> bool:
        for stage in list(trace.get("stages") or []):
            for event in list(stage.get("events") or []):
                if event.get("name") == "Retrieval Cache Hit":
                    return True
        return False

    def _verification_pass(self, verification: Dict[str, Any]) -> bool:
        if not verification:
            return False
        return all(
            [
                bool(verification.get("evidence_enough")),
                bool(verification.get("citation_ready")),
                not bool(verification.get("blocking_conflict")),
                bool(verification.get("answer_ready")),
            ]
        )

    def _question_for_case(self, suite: BenchmarkSuite, case_id: str) -> str:
        for case in suite.cases or []:
            if case.id == case_id:
                return case.question
        return ""

    def _ensure_results(self, results: List[BenchmarkResult | Dict[str, Any]]) -> List[BenchmarkResult]:
        out: List[BenchmarkResult] = []
        for item in results or []:
            if isinstance(item, BenchmarkResult):
                out.append(item)
            elif isinstance(item, dict):
                out.append(BenchmarkResult.from_dict(item))
        return out

    def _start_trace(self, question: str, *, pipeline: str) -> None:
        self.trace_center.start_session(question, pipeline=pipeline)

    def _finish_trace(self, *, summary: Dict[str, Any], pipeline: str) -> Dict[str, Any]:
        session = self.trace_center.finish_session(summary=summary, pipeline=pipeline)
        if session is None:
            return {}
        return session.to_dict()

    def _trace(
        self,
        stage: str,
        name: str,
        *,
        status: str = "ok",
        metadata: Dict[str, Any] | None = None,
    ) -> None:
        self.trace_center.record_event(stage, name, status=status, metadata=metadata or {})
