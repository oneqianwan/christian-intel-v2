from __future__ import annotations

import math
import threading
import tracemalloc
from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

from services.feature_flags import feature_flag_enabled


def _enabled(name: str, default: bool = True) -> bool:
    return feature_flag_enabled(name, default=default)


def _normalize_labels(labels: Dict[str, Any] | None = None) -> Dict[str, str]:
    payload = dict(labels or {})
    normalized: Dict[str, str] = {}
    for key, value in payload.items():
        text_key = str(key or "").strip()
        if not text_key:
            continue
        normalized[text_key] = str(value if value is not None else "").strip()
    return normalized


def _labels_key(labels: Dict[str, Any] | None = None) -> Tuple[Tuple[str, str], ...]:
    normalized = _normalize_labels(labels)
    return tuple(sorted(normalized.items(), key=lambda item: item[0]))


def _percentile(values: List[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(item) for item in values)
    if len(ordered) == 1:
        return round(ordered[0], 2)
    rank = max(0.0, min(1.0, float(p))) * (len(ordered) - 1)
    lower = int(math.floor(rank))
    upper = int(math.ceil(rank))
    if lower == upper:
        return round(ordered[lower], 2)
    fraction = rank - lower
    return round(ordered[lower] + (ordered[upper] - ordered[lower]) * fraction, 2)


@dataclass
class MetricCounter:
    name: str
    value: float = 0.0
    labels: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "value": float(self.value or 0.0),
            "labels": dict(self.labels or {}),
        }


@dataclass
class MetricHistogram:
    name: str
    values: List[float] = field(default_factory=list)
    labels: Dict[str, str] = field(default_factory=dict)

    def observe(self, value: float) -> None:
        self.values.append(float(value or 0.0))

    def summary(self) -> Dict[str, Any]:
        values = [float(item) for item in (self.values or [])]
        total = sum(values)
        count = len(values)
        return {
            "name": self.name,
            "labels": dict(self.labels or {}),
            "count": count,
            "sum": round(total, 2),
            "avg": round(total / count, 2) if count else 0.0,
            "min": round(min(values), 2) if values else 0.0,
            "max": round(max(values), 2) if values else 0.0,
            "p50": _percentile(values, 0.50),
            "p95": _percentile(values, 0.95),
        }


@dataclass
class MetricGauge:
    name: str
    value: float = 0.0
    labels: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "value": float(self.value or 0.0),
            "labels": dict(self.labels or {}),
        }


class RuntimeMetrics:
    def __init__(self, enabled: bool | None = None):
        self.enabled = _enabled("RUNTIME_METRICS_ENABLED", default=True) if enabled is None else bool(enabled)
        self._lock = threading.RLock()
        self._counters: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], MetricCounter] = {}
        self._histograms: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], MetricHistogram] = {}
        self._gauges: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], MetricGauge] = {}
        self._active_sessions = 0
        if self.enabled and not tracemalloc.is_tracing():
            tracemalloc.start()
        self.set("queue_size", 0.0)

    def inc(self, name: str, value: float = 1.0, labels: Dict[str, Any] | None = None) -> float:
        if not self.enabled:
            return 0.0
        with self._lock:
            key = (str(name or "").strip(), _labels_key(labels))
            if key not in self._counters:
                self._counters[key] = MetricCounter(name=key[0], value=0.0, labels=_normalize_labels(labels))
            self._counters[key].value += float(value or 0.0)
            return float(self._counters[key].value)

    def observe(self, name: str, value: float, labels: Dict[str, Any] | None = None) -> Dict[str, Any]:
        if not self.enabled:
            return {}
        with self._lock:
            key = (str(name or "").strip(), _labels_key(labels))
            if key not in self._histograms:
                self._histograms[key] = MetricHistogram(name=key[0], labels=_normalize_labels(labels))
            self._histograms[key].observe(float(value or 0.0))
            return self._histograms[key].summary()

    def set(self, name: str, value: float, labels: Dict[str, Any] | None = None) -> float:
        if not self.enabled:
            return 0.0
        with self._lock:
            key = (str(name or "").strip(), _labels_key(labels))
            self._gauges[key] = MetricGauge(name=key[0], value=float(value or 0.0), labels=_normalize_labels(labels))
            return float(self._gauges[key].value)

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            if self.enabled and tracemalloc.is_tracing():
                current, peak = tracemalloc.get_traced_memory()
                self.set("memory_usage_bytes", float(current))
                self.set("memory_peak_bytes", float(peak))
            counters = [item.to_dict() for item in self._counters.values()]
            histograms = [item.summary() for item in self._histograms.values()]
            gauges = [item.to_dict() for item in self._gauges.values()]
            return {
                "enabled": self.enabled,
                "counters": counters,
                "histograms": histograms,
                "gauges": gauges,
            }

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()
            self._histograms.clear()
            self._gauges.clear()
            self._active_sessions = 0
            if self.enabled and tracemalloc.is_tracing():
                tracemalloc.clear_traces()
            self.set("queue_size", 0.0)

    def export(self) -> Dict[str, Any]:
        return self.snapshot()

    def counter_total(self, name: str, labels: Dict[str, Any] | None = None) -> float:
        with self._lock:
            target = str(name or "").strip()
            expected = _normalize_labels(labels)
            total = 0.0
            for counter in self._counters.values():
                if counter.name != target:
                    continue
                if expected and any(counter.labels.get(key) != value for key, value in expected.items()):
                    continue
                total += float(counter.value or 0.0)
            return total

    def gauge_value(self, name: str, labels: Dict[str, Any] | None = None) -> float:
        with self._lock:
            target = str(name or "").strip()
            expected = _normalize_labels(labels)
            for gauge in self._gauges.values():
                if gauge.name != target:
                    continue
                if expected and any(gauge.labels.get(key) != value for key, value in expected.items()):
                    continue
                return float(gauge.value or 0.0)
            return 0.0

    def histogram_summaries(self, name: str, labels: Dict[str, Any] | None = None) -> List[Dict[str, Any]]:
        with self._lock:
            target = str(name or "").strip()
            expected = _normalize_labels(labels)
            output: List[Dict[str, Any]] = []
            for histogram in self._histograms.values():
                if histogram.name != target:
                    continue
                if expected and any(histogram.labels.get(key) != value for key, value in expected.items()):
                    continue
                output.append(histogram.summary())
            return output

    def counter_rate(self, numerator: str, denominator: str) -> float:
        base = self.counter_total(denominator)
        if base <= 0:
            return 0.0
        return round((self.counter_total(numerator) / base) * 100.0, 2)

    def session_started(self) -> None:
        if not self.enabled:
            return
        with self._lock:
            self._active_sessions += 1
            self.set("active_sessions", float(self._active_sessions))

    def session_finished(self) -> None:
        if not self.enabled:
            return
        with self._lock:
            self._active_sessions = max(0, int(self._active_sessions) - 1)
            self.set("active_sessions", float(self._active_sessions))


_RUNTIME_METRICS_SINGLETON: RuntimeMetrics | None = None


def get_runtime_metrics() -> RuntimeMetrics:
    global _RUNTIME_METRICS_SINGLETON
    if _RUNTIME_METRICS_SINGLETON is None:
        _RUNTIME_METRICS_SINGLETON = RuntimeMetrics()
    return _RUNTIME_METRICS_SINGLETON
