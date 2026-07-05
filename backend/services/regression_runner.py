from __future__ import annotations

import uuid
from typing import Any, Dict, List

from services.baseline_manager import BaselineManager
from services.benchmark_framework import BenchmarkResult, BenchmarkSuite
from services.benchmark_runner import BenchmarkRunner
from services.feature_flags import feature_flag_enabled
from services.regression_framework import (
    BaselineResult,
    RegressionCase,
    RegressionReport,
    _utc_now_iso,
    compare_benchmark_results,
    summarize_regression_cases,
)
from services.trace_center import TraceCenter


class RegressionRunner:
    def __init__(
        self,
        agent: Any,
        *,
        benchmark_runner: BenchmarkRunner | None = None,
        baseline_manager: BaselineManager | None = None,
        trace_center: TraceCenter | None = None,
        thresholds: Dict[str, float] | None = None,
    ):
        self.agent = agent
        self.trace_center = trace_center or TraceCenter(enabled=True)
        self.benchmark_runner = benchmark_runner or BenchmarkRunner(agent, trace_center=self.trace_center)
        self.baseline_manager = baseline_manager or BaselineManager()
        self.thresholds = dict(thresholds or {})
        self.last_trace: Dict[str, Any] = {}

    def create_baseline(
        self,
        version: str,
        *,
        suite: BenchmarkSuite | None = None,
        metadata: Dict[str, Any] | None = None,
    ) -> BaselineResult:
        self._ensure_enabled()
        active_suite = suite or self.benchmark_runner.suite
        self._start_trace(f"baseline-create:{version}", pipeline="RegressionBaseline")
        report = self.benchmark_runner.run_suite(active_suite)
        results = self._ensure_results(report.get("results") or [])
        baseline = BaselineResult(
            id=uuid.uuid4().hex,
            version=str(version or ""),
            created_at=_utc_now_iso(),
            benchmark_suite=active_suite,
            benchmark_results=results,
            overall_score=float((report.get("summary") or {}).get("average_answer_score") or 0.0),
            metadata=dict(metadata or {}),
        )
        saved_path = self.baseline_manager.save_baseline(baseline)
        self._trace("REGRESSION", "Baseline Saved", metadata={"version": baseline.version, "file_path": saved_path})
        self.last_trace = self._finish_trace(
            summary={"version": baseline.version, "overall_score": baseline.overall_score},
            pipeline="RegressionBaseline",
        )
        return baseline

    def load_baseline(self, version: str) -> BaselineResult:
        self._ensure_enabled()
        self._start_trace(f"baseline-load:{version}", pipeline="RegressionBaselineLoad")
        baseline = self.baseline_manager.load_baseline(version)
        self._trace(
            "REGRESSION",
            "Baseline Loaded",
            metadata={"version": baseline.version, "case_count": len(baseline.benchmark_results or [])},
        )
        self.last_trace = self._finish_trace(
            summary={"version": baseline.version, "case_count": len(baseline.benchmark_results or [])},
            pipeline="RegressionBaselineLoad",
        )
        return baseline

    def run_regression(
        self,
        baseline_version: str,
        current_version: str,
        *,
        suite: BenchmarkSuite | None = None,
        metadata: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        self._ensure_enabled()
        active_suite = suite or self.benchmark_runner.suite
        self._start_trace(f"regression:{baseline_version}->{current_version}", pipeline="RegressionRunner")
        self._trace(
            "REGRESSION",
            "Regression Started",
            metadata={"baseline_version": baseline_version, "current_version": current_version},
        )
        baseline = self.baseline_manager.load_baseline(baseline_version)
        self._trace(
            "REGRESSION",
            "Baseline Loaded",
            metadata={"version": baseline.version, "case_count": len(baseline.benchmark_results or [])},
        )
        current_report = self.benchmark_runner.run_suite(active_suite)
        current_results = self._ensure_results(current_report.get("results") or [])
        regression_report = self.compare_suite(
            baseline.benchmark_results,
            current_results,
            baseline_version=baseline.version,
            current_version=current_version,
        )
        exported = self.export_report(
            regression_report,
            baseline=baseline,
            current_suite=active_suite,
            current_results=current_results,
            metadata=metadata,
        )
        status_event = "Regression Failed" if regression_report.regression > 0 else "Regression Passed"
        status_value = "failed" if regression_report.regression > 0 else "ok"
        self._trace(
            "REGRESSION",
            status_event,
            status=status_value,
            metadata={
                "baseline_version": baseline.version,
                "current_version": current_version,
                "regression_count": regression_report.regression,
                "warning_count": regression_report.warnings,
            },
        )
        self.last_trace = self._finish_trace(
            summary={
                "baseline_version": baseline.version,
                "current_version": current_version,
                "overall_delta": regression_report.overall_delta,
                "regression_count": regression_report.regression,
            },
            pipeline="RegressionRunner",
        )
        exported["trace"] = dict(self.last_trace or {})
        return exported

    def compare_case(
        self,
        baseline_result: BenchmarkResult | Dict[str, Any],
        current_result: BenchmarkResult | Dict[str, Any],
    ) -> RegressionCase:
        baseline = self._ensure_result(baseline_result)
        current = self._ensure_result(current_result)
        case = compare_benchmark_results(baseline, current, thresholds=self.thresholds)
        self._trace(
            "REGRESSION",
            "Regression Compared",
            metadata={"case_id": case.case_id, "status": case.status, "delta": case.delta},
        )
        return case

    def compare_suite(
        self,
        baseline_results: List[BenchmarkResult | Dict[str, Any]],
        current_results: List[BenchmarkResult | Dict[str, Any]],
        *,
        baseline_version: str,
        current_version: str,
    ) -> RegressionReport:
        baseline_map = {item.case_id: item for item in self._ensure_results(baseline_results)}
        current_map = {item.case_id: item for item in self._ensure_results(current_results)}
        case_ids = sorted(set(baseline_map) | set(current_map))
        cases: List[RegressionCase] = []

        for case_id in case_ids:
            baseline = baseline_map.get(case_id)
            current = current_map.get(case_id)
            if baseline is None:
                baseline = BenchmarkResult(
                    case_id=case_id,
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
                    errors=["missing_baseline_case"],
                )
            if current is None:
                current = BenchmarkResult(
                    case_id=case_id,
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
                    errors=["missing_current_case"],
                )
            cases.append(self.compare_case(baseline, current))

        return summarize_regression_cases(baseline_version, current_version, cases)

    def export_report(
        self,
        regression_report: RegressionReport | Dict[str, Any],
        *,
        baseline: BaselineResult | Dict[str, Any] | None = None,
        current_suite: BenchmarkSuite | None = None,
        current_results: List[BenchmarkResult | Dict[str, Any]] | None = None,
        metadata: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        report = regression_report if isinstance(regression_report, RegressionReport) else RegressionReport.from_dict(regression_report or {})
        baseline_obj = baseline if isinstance(baseline, BaselineResult) or baseline is None else BaselineResult.from_dict(baseline or {})
        current_results = self._ensure_results(current_results or [])

        top_regression = sorted(
            [item for item in (report.details or []) if item.status == "REGRESSION"],
            key=lambda item: item.delta,
        )[:5]
        top_improvement = sorted(
            [item for item in (report.details or []) if item.status == "IMPROVEMENT"],
            key=lambda item: item.delta,
            reverse=True,
        )[:5]
        worst_cases = sorted(list(report.details or []), key=lambda item: item.current_score)[:5]

        baseline_latency = self._average_value(
            baseline_obj.benchmark_results if baseline_obj is not None else [],
            field_name="latency_ms",
        )
        current_latency = self._average_value(current_results, field_name="latency_ms")
        baseline_coverage = self._average_value(
            baseline_obj.benchmark_results if baseline_obj is not None else [],
            field_name="coverage_score",
        )
        current_coverage = self._average_value(current_results, field_name="coverage_score")

        markdown_lines = [
            f"# Regression Report: {report.baseline_version} -> {report.current_version}",
            "",
            f"- Total Cases: {report.total_cases}",
            f"- Passed: {report.passed}",
            f"- Improved: {report.improved}",
            f"- Regression: {report.regression}",
            f"- Warnings: {report.warnings}",
            f"- Overall Delta: {report.overall_delta}",
            f"- Latency Trend: {baseline_latency} ms -> {current_latency} ms",
            f"- Coverage Trend: {baseline_coverage} -> {current_coverage}",
            "",
            "| Case | Baseline | Current | Delta | Coverage Δ | Citation Δ | Reasoning Δ | Latency Δ | Tool Δ | Status |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
        for item in report.details or []:
            markdown_lines.append(
                f"| {item.case_id} | {item.baseline_score} | {item.current_score} | {item.delta} | {item.coverage_delta} | {item.citation_delta} | {item.reasoning_delta} | {item.latency_delta} | {item.tool_count_delta} | {item.status} |"
            )

        return {
            "report": report.to_dict(),
            "baseline": baseline_obj.to_dict() if baseline_obj is not None else None,
            "current_suite": current_suite.to_dict() if current_suite is not None else None,
            "metadata": dict(metadata or {}),
            "summary": {
                "overall_score": round(100.0 + report.overall_delta, 2),
                "regression_count": report.regression,
                "improvement_count": report.improved,
                "warning_count": report.warnings,
                "top_regression": [item.to_dict() for item in top_regression],
                "top_improvement": [item.to_dict() for item in top_improvement],
                "worst_cases": [item.to_dict() for item in worst_cases],
                "latency_trend": {"baseline": baseline_latency, "current": current_latency, "delta": round(current_latency - baseline_latency, 2)},
                "coverage_trend": {"baseline": baseline_coverage, "current": current_coverage, "delta": round(current_coverage - baseline_coverage, 2)},
            },
            "markdown": "\n".join(markdown_lines).strip(),
        }

    def _ensure_enabled(self) -> None:
        if not self._enabled():
            raise RuntimeError("regression_framework_disabled")

    def _enabled(self) -> bool:
        return feature_flag_enabled("REGRESSION_FRAMEWORK_ENABLED")

    def _ensure_result(self, value: BenchmarkResult | Dict[str, Any]) -> BenchmarkResult:
        if isinstance(value, BenchmarkResult):
            return value
        return BenchmarkResult.from_dict(value or {})

    def _ensure_results(self, values: List[BenchmarkResult | Dict[str, Any]]) -> List[BenchmarkResult]:
        return [self._ensure_result(item) for item in (values or [])]

    def _average_value(self, results: List[BenchmarkResult], *, field_name: str) -> float:
        if not results:
            return 0.0
        total = 0.0
        for item in results:
            total += float(getattr(item, field_name, 0.0) or 0.0)
        return round(total / max(len(results), 1), 2)

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
