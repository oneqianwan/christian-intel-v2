from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List

from services.capability_planner import CapabilityPlan, CapabilityPlanner
from services.core_models import AnswerContext, Conflict, Evidence, Fact, QuestionContext, QuestionType, Requirement, Section
from services.execution_policy import ExecutionPolicyContext, ExecutionPolicyEngine
from services.feature_flags import feature_flag_enabled
from services.knowledge_layer import KnowledgeGraph
from services.runtime_metrics import get_runtime_metrics
from services.tool_registry import ExecutionPlan, ToolDefinition, ToolRegistry


class StopCondition(str, Enum):
    MAX_LOOP = "MAX_LOOP"
    NO_NEW_EVIDENCE = "NO_NEW_EVIDENCE"
    NO_NEW_FACT = "NO_NEW_FACT"
    NO_PROGRESS = "NO_PROGRESS"
    VERIFICATION_PASS = "VERIFICATION_PASS"


@dataclass
class RetrievalPlan:
    tool_priority: List[str] = field(default_factory=list)
    capability_plan: CapabilityPlan | None = None
    question_type: str = "UNKNOWN"
    entity_type: str = ""
    entity: str = ""
    country: str = ""
    keywords: List[str] = field(default_factory=list)
    expected_fields: List[str] = field(default_factory=list)
    expected_sources: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_priority": list(self.tool_priority or []),
            "capability_plan": self.capability_plan.to_dict() if self.capability_plan else None,
            "question_type": self.question_type,
            "entity_type": self.entity_type,
            "entity": self.entity,
            "country": self.country,
            "keywords": list(self.keywords or []),
            "expected_fields": list(self.expected_fields or []),
            "expected_sources": list(self.expected_sources or []),
        }


@dataclass
class LoopContext:
    loop_count: int = 0
    history: List[Dict[str, Any]] = field(default_factory=list)
    previous_missing: List[Dict[str, Any]] = field(default_factory=list)
    retrieval_history: List[Dict[str, Any]] = field(default_factory=list)
    tool_history: List[List[Dict[str, Any]]] = field(default_factory=list)
    merged_evidence: List[Evidence] = field(default_factory=list)
    merged_facts: List[Fact] = field(default_factory=list)
    merged_conflicts: List[Conflict] = field(default_factory=list)
    stop_conditions: List[str] = field(default_factory=list)


class RetrievalLoopController:
    def __init__(
        self,
        *,
        max_loop: int = 3,
        default_entity: str = "",
        default_country: str = "",
        default_question_type: str = "UNKNOWN",
        registry: ToolRegistry | None = None,
        capability_planner: CapabilityPlanner | None = None,
        registry_enabled: bool | None = None,
        trace_center: Any = None,
    ):
        self.max_loop = max(1, int(max_loop or 3))
        self.default_entity = str(default_entity or "")
        self.default_country = str(default_country or "")
        self.default_question_type = str(default_question_type or "UNKNOWN").upper().strip()
        self.registry_enabled = (
            feature_flag_enabled("TOOL_REGISTRY_ENABLED")
            if registry_enabled is None
            else bool(registry_enabled)
        )
        self.capability_planner_enabled = feature_flag_enabled("CAPABILITY_PLANNER_ENABLED")
        self.registry = registry
        if self.registry_enabled and self.registry is None:
            try:
                from services.default_registry import get_default_registry

                self.registry = get_default_registry()
            except Exception:
                self.registry = None
        self.capability_planner = capability_planner
        if self.capability_planner is None and self.capability_planner_enabled:
            self.capability_planner = CapabilityPlanner()
        self.trace_center = trace_center
        self.runtime_metrics = get_runtime_metrics()

    def should_continue(
        self,
        verification_result: Dict[str, Any],
        loop_count: int,
        loop_context: LoopContext | None = None,
    ) -> Dict[str, Any]:
        payload = self.build_loop_policy_payload(verification_result, loop_count, loop_context)
        decision = self._get_execution_policy_engine().evaluate_loop(
            ExecutionPolicyContext(
                question_type=self.default_question_type,
                verification=dict(payload.get("verification") or {}),
                trace=dict(payload.get("trace") or {}),
                loop_count=int(payload.get("loop_count") or 0),
                coverage=float((payload.get("verification") or {}).get("coverage") or 0.0),
            ),
            default_decision={"continue": False, "reason": StopCondition.VERIFICATION_PASS.value},
        )
        output = dict(decision.decision or {})
        self.runtime_metrics.inc(
            "loop_continue" if output.get("continue") else "loop_stop",
            labels={"reason": str(output.get("reason") or "")},
        )
        self._trace(
            "Loop Stop Decision" if not output.get("continue") else "Retrieval Loop Continue",
            metadata={
                "loop_count": int(loop_count or 0),
                "reason": str(output.get("reason") or ""),
                "matched_rule": decision.matched_rule,
            },
        )
        return output

    def build_loop_policy_payload(
        self,
        verification_result: Dict[str, Any],
        loop_count: int,
        loop_context: LoopContext | None = None,
    ) -> Dict[str, Any]:
        payload = dict(verification_result or {})
        stagnation_reason = self._detect_stagnation(loop_context)
        return {
            "verification": {
                **payload,
                "coverage": float(payload.get("coverage") or 0.0),
                "coverage_threshold": float(payload.get("coverage_threshold") or 0.0),
                "missing_fields": list(payload.get("missing_fields") or []),
                "blocking_conflict": bool(payload.get("blocking_conflict")),
            },
            "trace": {
                "operation": "continue",
                "max_loop": int(self.max_loop or 0),
                "stagnation_reason": str(stagnation_reason or ""),
            },
            "loop_count": int(loop_count or 0),
        }

    def analyse_missing_information(
        self,
        requirement: Requirement | Dict[str, Any],
        answer_context: AnswerContext | KnowledgeGraph | Dict[str, Any],
    ) -> Dict[str, List[str]]:
        req = self._ensure_requirement(requirement)
        knowledge_graph = self._ensure_knowledge_graph(answer_context)
        if knowledge_graph is not None:
            return self._analyse_missing_from_knowledge_graph(req, knowledge_graph)
        ctx = self._ensure_answer_context(answer_context, req)

        evidence = list(ctx.evidence or [])
        facts = list(ctx.facts or [])
        sections = list(ctx.sections or [])
        distinct_sources = {
            (item.source_name or "").strip()
            for item in evidence
            if (item.source_name or "").strip()
        }

        missing_fields: List[str] = []
        for field_name in req.required_fields or []:
            if not self._field_is_covered(field_name, facts, evidence, sections):
                missing_fields.append(str(field_name))

        missing_sources: List[str] = []
        for source_name in req.required_sources or []:
            if source_name and source_name not in distinct_sources:
                missing_sources.append(str(source_name))
        if len(distinct_sources) < int(req.minimum_sources or 1):
            missing_sources.append(f"need_{int(req.minimum_sources or 1)}_sources_have_{len(distinct_sources)}")

        missing_entities: List[str] = []
        if any(field in missing_fields for field in ["name", "leader", "leader_name", "member_count", "official_website", "website"]):
            has_primary_entity = any((fact.field or "").strip() == "name" for fact in facts) or any(
                (item.title or "").strip() for item in evidence
            )
            if not has_primary_entity:
                missing_entities.append("primary_entity")
        if any(field in missing_fields for field in ["graph", "relationship"]) and not any(section.fact_ids for section in sections):
            missing_entities.append("related_entity")

        result = {
            "missing_fields": self._dedupe_list(missing_fields),
            "missing_sources": self._dedupe_list(missing_sources),
            "missing_entities": self._dedupe_list(missing_entities),
        }
        self._trace(
            "Missing Information Analysed",
            metadata={
                "missing_fields": list(result.get("missing_fields") or []),
                "missing_sources": list(result.get("missing_sources") or []),
                "missing_entities": list(result.get("missing_entities") or []),
            },
        )
        return result

    def _analyse_missing_from_knowledge_graph(self, requirement: Requirement, knowledge_graph: KnowledgeGraph) -> Dict[str, List[str]]:
        evidence_index = dict((knowledge_graph.metadata or {}).get("evidence_index") or {})
        distinct_sources = {
            str(item.get("source_name") or "").strip()
            for item in evidence_index.values()
            if isinstance(item, dict) and str(item.get("source_name") or "").strip()
        }

        missing_fields: List[str] = []
        for field_name in requirement.required_fields or []:
            if not self._field_is_covered_in_knowledge_graph(str(field_name), knowledge_graph, evidence_index):
                missing_fields.append(str(field_name))

        missing_sources: List[str] = []
        for source_name in requirement.required_sources or []:
            if source_name and source_name not in distinct_sources:
                missing_sources.append(str(source_name))
        if len(distinct_sources) < int(requirement.minimum_sources or 1):
            missing_sources.append(f"need_{int(requirement.minimum_sources or 1)}_sources_have_{len(distinct_sources)}")

        missing_entities: List[str] = []
        if any(field in missing_fields for field in ["name", "leader", "leader_name", "member_count", "official_website", "website"]):
            if not any(str(node.name or "").strip() and str(node.type or "").strip().lower() == "organization" for node in (knowledge_graph.nodes or [])):
                missing_entities.append("primary_entity")
        if any(field in missing_fields for field in ["graph", "relationship"]) and not list(knowledge_graph.relations or []):
            missing_entities.append("related_entity")

        result = {
            "missing_fields": self._dedupe_list(missing_fields),
            "missing_sources": self._dedupe_list(missing_sources),
            "missing_entities": self._dedupe_list(missing_entities),
        }
        self._trace(
            "Missing Information Analysed",
            metadata={
                "missing_fields": list(result.get("missing_fields") or []),
                "missing_sources": list(result.get("missing_sources") or []),
                "missing_entities": list(result.get("missing_entities") or []),
                "knowledge_nodes": len(knowledge_graph.nodes or []),
                "knowledge_relations": len(knowledge_graph.relations or []),
            },
        )
        return result

    def generate_retrieval_plan(self, missing_information: Dict[str, Any]) -> RetrievalPlan:
        payload = dict(missing_information or {})
        missing_fields = self._dedupe_list(list(payload.get("missing_fields") or []))
        missing_sources = self._dedupe_list(list(payload.get("missing_sources") or []))
        missing_entities = self._dedupe_list(list(payload.get("missing_entities") or []))

        tool_priority: List[str] = []
        if any(field in missing_fields for field in ["graph", "relationship"]):
            tool_priority.append("query_graph")
        if any(field in missing_fields for field in ["leader", "leader_name", "member_count", "official_website", "website", "denomination", "name"]):
            tool_priority.append("query_organization_profile")
            tool_priority.append("query_contacts")
        if any(field in missing_fields for field in ["title", "snippet", "url", "published_at", "source", "source_name", "updated_at", "ranking"]):
            tool_priority.append("query_intelligence")
            tool_priority.append("query_database")
        if any(field in missing_fields for field in ["country"]) or any(src.startswith("need_") for src in missing_sources):
            tool_priority.append("query_arda_country")
            tool_priority.append("query_database")
        if not tool_priority:
            tool_priority.append("query_database")

        keywords = self._dedupe_list([*missing_fields, *missing_sources])
        entity = missing_entities[0] if missing_entities else self.default_entity
        country = self.default_country
        capability_plan = None
        if self.capability_planner is not None:
            requirement = Requirement(
                required_fields=missing_fields,
                required_sources=missing_sources,
                minimum_sources=1,
                minimum_confidence=0.0,
                coverage_threshold=0.0,
                allow_partial=True,
            )
            question_context = self._build_question_context(entity, country)
            capability_plan = self.capability_planner.analyse_requirement(requirement, question_context)
        retrieval_plan = RetrievalPlan(
            tool_priority=self._dedupe_list(tool_priority),
            capability_plan=capability_plan,
            question_type=self.default_question_type,
            entity_type="organization" if (entity or self.default_entity) else "",
            entity=str(entity or ""),
            country=str(country or ""),
            keywords=keywords[:8],
            expected_fields=missing_fields,
            expected_sources=missing_sources,
        )
        self._trace(
            "Retrieval Plan Generated",
            metadata={
                "tool_priority": list(retrieval_plan.tool_priority or []),
                "expected_fields": list(retrieval_plan.expected_fields or []),
                "expected_sources": list(retrieval_plan.expected_sources or []),
                "capabilities": [
                    item.name
                    for item in (
                        list(retrieval_plan.capability_plan.required_capabilities or [])
                        + list(retrieval_plan.capability_plan.optional_capabilities or [])
                    )
                ] if retrieval_plan.capability_plan else [],
            },
        )
        return retrieval_plan

    def generate_tool_calls(self, retrieval_plan: RetrievalPlan | Dict[str, Any]) -> List[Dict[str, Any]]:
        plan = self._ensure_retrieval_plan(retrieval_plan)
        if self.registry_enabled and self.registry is not None:
            execution_plan = self._build_execution_plan_from_registry(plan)
            registry_calls = self._build_calls_from_execution_plan(execution_plan, plan)
            if registry_calls:
                self._trace(
                    "Execution Plan Built",
                    metadata={
                        "tool_calls": [item.get("tool_name") for item in registry_calls],
                        "parallel_groups": [[tool.name for tool in group] for group in (execution_plan.parallel_groups or [])],
                        "fallback_tools": [tool.name for tool in (execution_plan.fallback_tools or [])],
                    },
                )
                return registry_calls
        calls: List[Dict[str, Any]] = []

        for tool_name in plan.tool_priority or []:
            args: Dict[str, Any] = {}
            if tool_name == "query_graph":
                if not plan.entity:
                    continue
                args = {"entity_name": plan.entity}
            elif tool_name == "query_organization_profile":
                if not plan.entity:
                    continue
                args = {"org_name": plan.entity}
            elif tool_name == "query_contacts":
                if not plan.entity:
                    continue
                args = {"org_name": plan.entity}
            elif tool_name == "query_arda_country":
                if not plan.country:
                    continue
                args = {"country": plan.country}
            elif tool_name == "query_intelligence":
                scope = "entity" if plan.entity else ("country" if plan.country else "global")
                args = {
                    "scope": scope,
                    "country": plan.country or None,
                    "entity": plan.entity or None,
                    "keywords": list(plan.keywords or []),
                    "limit": 10,
                }
            elif tool_name == "query_database":
                scope = "country" if plan.country else "global"
                args = {
                    "scope": scope,
                    "country": plan.country or None,
                    "entity": plan.entity or None,
                    "keywords": list(plan.keywords or []),
                    "limit": 10,
                }
            else:
                continue

            calls.append({"tool_name": tool_name, "args": args})

        deduped: List[Dict[str, Any]] = []
        seen = set()
        for item in calls:
            key = (item.get("tool_name"), str(sorted((item.get("args") or {}).items())))
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        self._trace("Execution Plan Built", metadata={"tool_calls": [item.get("tool_name") for item in deduped]})
        return deduped

    def merge_new_tool_results(self, old_results: List[Dict[str, Any]], new_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        merged: List[Dict[str, Any]] = []
        seen = set()
        for group in [old_results or [], new_results or []]:
            for item in group:
                if not isinstance(item, dict):
                    continue
                signature = self._tool_result_signature(item)
                if signature in seen:
                    continue
                seen.add(signature)
                merged.append(item)
        return merged

    def summarize_loop(self, loop_context: LoopContext) -> Dict[str, Any]:
        summary = {
            "loop_count": int(loop_context.loop_count or 0),
            "retrieval_times": len(loop_context.tool_history or []),
            "coverage_history": [float(item.get("coverage") or 0.0) for item in (loop_context.retrieval_history or [])],
            "missing_history": list(loop_context.previous_missing or []),
            "tool_history": list(loop_context.tool_history or []),
            "stop_conditions": list(loop_context.stop_conditions or []),
        }
        self._trace(
            "Retrieval Loop Summary",
            metadata={
                "loop_count": summary["loop_count"],
                "coverage_history": list(summary["coverage_history"] or []),
                "stop_conditions": list(summary["stop_conditions"] or []),
            },
        )
        self.runtime_metrics.set("loop_average", float(summary["loop_count"]))
        for item in list(summary["coverage_history"] or []):
            self.runtime_metrics.observe("loop.coverage", float(item or 0.0))
        return summary

    def _build_continue_reason(
        self,
        missing_fields: List[str],
        coverage: float,
        threshold: float,
        blocking_conflict: bool,
    ) -> str:
        reasons: List[str] = []
        if missing_fields:
            reasons.append("MISSING_FIELDS")
        if coverage < threshold:
            reasons.append("LOW_COVERAGE")
        if blocking_conflict:
            reasons.append("BLOCKING_CONFLICT")
        return "+".join(reasons) or "CONTINUE"

    def _detect_stagnation(self, loop_context: LoopContext | None) -> str | None:
        if not loop_context:
            return None
        history = list(loop_context.retrieval_history or [])
        if len(history) < 3:
            return None
        recent = history[-3:]
        evidence_counts = [int(item.get("evidence_count") or 0) for item in recent]
        fact_counts = [int(item.get("fact_count") or 0) for item in recent]
        coverage_scores = [float(item.get("coverage") or 0.0) for item in recent]

        if evidence_counts[0] == evidence_counts[1] == evidence_counts[2]:
            return StopCondition.NO_NEW_EVIDENCE.value
        if fact_counts[0] == fact_counts[1] == fact_counts[2]:
            return StopCondition.NO_NEW_FACT.value
        if coverage_scores[0] >= coverage_scores[1] >= coverage_scores[2]:
            if coverage_scores[0] == coverage_scores[1] == coverage_scores[2]:
                return StopCondition.NO_PROGRESS.value
        return None

    def _field_is_covered(
        self,
        field_name: str,
        facts: List[Fact],
        evidence: List[Evidence],
        sections: List[Section],
    ) -> bool:
        field = (field_name or "").strip().lower()
        if not field:
            return False

        if field in {"source", "source_name"}:
            return any((item.source_name or "").strip() for item in evidence)
        if field in {"title", "snippet", "url", "confidence", "published_at", "updated_at", "type"}:
            return any(str(getattr(item, field, "") or "").strip() for item in evidence if hasattr(item, field))
        if field in {"ranking"}:
            return any(section.title.lower().startswith("top") or "ranking" in section.title.lower() for section in sections)
        if field in {"graph", "relationship"}:
            return any("graph" in section.title.lower() or "relationship" in section.title.lower() for section in sections) or any(
                fact.field in {"graph", "relationship"} for fact in facts
            )
        aliases = {
            "leader": {"leader", "leader_name"},
            "website": {"website", "official_website"},
            "official_website": {"website", "official_website"},
            "member_count": {"member_count", "member_estimate"},
        }
        accepted = aliases.get(field, {field})
        return any((fact.field or "").strip().lower() in accepted for fact in facts)

    def _ensure_requirement(self, requirement: Requirement | Dict[str, Any]) -> Requirement:
        if isinstance(requirement, Requirement):
            return requirement
        return Requirement.from_dict(requirement or {})

    def _ensure_answer_context(self, answer_context: AnswerContext | Dict[str, Any], requirement: Requirement) -> AnswerContext:
        if isinstance(answer_context, AnswerContext):
            return answer_context
        if isinstance(answer_context, dict):
            return AnswerContext.from_dict(answer_context or {})
        return AnswerContext(
            question="",
            requirement=requirement,
            sections=[],
            facts=[],
            conflicts=[],
            missing=list(requirement.required_fields or []),
            citation_map={},
            evidence=[],
        )

    def _ensure_knowledge_graph(self, payload: Any) -> KnowledgeGraph | None:
        if isinstance(payload, KnowledgeGraph):
            return payload
        if isinstance(payload, dict) and ("nodes" in payload or "relations" in payload):
            return KnowledgeGraph.from_dict(payload)
        return None

    def _ensure_retrieval_plan(self, plan: RetrievalPlan | Dict[str, Any]) -> RetrievalPlan:
        if isinstance(plan, RetrievalPlan):
            return plan
        payload = dict(plan or {})
        return RetrievalPlan(
            tool_priority=list(payload.get("tool_priority") or []),
            capability_plan=CapabilityPlan.from_dict(payload.get("capability_plan") or {})
            if isinstance(payload.get("capability_plan"), dict)
            else None,
            question_type=str(payload.get("question_type") or "UNKNOWN"),
            entity_type=str(payload.get("entity_type") or ""),
            entity=str(payload.get("entity") or ""),
            country=str(payload.get("country") or ""),
            keywords=list(payload.get("keywords") or []),
            expected_fields=list(payload.get("expected_fields") or []),
            expected_sources=list(payload.get("expected_sources") or []),
        )

    def _tool_result_signature(self, result: Dict[str, Any]) -> str:
        query_summary = result.get("query_summary") if isinstance(result.get("query_summary"), dict) else {}
        org_name = str(result.get("org_name") or "")
        status = str(result.get("status") or "")
        count = str(result.get("count") or "")
        evidence = result.get("evidence") if isinstance(result.get("evidence"), list) else []
        evidence_key = "|".join(
            [
                str(item.get("url") or f"{item.get('title')}|{item.get('source_name')}|{item.get('published_at')}")
                for item in evidence[:10]
                if isinstance(item, dict)
            ]
        )
        return "|".join(
            [
                status,
                org_name,
                count,
                str(query_summary.get("scope") or ""),
                str(query_summary.get("country") or ""),
                str(query_summary.get("entity") or ""),
                evidence_key,
            ]
        )

    def _build_execution_plan_from_registry(self, plan: RetrievalPlan) -> ExecutionPlan:
        question_type_value = str(plan.question_type or self.default_question_type or "UNKNOWN").upper().strip()
        qt = QuestionType(question_type_value) if question_type_value in getattr(QuestionType, "_value2member_map_", {}) else QuestionType.UNKNOWN
        requirement = Requirement(
            required_fields=list(plan.expected_fields or []),
            required_sources=list(plan.expected_sources or []),
            minimum_sources=1,
            minimum_confidence=0.0,
            coverage_threshold=0.0,
            allow_partial=True,
        )
        entities = []
        if plan.entity:
            entities.append({"name": plan.entity, "entity_type": plan.entity_type or "organization"})
        question_context = QuestionContext(
            question="",
            question_type=qt,
            language="",
            country=plan.country or "",
            entities=entities,
            time_range=None,
            comparison=qt == QuestionType.COMPARISON,
            ranking=qt == QuestionType.RANKING,
            relationship=qt in {QuestionType.RELATIONSHIP, QuestionType.GRAPH, QuestionType.INVESTMENT},
            conversation_id="",
        )
        if self.capability_planner is not None and plan.capability_plan is not None:
            execution_requirements = self.capability_planner.build_execution_requirements(
                plan.capability_plan,
                question_context,
                requirement=requirement,
            )
            execution_plan = self.registry.build_execution_plan_from_capability_plan(
                plan.capability_plan,
                question_context,
                requirement,
                execution_requirements=execution_requirements,
                trace_center=self.trace_center,
            )
        else:
            execution_plan = self.registry.build_execution_plan(requirement, question_context, trace_center=self.trace_center)
        if not plan.tool_priority:
            return execution_plan

        preferred = list(plan.tool_priority or [])
        ordered = list(execution_plan.ordered_tools or [])
        ordered.sort(
            key=lambda item: (
                preferred.index(item.name) if item.name in preferred else len(preferred),
                -int(item.priority),
            )
        )
        fallback = [item for item in (execution_plan.fallback_tools or []) if item.name not in {tool.name for tool in ordered}]
        return ExecutionPlan(
            ordered_tools=ordered,
            parallel_groups=list(execution_plan.parallel_groups or []),
            fallback_tools=fallback,
            execution_requirements=list(execution_plan.execution_requirements or []),
            stop_after_success=execution_plan.stop_after_success,
        )

    def _build_calls_from_execution_plan(self, execution_plan: ExecutionPlan, plan: RetrievalPlan) -> List[Dict[str, Any]]:
        calls: List[Dict[str, Any]] = []
        execution_requirements = list(execution_plan.execution_requirements or [])
        for index, tool in enumerate(execution_plan.ordered_tools or []):
            execution_requirement = execution_requirements[index] if index < len(execution_requirements) else None
            args = self._build_args_for_tool(tool, plan, execution_requirement)
            if args is None:
                continue
            calls.append({"tool_name": tool.name, "args": args})
        deduped: List[Dict[str, Any]] = []
        seen = set()
        for item in calls:
            key = (item.get("tool_name"), str(sorted((item.get("args") or {}).items())))
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        return deduped

    def _build_args_for_tool(
        self,
        tool: ToolDefinition,
        plan: RetrievalPlan,
        execution_requirement: Any = None,
    ) -> Dict[str, Any] | None:
        args: Dict[str, Any] = {}
        planned_parameters = dict(getattr(execution_requirement, "parameters", {}) or {})
        for arg_name in list(tool.required_arguments or []) + list(tool.optional_arguments or []):
            value = self._resolve_argument_value(arg_name, plan, planned_parameters)
            if value is None:
                continue
            args[arg_name] = value
        missing_required = [name for name in (tool.required_arguments or []) if name not in args]
        if missing_required:
            return None
        return args

    def _resolve_argument_value(self, arg_name: str, plan: RetrievalPlan, planned_parameters: Dict[str, Any] | None = None) -> Any:
        name = str(arg_name or "").strip()
        if not name:
            return None
        planned_parameters = dict(planned_parameters or {})
        if name in planned_parameters and planned_parameters.get(name) not in (None, "", [], {}):
            return planned_parameters.get(name)
        if name == "org_name":
            return planned_parameters.get("org_name") or planned_parameters.get("entity") or plan.entity or None
        if name == "entity_name":
            return planned_parameters.get("entity_name") or planned_parameters.get("entity") or plan.entity or None
        if name == "country":
            return planned_parameters.get("country") or plan.country or None
        if name == "entity":
            return planned_parameters.get("entity") or plan.entity or None
        if name == "keywords":
            return list(planned_parameters.get("keywords") or plan.keywords or [])
        if name == "scope":
            if planned_parameters.get("scope"):
                return planned_parameters.get("scope")
            if plan.entity:
                return "entity"
            if plan.country:
                return "country"
            return "global"
        if name == "limit":
            return 10
        if name == "relation_type":
            return "all"
        if name == "depth":
            return 1
        return None

    def _build_question_context(self, entity: str, country: str) -> QuestionContext:
        question_type_value = str(self.default_question_type or "UNKNOWN").upper().strip()
        qt = QuestionType(question_type_value) if question_type_value in getattr(QuestionType, "_value2member_map_", {}) else QuestionType.UNKNOWN
        entities = []
        if entity:
            entity_type = "organization" if entity != "primary_entity" else "organization"
            entities.append({"name": entity if entity != "primary_entity" else self.default_entity, "entity_type": entity_type})
        return QuestionContext(
            question="",
            question_type=qt,
            language="",
            country=str(country or ""),
            entities=entities,
            time_range=None,
            comparison=qt == QuestionType.COMPARISON,
            ranking=qt == QuestionType.RANKING,
            relationship=qt in {QuestionType.RELATIONSHIP, QuestionType.GRAPH, QuestionType.INVESTMENT},
            conversation_id="",
        )

    def _field_is_covered_in_knowledge_graph(
        self,
        field_name: str,
        knowledge_graph: KnowledgeGraph,
        evidence_index: Dict[str, Dict[str, Any]],
    ) -> bool:
        field = (field_name or "").strip().lower()
        if not field:
            return False
        if field in {"source", "source_name"}:
            return any(str(item.get("source_name") or "").strip() for item in evidence_index.values() if isinstance(item, dict))
        if field in {"title", "snippet", "url", "confidence", "published_at", "updated_at", "type"}:
            return any(str(item.get(field) or "").strip() for item in evidence_index.values() if isinstance(item, dict))
        if field in {"graph", "relationship"}:
            return bool(knowledge_graph.relations)

        for node in knowledge_graph.nodes or []:
            properties = dict(node.properties or {})
            node_type = str(node.type or "").strip().lower()
            if field == "name" and node_type == "organization" and str(node.name or "").strip():
                return True
            if field in {"leader", "leader_name"}:
                if str(properties.get("leader_name") or properties.get("leader") or "").strip():
                    return True
                if any(str(relation.relation or "").upper() == "LED_BY" and relation.source_node == node.id for relation in (knowledge_graph.relations or [])):
                    return True
            if field in {"website", "official_website"} and str(properties.get("official_website") or properties.get("website") or "").strip():
                return True
            if field in {"member_count", "member_estimate"} and str(properties.get("member_count") or properties.get("member_estimate") or "").strip():
                return True
            if field == "country":
                if node_type == "country" and str(node.name or "").strip():
                    return True
                if str(properties.get("country") or "").strip():
                    return True
            if field == "denomination" and str(properties.get("denomination") or "").strip():
                return True
        return False

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

    def _trace(self, event_name: str, metadata: Dict[str, Any] | None = None) -> None:
        if self.trace_center is None:
            return
        self.trace_center.record_event("RETRIEVAL_LOOP", event_name, metadata=metadata or {})

    def _get_execution_policy_engine(self) -> ExecutionPolicyEngine:
        return ExecutionPolicyEngine(trace_center=self.trace_center)
