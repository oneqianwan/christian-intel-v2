from __future__ import annotations

import asyncio
import json
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List

from services.capability_planner import Capability, CapabilityPlan
from services.core_models import QuestionContext, Requirement
from services.execution_policy import ExecutionPolicyContext, ExecutionPolicyEngine
from services.feature_flags import feature_flag_enabled
from services.runtime_metrics import get_runtime_metrics
from services.service_container import ServiceContainer
from services.trace_center import trace_span


def _safe_json_dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=True, default=str)


def _safe_governor_print(message: str) -> None:
    try:
        print(message)
    except Exception:
        try:
            print("GOVERNOR_LOG_SKIPPED")
        except Exception:
            pass


def _governor_stream_trace(event: str, **payload: Any) -> None:
    try:
        _safe_governor_print("GOVERNOR_EXECUTE_STREAM_TRACE " + _safe_json_dumps({"event": event, **payload}))
    except Exception:
        _safe_governor_print("GOVERNOR_LOG_SKIPPED")


def _governor_lifecycle_trace(event: str, *, conversation_id: str, generator_id: str, started_at: float, **payload: Any) -> None:
    try:
        _safe_governor_print(
            "GOVERNOR_STREAM_TRACE "
            + _safe_json_dumps(
                {
                    "event": event,
                    "conversation_id": conversation_id,
                    "generator_id": generator_id,
                    "thread_id": threading.get_ident(),
                    "elapsed_ms": round((time.perf_counter() - started_at) * 1000, 3),
                    **payload,
                }
            )
        )
    except Exception:
        _safe_governor_print("GOVERNOR_LOG_SKIPPED")


@dataclass(frozen=True)
class PipelineDefinition:
    name: str
    description: str
    supported_question_types: List[str] = field(default_factory=list)
    supported_capabilities: List[str] = field(default_factory=list)
    priority: int = 0
    cost: str = "medium"
    latency: str = "medium"
    supports_stream: bool = True
    enabled: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "supported_question_types": list(self.supported_question_types or []),
            "supported_capabilities": list(self.supported_capabilities or []),
            "priority": int(self.priority),
            "cost": self.cost,
            "latency": self.latency,
            "supports_stream": bool(self.supports_stream),
            "enabled": bool(self.enabled),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PipelineDefinition":
        payload = data or {}
        return cls(
            name=str(payload.get("name") or ""),
            description=str(payload.get("description") or ""),
            supported_question_types=list(payload.get("supported_question_types") or []),
            supported_capabilities=list(payload.get("supported_capabilities") or []),
            priority=int(payload.get("priority") or 0),
            cost=str(payload.get("cost") or "medium"),
            latency=str(payload.get("latency") or "medium"),
            supports_stream=bool(payload.get("supports_stream", True)),
            enabled=bool(payload.get("enabled", True)),
        )


@dataclass(frozen=True)
class PipelineSelection:
    selected_pipeline: PipelineDefinition
    candidate_pipelines: List[PipelineDefinition] = field(default_factory=list)
    selection_reason: str = ""
    confidence: float = 0.0
    fallback_pipeline: PipelineDefinition | None = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "selected_pipeline": self.selected_pipeline.to_dict(),
            "candidate_pipelines": [item.to_dict() for item in (self.candidate_pipelines or [])],
            "selection_reason": self.selection_reason,
            "confidence": float(self.confidence),
            "fallback_pipeline": self.fallback_pipeline.to_dict() if self.fallback_pipeline else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PipelineSelection":
        payload = data or {}
        selected = payload.get("selected_pipeline") if isinstance(payload.get("selected_pipeline"), dict) else {}
        fallback = payload.get("fallback_pipeline") if isinstance(payload.get("fallback_pipeline"), dict) else None
        return cls(
            selected_pipeline=PipelineDefinition.from_dict(selected),
            candidate_pipelines=[
                PipelineDefinition.from_dict(item)
                for item in (payload.get("candidate_pipelines") or [])
                if isinstance(item, dict)
            ],
            selection_reason=str(payload.get("selection_reason") or ""),
            confidence=float(payload.get("confidence") or 0.0),
            fallback_pipeline=PipelineDefinition.from_dict(fallback) if fallback else None,
        )


@dataclass(frozen=True)
class GovernorContext:
    question: str
    question_type: str
    requirement: Requirement
    capabilities: List[Capability] = field(default_factory=list)
    conversation_context: Dict[str, Any] = field(default_factory=dict)
    entities: List[Dict[str, Any]] = field(default_factory=list)
    country: str = ""
    history: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "question": self.question,
            "question_type": self.question_type,
            "requirement": self.requirement.to_dict(),
            "capabilities": [item.to_dict() for item in (self.capabilities or [])],
            "conversation_context": dict(self.conversation_context or {}),
            "entities": list(self.entities or []),
            "country": self.country,
            "history": list(self.history or []),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GovernorContext":
        payload = data or {}
        return cls(
            question=str(payload.get("question") or ""),
            question_type=str(payload.get("question_type") or "UNKNOWN"),
            requirement=Requirement.from_dict(payload.get("requirement") or {}),
            capabilities=[Capability.from_dict(item) for item in (payload.get("capabilities") or []) if isinstance(item, dict)],
            conversation_context=dict(payload.get("conversation_context") or {}),
            entities=list(payload.get("entities") or []),
            country=str(payload.get("country") or ""),
            history=list(payload.get("history") or []),
        )


class ArchitectureGovernor:
    def __init__(
        self,
        brain: Any | None = None,
        pipeline_definitions: List[PipelineDefinition] | None = None,
        container: ServiceContainer | None = None,
    ):
        self.brain = brain
        self.container = container
        self.pipeline_definitions = list(pipeline_definitions or self._load_default_pipelines())
        self.runtime_metrics = get_runtime_metrics()

    def analyse_request(
        self,
        question_context: QuestionContext,
        requirement: Requirement,
        capability_plan: CapabilityPlan,
        history: List[Dict[str, Any]] | None = None,
    ) -> GovernorContext:
        capabilities = list(capability_plan.required_capabilities or []) + list(capability_plan.optional_capabilities or [])
        question_type = (
            question_context.question_type.value
            if hasattr(question_context.question_type, "value")
            else str(question_context.question_type or "UNKNOWN")
        )
        return GovernorContext(
            question=str(question_context.question or ""),
            question_type=str(question_type or "UNKNOWN"),
            requirement=requirement,
            capabilities=self._dedupe_capabilities(capabilities),
            conversation_context={
                "conversation_id": str(question_context.conversation_id or ""),
                "language": str(question_context.language or ""),
                "comparison": bool(question_context.comparison),
                "ranking": bool(question_context.ranking),
                "relationship": bool(question_context.relationship),
            },
            entities=list(question_context.entities or []),
            country=str(question_context.country or ""),
            history=list(history or []),
        )

    def match_pipeline(self, governor_context: GovernorContext) -> List[PipelineDefinition]:
        matched: List[PipelineDefinition] = []
        question_type = str(governor_context.question_type or "UNKNOWN").upper().strip()
        capability_names = {self._normalize_capability_name(item.name) for item in (governor_context.capabilities or [])}
        has_entity = any(isinstance(item, dict) and (item.get("name") or "").strip() for item in (governor_context.entities or []))
        has_country = bool((governor_context.country or "").strip())

        for pipeline in self.pipeline_definitions:
            if not pipeline.enabled:
                continue
            supported_qt = {str(item).upper().strip() for item in (pipeline.supported_question_types or [])}
            supported_caps = {self._normalize_capability_name(item) for item in (pipeline.supported_capabilities or [])}
            question_match = (not supported_qt) or (question_type in supported_qt) or ("UNKNOWN" in supported_qt)
            capability_match = (not supported_caps) or bool(capability_names & supported_caps)
            entity_guard = True
            country_guard = True
            if pipeline.name == "OrganizationPipeline":
                entity_guard = has_entity
            elif pipeline.name in {"GraphPipeline", "InvestmentPipeline", "RelationshipPipeline"}:
                entity_guard = has_entity
            elif pipeline.name == "TimelinePipeline":
                entity_guard = has_entity or has_country
            elif pipeline.name == "ResearchPipeline":
                country_guard = has_country or has_entity or question_type in {"NEWS", "TIMELINE", "RANKING", "UNKNOWN"}
            if question_match and capability_match and entity_guard and country_guard:
                matched.append(pipeline)

        if not matched:
            matched = [item for item in self.pipeline_definitions if item.enabled]
        return matched

    def rank_pipelines(
        self,
        pipelines: List[PipelineDefinition],
        governor_context: GovernorContext,
    ) -> List[PipelineDefinition]:
        def score(item: PipelineDefinition) -> tuple[int, int, int, int, int, int, str]:
            capability_match = self._pipeline_capability_match(item, governor_context)
            requirement_match = self._pipeline_requirement_match(item, governor_context.requirement)
            question_type_match = self._pipeline_question_match(item, governor_context.question_type)
            cost_score = self._cost_score(item.cost)
            latency_score = self._latency_score(item.latency)
            priority_score = int(item.priority or 0)
            return (
                capability_match,
                requirement_match,
                question_type_match,
                cost_score,
                latency_score,
                priority_score,
                item.name,
            )

        return sorted(list(pipelines or []), key=score, reverse=True)

    def build_selection(self, governor_context: GovernorContext) -> PipelineSelection:
        candidates = self.rank_pipelines(self.match_pipeline(governor_context), governor_context)
        selected = candidates[0] if candidates else self._fallback_pipeline_definition()
        fallback = candidates[1] if len(candidates) > 1 else self._fallback_pipeline_definition()
        confidence = self._selection_confidence(selected, candidates[1] if len(candidates) > 1 else None, governor_context)
        reason = self._build_selection_reason(selected, governor_context)
        return PipelineSelection(
            selected_pipeline=selected,
            candidate_pipelines=candidates,
            selection_reason=reason,
            confidence=confidence,
            fallback_pipeline=fallback,
        )

    def should_switch_pipeline(self, *_args, **_kwargs) -> bool:
        return False

    def execute(self, user_message: str, conversation_id: str, history: List[Dict[str, Any]]) -> Dict[str, Any]:
        with trace_span("Governor", input_obj={"message": user_message, "conversation_id": conversation_id}) as span:
            orchestrator = self._get_pipeline_service()
            if orchestrator is None:
                result = {"answer": "", "evidence": [], "error": "pipeline_service_unavailable"}
                span.set_output_obj(result)
                return result
            trace_center = self._get_trace_center() if self._trace_center_enabled() else None
            trace_session = trace_center.start_session(user_message, pipeline="") if trace_center else None
            question_context, requirement, capability_plan = orchestrator.prepare_governor_context(
                user_message,
                conversation_id,
                history,
                trace_center=trace_center,
                trace_session=trace_session,
            )
            self._trace_governor_request(trace_center, question_context, requirement, capability_plan)
            governor_context = self.analyse_request(question_context, requirement, capability_plan, history=history)
            selection = self._build_selection_with_trace(governor_context, trace_center=trace_center)
            result = orchestrator.execute(
                user_message,
                conversation_id,
                history,
                _skip_governor=True,
                _selection=selection,
                _trace_center=trace_center,
                _trace_session=trace_session,
                _prepared_context=(question_context, requirement, capability_plan),
            )
            span.set_output_obj(result)
            return result

    def execute_stream(self, user_message: str, conversation_id: str, history: List[Dict[str, Any]]):
        generator_id = f"governor-execute-stream-{uuid.uuid4()}"
        started_at = time.perf_counter()
        _governor_lifecycle_trace(
            "STREAM ENTER",
            conversation_id=conversation_id,
            generator_id=generator_id,
            started_at=started_at,
        )
        try:
            with trace_span("Governor", input_obj={"message": user_message, "conversation_id": conversation_id}) as span:
                selected_pipeline = None
                workflow_definition = None
                workflow_outputs = None
                delivery = None
                full_content_length = 0
                need_llm = None
                should_call_llm = None
                _governor_stream_trace(
                    "ENTER Governor",
                    conversation_id=conversation_id,
                    selected_pipeline=selected_pipeline,
                    workflow_definition=workflow_definition,
                    workflow_outputs=workflow_outputs,
                    delivery=delivery,
                    full_content_length=full_content_length,
                    need_llm=need_llm,
                    should_call_llm=should_call_llm,
                )
                orchestrator = self._get_pipeline_service()
                if orchestrator is None:
                    span.set_output_obj({"error": "pipeline_service_unavailable"})
                    _governor_stream_trace(
                        "RETURN=A",
                        Reason="pipeline_service_unavailable",
                        selected_pipeline=selected_pipeline,
                        workflow_definition=workflow_definition,
                        workflow_outputs=workflow_outputs,
                        delivery=delivery,
                        full_content_length=full_content_length,
                        need_llm=need_llm,
                        should_call_llm=should_call_llm,
                        conversation_id=conversation_id,
                    )
                    return
                trace_center = self._get_trace_center() if self._trace_center_enabled() else None
                trace_session = trace_center.start_session(user_message, pipeline="") if trace_center else None
                question_context, requirement, capability_plan = orchestrator.prepare_governor_context(
                    user_message,
                    conversation_id,
                    history,
                    trace_center=trace_center,
                    trace_session=trace_session,
                )
                self._trace_governor_request(trace_center, question_context, requirement, capability_plan)
                governor_context = self.analyse_request(question_context, requirement, capability_plan, history=history)
                selection = self._build_selection_with_trace(governor_context, trace_center=trace_center)
                selected_pipeline = getattr(getattr(selection, "selected_pipeline", None), "name", None)
                try:
                    from services.default_workflow_registry import get_workflow_for_pipeline

                    workflow_definition_obj = get_workflow_for_pipeline(selected_pipeline or "")
                    workflow_definition = getattr(workflow_definition_obj, "name", None)
                except Exception:
                    workflow_definition = None
                _governor_stream_trace(
                    "CALL Pipeline.execute_stream()",
                    conversation_id=conversation_id,
                    selected_pipeline=selected_pipeline,
                    workflow_definition=workflow_definition,
                )
                token_count = 0
                for chunk in orchestrator.execute_stream(
                    user_message,
                    conversation_id,
                    history,
                    _skip_governor=True,
                    _selection=selection,
                    _trace_center=trace_center,
                    _trace_session=trace_session,
                    _prepared_context=(question_context, requirement, capability_plan),
                ):
                    if isinstance(chunk, dict) and chunk.get("type") == "token":
                        token_count += 1
                        last_token = str(chunk.get("content") or "")
                        if token_count == 1:
                            _governor_lifecycle_trace(
                                "STREAM FIRST TOKEN",
                                conversation_id=conversation_id,
                                generator_id=generator_id,
                                started_at=started_at,
                                token_length=len(last_token),
                            )
                    if isinstance(chunk, dict) and chunk.get("type") == "done":
                        workflow_outputs = {
                            "type": type(chunk).__name__,
                            "keys": list(chunk.keys()),
                            "path": chunk.get("path"),
                            "delivery": chunk.get("delivery"),
                            "full_content": chunk.get("full_content"),
                            "stream": chunk.get("stream"),
                            "need_llm": chunk.get("need_llm"),
                            "finished": chunk.get("finished"),
                            "should_call_llm": chunk.get("should_call_llm"),
                        }
                        delivery = chunk.get("delivery")
                        full_content_length = len(str(chunk.get("full_content") or ""))
                        need_llm = chunk.get("need_llm")
                        should_call_llm = chunk.get("should_call_llm")
                        if token_count > 0:
                            _governor_lifecycle_trace(
                                "STREAM LAST TOKEN",
                                conversation_id=conversation_id,
                                generator_id=generator_id,
                                started_at=started_at,
                                token_count=token_count,
                                last_token_length=len(last_token),
                            )
                    yield chunk
                span.set_output_obj({"done": True})
                _governor_stream_trace(
                    "RETURN=B",
                    Reason="pipeline_execute_stream_completed",
                    selected_pipeline=selected_pipeline,
                    workflow_definition=workflow_definition,
                    workflow_outputs=workflow_outputs,
                    delivery=delivery,
                    full_content_length=full_content_length,
                    need_llm=need_llm,
                    should_call_llm=should_call_llm,
                    conversation_id=conversation_id,
                )
                _governor_lifecycle_trace(
                    "STREAM FINISH",
                    conversation_id=conversation_id,
                    generator_id=generator_id,
                    started_at=started_at,
                    selected_pipeline=selected_pipeline,
                )
        except GeneratorExit:
            _governor_lifecycle_trace(
                "STREAM CLOSE",
                conversation_id=conversation_id,
                generator_id=generator_id,
                started_at=started_at,
                reason="GeneratorExit",
            )
            raise
        except asyncio.CancelledError:
            _governor_lifecycle_trace(
                "STREAM CANCEL",
                conversation_id=conversation_id,
                generator_id=generator_id,
                started_at=started_at,
                reason="asyncio.CancelledError",
            )
            raise
        except Exception as exc:
            _governor_lifecycle_trace(
                "STREAM EXCEPTION",
                conversation_id=conversation_id,
                generator_id=generator_id,
                started_at=started_at,
                error_type=type(exc).__name__,
                error=str(exc),
                full_exception=traceback.format_exc(),
            )
            raise
        finally:
            _governor_lifecycle_trace(
                "STREAM CLOSE",
                conversation_id=conversation_id,
                generator_id=generator_id,
                started_at=started_at,
                reason="finally",
            )

    def _pipeline_capability_match(self, pipeline: PipelineDefinition, governor_context: GovernorContext) -> int:
        supported = {self._normalize_capability_name(item) for item in (pipeline.supported_capabilities or [])}
        current = {self._normalize_capability_name(item.name) for item in (governor_context.capabilities or [])}
        if not supported:
            return 0
        return len(current & supported)

    def _pipeline_requirement_match(self, pipeline: PipelineDefinition, requirement: Requirement) -> int:
        supported = {self._normalize_capability_name(item) for item in (pipeline.supported_capabilities or [])}
        fields = {str(item or "").strip().lower() for item in (requirement.required_fields or [])}
        score = 0
        if {"name", "website", "leader", "leader_name", "member_count", "denomination"} & fields and "PROFILE" in supported:
            score += 3
        if {"title", "snippet", "url", "published_at", "updated_at", "source", "source_name"} & fields and {"NEWS", "TIMELINE", "DATABASE"} & supported:
            score += 3
        if {"graph"} & fields and "GRAPH" in supported:
            score += 3
        if {"relationship"} & fields and "RELATIONSHIP" in supported:
            score += 3
        if {"ranking"} & fields and "RANKING" in supported:
            score += 2
        if {"country"} & fields and "COUNTRY_BASELINE" in supported:
            score += 2
        return score

    def _pipeline_question_match(self, pipeline: PipelineDefinition, question_type: str) -> int:
        supported = {str(item).upper().strip() for item in (pipeline.supported_question_types or [])}
        current = str(question_type or "UNKNOWN").upper().strip()
        return 1 if (not supported or current in supported or "UNKNOWN" in supported) else 0

    def _selection_confidence(
        self,
        selected: PipelineDefinition,
        second: PipelineDefinition | None,
        governor_context: GovernorContext,
    ) -> float:
        top = (
            self._pipeline_capability_match(selected, governor_context) * 3
            + self._pipeline_requirement_match(selected, governor_context.requirement) * 2
            + self._pipeline_question_match(selected, governor_context.question_type)
            + int(selected.priority or 0) / 100
        )
        second_score = 0.0
        if second is not None:
            second_score = (
                self._pipeline_capability_match(second, governor_context) * 3
                + self._pipeline_requirement_match(second, governor_context.requirement) * 2
                + self._pipeline_question_match(second, governor_context.question_type)
                + int(second.priority or 0) / 100
            )
        if top <= 0:
            return 0.5
        gap = max(top - second_score, 0.0)
        confidence = min(0.99, 0.55 + (gap / max(top, 1.0)) * 0.4)
        return round(confidence, 2)

    def _build_selection_reason(self, selected: PipelineDefinition, governor_context: GovernorContext) -> str:
        capability_names = [self._normalize_capability_name(item.name) for item in (governor_context.capabilities or [])]
        matched_capabilities = [
            item for item in capability_names if item in {self._normalize_capability_name(cap) for cap in (selected.supported_capabilities or [])}
        ]
        if matched_capabilities:
            return (
                f"Selected {selected.name} because question type {governor_context.question_type} "
                f"matches pipeline specialization and capabilities {', '.join(matched_capabilities[:4])}."
            )
        return f"Selected {selected.name} as the best available enabled pipeline fallback for {governor_context.question_type}."

    def _fallback_pipeline_definition(self) -> PipelineDefinition:
        for pipeline in self.pipeline_definitions:
            if pipeline.name == "StandardPipeline" and pipeline.enabled:
                return pipeline
        enabled = [item for item in self.pipeline_definitions if item.enabled]
        if enabled:
            return enabled[0]
        return PipelineDefinition(name="StandardPipeline", description="Fallback pipeline", priority=1)

    def _load_default_pipelines(self) -> List[PipelineDefinition]:
        try:
            from services.default_pipeline_registry import get_default_pipeline_registry

            return list(get_default_pipeline_registry() or [])
        except Exception:
            return []

    def _normalize_capability_name(self, name: str) -> str:
        aliases = {
            "organization profile": "PROFILE",
            "profile": "PROFILE",
            "contacts": "CONTACTS",
            "contact": "CONTACTS",
            "relationship": "RELATIONSHIP",
            "graph": "GRAPH",
            "timeline": "TIMELINE",
            "news": "NEWS",
            "country baseline": "COUNTRY_BASELINE",
            "country": "COUNTRY_BASELINE",
            "investment": "INVESTMENT",
            "ranking": "RANKING",
            "database": "DATABASE",
        }
        lowered = str(name or "").strip().lower()
        return aliases.get(lowered, str(name or "").strip().upper())

    def _cost_score(self, cost: str) -> int:
        mapping = {"low": 3, "medium": 2, "high": 1}
        return mapping.get(str(cost or "medium").strip().lower(), 2)

    def _latency_score(self, latency: str) -> int:
        mapping = {"low": 3, "medium": 2, "high": 1}
        return mapping.get(str(latency or "medium").strip().lower(), 2)

    def _dedupe_capabilities(self, capabilities: List[Capability]) -> List[Capability]:
        merged: Dict[str, Capability] = {}
        for capability in capabilities or []:
            key = self._normalize_capability_name(capability.name)
            existing = merged.get(key)
            if existing is None or int(capability.priority or 0) > int(existing.priority or 0):
                merged[key] = Capability(
                    name=key,
                    description=capability.description,
                    priority=int(capability.priority or 0),
                    required=bool(capability.required),
                    parameters=dict(capability.parameters or {}),
                )
        return list(merged.values())

    def _trace_center_enabled(self) -> bool:
        return feature_flag_enabled("TRACE_CENTER_ENABLED")

    def _service_container_enabled(self) -> bool:
        return feature_flag_enabled("SERVICE_CONTAINER_ENABLED")

    def _get_pipeline_service(self) -> Any:
        if self._service_container_enabled() and self.container is not None and self.container.has("pipeline_service"):
            try:
                return self.container.get("pipeline_service")
            except Exception:
                pass
        try:
            from services.pipeline_orchestrator import PipelineOrchestrator

            return PipelineOrchestrator(self.brain, container=self.container)
        except Exception:
            return None

    def _get_trace_center(self) -> Any:
        if self._service_container_enabled() and self.container is not None and self.container.has("trace_center"):
            try:
                trace_center = self.container.get("trace_center")
                self.container.trace_center = trace_center
                return trace_center
            except Exception:
                pass
        try:
            from services.trace_center import TraceCenter

            return TraceCenter(enabled=self._trace_center_enabled())
        except Exception:
            return None

    def _trace_governor_request(
        self,
        trace_center: Any,
        question_context: QuestionContext,
        requirement: Requirement,
        capability_plan: CapabilityPlan,
    ) -> None:
        if trace_center is None:
            return
        trace_center.start_stage("GOVERNOR")
        trace_center.record_event(
            "GOVERNOR",
            "Governor Analysed Request",
            metadata={
                "question_type": question_context.question_type.value if hasattr(question_context.question_type, "value") else str(question_context.question_type or "UNKNOWN"),
                "country": str(question_context.country or ""),
                "entity_count": len(question_context.entities or []),
                "required_fields": list(requirement.required_fields or []),
                "capabilities": [item.name for item in list(capability_plan.required_capabilities or []) + list(capability_plan.optional_capabilities or [])],
            },
        )

    def _build_selection_with_trace(self, governor_context: GovernorContext, trace_center: Any = None) -> PipelineSelection:
        matched = self.match_pipeline(governor_context)
        if trace_center is not None:
            trace_center.record_event(
                "GOVERNOR",
                "Pipeline Matching",
                metadata={
                    "matched_pipelines": [item.name for item in matched],
                    "question_type": governor_context.question_type,
                    "capabilities": [item.name for item in (governor_context.capabilities or [])],
                },
            )
        ranked = self.rank_pipelines(matched, governor_context)
        if trace_center is not None:
            trace_center.record_event(
                "GOVERNOR",
                "Pipeline Ranking",
                metadata={"ranked_pipelines": [item.name for item in ranked]},
            )
        original_selection = self.build_selection(governor_context)
        selection = self._get_execution_policy_engine(trace_center=trace_center).evaluate_pipeline(
            ExecutionPolicyContext(
                question=governor_context.question,
                question_type=governor_context.question_type,
                requirement=governor_context.requirement,
                capabilities=list(governor_context.capabilities or []),
                pipeline=original_selection,
                trace={
                    "operation": "select",
                    "selection_confidence": float(original_selection.confidence or 0.0),
                    "has_entities": any(
                        isinstance(item, dict) and (item.get("name") or "").strip()
                        for item in (governor_context.entities or [])
                    ),
                    "history_count": len(governor_context.history or []),
                },
            ),
            default_decision=original_selection,
        ).decision
        self.runtime_metrics.inc(
            "governor_pipeline_selected",
            labels={"pipeline": str(selection.selected_pipeline.name or "")},
        )
        self.runtime_metrics.observe(
            "governor.confidence",
            float(selection.confidence or 0.0),
            labels={"pipeline": str(selection.selected_pipeline.name or "")},
        )
        if str(selection.selected_pipeline.name or "") != str(original_selection.selected_pipeline.name or ""):
            self.runtime_metrics.inc(
                "governor_fallback",
                labels={
                    "from_pipeline": str(original_selection.selected_pipeline.name or ""),
                    "to_pipeline": str(selection.selected_pipeline.name or ""),
                },
            )
        if trace_center is not None:
            trace_center.record_event(
                "GOVERNOR",
                "Pipeline Selected",
                metadata={
                    "selected_pipeline": selection.selected_pipeline.name,
                    "fallback_pipeline": selection.fallback_pipeline.name if selection.fallback_pipeline else "",
                    "confidence": selection.confidence,
                    "selection_reason": selection.selection_reason,
                },
            )
            trace_center.end_stage("GOVERNOR", metadata={"selected_pipeline": selection.selected_pipeline.name})
        return selection

    def _get_execution_policy_engine(self, *, trace_center: Any = None) -> ExecutionPolicyEngine:
        return ExecutionPolicyEngine(trace_center=trace_center or self._get_trace_center())
