from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List

from services.benchmark_framework import BenchmarkResult, BenchmarkSuite


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _clamp(value: float, minimum: float = -999999.0, maximum: float = 999999.0) -> float:
    return round(max(minimum, min(maximum, _to_float(value, 0.0))), 2)


@dataclass(frozen=True)
class BaselineResult:
    id: str
    version: str
    created_at: str
    benchmark_suite: BenchmarkSuite
    benchmark_results: List[BenchmarkResult] = field(default_factory=list)
    overall_score: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "version": self.version,
            "created_at": self.created_at,
            "benchmark_suite": self.benchmark_suite.to_dict(),
            "benchmark_results": [item.to_dict() for item in (self.benchmark_results or [])],
            "overall_score": float(self.overall_score or 0.0),
            "metadata": dict(self.metadata or {}),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BaselineResult":
        payload = data or {}
        suite_payload = payload.get("benchmark_suite") if isinstance(payload.get("benchmark_suite"), dict) else {}
        return cls(
            id=str(payload.get("id") or ""),
            version=str(payload.get("version") or ""),
            created_at=str(payload.get("created_at") or ""),
            benchmark_suite=BenchmarkSuite.from_dict(suite_payload),
            benchmark_results=[
                BenchmarkResult.from_dict(item)
                for item in (payload.get("benchmark_results") or [])
                if isinstance(item, dict)
            ],
            overall_score=float(payload.get("overall_score") or 0.0),
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass(frozen=True)
class RegressionCase:
    case_id: str
    baseline_score: float
    current_score: float
    delta: float
    coverage_delta: float
    citation_delta: float
    reasoning_delta: float
    latency_delta: float
    tool_count_delta: int
    status: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "case_id": self.case_id,
            "baseline_score": float(self.baseline_score or 0.0),
            "current_score": float(self.current_score or 0.0),
            "delta": float(self.delta or 0.0),
            "coverage_delta": float(self.coverage_delta or 0.0),
            "citation_delta": float(self.citation_delta or 0.0),
            "reasoning_delta": float(self.reasoning_delta or 0.0),
            "latency_delta": float(self.latency_delta or 0.0),
            "tool_count_delta": int(self.tool_count_delta or 0),
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RegressionCase":
        payload = data or {}
        return cls(
            case_id=str(payload.get("case_id") or ""),
            baseline_score=float(payload.get("baseline_score") or 0.0),
            current_score=float(payload.get("current_score") or 0.0),
            delta=float(payload.get("delta") or 0.0),
            coverage_delta=float(payload.get("coverage_delta") or 0.0),
            citation_delta=float(payload.get("citation_delta") or 0.0),
            reasoning_delta=float(payload.get("reasoning_delta") or 0.0),
            latency_delta=float(payload.get("latency_delta") or 0.0),
            tool_count_delta=int(payload.get("tool_count_delta") or 0),
            status=str(payload.get("status") or "PASS"),
        )


@dataclass(frozen=True)
class RegressionReport:
    baseline_version: str
    current_version: str
    total_cases: int
    passed: int
    improved: int
    regression: int
    warnings: int
    overall_delta: float
    details: List[RegressionCase] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "baseline_version": self.baseline_version,
            "current_version": self.current_version,
            "total_cases": int(self.total_cases or 0),
            "passed": int(self.passed or 0),
            "improved": int(self.improved or 0),
            "regression": int(self.regression or 0),
            "warnings": int(self.warnings or 0),
            "overall_delta": float(self.overall_delta or 0.0),
            "details": [item.to_dict() for item in (self.details or [])],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RegressionReport":
        payload = data or {}
        return cls(
            baseline_version=str(payload.get("baseline_version") or ""),
            current_version=str(payload.get("current_version") or ""),
            total_cases=int(payload.get("total_cases") or 0),
            passed=int(payload.get("passed") or 0),
            improved=int(payload.get("improved") or 0),
            regression=int(payload.get("regression") or 0),
            warnings=int(payload.get("warnings") or 0),
            overall_delta=float(payload.get("overall_delta") or 0.0),
            details=[RegressionCase.from_dict(item) for item in (payload.get("details") or []) if isinstance(item, dict)],
        )


def default_regression_thresholds() -> Dict[str, float]:
    return {
        "coverage_drop_regression": 5.0,
        "citation_drop_regression": 5.0,
        "answer_drop_regression": 5.0,
        "latency_increase_warning_pct": 20.0,
        "tool_count_increase_warning": 2.0,
    }


def compare_benchmark_results(
    baseline: BenchmarkResult,
    current: BenchmarkResult,
    *,
    thresholds: Dict[str, float] | None = None,
) -> RegressionCase:
    config = dict(default_regression_thresholds())
    config.update(dict(thresholds or {}))

    delta = _clamp(current.answer_score - baseline.answer_score)
    coverage_delta = _clamp(current.coverage_score - baseline.coverage_score)
    citation_delta = _clamp(current.citation_score - baseline.citation_score)
    reasoning_delta = _clamp(current.reasoning_score - baseline.reasoning_score)
    latency_delta = _clamp(current.latency_ms - baseline.latency_ms)
    tool_count_delta = _to_int(current.tool_count - baseline.tool_count, 0)

    status = "PASS"
    if coverage_delta <= -abs(_to_float(config.get("coverage_drop_regression"), 5.0)):
        status = "REGRESSION"
    elif citation_delta <= -abs(_to_float(config.get("citation_drop_regression"), 5.0)):
        status = "REGRESSION"
    elif delta <= -abs(_to_float(config.get("answer_drop_regression"), 5.0)):
        status = "REGRESSION"
    else:
        latency_warning = False
        if baseline.latency_ms > 0:
            latency_ratio = ((current.latency_ms - baseline.latency_ms) / baseline.latency_ms) * 100.0
            latency_warning = latency_ratio >= abs(_to_float(config.get("latency_increase_warning_pct"), 20.0))
        tool_warning = tool_count_delta >= _to_int(config.get("tool_count_increase_warning"), 2)
        if latency_warning or tool_warning:
            status = "WARNING"
        elif delta > 0 or coverage_delta > 0 or citation_delta > 0 or reasoning_delta > 0:
            status = "IMPROVEMENT"

    return RegressionCase(
        case_id=current.case_id or baseline.case_id,
        baseline_score=float(baseline.answer_score or 0.0),
        current_score=float(current.answer_score or 0.0),
        delta=delta,
        coverage_delta=coverage_delta,
        citation_delta=citation_delta,
        reasoning_delta=reasoning_delta,
        latency_delta=latency_delta,
        tool_count_delta=tool_count_delta,
        status=status,
    )


def summarize_regression_cases(
    baseline_version: str,
    current_version: str,
    cases: List[RegressionCase],
) -> RegressionReport:
    total_cases = len(cases or [])
    passed = sum(1 for item in (cases or []) if item.status == "PASS")
    improved = sum(1 for item in (cases or []) if item.status == "IMPROVEMENT")
    regression = sum(1 for item in (cases or []) if item.status == "REGRESSION")
    warnings = sum(1 for item in (cases or []) if item.status == "WARNING")
    overall_delta = round(sum(item.delta for item in (cases or [])) / max(total_cases, 1), 2)
    return RegressionReport(
        baseline_version=baseline_version,
        current_version=current_version,
        total_cases=total_cases,
        passed=passed,
        improved=improved,
        regression=regression,
        warnings=warnings,
        overall_delta=overall_delta,
        details=list(cases or []),
    )
