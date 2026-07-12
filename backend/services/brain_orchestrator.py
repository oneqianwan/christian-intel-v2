from __future__ import annotations

import re
from typing import Any, Dict, Iterable, Optional

from services.query_parser import QueryParser


class BrainOrchestrator:
    MODULE_DISPATCH: dict[str, dict[str, Any]] = {
        "organization_score_lookup": {
            "selected_module": "score_lookup",
            "method": "_resolve_score_lookup_if_applicable",
            "payload_type": "score_snapshot",
            "required_parameters": ["organization_name"],
            "optional_parameters": [],
        },
        "organization_relationship_graph_lookup": {
            "selected_module": "relationship_graph",
            "method": "_resolve_relationship_graph_if_applicable",
            "payload_type": "relationship_graph",
            "required_parameters": ["organization_name"],
            "optional_parameters": [],
        },
        "organization_contact_lookup": {
            "selected_module": "contact_intelligence",
            "method": "_resolve_contact_lookup_if_applicable",
            "payload_type": "contact_intelligence",
            "required_parameters": ["organization_name"],
            "optional_parameters": [],
        },
        "organization_partnership_recommendation_lookup": {
            "selected_module": "partnership_recommender",
            "method": "_resolve_recommendation_lookup_if_applicable",
            "payload_type": "partnership_recommendation",
            "required_parameters": ["organization_name"],
            "optional_parameters": ["target_organization_name"],
        },
        "organization_partnership_action_plan_lookup": {
            "selected_module": "partnership_action_planner",
            "method": "_resolve_action_plan_lookup_if_applicable",
            "payload_type": "partnership_action_plan",
            "required_parameters": ["organization_name"],
            "optional_parameters": ["target_organization_name"],
        },
        "organization_partnership_evidence_brief_lookup": {
            "selected_module": "partnership_evidence_brief",
            "method": "_resolve_evidence_brief_lookup_if_applicable",
            "payload_type": "partnership_evidence_brief",
            "required_parameters": ["organization_name"],
            "optional_parameters": ["target_organization_name"],
        },
        "general_chat": {
            "selected_module": "general_chat",
            "method": "",
            "payload_type": "general_chat",
            "required_parameters": [],
            "optional_parameters": [],
        },
    }

    SAFE_SUPPORTED_INTENTS = set(MODULE_DISPATCH.keys()) | {"unsupported_or_ambiguous"}
    ROUTE_STATUS_VALUES = {"ready", "ask_clarification", "unsupported", "ambiguous", "blocked"}
    TRACE_ORDER = [
        "intent_router",
        "organization_resolver",
        "policy_guard",
        "module_dispatcher",
        "final_route_decision",
    ]

    def orchestrate(
        self,
        query: str,
        *,
        parser: Optional[QueryParser] = None,
        alias_map: Optional[dict[str, str]] = None,
        known_organizations: Optional[Iterable[Any]] = None,
        db: Any = None,
    ) -> Dict[str, Any]:
        raw_query = str(query or "").strip()
        owns_parser = parser is None
        parser = parser or QueryParser()
        try:
            intent_result = parser.parse_intent_final(raw_query)
            organization_resolution = self._resolve_organizations(
                parser=parser,
                query=raw_query,
                alias_map=alias_map,
                known_organizations=known_organizations,
                db=db,
                intent_result=intent_result,
            )
            target_resolution = {
                "target_organization_name": organization_resolution.get("target_organization_name"),
                "target_organization_id": organization_resolution.get("target_organization_id"),
                "target_canonical_name": organization_resolution.get("target_canonical_name"),
                "target_candidates": list(organization_resolution.get("target_candidates") or []),
            }

            selected_intent = str(intent_result.get("intent") or "unsupported_or_ambiguous").strip() or "unsupported_or_ambiguous"
            dispatch_template = self.MODULE_DISPATCH.get(selected_intent)
            selected_module = dispatch_template["selected_module"] if dispatch_template else None
            normalized_query = str(intent_result.get("normalized_query") or organization_resolution.get("normalized_query") or raw_query)
            organization_name = organization_resolution.get("organization_name") or intent_result.get("organization_name")
            target_organization_name = (
                organization_resolution.get("target_organization_name") or intent_result.get("target_organization_name")
            )

            missing_parameters = self._merge_lists(
                intent_result.get("missing_parameters") or [],
                organization_resolution.get("missing_parameters") or [],
            )
            missing_parameters = self._filter_missing_parameters(
                missing_parameters,
                organization_name=organization_name,
                target_organization_name=target_organization_name,
                organization_resolution=organization_resolution,
            )
            candidate_intents = list(intent_result.get("candidate_intents") or [])
            candidate_organizations = list(organization_resolution.get("candidates") or [])[:5]
            warnings = self._merge_lists(
                intent_result.get("warnings") or [],
                organization_resolution.get("warnings") or [],
            )
            reason_codes = self._merge_lists(
                intent_result.get("reason_codes") or [],
                organization_resolution.get("reason_codes") or [],
            )

            route_status, requires_clarification, safe_default_used = self._decide_route_status(
                selected_intent=selected_intent,
                intent_result=intent_result,
                organization_resolution=organization_resolution,
                missing_parameters=missing_parameters,
            )
            clarification_prompt = self._build_clarification_prompt(
                raw_query=raw_query,
                route_status=route_status,
                organization_resolution=organization_resolution,
                missing_parameters=missing_parameters,
                candidate_organizations=candidate_organizations,
            )

            dispatch = {
                "module": selected_module if selected_module in {item["selected_module"] for item in self.MODULE_DISPATCH.values()} else None,
                "method": dispatch_template["method"] if dispatch_template else None,
                "payload_type": dispatch_template["payload_type"] if dispatch_template else None,
                "required_parameters": list(dispatch_template["required_parameters"]) if dispatch_template else [],
                "optional_parameters": list(dispatch_template["optional_parameters"]) if dispatch_template else [],
            }
            if route_status != "ready":
                dispatch["method"] = None

            trace = [
                self._trace_step(
                    "intent_router",
                    "pass" if selected_intent in self.SAFE_SUPPORTED_INTENTS else "blocked",
                    intent_result.get("reason_codes") or [],
                    selected_value=selected_intent,
                    warnings=intent_result.get("warnings") or [],
                ),
                self._trace_step(
                    "organization_resolver",
                    "pass" if organization_resolution.get("resolution_status") not in {"ambiguous", "context_required"} else "blocked",
                    organization_resolution.get("reason_codes") or [],
                    selected_value=organization_resolution.get("organization_name"),
                    warnings=organization_resolution.get("warnings") or [],
                ),
                self._trace_step(
                    "policy_guard",
                    "pass",
                    ["db_first_required", "llm_disabled", "network_disabled", "fabrication_disabled"],
                    selected_value="db_first_local_only",
                    warnings=[],
                ),
                self._trace_step(
                    "module_dispatcher",
                    "pass" if route_status == "ready" and dispatch.get("module") else "blocked",
                    reason_codes,
                    selected_value=dispatch.get("module"),
                    warnings=[] if route_status == "ready" else [route_status],
                ),
                self._trace_step(
                    "final_route_decision",
                    "pass" if route_status == "ready" else "blocked",
                    reason_codes + [f"route_status_{route_status}"],
                    selected_value=route_status,
                    warnings=warnings,
                ),
            ]

            result = {
                "query": raw_query,
                "normalized_query": normalized_query,
                "route_status": route_status,
                "selected_intent": selected_intent,
                "selected_module": selected_module,
                "intent_result": intent_result,
                "organization_resolution": organization_resolution,
                "target_organization_resolution": target_resolution,
                "organization_name": organization_name,
                "target_organization_name": target_organization_name,
                "missing_parameters": missing_parameters,
                "ambiguous": route_status == "ambiguous",
                "candidate_intents": candidate_intents,
                "candidate_organizations": candidate_organizations,
                "safe_default_used": safe_default_used,
                "requires_clarification": requires_clarification,
                "clarification_prompt": clarification_prompt,
                "policy": {
                    "db_first": True,
                    "allow_llm": False,
                    "allow_network": False,
                    "allow_fabrication": False,
                },
                "dispatch": dispatch,
                "trace": trace,
                "warnings": warnings,
                "reason_codes": reason_codes,
            }
            if result["route_status"] not in self.ROUTE_STATUS_VALUES:
                result["route_status"] = "blocked"
            return result
        finally:
            if owns_parser and parser is not None:
                parser.close()

    def _resolve_organizations(
        self,
        *,
        parser: QueryParser,
        query: str,
        alias_map: Optional[dict[str, str]],
        known_organizations: Optional[Iterable[Any]],
        db: Any,
        intent_result: dict[str, Any],
    ) -> Dict[str, Any]:
        existing = intent_result.get("organization_resolution")
        should_rerun = alias_map is not None or known_organizations is not None or db is not None
        if isinstance(existing, dict) and not should_rerun:
            return existing
        return parser.resolve_organization_entities(
            query,
            alias_map=alias_map,
            known_organizations=list(known_organizations or []),
            db=db,
            use_db=db is not None,
        )

    def _filter_missing_parameters(
        self,
        missing_parameters: list[str],
        *,
        organization_name: Optional[str],
        target_organization_name: Optional[str],
        organization_resolution: dict[str, Any],
    ) -> list[str]:
        filtered: list[str] = []
        resolution_status = str(organization_resolution.get("resolution_status") or "").strip()
        for item in missing_parameters:
            if item == "organization_name" and organization_name and resolution_status not in {"ambiguous", "context_required"}:
                continue
            if item == "target_organization_name" and target_organization_name:
                continue
            filtered.append(item)
        return filtered

    def _decide_route_status(
        self,
        *,
        selected_intent: str,
        intent_result: dict[str, Any],
        organization_resolution: dict[str, Any],
        missing_parameters: list[str],
    ) -> tuple[str, bool, bool]:
        resolution_status = str(organization_resolution.get("resolution_status") or "").strip()
        routing_decision = str(intent_result.get("routing_decision") or "").strip()

        if resolution_status == "ambiguous":
            return "ambiguous", True, True
        if resolution_status == "context_required":
            return "ask_clarification", True, True
        if selected_intent == "unsupported_or_ambiguous":
            if routing_decision == "ask_clarification" or missing_parameters:
                return "ask_clarification", True, True
            return "unsupported", False, True
        if selected_intent == "general_chat":
            return "unsupported", False, True
        if selected_intent not in self.MODULE_DISPATCH:
            return "unsupported", False, True
        if missing_parameters:
            return "ask_clarification", True, True
        return "ready", False, False

    def _build_clarification_prompt(
        self,
        *,
        raw_query: str,
        route_status: str,
        organization_resolution: dict[str, Any],
        missing_parameters: list[str],
        candidate_organizations: list[dict[str, Any]],
    ) -> Optional[str]:
        if route_status == "ask_clarification":
            if organization_resolution.get("context_reference"):
                return "我需要知道你指的是哪个机构。" if self._is_zh(raw_query) else "I need to know which organization you mean."
            if "organization_name" in missing_parameters or "organization_context" in missing_parameters:
                return (
                    "我需要你先指定一个机构，例如 Victory Philippines。"
                    if self._is_zh(raw_query)
                    else "I need you to specify an organization first, for example Victory Philippines."
                )
        if route_status == "ambiguous":
            names = [str(item.get("canonical_name") or item.get("name") or "").strip() for item in candidate_organizations[:5]]
            names = [name for name in names if name]
            if self._is_zh(raw_query):
                base = "我找到了多个可能机构，请选择。"
                if names:
                    return base + "\n- " + "\n- ".join(names)
                return base
            base = "I found multiple possible organizations. Please choose one."
            if names:
                return base + "\n- " + "\n- ".join(names)
            return base
        if route_status == "unsupported":
            return (
                "请明确你要查询评分、关系图谱、联系方式、推荐、行动计划或证据简报。"
                if self._is_zh(raw_query)
                else "Please specify whether you want a score, relationship graph, contact info, recommendation, action plan, or evidence brief."
            )
        return None

    def _trace_step(
        self,
        step: str,
        status: str,
        reason_codes: list[str],
        *,
        selected_value: Any = None,
        warnings: list[str],
    ) -> dict[str, Any]:
        payload = {
            "step": step,
            "status": status,
            "reason_codes": list(dict.fromkeys(str(code) for code in reason_codes if str(code).strip())),
        }
        if selected_value not in {None, ""}:
            payload["selected_value"] = selected_value
        if warnings:
            payload["warnings"] = list(dict.fromkeys(str(item) for item in warnings if str(item).strip()))
        return payload

    def _merge_lists(self, *values: Iterable[Any]) -> list[str]:
        merged: list[str] = []
        seen: set[str] = set()
        for group in values:
            for item in group or []:
                text = str(item or "").strip()
                if not text or text in seen:
                    continue
                seen.add(text)
                merged.append(text)
        return merged

    def _is_zh(self, query: str) -> bool:
        return bool(re.search(r"[\u4e00-\u9fff]", str(query or "")))
