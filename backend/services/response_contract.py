from __future__ import annotations

from datetime import datetime, timezone
import uuid
from typing import Any, Optional


class ResponseContractBuilder:
    RESPONSE_CONTRACT_VERSION = "6.0D"
    PAYLOAD_TYPES = {
        "score_snapshot",
        "relationship_graph",
        "contact_intelligence",
        "partnership_recommendation",
        "partnership_action_plan",
        "partnership_evidence_brief",
        "safe_fallback",
        "ask_clarification",
        "unsupported",
        "ambiguous",
    }
    SOURCES = {
        "database",
        "database_first",
        "resolver",
        "extracted",
        "fallback",
        "none",
    }
    SELECTED_MODULES = {
        "score_lookup",
        "relationship_graph",
        "contact_intelligence",
        "partnership_recommender",
        "partnership_action_planner",
        "partnership_evidence_brief",
        "general_chat",
        None,
    }
    INTENT_GROUPS = {
        "organization_score_lookup": "score",
        "organization_relationship_graph_lookup": "relationship_graph",
        "organization_contact_lookup": "contact",
        "organization_partnership_recommendation_lookup": "recommendation",
        "organization_partnership_action_plan_lookup": "action_plan",
        "organization_partnership_evidence_brief_lookup": "evidence_brief",
        "general_chat": "general_chat",
        "unsupported_or_ambiguous": "unsupported",
    }

    def build(
        self,
        *,
        query: str,
        orchestration_result: dict[str, Any],
        payload: Optional[dict[str, Any]] = None,
        legacy_payload: Optional[dict[str, Any]] = None,
        answer: str = "",
        safe_message: Optional[str] = None,
        data_source: Optional[str] = None,
    ) -> dict[str, Any]:
        payload = dict(payload or {})
        legacy_payload = dict(legacy_payload or {})
        decision = orchestration_result or {}
        route_status = str(decision.get("route_status") or "blocked").strip() or "blocked"
        selected_module = decision.get("selected_module")
        intent = str(decision.get("selected_intent") or "unsupported_or_ambiguous").strip() or "unsupported_or_ambiguous"
        intent_result = decision.get("intent_result") or {}
        organization_resolution = decision.get("organization_resolution") or {}
        target_resolution = decision.get("target_organization_resolution") or {}
        trace = list(decision.get("trace") or [])
        warnings = list(decision.get("warnings") or [])
        reason_codes = list(decision.get("reason_codes") or [])
        missing_parameters = list(decision.get("missing_parameters") or [])

        payload_type = self._resolve_payload_type(route_status=route_status, decision=decision)
        source = self._resolve_source(route_status=route_status, data_source=data_source, organization_resolution=organization_resolution)
        confidence = self._clamp_float(
            intent_result.get("confidence", organization_resolution.get("confidence", 0.0)),
            default=0.0,
        )
        fallback_reason = self._resolve_fallback_reason(
            route_status=route_status,
            decision=decision,
            organization_resolution=organization_resolution,
            missing_parameters=missing_parameters,
        )
        if safe_message is None and route_status != "ready":
            safe_message = str(decision.get("clarification_prompt") or answer or "").strip() or None

        contract = {
            "response_contract_version": self.RESPONSE_CONTRACT_VERSION,
            "response_id": self._new_id("resp"),
            "trace_id": self._new_id("trace"),
            "query": str(query or ""),
            "normalized_query": str(decision.get("normalized_query") or query or ""),
            "route_status": route_status,
            "intent": intent,
            "intent_group": self.INTENT_GROUPS.get(intent, "unsupported"),
            "payload_type": payload_type,
            "selected_module": selected_module if selected_module in self.SELECTED_MODULES else None,
            "data_found": self._resolve_data_found(route_status=route_status, payload=payload),
            "confidence": confidence,
            "source": source,
            "organization": self._build_organization_snapshot(
                name=decision.get("organization_name"),
                resolution=organization_resolution,
                payload=payload.get("organization") if isinstance(payload.get("organization"), dict) else None,
            ),
            "target_organization": self._build_target_snapshot(
                target_resolution=target_resolution,
                payload=payload.get("target_org") if isinstance(payload.get("target_org"), dict) else None,
            ),
            "payload": payload,
            "legacy_payload": legacy_payload,
            "safe_message": safe_message,
            "missing_parameters": missing_parameters,
            "warnings": warnings,
            "reason_codes": reason_codes,
            "fallback_reason": fallback_reason,
            "policy": {
                "db_first": True,
                "allow_llm": False,
                "allow_network": False,
                "allow_fabrication": False,
            },
            "audit": {
                "no_llm": True,
                "no_network": True,
                "no_fabrication": True,
                "db_first": True,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "contract_builder": "response_contract",
            },
            "trace": trace,
            "errors": [],
        }
        return contract

    def _resolve_payload_type(self, *, route_status: str, decision: dict[str, Any]) -> str:
        if route_status == "ready":
            payload_type = str(((decision.get("dispatch") or {}).get("payload_type")) or "").strip()
            if payload_type in self.PAYLOAD_TYPES:
                return payload_type
            return "safe_fallback"
        if route_status == "ask_clarification":
            return "ask_clarification"
        if route_status == "ambiguous":
            return "ambiguous"
        if route_status == "unsupported":
            return "unsupported"
        return "safe_fallback"

    def _resolve_source(
        self,
        *,
        route_status: str,
        data_source: Optional[str],
        organization_resolution: dict[str, Any],
    ) -> str:
        if route_status != "ready":
            return "fallback"
        normalized = str(data_source or "").strip().lower()
        if normalized in self.SOURCES:
            return normalized
        resolution_status = str(organization_resolution.get("resolution_status") or "").strip()
        if resolution_status == "resolved":
            return "resolver"
        if resolution_status == "unresolved":
            return "extracted"
        return "none"

    def _resolve_data_found(self, *, route_status: str, payload: dict[str, Any]) -> bool:
        if route_status != "ready":
            return False
        if "found" in payload:
            return bool(payload.get("found"))
        if "summary" in payload and isinstance(payload.get("summary"), dict):
            summary = payload.get("summary") or {}
            for key in ("contact_count", "recommended_count", "candidate_count"):
                if key in summary:
                    return bool(summary.get(key))
            if "brief_available" in summary:
                return bool(summary.get("brief_available"))
        if "scores" in payload and isinstance(payload.get("scores"), dict):
            return any(value is not None for value in (payload.get("scores") or {}).values())
        return bool(payload)

    def _resolve_fallback_reason(
        self,
        *,
        route_status: str,
        decision: dict[str, Any],
        organization_resolution: dict[str, Any],
        missing_parameters: list[str],
    ) -> Optional[str]:
        if route_status == "ready":
            return None
        if organization_resolution.get("context_reference"):
            return "context_reference_requires_previous_organization"
        if route_status == "ambiguous":
            return "ambiguous_organization"
        if route_status == "unsupported":
            return "unsupported_query"
        if "organization_name" in missing_parameters:
            return "organization_name_missing"
        if "organization_context" in missing_parameters:
            return "organization_context_missing"
        if decision.get("requires_clarification"):
            return "clarification_required"
        return "safe_fallback"

    def _build_organization_snapshot(
        self,
        *,
        name: Any,
        resolution: dict[str, Any],
        payload: Optional[dict[str, Any]],
    ) -> dict[str, Any]:
        payload = payload or {}
        return {
            "name": self._text_or_none(name) or self._text_or_none(payload.get("name")),
            "canonical_name": self._text_or_none(resolution.get("canonical_name")) or self._text_or_none(payload.get("name")),
            "organization_id": self._text_or_none(resolution.get("organization_id")) or self._text_or_none(payload.get("id")),
            "resolution_status": self._text_or_none(resolution.get("resolution_status")) or ("resolved" if self._text_or_none(name) else "missing"),
            "confidence": self._clamp_optional_float(resolution.get("confidence")),
        }

    def _build_target_snapshot(
        self,
        *,
        target_resolution: dict[str, Any],
        payload: Optional[dict[str, Any]],
    ) -> dict[str, Any]:
        payload = payload or {}
        target_name = self._text_or_none(target_resolution.get("target_organization_name")) or self._text_or_none(payload.get("name"))
        target_id = self._text_or_none(target_resolution.get("target_organization_id")) or self._text_or_none(payload.get("id"))
        canonical_name = self._text_or_none(target_resolution.get("target_canonical_name")) or self._text_or_none(payload.get("name"))
        if not any([target_name, target_id, canonical_name]):
            return {
                "name": None,
                "canonical_name": None,
                "organization_id": None,
                "resolution_status": None,
                "confidence": None,
            }
        return {
            "name": target_name,
            "canonical_name": canonical_name,
            "organization_id": target_id,
            "resolution_status": "resolved",
            "confidence": None,
        }

    def _new_id(self, prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex}"

    def _clamp_float(self, value: Any, *, default: float) -> float:
        try:
            result = float(value)
        except Exception:
            result = default
        return max(0.0, min(result, 1.0))

    def _clamp_optional_float(self, value: Any) -> Optional[float]:
        if value in {None, ""}:
            return None
        return self._clamp_float(value, default=0.0)

    def _text_or_none(self, value: Any) -> Optional[str]:
        text = str(value or "").strip()
        return text or None
