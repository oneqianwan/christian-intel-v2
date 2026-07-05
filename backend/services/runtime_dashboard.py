from __future__ import annotations

import json
from typing import Any, Dict, List

from services.runtime_health import HealthCheck
from services.runtime_metrics import RuntimeMetrics, get_runtime_metrics


def _match_counter(counters: List[Dict[str, Any]], name: str, labels: Dict[str, Any] | None = None) -> float:
    expected = dict(labels or {})
    total = 0.0
    for item in counters:
        if str(item.get("name") or "") != name:
            continue
        current_labels = dict(item.get("labels") or {})
        if all(str(current_labels.get(key) or "") == str(value or "") for key, value in expected.items()):
            total += float(item.get("value") or 0.0)
    return total


def _match_histograms(histograms: List[Dict[str, Any]], name: str, labels: Dict[str, Any] | None = None) -> List[Dict[str, Any]]:
    expected = dict(labels or {})
    matched: List[Dict[str, Any]] = []
    for item in histograms:
        if str(item.get("name") or "") != name:
            continue
        current_labels = dict(item.get("labels") or {})
        if all(str(current_labels.get(key) or "") == str(value or "") for key, value in expected.items()):
            matched.append(dict(item))
    return matched


def _match_gauge(gauges: List[Dict[str, Any]], name: str, labels: Dict[str, Any] | None = None) -> float:
    expected = dict(labels or {})
    for item in gauges:
        if str(item.get("name") or "") != name:
            continue
        current_labels = dict(item.get("labels") or {})
        if all(str(current_labels.get(key) or "") == str(value or "") for key, value in expected.items()):
            return float(item.get("value") or 0.0)
    return 0.0


class RuntimeDashboard:
    def __init__(self, metrics: RuntimeMetrics | None = None):
        self.metrics = metrics or get_runtime_metrics()

    def build(self) -> Dict[str, Any]:
        snapshot = self.metrics.snapshot()
        counters = list(snapshot.get("counters") or [])
        histograms = list(snapshot.get("histograms") or [])
        gauges = list(snapshot.get("gauges") or [])

        pipeline_hist = _match_histograms(histograms, "pipeline.stage.latency_ms")
        pipeline_total_hist = _match_histograms(histograms, "pipeline.total.latency_ms")
        llm_hist = _match_histograms(histograms, "llm.latency_ms")
        tool_hist = _match_histograms(histograms, "tool.time_ms")
        merge_hist = _match_histograms(histograms, "knowledge.merge.time_ms")
        confidence_hist = _match_histograms(histograms, "governor.confidence")

        tool_success = _match_counter(counters, "tool_success")
        tool_failure = _match_counter(counters, "tool_failure")
        tool_total = tool_success + tool_failure
        memory_hit = _match_counter(counters, "memory_cache_hit")
        memory_miss = _match_counter(counters, "memory_cache_miss")
        memory_total = memory_hit + memory_miss
        policy_hit = _match_counter(counters, "policy_hit")
        policy_override = _match_counter(counters, "policy_override")
        policy_reject = _match_counter(counters, "policy_reject")
        pipeline_selected = _match_counter(counters, "governor_pipeline_selected")
        governor_fallback = _match_counter(counters, "governor_fallback")
        loop_continue = _match_counter(counters, "loop_continue")
        loop_stop = _match_counter(counters, "loop_stop")

        dashboard = {
            "overall_runtime": {
                "healthy": "Healthy",
                "active_sessions": int(_match_gauge(gauges, "active_sessions")),
                "memory_usage_bytes": _match_gauge(gauges, "memory_usage_bytes"),
                "queue_size": _match_gauge(gauges, "queue_size"),
            },
            "pipeline_statistics": {
                "stage_count": len(pipeline_hist),
                "p95_latency_ms": max([float(item.get("p95") or 0.0) for item in pipeline_hist] or [0.0]),
                "pipeline_time_p95_ms": max([float(item.get("p95") or 0.0) for item in pipeline_total_hist] or [0.0]),
            },
            "governor_statistics": {
                "pipeline_selected": int(pipeline_selected),
                "fallback": int(governor_fallback),
                "fallback_rate_pct": round((governor_fallback / pipeline_selected) * 100, 2) if pipeline_selected else 0.0,
                "confidence_p95": max([float(item.get("p95") or 0.0) for item in confidence_hist] or [0.0]),
            },
            "tool_statistics": {
                "success_count": int(tool_success),
                "failure_count": int(tool_failure),
                "failure_rate_pct": round((tool_failure / tool_total) * 100, 2) if tool_total else 0.0,
                "p95_latency_ms": max([float(item.get("p95") or 0.0) for item in tool_hist] or [0.0]),
            },
            "knowledge_statistics": {
                "merge_count": int(_match_counter(counters, "knowledge_merge_count")),
                "merge_fail_count": int(_match_counter(counters, "knowledge_merge_fail")),
                "node_count": int(_match_gauge(gauges, "knowledge_node_count")),
                "relation_count": int(_match_gauge(gauges, "knowledge_relation_count")),
                "merge_time_p95_ms": max([float(item.get("p95") or 0.0) for item in merge_hist] or [0.0]),
            },
            "memory_statistics": {
                "cache_hit": int(memory_hit),
                "cache_miss": int(memory_miss),
                "hit_rate_pct": round((memory_hit / memory_total) * 100, 2) if memory_total else 0.0,
                "snapshot_count": int(_match_counter(counters, "memory_snapshot_count")),
            },
            "policy_statistics": {
                "policy_hit": int(policy_hit),
                "policy_override": int(policy_override),
                "policy_reject": int(policy_reject),
                "override_rate_pct": round((policy_override / policy_hit) * 100, 2) if policy_hit else 0.0,
            },
            "trace_statistics": {
                "session_count": int(_match_counter(counters, "trace_session_count")),
                "event_count": int(_match_counter(counters, "trace_event_count")),
                "stage_count": int(_match_counter(counters, "trace_stage_count")),
            },
            "container_statistics": {
                "singleton_created": int(_match_counter(counters, "container_singleton")),
                "resolve_count": int(_match_counter(counters, "container_resolve")),
                "dependency_count": int(_match_counter(counters, "container_dependency")),
                "singleton_count": int(_match_gauge(gauges, "singleton_count")),
            },
            "loop_statistics": {
                "continue_count": int(loop_continue),
                "stop_count": int(loop_stop),
                "average_loop": round(_match_gauge(gauges, "loop_average"), 2),
                "coverage_p95": max([float(item.get("p95") or 0.0) for item in _match_histograms(histograms, "loop.coverage")] or [0.0]),
            },
            "llm_statistics": {
                "generation_count": int(_match_counter(counters, "llm_generation_count")),
                "stream_count": int(_match_counter(counters, "llm_stream_count")),
                "token_usage": int(_match_counter(counters, "llm_token_usage")),
                "latency_p95_ms": max([float(item.get("p95") or 0.0) for item in llm_hist] or [0.0]),
            },
        }

        dashboard["runtime_score"] = self._runtime_score(dashboard)
        dashboard["health"] = HealthCheck.evaluate(dashboard).to_dict()
        return dashboard

    def render_json(self) -> Dict[str, Any]:
        return self.build()

    def render_markdown(self) -> str:
        dashboard = self.build()
        lines = [
            "# Runtime Dashboard",
            "",
            f"- Overall Runtime: {dashboard['health']['status']}",
            f"- Overall Runtime Score: {dashboard['runtime_score']['overall_runtime_score']}",
            f"- Pipeline P95 Latency: {dashboard['pipeline_statistics']['p95_latency_ms']}ms",
            f"- Knowledge Merge P95: {dashboard['knowledge_statistics']['merge_time_p95_ms']}ms",
            f"- Memory Hit: {dashboard['memory_statistics']['hit_rate_pct']}%",
            f"- Policy Override: {dashboard['policy_statistics']['override_rate_pct']}%",
            f"- Loop Avg: {dashboard['loop_statistics']['average_loop']}",
            f"- Tool Failure: {dashboard['tool_statistics']['failure_rate_pct']}%",
            f"- Governor Fallback: {dashboard['governor_statistics']['fallback_rate_pct']}%",
        ]
        return "\n".join(lines)

    def export(self, format: str = "json") -> Dict[str, Any] | str:
        mode = str(format or "json").strip().lower()
        if mode == "markdown":
            return self.render_markdown()
        if mode == "json_string":
            return json.dumps(self.render_json(), ensure_ascii=False, indent=2)
        return self.render_json()

    def _runtime_score(self, dashboard: Dict[str, Any]) -> Dict[str, Any]:
        tool_failure = float((dashboard.get("tool_statistics") or {}).get("failure_rate_pct") or 0.0)
        memory_hit = float((dashboard.get("memory_statistics") or {}).get("hit_rate_pct") or 0.0)
        override_rate = float((dashboard.get("policy_statistics") or {}).get("override_rate_pct") or 0.0)
        fallback_rate = float((dashboard.get("governor_statistics") or {}).get("fallback_rate_pct") or 0.0)
        pipeline_p95 = float((dashboard.get("pipeline_statistics") or {}).get("pipeline_time_p95_ms") or 0.0)
        knowledge_fail = float((dashboard.get("knowledge_statistics") or {}).get("merge_fail_count") or 0.0)
        loop_avg = float((dashboard.get("loop_statistics") or {}).get("average_loop") or 0.0)

        performance = max(0.0, 100.0 - min(100.0, pipeline_p95 / 10.0))
        stability = max(0.0, 100.0 - min(100.0, tool_failure * 2.0 + knowledge_fail * 25.0))
        accuracy = max(0.0, 100.0 - min(100.0, fallback_rate + override_rate))
        coverage = min(100.0, max(0.0, float((dashboard.get("loop_statistics") or {}).get("coverage_p95") or 0.0) * 100.0))
        health = 100.0 if (dashboard.get("health") or {}).get("status") == "Healthy" else (75.0 if (dashboard.get("health") or {}).get("status") == "Warning" else 45.0)
        cost = max(0.0, 100.0 - min(100.0, max(loop_avg - 1.0, 0.0) * 20.0 + max(0.0, 50.0 - memory_hit) * 0.4))
        overall = round((performance + stability + accuracy + coverage + health + cost) / 6.0, 1)
        return {
            "performance": round(performance, 1),
            "stability": round(stability, 1),
            "accuracy": round(accuracy, 1),
            "coverage": round(coverage, 1),
            "health": round(health, 1),
            "cost": round(cost, 1),
            "overall_runtime_score": overall,
        }
