from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from services.core_models import QuestionContext, QuestionType, Requirement


@dataclass(frozen=True)
class Capability:
    name: str
    description: str
    priority: int
    required: bool
    parameters: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "priority": int(self.priority),
            "required": bool(self.required),
            "parameters": dict(self.parameters or {}),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Capability":
        payload = data or {}
        return cls(
            name=str(payload.get("name") or ""),
            description=str(payload.get("description") or ""),
            priority=int(payload.get("priority") or 0),
            required=bool(payload.get("required")),
            parameters=dict(payload.get("parameters") or {}),
        )


@dataclass(frozen=True)
class CapabilityPlan:
    required_capabilities: List[Capability] = field(default_factory=list)
    optional_capabilities: List[Capability] = field(default_factory=list)
    parallel_groups: List[List[Capability]] = field(default_factory=list)
    fallback_capabilities: List[Capability] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "required_capabilities": [item.to_dict() for item in (self.required_capabilities or [])],
            "optional_capabilities": [item.to_dict() for item in (self.optional_capabilities or [])],
            "parallel_groups": [[item.to_dict() for item in group] for group in (self.parallel_groups or [])],
            "fallback_capabilities": [item.to_dict() for item in (self.fallback_capabilities or [])],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CapabilityPlan":
        payload = data or {}
        return cls(
            required_capabilities=[
                Capability.from_dict(item)
                for item in (payload.get("required_capabilities") or [])
                if isinstance(item, dict)
            ],
            optional_capabilities=[
                Capability.from_dict(item)
                for item in (payload.get("optional_capabilities") or [])
                if isinstance(item, dict)
            ],
            parallel_groups=[
                [Capability.from_dict(item) for item in group if isinstance(item, dict)]
                for group in (payload.get("parallel_groups") or [])
                if isinstance(group, list)
            ],
            fallback_capabilities=[
                Capability.from_dict(item)
                for item in (payload.get("fallback_capabilities") or [])
                if isinstance(item, dict)
            ],
        )


@dataclass(frozen=True)
class ExecutionRequirement:
    capability: Capability
    parameters: Dict[str, Any] = field(default_factory=dict)
    expected_output: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "capability": self.capability.to_dict(),
            "parameters": dict(self.parameters or {}),
            "expected_output": list(self.expected_output or []),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExecutionRequirement":
        payload = data or {}
        capability = payload.get("capability") if isinstance(payload.get("capability"), dict) else {}
        return cls(
            capability=Capability.from_dict(capability),
            parameters=dict(payload.get("parameters") or {}),
            expected_output=list(payload.get("expected_output") or []),
        )


class CapabilityPlanner:
    _CANONICAL_NAMES = {
        "organization profile": "PROFILE",
        "org profile": "PROFILE",
        "profile": "PROFILE",
        "graph profile": "PROFILE",
        "organization": "PROFILE",
        "contacts": "CONTACTS",
        "contact": "CONTACTS",
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

    _QUESTION_TYPE_WEIGHT = {
        QuestionType.PROFILE.value: {"PROFILE": 40, "NEWS": 15, "CONTACTS": 10},
        QuestionType.NEWS.value: {"NEWS": 40, "TIMELINE": 25, "PROFILE": 10},
        QuestionType.TIMELINE.value: {"TIMELINE": 40, "NEWS": 25, "PROFILE": 10},
        QuestionType.COMPARISON.value: {"PROFILE": 35, "GRAPH": 15, "NEWS": 10},
        QuestionType.RANKING.value: {"RANKING": 40, "PROFILE": 25, "NEWS": 15},
        QuestionType.RELATIONSHIP.value: {"RELATIONSHIP": 40, "GRAPH": 35, "PROFILE": 10},
        QuestionType.GRAPH.value: {"GRAPH": 40, "RELATIONSHIP": 35, "PROFILE": 10},
        QuestionType.CONTACT.value: {"CONTACTS": 40, "PROFILE": 25},
        QuestionType.INVESTMENT.value: {"INVESTMENT": 40, "GRAPH": 25, "PROFILE": 10},
        QuestionType.COUNTRY.value: {"COUNTRY_BASELINE": 40, "NEWS": 15, "DATABASE": 10},
        QuestionType.UNKNOWN.value: {"PROFILE": 15, "NEWS": 10, "DATABASE": 10},
    }

    def analyse_requirement(self, requirement: Requirement, question_context: QuestionContext) -> CapabilityPlan:
        required: List[Capability] = []
        optional: List[Capability] = []
        fallback: List[Capability] = []

        question_type = self._question_type_value(question_context)
        fields = {str(item or "").strip().lower() for item in (requirement.required_fields or []) if str(item or "").strip()}
        has_entity = bool(self._pick_entity_name(question_context))
        has_country = bool((question_context.country or "").strip())

        if {"name", "website", "official_website", "leader", "leader_name", "member_count", "denomination"} & fields:
            required.append(self._build_capability("PROFILE", True, 95, question_context, requirement))

        if {"title", "snippet", "published_at", "updated_at", "url", "source", "source_name"} & fields:
            priority = 92 if question_type in {QuestionType.NEWS.value, QuestionType.TIMELINE.value} else 78
            required.append(self._build_capability("NEWS", True, priority, question_context, requirement))

        if {"graph"} & fields or question_type == QuestionType.GRAPH.value:
            required.append(self._build_capability("GRAPH", True, 94, question_context, requirement))

        if {"relationship"} & fields or question_type == QuestionType.RELATIONSHIP.value:
            required.append(self._build_capability("RELATIONSHIP", True, 93, question_context, requirement))

        if question_type == QuestionType.TIMELINE.value:
            required.append(self._build_capability("TIMELINE", True, 90, question_context, requirement))

        if question_type == QuestionType.CONTACT.value:
            required.append(self._build_capability("CONTACTS", True, 96, question_context, requirement))

        if question_type == QuestionType.INVESTMENT.value:
            required.append(self._build_capability("INVESTMENT", True, 94, question_context, requirement))

        if question_type == QuestionType.RANKING.value or "ranking" in fields:
            required.append(self._build_capability("RANKING", True, 88, question_context, requirement))

        if question_type == QuestionType.COUNTRY.value or ("country" in fields and not has_entity and has_country):
            required.append(self._build_capability("COUNTRY_BASELINE", True, 90, question_context, requirement))

        if not required:
            default_name = "COUNTRY_BASELINE" if (has_country and not has_entity) else "PROFILE"
            required.append(self._build_capability(default_name, True, 70, question_context, requirement))

        if has_entity and question_type in {
            QuestionType.PROFILE.value,
            QuestionType.CONTACT.value,
            QuestionType.INVESTMENT.value,
            QuestionType.RELATIONSHIP.value,
            QuestionType.GRAPH.value,
        }:
            optional.append(self._build_capability("NEWS", False, 60, question_context, requirement))

        if question_type in {QuestionType.NEWS.value, QuestionType.TIMELINE.value, QuestionType.RANKING.value}:
            optional.append(self._build_capability("DATABASE", False, 55, question_context, requirement))

        if has_entity and question_type in {QuestionType.GRAPH.value, QuestionType.RELATIONSHIP.value, QuestionType.INVESTMENT.value}:
            optional.append(self._build_capability("PROFILE", False, 58, question_context, requirement))

        fallback.append(self._build_capability("DATABASE", False, 40, question_context, requirement))

        ranked_required = self.rank_capabilities(self.merge_duplicate_capabilities(required), question_context)
        ranked_optional = self.rank_capabilities(self.merge_duplicate_capabilities(optional), question_context)
        ranked_fallback = self.rank_capabilities(self.merge_duplicate_capabilities(fallback), question_context)

        parallel_groups = self._build_parallel_groups(ranked_required, ranked_optional, question_type)
        return CapabilityPlan(
            required_capabilities=ranked_required,
            optional_capabilities=ranked_optional,
            parallel_groups=parallel_groups,
            fallback_capabilities=ranked_fallback,
        )

    def rank_capabilities(
        self,
        capabilities: List[Capability],
        question_context: QuestionContext | None = None,
    ) -> List[Capability]:
        question_type = self._question_type_value(question_context)

        def score(item: Capability) -> tuple[int, int, int, str]:
            type_weight = self._QUESTION_TYPE_WEIGHT.get(question_type, {}).get(self._canonical_name(item.name), 0)
            return (1 if item.required else 0, int(item.priority), int(type_weight), item.name)

        return sorted(list(capabilities or []), key=score, reverse=True)

    def merge_duplicate_capabilities(self, capabilities: List[Capability]) -> List[Capability]:
        merged: Dict[str, Capability] = {}
        for capability in capabilities or []:
            canonical = self._canonical_name(capability.name)
            existing = merged.get(canonical)
            normalized = Capability(
                name=canonical,
                description=capability.description or self._default_description(canonical),
                priority=int(capability.priority or 0),
                required=bool(capability.required),
                parameters=dict(capability.parameters or {}),
            )
            if existing is None:
                merged[canonical] = normalized
                continue
            merged[canonical] = Capability(
                name=canonical,
                description=existing.description or normalized.description,
                priority=max(int(existing.priority or 0), int(normalized.priority or 0)),
                required=bool(existing.required or normalized.required),
                parameters=self._merge_parameters(existing.parameters, normalized.parameters),
            )
        return list(merged.values())

    def build_execution_requirement(
        self,
        capability: Capability | Dict[str, Any],
        question_context: QuestionContext,
        requirement: Requirement | None = None,
    ) -> ExecutionRequirement:
        item = capability if isinstance(capability, Capability) else Capability.from_dict(capability or {})
        entity_name = self._pick_entity_name(question_context)
        params = dict(item.parameters or {})
        if entity_name and "org_name" not in params:
            params["org_name"] = entity_name
            params.setdefault("entity_name", entity_name)
            params.setdefault("entity", entity_name)
        if (question_context.country or "").strip():
            params.setdefault("country", question_context.country)
        if "keywords" not in params:
            params["keywords"] = self._build_keywords(requirement, question_context)
        params.setdefault("scope", self._infer_scope(question_context))
        params.setdefault("limit", 10)
        expected_output = self._build_expected_output(item, requirement)
        return ExecutionRequirement(capability=item, parameters=params, expected_output=expected_output)

    def build_execution_requirements(
        self,
        capability_plan: CapabilityPlan,
        question_context: QuestionContext,
        requirement: Requirement | None = None,
    ) -> List[ExecutionRequirement]:
        out: List[ExecutionRequirement] = []
        for capability in list(capability_plan.required_capabilities or []) + list(capability_plan.optional_capabilities or []):
            out.append(self.build_execution_requirement(capability, question_context, requirement=requirement))
        return out

    def build_task_seed(
        self,
        capability_plan: CapabilityPlan,
        question_context: QuestionContext,
        requirement: Requirement | None = None,
    ) -> Dict[str, Any]:
        requirement = requirement or ensure_requirement_fallback()
        ranked_required = self.rank_capabilities(list(capability_plan.required_capabilities or []), question_context)
        ranked_optional = self.rank_capabilities(list(capability_plan.optional_capabilities or []), question_context)
        return {
            "question_type": self._question_type_value(question_context),
            "required_capabilities": [item.to_dict() for item in ranked_required],
            "optional_capabilities": [item.to_dict() for item in ranked_optional],
            "parallel_groups": [[item.to_dict() for item in group] for group in (capability_plan.parallel_groups or [])],
            "required_fields": list(requirement.required_fields or []),
            "entity_name": self._pick_entity_name(question_context),
            "country": str(question_context.country or ""),
        }

    def summarise_capability_plan(self, capability_plan: CapabilityPlan) -> Dict[str, Any]:
        required = [str(item.name or "") for item in (capability_plan.required_capabilities or [])]
        optional = [str(item.name or "") for item in (capability_plan.optional_capabilities or [])]
        fallback = [str(item.name or "") for item in (capability_plan.fallback_capabilities or [])]
        return {
            "required_count": len(required),
            "optional_count": len(optional),
            "fallback_count": len(fallback),
            "required_capabilities": required,
            "optional_capabilities": optional,
            "fallback_capabilities": fallback,
            "parallel_group_count": len(capability_plan.parallel_groups or []),
        }

    def _build_capability(
        self,
        name: str,
        required: bool,
        priority: int,
        question_context: QuestionContext,
        requirement: Requirement,
    ) -> Capability:
        canonical = self._canonical_name(name)
        params: Dict[str, Any] = {}
        entity_name = self._pick_entity_name(question_context)
        if entity_name:
            params["entity"] = entity_name
        if (question_context.country or "").strip():
            params["country"] = question_context.country
        params["question_type"] = self._question_type_value(question_context)
        params["required_fields"] = list(requirement.required_fields or [])
        return Capability(
            name=canonical,
            description=self._default_description(canonical),
            priority=int(priority or 0),
            required=bool(required),
            parameters=params,
        )

    def _build_parallel_groups(
        self,
        required_capabilities: List[Capability],
        optional_capabilities: List[Capability],
        question_type: str,
    ) -> List[List[Capability]]:
        groups: List[List[Capability]] = []
        by_name = {cap.name: cap for cap in list(required_capabilities or []) + list(optional_capabilities or [])}
        if question_type in {QuestionType.PROFILE.value, QuestionType.CONTACT.value}:
            if "PROFILE" in by_name and "NEWS" in by_name:
                groups.append([by_name["PROFILE"], by_name["NEWS"]])
        if question_type in {QuestionType.RELATIONSHIP.value, QuestionType.GRAPH.value, QuestionType.INVESTMENT.value}:
            pair: List[Capability] = []
            if "GRAPH" in by_name:
                pair.append(by_name["GRAPH"])
            if "PROFILE" in by_name:
                pair.append(by_name["PROFILE"])
            if len(pair) >= 2:
                groups.append(pair[:2])
        return groups

    def _build_expected_output(self, capability: Capability, requirement: Requirement | None) -> List[str]:
        outputs = list(requirement.required_fields or []) if requirement else []
        if outputs:
            return outputs
        defaults = {
            "PROFILE": ["name", "website", "leader", "member_count", "country"],
            "NEWS": ["title", "snippet", "url", "published_at", "source_name"],
            "TIMELINE": ["title", "published_at", "updated_at", "source_name"],
            "CONTACTS": ["name", "leader", "website", "source_name"],
            "GRAPH": ["graph", "relationship", "source_name"],
            "RELATIONSHIP": ["relationship", "source_name", "updated_at"],
            "INVESTMENT": ["investment", "relationship", "source_name"],
            "COUNTRY_BASELINE": ["country", "source_name", "updated_at"],
            "RANKING": ["ranking", "member_count", "source_name"],
            "DATABASE": ["source_name", "updated_at"],
        }
        return list(defaults.get(self._canonical_name(capability.name), ["source_name"]))

    def _build_keywords(self, requirement: Requirement | None, question_context: QuestionContext) -> List[str]:
        keywords = []
        if requirement:
            keywords.extend(list(requirement.required_fields or []))
        if question_context.question:
            keywords.extend(str(question_context.question or "").split()[:6])
        return self._dedupe_list([item for item in keywords if item])[:10]

    def _infer_scope(self, question_context: QuestionContext) -> str:
        if self._pick_entity_name(question_context):
            return "entity"
        if (question_context.country or "").strip():
            return "country"
        return "global"

    def _pick_entity_name(self, question_context: QuestionContext) -> str:
        for item in list(question_context.entities or []):
            if isinstance(item, dict) and (item.get("name") or "").strip():
                return str(item.get("name") or "").strip()
        return ""

    def _question_type_value(self, question_context: QuestionContext | None) -> str:
        if question_context is None:
            return QuestionType.UNKNOWN.value
        question_type = getattr(question_context, "question_type", QuestionType.UNKNOWN)
        return question_type.value if hasattr(question_type, "value") else str(question_type or QuestionType.UNKNOWN.value)

    def _canonical_name(self, name: str) -> str:
        normalized = str(name or "").strip().lower()
        return self._CANONICAL_NAMES.get(normalized, str(name or "").strip().upper() or "DATABASE")

    def _default_description(self, capability_name: str) -> str:
        descriptions = {
            "PROFILE": "Retrieve organization profile facts such as website, leader, denomination and member count.",
            "NEWS": "Retrieve recent news, intelligence and supporting evidence snippets.",
            "TIMELINE": "Retrieve chronological events and recent updates.",
            "CONTACTS": "Retrieve organization contacts or contact-adjacent public profile information.",
            "GRAPH": "Retrieve graph structure and key links between entities.",
            "RELATIONSHIP": "Retrieve relationship evidence between organizations, investors or people.",
            "INVESTMENT": "Retrieve funding, investor and financing relationship information.",
            "COUNTRY_BASELINE": "Retrieve country-level religious or organization baseline information.",
            "RANKING": "Retrieve ranking-oriented data and comparable measures.",
            "DATABASE": "Retrieve generic fallback evidence from internal databases.",
        }
        return descriptions.get(capability_name, "Retrieve supporting information for the current question.")

    def _merge_parameters(self, left: Dict[str, Any], right: Dict[str, Any]) -> Dict[str, Any]:
        merged = dict(left or {})
        for key, value in (right or {}).items():
            if key not in merged or merged.get(key) in (None, "", [], {}):
                merged[key] = value
        return merged

    def _dedupe_list(self, items: List[str]) -> List[str]:
        seen = set()
        ordered: List[str] = []
        for item in items or []:
            text = str(item or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            ordered.append(text)
        return ordered


def ensure_requirement_fallback() -> Requirement:
    return Requirement(
        required_fields=[],
        required_sources=[],
        minimum_sources=1,
        minimum_confidence=0.0,
        coverage_threshold=0.0,
        allow_partial=True,
    )
