from __future__ import annotations

from datetime import datetime, timedelta, timezone
import uuid
from typing import Any, Optional

from .audit_trail import AuditTrailRedactor


class ResponseObservabilityBuilder:
    AUDIT_VERSION = "6.0E"
    TRACE_STEP_WHITELIST = {
        "request_received",
        "intent_router",
        "organization_resolver",
        "policy_guard",
        "module_dispatcher",
        "module_execution",
        "response_contract_builder",
        "safe_fallback_builder",
        "final_route_decision",
        "response_ready",
    }
    TRACE_STATUS_WHITELIST = {"pass", "fail", "skipped", "blocked"}

    def __init__(self, *, redactor: Optional[AuditTrailRedactor] = None) -> None:
        self.redactor = redactor or AuditTrailRedactor()

    def build(
        self,
        *,
        contract: dict[str, Any],
        orchestration_result: dict[str, Any],
        execution_trace: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        execution_trace = execution_trace if isinstance(execution_trace, dict) else {}
        stage_durations = self._build_stage_durations(contract=contract, execution_trace=execution_trace)
        trace_events = self._build_trace_events(
            contract=contract,
            orchestration_result=orchestration_result,
            execution_trace=execution_trace,
            stage_durations=stage_durations,
        )
        total_duration_ms = round(
            max(
                sum(stage_durations.values()),
                self._to_non_negative_float(execution_trace.get("total_ms")),
            ),
            3,
        )
        redacted_query = self.redactor.redact_text(str(contract.get("query") or ""))
        audit_summary = {
            "audit_version": self.AUDIT_VERSION,
            "trace_id": str(contract.get("trace_id") or ""),
            "response_id": str(contract.get("response_id") or ""),
            "query_fingerprint": self.redactor.fingerprint(str(contract.get("query") or "")),
            "query_redacted": redacted_query,
            "intent": str(contract.get("intent") or ""),
            "route_status": str(contract.get("route_status") or ""),
            "payload_type": str(contract.get("payload_type") or ""),
            "selected_module": contract.get("selected_module"),
            "organization_resolution_status": (contract.get("organization") or {}).get("resolution_status"),
            "target_organization_resolution_status": (contract.get("target_organization") or {}).get("resolution_status"),
            "data_found": bool(contract.get("data_found")),
            "db_first": bool(((contract.get("policy") or {}).get("db_first"))),
            "no_llm": bool(((contract.get("audit") or {}).get("no_llm"))),
            "no_network": bool(((contract.get("audit") or {}).get("no_network"))),
            "no_fabrication": bool(((contract.get("audit") or {}).get("no_fabrication"))),
            "safe_fallback_used": self._safe_fallback_used(contract),
            "fallback_reason": contract.get("fallback_reason"),
            "warnings_count": len(list(contract.get("warnings") or [])),
            "errors_count": len(list(contract.get("errors") or [])),
            "trace_steps_count": len(trace_events),
            "total_duration_ms": total_duration_ms,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "redaction_applied": redacted_query != str(contract.get("query") or ""),
        }
        return {
            "audit_summary": audit_summary,
            "trace_events": trace_events,
            "metrics": {
                "total_duration_ms": total_duration_ms,
                "stage_durations": stage_durations,
            },
        }

    def _build_stage_durations(
        self,
        *,
        contract: dict[str, Any],
        execution_trace: dict[str, Any],
    ) -> dict[str, float]:
        intent_router_ms = self._to_non_negative_float(execution_trace.get("intent_detection_ms"))
        organization_resolver_ms = self._to_non_negative_float(execution_trace.get("organization_resolver_ms"))
        module_execution_ms = self._sum_non_negative(
            execution_trace.get("db_lookup_ms"),
            execution_trace.get("scorer_lookup_ms"),
            execution_trace.get("planner_ms"),
            execution_trace.get("module_execution_ms"),
        )
        known_total = self._sum_non_negative(intent_router_ms, organization_resolver_ms, module_execution_ms)
        trace_total = self._to_non_negative_float(execution_trace.get("total_ms"))
        if trace_total > known_total:
            module_execution_ms = round(module_execution_ms + (trace_total - known_total), 3)

        stage_durations = {
            "request_received": 0.0,
            "intent_router": intent_router_ms,
            "organization_resolver": organization_resolver_ms,
            "policy_guard": 0.0,
            "module_dispatcher": 0.0,
            "final_route_decision": 0.0,
            "response_contract_builder": 0.0,
            "response_ready": 0.0,
        }
        if self._safe_fallback_used(contract):
            stage_durations["safe_fallback_builder"] = 0.0
        else:
            stage_durations["module_execution"] = module_execution_ms
        return {key: round(max(0.0, float(value)), 3) for key, value in stage_durations.items()}

    def _build_trace_events(
        self,
        *,
        contract: dict[str, Any],
        orchestration_result: dict[str, Any],
        execution_trace: dict[str, Any],
        stage_durations: dict[str, float],
    ) -> list[dict[str, Any]]:
        route_status = str(contract.get("route_status") or "")
        trace_id = str(contract.get("trace_id") or "")
        root_span_id = self._new_span_id()
        cursor_ms = 0.0
        base_time = datetime.now(timezone.utc)
        events: list[dict[str, Any]] = []

        redacted_query = self.redactor.redact_text(str(contract.get("query") or ""))
        events.append(
            self._make_event(
                trace_id=trace_id,
                span_id=root_span_id,
                parent_span_id=None,
                step="request_received",
                status="pass",
                duration_ms=stage_durations.get("request_received", 0.0),
                cursor_ms=cursor_ms,
                base_time=base_time,
                selected_value=None,
                reason_codes=["request_received"],
                warnings=[],
                errors=[],
                metadata={
                    "query_redacted": redacted_query,
                    "query_length": len(redacted_query),
                    "redaction_applied": redacted_query != str(contract.get("query") or ""),
                },
            )
        )
        cursor_ms += stage_durations.get("request_received", 0.0)

        for item in list(contract.get("trace") or []):
            step = str(item.get("step") or "").strip()
            if step not in self.TRACE_STEP_WHITELIST:
                continue
            duration_ms = stage_durations.get(step, 0.0)
            events.append(
                self._make_event(
                    trace_id=trace_id,
                    span_id=self._new_span_id(),
                    parent_span_id=root_span_id,
                    step=step,
                    status=self._normalize_status(item.get("status")),
                    duration_ms=duration_ms,
                    cursor_ms=cursor_ms,
                    base_time=base_time,
                    selected_value=item.get("selected_value"),
                    reason_codes=item.get("reason_codes") or [],
                    warnings=item.get("warnings") or [],
                    errors=item.get("errors") or [],
                    metadata={},
                )
            )
            cursor_ms += duration_ms

        if self._safe_fallback_used(contract):
            events.append(
                self._make_event(
                    trace_id=trace_id,
                    span_id=self._new_span_id(),
                    parent_span_id=root_span_id,
                    step="safe_fallback_builder",
                    status="pass",
                    duration_ms=stage_durations.get("safe_fallback_builder", 0.0),
                    cursor_ms=cursor_ms,
                    base_time=base_time,
                    selected_value=route_status,
                    reason_codes=[str(contract.get("fallback_reason") or "safe_fallback")],
                    warnings=contract.get("warnings") or [],
                    errors=[],
                    metadata={
                        "safe_fallback_used": True,
                        "payload_type": contract.get("payload_type"),
                    },
                )
            )
            cursor_ms += stage_durations.get("safe_fallback_builder", 0.0)
        else:
            events.append(
                self._make_event(
                    trace_id=trace_id,
                    span_id=self._new_span_id(),
                    parent_span_id=root_span_id,
                    step="module_execution",
                    status="pass",
                    duration_ms=stage_durations.get("module_execution", 0.0),
                    cursor_ms=cursor_ms,
                    base_time=base_time,
                    selected_value=contract.get("selected_module"),
                    reason_codes=[f"payload_type_{contract.get('payload_type')}"],
                    warnings=contract.get("warnings") or [],
                    errors=[],
                    metadata={
                        "data_found": bool(contract.get("data_found")),
                        "source": contract.get("source"),
                        "db_hit": bool(execution_trace.get("db_hit")),
                    },
                )
            )
            cursor_ms += stage_durations.get("module_execution", 0.0)

        events.append(
            self._make_event(
                trace_id=trace_id,
                span_id=self._new_span_id(),
                parent_span_id=root_span_id,
                step="response_contract_builder",
                status="pass",
                duration_ms=stage_durations.get("response_contract_builder", 0.0),
                cursor_ms=cursor_ms,
                base_time=base_time,
                selected_value=contract.get("response_contract_version"),
                reason_codes=["response_contract_enriched_with_observability"],
                warnings=[],
                errors=[],
                metadata={
                    "audit_version": self.AUDIT_VERSION,
                    "payload_type": contract.get("payload_type"),
                },
            )
        )
        cursor_ms += stage_durations.get("response_contract_builder", 0.0)

        events.append(
            self._make_event(
                trace_id=trace_id,
                span_id=self._new_span_id(),
                parent_span_id=root_span_id,
                step="response_ready",
                status="pass" if route_status == "ready" else "blocked",
                duration_ms=stage_durations.get("response_ready", 0.0),
                cursor_ms=cursor_ms,
                base_time=base_time,
                selected_value=route_status,
                reason_codes=[
                    f"route_status_{route_status}",
                    f"trace_steps_{len(events) + 1}",
                ],
                warnings=contract.get("warnings") or [],
                errors=contract.get("errors") or [],
                metadata={
                    "selected_module": contract.get("selected_module"),
                    "payload_type": contract.get("payload_type"),
                },
            )
        )
        return events

    def _make_event(
        self,
        *,
        trace_id: str,
        span_id: str,
        parent_span_id: Optional[str],
        step: str,
        status: str,
        duration_ms: float,
        cursor_ms: float,
        base_time: datetime,
        selected_value: Any,
        reason_codes: list[Any],
        warnings: list[Any],
        errors: list[Any],
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        started_at = base_time + timedelta(milliseconds=max(0.0, cursor_ms))
        ended_at = started_at + timedelta(milliseconds=max(0.0, duration_ms))
        payload = {
            "trace_id": trace_id,
            "span_id": span_id,
            "parent_span_id": parent_span_id,
            "step": step,
            "status": status,
            "started_at": started_at.isoformat(),
            "ended_at": ended_at.isoformat(),
            "duration_ms": round(max(0.0, float(duration_ms)), 3),
            "selected_value": selected_value,
            "reason_codes": self._normalize_text_list(reason_codes),
            "warnings": self._normalize_text_list(warnings),
            "errors": self._normalize_text_list(errors),
            "metadata": self.redactor.sanitize_metadata(metadata),
        }
        return payload

    def _new_span_id(self) -> str:
        return f"span_{uuid.uuid4().hex}"

    def _normalize_status(self, value: Any) -> str:
        status = str(value or "blocked").strip().lower()
        if status not in self.TRACE_STATUS_WHITELIST:
            return "blocked"
        return status

    def _normalize_text_list(self, values: list[Any]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for item in values or []:
            text = str(item or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            normalized.append(self.redactor.redact_text(text))
        return normalized

    def _to_non_negative_float(self, value: Any) -> float:
        try:
            return max(0.0, float(value or 0.0))
        except Exception:
            return 0.0

    def _sum_non_negative(self, *values: Any) -> float:
        return round(sum(self._to_non_negative_float(value) for value in values), 3)

    def _safe_fallback_used(self, contract: dict[str, Any]) -> bool:
        return str(contract.get("route_status") or "") != "ready"
