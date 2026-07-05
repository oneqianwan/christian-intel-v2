from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from services.capability_planner import Capability, CapabilityPlan, ExecutionRequirement
from services.core_models import QuestionContext, Requirement


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    display_name: str
    description: str
    category: str
    supported_question_types: List[str] = field(default_factory=list)
    supported_entities: List[str] = field(default_factory=list)
    supported_countries: List[str] = field(default_factory=list)
    required_arguments: List[str] = field(default_factory=list)
    optional_arguments: List[str] = field(default_factory=list)
    priority: int = 0
    cost: str = "medium"
    latency_level: str = "medium"
    supports_batch: bool = False
    supports_stream: bool = False
    enabled: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "category": self.category,
            "supported_question_types": list(self.supported_question_types or []),
            "supported_entities": list(self.supported_entities or []),
            "supported_countries": list(self.supported_countries or []),
            "required_arguments": list(self.required_arguments or []),
            "optional_arguments": list(self.optional_arguments or []),
            "priority": int(self.priority),
            "cost": self.cost,
            "latency_level": self.latency_level,
            "supports_batch": bool(self.supports_batch),
            "supports_stream": bool(self.supports_stream),
            "enabled": bool(self.enabled),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ToolDefinition":
        payload = data or {}
        return cls(
            name=str(payload.get("name") or ""),
            display_name=str(payload.get("display_name") or ""),
            description=str(payload.get("description") or ""),
            category=str(payload.get("category") or ""),
            supported_question_types=list(payload.get("supported_question_types") or []),
            supported_entities=list(payload.get("supported_entities") or []),
            supported_countries=list(payload.get("supported_countries") or []),
            required_arguments=list(payload.get("required_arguments") or []),
            optional_arguments=list(payload.get("optional_arguments") or []),
            priority=int(payload.get("priority") or 0),
            cost=str(payload.get("cost") or "medium"),
            latency_level=str(payload.get("latency_level") or "medium"),
            supports_batch=bool(payload.get("supports_batch")),
            supports_stream=bool(payload.get("supports_stream")),
            enabled=bool(payload.get("enabled", True)),
        )


@dataclass(frozen=True)
class ExecutionPlan:
    ordered_tools: List[ToolDefinition] = field(default_factory=list)
    parallel_groups: List[List[ToolDefinition]] = field(default_factory=list)
    fallback_tools: List[ToolDefinition] = field(default_factory=list)
    execution_requirements: List[ExecutionRequirement] = field(default_factory=list)
    stop_after_success: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ordered_tools": [item.to_dict() for item in (self.ordered_tools or [])],
            "parallel_groups": [[item.to_dict() for item in group] for group in (self.parallel_groups or [])],
            "fallback_tools": [item.to_dict() for item in (self.fallback_tools or [])],
            "execution_requirements": [item.to_dict() for item in (self.execution_requirements or [])],
            "stop_after_success": bool(self.stop_after_success),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExecutionPlan":
        payload = data or {}
        return cls(
            ordered_tools=[ToolDefinition.from_dict(item) for item in (payload.get("ordered_tools") or []) if isinstance(item, dict)],
            parallel_groups=[
                [ToolDefinition.from_dict(item) for item in group if isinstance(item, dict)]
                for group in (payload.get("parallel_groups") or [])
                if isinstance(group, list)
            ],
            fallback_tools=[ToolDefinition.from_dict(item) for item in (payload.get("fallback_tools") or []) if isinstance(item, dict)],
            execution_requirements=[
                ExecutionRequirement.from_dict(item)
                for item in (payload.get("execution_requirements") or [])
                if isinstance(item, dict)
            ],
            stop_after_success=bool(payload.get("stop_after_success")),
        )


class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, ToolDefinition] = {}

    def register(self, tool_definition: ToolDefinition) -> None:
        if not isinstance(tool_definition, ToolDefinition):
            raise TypeError("tool_definition must be ToolDefinition")
        if not tool_definition.name:
            raise ValueError("tool_definition.name is required")
        self._tools[tool_definition.name] = tool_definition

    def unregister(self, name: str) -> None:
        self._tools.pop(str(name or ""), None)

    def get(self, name: str) -> Optional[ToolDefinition]:
        return self._tools.get(str(name or ""))

    def list_tools(
        self,
        *,
        category: str | None = None,
        question_type: str | None = None,
        entity_type: str | None = None,
        enabled: bool | None = None,
    ) -> List[ToolDefinition]:
        items = list(self._tools.values())
        if category:
            items = [item for item in items if item.category == category]
        if question_type:
            qt = str(question_type or "").upper().strip()
            items = [
                item
                for item in items
                if not item.supported_question_types
                or qt in {str(v).upper().strip() for v in item.supported_question_types}
            ]
        if entity_type:
            et = str(entity_type or "").lower().strip()
            items = [
                item
                for item in items
                if not item.supported_entities
                or et in {str(v).lower().strip() for v in item.supported_entities}
            ]
        if enabled is not None:
            items = [item for item in items if bool(item.enabled) == bool(enabled)]
        return items

    def match_tools(
        self,
        question_type: str,
        entities: List[Dict[str, Any]] | None,
        country: str | None,
    ) -> List[ToolDefinition]:
        qt = str(question_type or "UNKNOWN").upper().strip()
        country_text = str(country or "").strip().lower()
        entity_types = {
            str(item.get("entity_type") or item.get("type") or "").strip().lower()
            for item in (entities or [])
            if isinstance(item, dict)
        }
        entity_types = {item for item in entity_types if item}

        def score(item: ToolDefinition) -> tuple[int, int, int, int]:
            qt_match = 1 if (not item.supported_question_types or qt in {str(v).upper().strip() for v in item.supported_question_types}) else 0
            entity_match = 1
            if item.supported_entities:
                normalized = {str(v).lower().strip() for v in item.supported_entities}
                entity_match = 1 if (not entity_types or bool(entity_types & normalized)) else 0
            country_match = 1
            if item.supported_countries:
                normalized_countries = {str(v).lower().strip() for v in item.supported_countries}
                country_match = 1 if (not country_text or country_text in normalized_countries or "*" in normalized_countries) else 0
            return (int(item.priority), qt_match, entity_match, country_match)

        matched = [item for item in self._tools.values() if item.enabled]
        matched.sort(key=score, reverse=True)
        return matched

    def match_capability(self, capability: Capability | Dict[str, Any]) -> List[ToolDefinition]:
        return self.match_capability_with_trace(capability)

    def match_capability_with_trace(self, capability: Capability | Dict[str, Any], trace_center: Any = None) -> List[ToolDefinition]:
        item = capability if isinstance(capability, Capability) else Capability.from_dict(capability or {})
        capability_name = self._normalize_capability_name(item.name)
        matched: List[ToolDefinition] = []
        for tool in self._tools.values():
            if not tool.enabled:
                continue
            tags = self._infer_tool_capabilities(tool)
            if capability_name in tags:
                matched.append(tool)
        matched.sort(key=lambda tool: (int(tool.priority), tool.name), reverse=True)
        if trace_center is not None:
            trace_center.record_event(
                "TOOL_REGISTRY",
                "Capability Match",
                metadata={
                    "capability": capability_name,
                    "matched_tools": [tool.name for tool in matched],
                },
            )
        return matched

    def build_execution_plan(self, requirement: Requirement, question_context: QuestionContext, trace_center: Any = None) -> ExecutionPlan:
        matched = self.match_tools(
            question_type=question_context.question_type.value if hasattr(question_context.question_type, "value") else str(question_context.question_type or "UNKNOWN"),
            entities=list(question_context.entities or []),
            country=question_context.country,
        )
        if not matched:
            return ExecutionPlan()

        ranked = sorted(
            matched,
            key=lambda item: self._plan_score(item, requirement, question_context),
            reverse=True,
        )

        ordered_tools = ranked[:]
        parallel_groups: List[List[ToolDefinition]] = []
        if len(ordered_tools) >= 2:
            first = ordered_tools[0]
            second = ordered_tools[1]
            if first.category == second.category and first.supports_batch and second.supports_batch:
                parallel_groups.append([first, second])
        fallback_tools = ordered_tools[1:] if len(ordered_tools) > 1 else []
        stop_after_success = bool(question_context.question_type.value in {"CONTACT"} if hasattr(question_context.question_type, "value") else False)
        execution_plan = ExecutionPlan(
            ordered_tools=ordered_tools,
            parallel_groups=parallel_groups,
            fallback_tools=fallback_tools,
            stop_after_success=stop_after_success,
        )
        if trace_center is not None:
            trace_center.record_event(
                "TOOL_REGISTRY",
                "Execution Plan",
                metadata={
                    "ordered_tools": [tool.name for tool in execution_plan.ordered_tools],
                    "parallel_groups": [[tool.name for tool in group] for group in execution_plan.parallel_groups],
                    "fallback_tools": [tool.name for tool in execution_plan.fallback_tools],
                },
            )
        return execution_plan

    def build_execution_plan_from_capability_plan(
        self,
        capability_plan: CapabilityPlan,
        question_context: QuestionContext,
        requirement: Requirement,
        execution_requirements: List[ExecutionRequirement] | None = None,
        trace_center: Any = None,
    ) -> ExecutionPlan:
        execution_requirements = list(execution_requirements or [])
        ordered_tools: List[ToolDefinition] = []
        fallback_tools: List[ToolDefinition] = []
        parallel_groups: List[List[ToolDefinition]] = []
        seen_ordered = set()
        seen_fallback = set()

        for execution_requirement in execution_requirements:
            matched = self.match_capability_with_trace(execution_requirement.capability, trace_center=trace_center)
            if not matched:
                continue
            ranked = sorted(
                matched,
                key=lambda item: self._capability_plan_score(item, execution_requirement, requirement, question_context),
                reverse=True,
            )
            primary = ranked[0]
            if primary.name not in seen_ordered:
                ordered_tools.append(primary)
                seen_ordered.add(primary.name)
            for tool in ranked[1:]:
                if tool.name in seen_ordered or tool.name in seen_fallback:
                    continue
                fallback_tools.append(tool)
                seen_fallback.add(tool.name)

        for group in capability_plan.parallel_groups or []:
            tool_group: List[ToolDefinition] = []
            local_seen = set()
            for capability in group:
                matched = self.match_capability_with_trace(capability, trace_center=trace_center)
                if not matched:
                    continue
                tool = matched[0]
                if tool.name in local_seen:
                    continue
                local_seen.add(tool.name)
                tool_group.append(tool)
            if len(tool_group) >= 2:
                parallel_groups.append(tool_group)

        for capability in capability_plan.fallback_capabilities or []:
            for tool in self.match_capability_with_trace(capability, trace_center=trace_center):
                if tool.name in seen_ordered or tool.name in seen_fallback:
                    continue
                fallback_tools.append(tool)
                seen_fallback.add(tool.name)

        stop_after_success = bool(question_context.question_type.value in {"CONTACT"} if hasattr(question_context.question_type, "value") else False)
        execution_plan = ExecutionPlan(
            ordered_tools=ordered_tools,
            parallel_groups=parallel_groups,
            fallback_tools=fallback_tools,
            execution_requirements=execution_requirements,
            stop_after_success=stop_after_success,
        )
        if trace_center is not None:
            trace_center.record_event(
                "TOOL_REGISTRY",
                "Execution Plan",
                metadata={
                    "ordered_tools": [tool.name for tool in execution_plan.ordered_tools],
                    "parallel_groups": [[tool.name for tool in group] for group in execution_plan.parallel_groups],
                    "fallback_tools": [tool.name for tool in execution_plan.fallback_tools],
                },
            )
        return execution_plan

    def _plan_score(self, tool: ToolDefinition, requirement: Requirement, question_context: QuestionContext) -> tuple[int, int, int, int, int]:
        required_fields = {str(item).lower().strip() for item in (requirement.required_fields or [])}
        arg_names = {str(item).lower().strip() for item in ([*tool.required_arguments, *tool.optional_arguments] or [])}
        field_match = 0
        if {"member_count", "leader", "leader_name", "website", "official_website", "name"} & required_fields:
            if "org_name" in arg_names:
                field_match += 3
        if {"title", "snippet", "published_at", "updated_at", "url", "source"} & required_fields:
            if {"scope", "entity", "keywords"} & arg_names:
                field_match += 2
        if {"graph", "relationship"} & required_fields:
            if "entity_name" in arg_names:
                field_match += 3
        if {"country"} & required_fields:
            if "country" in arg_names:
                field_match += 2

        qt_match = 1 if (not tool.supported_question_types or question_context.question_type.value in {str(v).upper().strip() for v in tool.supported_question_types}) else 0
        entity_match = 1 if (not tool.supported_entities) else 0
        if tool.supported_entities:
            available_entity_types = {
                str(item.get("entity_type") or item.get("type") or "").strip().lower()
                for item in (question_context.entities or [])
                if isinstance(item, dict)
            }
            if available_entity_types & {str(v).lower().strip() for v in tool.supported_entities}:
                entity_match = 1
        country_match = 1 if (not tool.supported_countries or not question_context.country) else 0
        if tool.supported_countries:
            normalized = {str(v).lower().strip() for v in tool.supported_countries}
            if question_context.country.lower() in normalized or "*" in normalized:
                country_match = 1
        return (int(tool.priority), field_match, qt_match, entity_match, country_match)

    def _capability_plan_score(
        self,
        tool: ToolDefinition,
        execution_requirement: ExecutionRequirement,
        requirement: Requirement,
        question_context: QuestionContext,
    ) -> tuple[int, int, int, int, int, int]:
        capability = execution_requirement.capability
        capability_match = 1 if self._normalize_capability_name(capability.name) in self._infer_tool_capabilities(tool) else 0
        required_match = 1 if capability.required else 0
        param_match = self._count_parameter_match(tool, execution_requirement.parameters)
        base = self._plan_score(tool, requirement, question_context)
        return (required_match, int(capability.priority or 0), capability_match, param_match, *base[:2])

    def _count_parameter_match(self, tool: ToolDefinition, parameters: Dict[str, Any]) -> int:
        arg_names = {str(item).lower().strip() for item in ([*tool.required_arguments, *tool.optional_arguments] or [])}
        matched = 0
        for key, value in (parameters or {}).items():
            if value in (None, "", [], {}):
                continue
            if str(key or "").lower().strip() in arg_names:
                matched += 1
        return matched

    def _infer_tool_capabilities(self, tool: ToolDefinition) -> set[str]:
        tags = set()
        lowered_name = tool.name.lower().strip()
        lowered_display = tool.display_name.lower().strip()
        category = tool.category.lower().strip()

        if "organization_profile" in lowered_name or "profile" in lowered_display or category == "profile":
            tags.add("PROFILE")
        if "contacts" in lowered_name or "contact" in lowered_display:
            tags.add("CONTACTS")
        if "graph" in lowered_name or category == "graph":
            tags.add("GRAPH")
            tags.add("RELATIONSHIP")
        if "intelligence" in lowered_name:
            tags.add("NEWS")
            tags.add("TIMELINE")
        if "database" in lowered_name:
            tags.add("DATABASE")
            tags.add("NEWS")
            tags.add("RANKING")
        if "arda_country" in lowered_name or category == "country":
            tags.add("COUNTRY_BASELINE")
        if "investor" in lowered_name or "funding" in lowered_name or category == "investment":
            tags.add("INVESTMENT")
            tags.add("RELATIONSHIP")
        if "fused" in lowered_name:
            tags.add("PROFILE")
            tags.add("DATABASE")
        if "ontology" in lowered_name or category == "classification":
            tags.add("PROFILE")
            tags.add("COUNTRY_BASELINE")
        if tool.supported_question_types:
            supported = {str(item).upper().strip() for item in tool.supported_question_types}
            if "TIMELINE" in supported:
                tags.add("TIMELINE")
            if "RANKING" in supported:
                tags.add("RANKING")
            if "CONTACT" in supported:
                tags.add("CONTACTS")
        return tags

    def _normalize_capability_name(self, name: str) -> str:
        lowered = str(name or "").strip().lower()
        aliases = {
            "organization profile": "PROFILE",
            "org profile": "PROFILE",
            "profile": "PROFILE",
            "graph profile": "PROFILE",
            "contact": "CONTACTS",
            "contacts": "CONTACTS",
            "relationship": "RELATIONSHIP",
            "relationships": "RELATIONSHIP",
            "graph": "GRAPH",
            "timeline": "TIMELINE",
            "news": "NEWS",
            "country": "COUNTRY_BASELINE",
            "country baseline": "COUNTRY_BASELINE",
            "investment": "INVESTMENT",
            "ranking": "RANKING",
            "database": "DATABASE",
        }
        return aliases.get(lowered, str(name or "").strip().upper())
