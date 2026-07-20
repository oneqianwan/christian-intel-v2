from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any

from services.runtime_metrics import get_runtime_metrics


@dataclass(frozen=True)
class MonitoringEvent:
    event_type: str
    severity: str
    message: str
    labels: dict[str, str]
    created_at: float
    alert: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "severity": self.severity,
            "message": self.message,
            "labels": dict(self.labels or {}),
            "created_at": float(self.created_at),
            "alert": bool(self.alert),
        }


def _normalize_labels(labels: dict[str, Any] | None = None) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for key, value in dict(labels or {}).items():
        text_key = str(key or "").strip()
        if not text_key:
            continue
        normalized[text_key] = str(value if value is not None else "").strip()
    return normalized


class InMemoryMonitoringEventSink:
    def __init__(self, *, max_events: int = 256, now_func=None) -> None:
        self._max_events = max(32, int(max_events))
        self._now_func = now_func or time.time
        self._lock = threading.RLock()
        self._events: list[MonitoringEvent] = []
        self._test_time: float | None = None

    def _now(self) -> float:
        if self._test_time is not None:
            return float(self._test_time)
        return float(self._now_func())

    def record(
        self,
        *,
        event_type: str,
        severity: str,
        message: str,
        labels: dict[str, Any] | None = None,
        alert: bool = False,
    ) -> MonitoringEvent:
        event = MonitoringEvent(
            event_type=str(event_type or "").strip() or "unknown",
            severity=str(severity or "").strip().lower() or "info",
            message=str(message or "").strip() or "monitoring event",
            labels=_normalize_labels(labels),
            created_at=self._now(),
            alert=bool(alert),
        )
        with self._lock:
            self._events.append(event)
            if len(self._events) > self._max_events:
                self._events = self._events[-self._max_events :]
        return event

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            events = [item.to_dict() for item in self._events]
        alerts = [item for item in events if item.get("alert") is True]
        return {
            "total": len(events),
            "alert_total": len(alerts),
            "events": events,
            "alerts": alerts,
        }

    def reset_for_tests(self) -> None:
        with self._lock:
            self._events.clear()
            self._test_time = None

    def set_time_for_tests(self, current_time: float) -> None:
        with self._lock:
            self._test_time = float(current_time)

    def advance_time_for_tests(self, delta_seconds: float) -> None:
        with self._lock:
            base = self._test_time if self._test_time is not None else self._now_func()
            self._test_time = float(base) + float(delta_seconds)


_MONITORING_SINK_SINGLETON: InMemoryMonitoringEventSink | None = None


def get_monitoring_event_sink() -> InMemoryMonitoringEventSink:
    global _MONITORING_SINK_SINGLETON
    if _MONITORING_SINK_SINGLETON is None:
        _MONITORING_SINK_SINGLETON = InMemoryMonitoringEventSink()
    return _MONITORING_SINK_SINGLETON


def record_monitoring_event(
    *,
    event_type: str,
    severity: str = "info",
    message: str = "",
    labels: dict[str, Any] | None = None,
    alert: bool = False,
) -> MonitoringEvent:
    metrics = get_runtime_metrics()
    metrics.inc("monitoring_events_total", labels={"event_type": str(event_type or "").strip() or "unknown"})
    if alert:
        metrics.inc("alert_events_total", labels={"event_type": str(event_type or "").strip() or "unknown"})
    return get_monitoring_event_sink().record(
        event_type=event_type,
        severity=severity,
        message=message,
        labels=labels,
        alert=alert,
    )


def record_rate_limit_trip(*, rule_name: str, error_code: str) -> None:
    get_runtime_metrics().inc("rate_limit_trips", labels={"rule_name": str(rule_name or "").strip() or "unknown"})
    record_monitoring_event(
        event_type="rate_limit_trip",
        severity="warning",
        message="Rate limit triggered",
        labels={"rule_name": rule_name, "error_code": error_code},
        alert=True,
    )


def record_auth_failure(*, error_code: str, email: str | None = None) -> None:
    get_runtime_metrics().inc("auth_failures", labels={"error_code": str(error_code or "").strip() or "unknown"})
    record_monitoring_event(
        event_type="auth_failure",
        severity="warning",
        message="Authentication failure",
        labels={"error_code": error_code, "email": str(email or "").strip().lower()},
        alert=error_code in {"LOGIN_RATE_LIMITED", "ACCOUNT_DISABLED"},
    )


def record_tenant_isolation_denial(*, error_code: str, route: str | None = None) -> None:
    get_runtime_metrics().inc(
        "tenant_isolation_denials",
        labels={"error_code": str(error_code or "").strip() or "unknown"},
    )
    record_monitoring_event(
        event_type="tenant_isolation_denial",
        severity="error",
        message="Tenant isolation denial",
        labels={"error_code": error_code, "route": str(route or "").strip()},
        alert=True,
    )


def record_background_job_failure(*, error_code: str, component: str) -> None:
    get_runtime_metrics().inc(
        "background_job_failures",
        labels={
            "error_code": str(error_code or "").strip() or "unknown",
            "component": str(component or "").strip() or "unknown",
        },
    )
    record_monitoring_event(
        event_type="background_job_failure",
        severity="error",
        message="Background job failure",
        labels={"error_code": error_code, "component": component},
        alert=True,
    )


def reset_monitoring_for_tests() -> None:
    get_runtime_metrics().reset()
    get_monitoring_event_sink().reset_for_tests()


def set_monitoring_time_for_tests(current_time: float) -> None:
    get_monitoring_event_sink().set_time_for_tests(current_time)


def advance_monitoring_time_for_tests(delta_seconds: float) -> None:
    get_monitoring_event_sink().advance_time_for_tests(delta_seconds)


def monitoring_snapshot() -> dict[str, Any]:
    metrics = get_runtime_metrics()
    sink_snapshot = get_monitoring_event_sink().snapshot()
    return {
        "counters": {
            "rate_limit_trips": int(metrics.counter_total("rate_limit_trips")),
            "auth_failures": int(metrics.counter_total("auth_failures")),
            "tenant_isolation_denials": int(metrics.counter_total("tenant_isolation_denials")),
            "background_job_failures": int(metrics.counter_total("background_job_failures")),
            "monitoring_events_total": int(metrics.counter_total("monitoring_events_total")),
            "alert_events_total": int(metrics.counter_total("alert_events_total")),
        },
        "events": sink_snapshot["events"],
        "alerts": sink_snapshot["alerts"],
        "total_events": int(sink_snapshot["total"]),
        "total_alerts": int(sink_snapshot["alert_total"]),
    }
