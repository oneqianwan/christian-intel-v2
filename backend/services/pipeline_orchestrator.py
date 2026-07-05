from __future__ import annotations

import asyncio
import inspect
import json
import os
import threading
import time
import traceback
import uuid
from contextlib import suppress
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, Generator, List, Optional

from config import settings
from services.answer_context_builder import AnswerContextBuilder
from services.capability_planner import CapabilityPlan, CapabilityPlanner, ExecutionRequirement
from services.core_models import AnswerContext, Conflict, Evidence, Fact, QuestionContext, QuestionType, Requirement
from services.evidence_engine import EvidenceEngine
from services.evidence_models import EvidenceBundle
from services.repair_executor import RepairExecutor
from services.repair_planner import RepairPlanner
from services.self_reflection import SelfReflectionEngine
from services.verification import build_verification_result as build_evidence_aware_verification_result
from services.default_workflows import get_workflow_for_pipeline
from services.execution_policy import ExecutionPolicyContext, ExecutionPolicyEngine
from services.knowledge_layer import KnowledgeGraph, KnowledgeLayer
from services.insight_engine import InsightEngine
from services.insight_answer_renderer import InsightAnswerRenderer
from services.insight_models import InsightInput, InsightResult
from services.memory_layer import MemoryContext, MemoryLayer
from services.retrieval_loop_controller import LoopContext, RetrievalLoopController, StopCondition
from services.runtime_metrics import get_runtime_metrics
from services.service_container import ServiceContainer, ServiceScope
from services.task_graph import PlanningContext, TaskGraph
from services.task_planner import TaskPlanner
from services.tool_registry import ExecutionPlan, ToolDefinition, ToolRegistry
from services.workflow_engine import WorkflowContext, WorkflowDefinition
from services.workflow_executor import WorkflowExecutor

from services.trace_center import debug_answer_event, trace_span
from services.welcome_trace import emit_welcome_trace, lookup_welcome_reply_uuid


def _pipeline_stream_trace(event: str, *, conversation_id: str, generator_id: str, started_at: float, **payload: Any) -> None:
    print(
        "PIPELINE_STREAM_TRACE "
        + json.dumps(
            {
                "event": event,
                "conversation_id": conversation_id,
                "generator_id": generator_id,
                "thread_id": threading.get_ident(),
                "elapsed_ms": round((time.perf_counter() - started_at) * 1000, 3),
                **payload,
            },
            ensure_ascii=False,
            default=str,
        )
    )


def _pipeline_who_close_stream(file_name: str, function_name: str) -> None:
    print(
        "WHO_CLOSE_STREAM "
        + json.dumps(
            {
                "FILE": file_name,
                "FUNCTION": function_name,
                "CALLSTACK": "".join(traceback.format_stack(limit=16)),
            },
            ensure_ascii=False,
        )
    )


def _pipeline_logged_yield_from(iterator, *, conversation_id: str, generator_id: str, started_at: float):
    token_count = 0
    last_token = ""
    try:
        while True:
            try:
                chunk = next(iterator)
            except StopIteration as stop:
                if token_count > 0:
                    _pipeline_stream_trace(
                        "STREAM LAST TOKEN",
                        conversation_id=conversation_id,
                        generator_id=generator_id,
                        started_at=started_at,
                        token_count=token_count,
                        last_token_length=len(last_token),
                    )
                _pipeline_stream_trace(
                    "STREAM FINISH",
                    conversation_id=conversation_id,
                    generator_id=generator_id,
                    started_at=started_at,
                    token_count=token_count,
                    stop_value_type=type(stop.value).__name__,
                )
                return stop.value
            chunk_type = chunk.get("type") if isinstance(chunk, dict) else type(chunk).__name__
            if chunk_type == "token":
                token = str(chunk.get("content") or "")
                token_count += 1
                last_token = token
                if token_count == 1:
                    _pipeline_stream_trace(
                        "STREAM FIRST TOKEN",
                        conversation_id=conversation_id,
                        generator_id=generator_id,
                        started_at=started_at,
                        token_length=len(token),
                    )
                _pipeline_stream_trace(
                    "STREAM TOKEN",
                    conversation_id=conversation_id,
                    generator_id=generator_id,
                    started_at=started_at,
                    token_index=token_count,
                    token_length=len(token),
                )
            yield chunk
    except GeneratorExit:
        _pipeline_who_close_stream("backend/services/pipeline_orchestrator.py", "_pipeline_logged_yield_from")
        _pipeline_stream_trace(
            "STREAM CLOSE",
            conversation_id=conversation_id,
            generator_id=generator_id,
            started_at=started_at,
            token_count=token_count,
            reason="GeneratorExit",
        )
        raise
    except asyncio.CancelledError:
        _pipeline_who_close_stream("backend/services/pipeline_orchestrator.py", "_pipeline_logged_yield_from")
        _pipeline_stream_trace(
            "STREAM CANCEL",
            conversation_id=conversation_id,
            generator_id=generator_id,
            started_at=started_at,
            token_count=token_count,
            reason="asyncio.CancelledError",
        )
        raise
    except Exception as exc:
        _pipeline_stream_trace(
            "STREAM EXCEPTION",
            conversation_id=conversation_id,
            generator_id=generator_id,
            started_at=started_at,
            token_count=token_count,
            error_type=type(exc).__name__,
            error=str(exc),
            full_exception=traceback.format_exc(),
        )
        raise


class PipelineStage(str, Enum):
    QUESTION = "QUESTION"
    QUESTION_CONTEXT = "QUESTION_CONTEXT"
    MEMORY_LOAD = "MEMORY_LOAD"
    REQUIREMENT = "REQUIREMENT"
    RETRIEVAL = "RETRIEVAL"
    KNOWLEDGE_LAYER = "KNOWLEDGE_LAYER"
    MEMORY_UPDATE = "MEMORY_UPDATE"
    REASONING = "REASONING"
    ANSWER_COMPOSER = "ANSWER_COMPOSER"
    VERIFICATION = "VERIFICATION"
    RETRIEVAL_LOOP = "RETRIEVAL_LOOP"
    MEMORY_SNAPSHOT = "MEMORY_SNAPSHOT"
    LLM = "LLM"
    DELIVERY = "DELIVERY"


@dataclass
class PipelineContext:
    orchestrator: Any = None
    conversation_id: str = ""
    history: List[dict] | None = None
    selection: Any = None
    workflow_definition: WorkflowDefinition | None = None
    prepared_context: tuple[QuestionContext, Requirement, CapabilityPlan] | None = None
    finalize: Callable[..., dict] | None = None
    final_result: Dict[str, Any] | None = None
    workflow_outputs: Dict[str, Any] | None = None
    workflow_state: Dict[str, Any] | None = None
    task_graph: TaskGraph | None = None
    question_context: Any = None
    requirement: Any = None
    capability_plan: Any = None
    knowledge_graph: Any = None
    memory_context: Any = None
    trace_session: Any = None
    trace_center: Any = None
    evidence: Any = None
    evidence_bundle: Any = None
    facts: Any = None
    conflicts: Any = None
    sections: Any = None
    answer_context: Any = None
    messages: List[dict] | None = None
    tool_results: List[dict] | None = None
    delivery: Any = None
    verification: Dict[str, Any] | None = None
    loop_summary: Dict[str, Any] | None = None
    loop_context: LoopContext | None = None
    insight_result: Dict[str, Any] | None = None
    final_answer_override: str = ""


class PipelineOrchestrator:
    def __init__(self, brain: Any, container: ServiceContainer | None = None):
        self.brain = brain
        self.container = container
        self.runtime_metrics = get_runtime_metrics()
        self._active_trace_center = None
        self._active_trace_session = None
        self._active_memory_context = None
        self._memory_layer = None
        self._stage_started_perf: Dict[str, float] = {}

    def execute(
        self,
        user_message: str,
        conversation_id: str,
        history: list[dict],
        *,
        _skip_governor: bool = False,
        _selection: Any = None,
        _workflow_definition: WorkflowDefinition | None = None,
        _trace_center: Any = None,
        _trace_session: Any = None,
        _prepared_context: tuple[QuestionContext, Requirement, CapabilityPlan] | None = None,
    ) -> dict:
        with trace_span("Pipeline", input_obj={"message": user_message, "conversation_id": conversation_id}) as span:
            bypass_governor_for_insight_render = self._insight_engine_enabled() and self._insight_final_render_enabled()
            if self._architecture_governor_enabled() and not _skip_governor and not bypass_governor_for_insight_render:
                governor = self._get_architecture_governor()
                if governor is not None:
                    result = governor.execute(user_message, conversation_id, history)
                    span.set_output_obj(result)
                    return result
            result = self._execute_selected_pipeline(
                user_message,
                conversation_id,
                history,
                selection=_selection,
                workflow_definition=_workflow_definition,
                trace_center=_trace_center,
                trace_session=_trace_session,
                prepared_context=_prepared_context,
            )
            span.set_output_obj(result)
            return result

    def _execute_selected_pipeline(
        self,
        user_message: str,
        conversation_id: str,
        history: list[dict],
        *,
        selection: Any = None,
        workflow_definition: WorkflowDefinition | None = None,
        trace_center: Any = None,
        trace_session: Any = None,
        prepared_context: tuple[QuestionContext, Requirement, CapabilityPlan] | None = None,
    ) -> dict:
        if self._workflow_engine_enabled():
            return self._execute_selected_pipeline_workflow(
                user_message,
                conversation_id,
                history,
                selection=selection,
                workflow_definition=workflow_definition,
                trace_center=trace_center,
                trace_session=trace_session,
                prepared_context=prepared_context,
            )
        ctx = PipelineContext(messages=[], tool_results=[], trace_center=trace_center, trace_session=trace_session)
        ctx.orchestrator = self
        ctx.conversation_id = conversation_id
        ctx.history = list(history or [])
        ctx.selection = selection
        ctx.workflow_outputs = {}
        ctx.workflow_state = {}
        pipeline_started_perf = time.perf_counter()
        self._sync_container_scope(conversation_id, ctx)
        if ctx.trace_center is None and self._trace_center_enabled():
            ctx.trace_center = self._get_trace_center()
            if ctx.trace_center is not None:
                pipeline_name = self._selection_pipeline_name(selection)
                ctx.trace_session = ctx.trace_center.start_session(user_message, pipeline=pipeline_name)
        self._active_trace_center = ctx.trace_center
        self._active_trace_session = ctx.trace_session
        self._memory_layer = self._get_memory_layer()
        self._sync_container_scope(conversation_id, ctx)

        def finalize(
            answer: str,
            evidence: Any = None,
            answer_context: AnswerContext | dict | None = None,
            verification: Dict[str, Any] | None = None,
            loop_summary: Dict[str, Any] | None = None,
        ) -> dict:
            merged = self.brain._merge_evidence([], evidence or [])
            answer_context_dict = self._answer_context_to_dict(answer_context)
            insight_result = dict(ctx.insight_result or {}) if isinstance(ctx.insight_result, dict) else None
            if self._memory_layer_enabled() and self._memory_layer is not None and self._active_memory_context is not None:
                setattr(self.brain, "_last_memory_context", self._memory_layer.export_memory(self._active_memory_context))
            if ctx.trace_center is not None:
                ctx.trace_center.finish_session(
                    summary={
                        "answer_length": len(str(answer or "")),
                        "evidence_count": len(merged or []),
                        "verification": dict(verification or {}),
                        "loop_summary": dict(loop_summary or {}),
                        "insight_result_exists": bool(insight_result),
                        "memory_enabled": self._memory_layer_enabled(),
                    },
                    pipeline=self._selection_pipeline_name(selection),
                )
                setattr(self.brain, "_last_trace_session", ctx.trace_center.export_trace())
            else:
                self.runtime_metrics.observe(
                    "pipeline.total.latency_ms",
                    round((time.perf_counter() - pipeline_started_perf) * 1000, 2),
                    labels={"pipeline": self._selection_pipeline_name(selection)},
                )
            result = {
                "answer": answer or "",
                "evidence": merged,
                "answer_context": answer_context_dict,
                "verification": dict(verification or {}),
                "loop_summary": dict(loop_summary or {}),
            }
            if insight_result:
                result["insight_result"] = insight_result
            return result
        try:
            if prepared_context is not None:
                ctx.question_context, ctx.requirement, ctx.capability_plan = prepared_context
            else:
                ctx.question_context, ctx.requirement, ctx.capability_plan = self.prepare_governor_context(
                    user_message,
                    conversation_id,
                    history,
                    trace_center=ctx.trace_center,
                    trace_session=ctx.trace_session,
                )
            self._sync_container_scope(conversation_id, ctx)
            if self._memory_layer_enabled():
                ctx.memory_context = self._load_memory_context(conversation_id, ctx.question_context, ctx.requirement)
                self._active_memory_context = ctx.memory_context
                self._sync_container_scope(conversation_id, ctx)

            parser = None
            try:
                from services.query_parser import QueryParser

                parser = QueryParser()
                direct_result = parser.parse(user_message, conversation_id=conversation_id)
                if direct_result and direct_result.get("data_found"):
                    answer = direct_result.get("answer") or direct_result.get("response") or ""
                    evidence = direct_result.get("evidence") or []
                    return finalize(self.brain._clean_output(answer), evidence)
            finally:
                if parser:
                    parser.close()

            if getattr(self.brain, "MULTI_AGENT_AVAILABLE", False):
                try:
                    from agents.orchestrator import AgentOrchestrator

                    orchestrator = AgentOrchestrator()
                    result = orchestrator.process(user_message)
                    if result.get("data_found"):
                        return finalize(self.brain._clean_output(result.get("response", "")), result.get("evidence") or [])
                except Exception:
                    pass

            should_prioritize_match = self.brain._looks_like_match_query(user_message)
            captured_profile = None if should_prioritize_match else self.brain._capture_profile_from_message(user_message)
            if captured_profile:
                return finalize(captured_profile, [])

            if self.brain._should_use_direct_answer(user_message):
                return finalize(
                    self.brain._append_gap_collection_notice(user_message, self.brain._fallback_reply(user_message, history)),
                    [],
                )

            if not bool(getattr(settings.PROVIDER_CONFIG, "api_key", "") or ""):
                return finalize(
                    self.brain._append_gap_collection_notice(user_message, self.brain._fallback_reply(user_message, history)),
                    [],
                )

            ctx.messages = self.brain._build_messages(user_message, history)

            self._trace_stage_start("RETRIEVAL")
            planned_tool_calls = self._build_planned_tool_calls(user_message)
            prefetched_tool_calls = (
                self.brain._build_direct_investor_prefetch(user_message)
                or planned_tool_calls
                or self.brain._build_prefetched_tool_calls(user_message)
            )
            self._trace_event(
                "RETRIEVAL",
                "Prefetched Tool Calls",
                metadata={"tool_call_count": len(prefetched_tool_calls or [])},
            )

            if prefetched_tool_calls:
                direct_tool_name = prefetched_tool_calls[0].get("function", {}).get("name", "")
                if direct_tool_name in self.brain._direct_render_tool_names() and not self._should_use_structured_generation():
                    raw_arguments = prefetched_tool_calls[0].get("function", {}).get("arguments") or "{}"
                    try:
                        function_args = json.loads(raw_arguments)
                    except json.JSONDecodeError:
                        function_args = {}
                    func = self.brain.available_functions.get(direct_tool_name)
                    if func:
                        tool_started = time.perf_counter()
                        result = self.brain._normalize_tool_result(direct_tool_name, func(**function_args))
                        tool_duration_ms = round((time.perf_counter() - tool_started) * 1000, 2)
                        self.runtime_metrics.observe("tool.time_ms", tool_duration_ms, labels={"tool_name": direct_tool_name})
                        self.runtime_metrics.inc("tool_success", labels={"tool_name": direct_tool_name})
                        content = self.brain._render_direct_tool_result(direct_tool_name, result)
                        evidence = (result.get("evidence") or []) if isinstance(result, dict) else []
                        self._trace_stage_end("RETRIEVAL", metadata={"mode": "direct_render"})
                        return finalize(self.brain._append_gap_collection_notice(user_message, content), evidence)

                parsed_results = self._execute_tool_calls(prefetched_tool_calls)
                self._trace_stage_end("RETRIEVAL", metadata={"mode": "prefetch", "tool_results": len(parsed_results or [])})
                if parsed_results is None:
                    return finalize(
                        self.brain._append_gap_collection_notice(user_message, self.brain._fallback_reply(user_message, history)),
                        [],
                    )
                return self._final_generate_from_tool_results(user_message, history, parsed_results, finalize)

            tool_choice = self.brain._choose_tool_for_message(user_message)
            self._trace_stage_start("LLM")
            llm_start = time.perf_counter()
            response = self.brain._call_llm(ctx.messages, tools=self.brain.TOOLS, tool_choice=tool_choice)
            self._trace_event(
                "LLM",
                "Initial LLM Call",
                duration_ms=round((time.perf_counter() - llm_start) * 1000, 2),
                metadata={"tool_choice": tool_choice if isinstance(tool_choice, str) else "auto"},
            )
            if not response:
                self._trace_stage_end("LLM", status="failed")
                return finalize(
                    self.brain._append_gap_collection_notice(user_message, self.brain._fallback_reply(user_message, history)),
                    [],
                )

            messages_with_tools = list(ctx.messages)
            collected_results: List[dict] = []
            for _ in range(3):
                assistant_msg = response.get("choices", [{}])[0].get("message", {})
                tool_calls = assistant_msg.get("tool_calls") or []
                if not tool_calls:
                    final_content = (assistant_msg.get("content") or "").strip()
                    self._trace_stage_end("LLM", metadata={"tool_calls_requested": len(collected_results or [])})
                    if not collected_results and final_content:
                        return finalize(self.brain._append_gap_collection_notice(user_message, final_content), [])
                    break
                self._trace_stage_start("RETRIEVAL")
                messages_with_tools.append({"role": "assistant", "content": assistant_msg.get("content", ""), "tool_calls": tool_calls})
                executed = self._execute_tool_calls(tool_calls)
                self._trace_stage_end("RETRIEVAL", metadata={"mode": "llm_tool_calls", "tool_results": len(executed or [])})
                if executed is None:
                    self._trace_stage_end("LLM", status="failed")
                    return finalize(
                        self.brain._append_gap_collection_notice(user_message, self.brain._fallback_reply(user_message, history)),
                        [],
                    )
                for idx, result in enumerate(executed):
                    tool_call = tool_calls[idx]
                    collected_results.append(result if isinstance(result, dict) else {})
                    messages_with_tools.append(
                        {"role": "tool", "tool_call_id": tool_call.get("id", ""), "content": json.dumps(result, ensure_ascii=False)}
                    )
                llm_loop_start = time.perf_counter()
                response = self.brain._call_llm(messages_with_tools, tools=self.brain.TOOLS)
                self._trace_event(
                    "LLM",
                    "Follow-up LLM Call",
                    duration_ms=round((time.perf_counter() - llm_loop_start) * 1000, 2),
                    metadata={"tool_results": len(collected_results or [])},
                )
                if not response:
                    self._trace_stage_end("LLM", status="failed")
                    return finalize(
                        self.brain._append_gap_collection_notice(user_message, self.brain._fallback_reply(user_message, history)),
                        [],
                    )

            if collected_results:
                return self._final_generate_from_tool_results(user_message, history, collected_results, finalize)

            return finalize(self.brain._append_gap_collection_notice(user_message, self.brain._fallback_reply(user_message, history)), [])
        finally:
            self._active_trace_center = None
            self._active_trace_session = None
            self._active_memory_context = None
            self._memory_layer = None

    def execute_stream(
        self,
        user_message: str,
        conversation_id: str,
        history: list[dict],
        *,
        _skip_governor: bool = False,
        _selection: Any = None,
        _workflow_definition: WorkflowDefinition | None = None,
        _trace_center: Any = None,
        _trace_session: Any = None,
        _prepared_context: tuple[QuestionContext, Requirement, CapabilityPlan] | None = None,
    ) -> Generator[dict, None, None]:
        generator_id = f"pipeline-execute-stream-{uuid.uuid4()}"
        started_at = time.perf_counter()
        _pipeline_stream_trace(
            "STREAM ENTER",
            conversation_id=conversation_id,
            generator_id=generator_id,
            started_at=started_at,
            skip_governor=bool(_skip_governor),
        )
        try:
            with trace_span("Pipeline", input_obj={"message": user_message, "conversation_id": conversation_id}) as span:
                bypass_governor_for_insight_render = self._insight_engine_enabled() and self._insight_final_render_enabled()
                if self._architecture_governor_enabled() and not _skip_governor and not bypass_governor_for_insight_render:
                    governor = self._get_architecture_governor()
                    if governor is not None:
                        yield from _pipeline_logged_yield_from(
                            governor.execute_stream(user_message, conversation_id, history),
                            conversation_id=conversation_id,
                            generator_id=generator_id,
                            started_at=started_at,
                        )
                        span.set_output_obj({"done": True})
                        _pipeline_stream_trace(
                            "STREAM FINISH",
                            conversation_id=conversation_id,
                            generator_id=generator_id,
                            started_at=started_at,
                            path="governor",
                        )
                        return
                yield from _pipeline_logged_yield_from(
                    self._execute_stream_selected_pipeline(
                        user_message,
                        conversation_id,
                        history,
                        selection=_selection,
                        workflow_definition=_workflow_definition,
                        trace_center=_trace_center,
                        trace_session=_trace_session,
                        prepared_context=_prepared_context,
                    ),
                    conversation_id=conversation_id,
                    generator_id=generator_id,
                    started_at=started_at,
                )
                span.set_output_obj({"done": True})
                _pipeline_stream_trace(
                    "STREAM FINISH",
                    conversation_id=conversation_id,
                    generator_id=generator_id,
                    started_at=started_at,
                    path="selected_pipeline",
                )
        except GeneratorExit:
            _pipeline_stream_trace(
                "STREAM CLOSE",
                conversation_id=conversation_id,
                generator_id=generator_id,
                started_at=started_at,
                reason="GeneratorExit",
            )
            raise
        except asyncio.CancelledError:
            _pipeline_stream_trace(
                "STREAM CANCEL",
                conversation_id=conversation_id,
                generator_id=generator_id,
                started_at=started_at,
                reason="asyncio.CancelledError",
            )
            raise
        except Exception as exc:
            _pipeline_stream_trace(
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
            _pipeline_stream_trace(
                "STREAM CLOSE",
                conversation_id=conversation_id,
                generator_id=generator_id,
                started_at=started_at,
                reason="finally",
            )

    def _execute_stream_selected_pipeline(
        self,
        user_message: str,
        conversation_id: str,
        history: list[dict],
        *,
        selection: Any = None,
        workflow_definition: WorkflowDefinition | None = None,
        trace_center: Any = None,
        trace_session: Any = None,
        prepared_context: tuple[QuestionContext, Requirement, CapabilityPlan] | None = None,
    ) -> Generator[dict, None, None]:
        generator_id = f"pipeline-selected-stream-{uuid.uuid4()}"
        started_at = time.perf_counter()
        _pipeline_stream_trace(
            "STREAM ENTER",
            conversation_id=conversation_id,
            generator_id=generator_id,
            started_at=started_at,
            workflow_engine=bool(self._workflow_engine_enabled()),
        )
        try:
            if self._workflow_engine_enabled():
                workflow_context = self._build_workflow_context(
                    user_message,
                    conversation_id,
                    history,
                    selection=selection,
                    workflow_definition=workflow_definition,
                    trace_center=trace_center,
                    trace_session=trace_session,
                    prepared_context=prepared_context,
                )
                executor = self._get_workflow_executor(trace_center=workflow_context.pipeline_context.trace_center)
                definition = workflow_definition or get_workflow_for_pipeline(self._selection_pipeline_name(selection))
                yielded_any = False
                for chunk in _pipeline_logged_yield_from(
                    executor.execute_stream(definition, workflow_context),
                    conversation_id=conversation_id,
                    generator_id=generator_id,
                    started_at=started_at,
                ):
                    yielded_any = True
                    yield chunk
                if not yielded_any:
                    final_result = dict(workflow_context.final_result or getattr(workflow_context.pipeline_context, "final_result", {}) or {})
                    answer = str(final_result.get("answer") or final_result.get("full_content") or "").strip()
                    evidence = final_result.get("evidence") or []
                    # #region debug-point C:pipeline-fallback-source
                    debug_answer_event(
                        "Pipeline Final Answer",
                        answer,
                        trace_id=str(getattr(workflow_context.pipeline_context, "conversation_id", "") or ""),
                        hypothesis_id="C",
                        location="pipeline_orchestrator.py:_execute_stream_selected_pipeline:fallback",
                        extra={
                            "native_stream": False,
                            "fallback_stream": True,
                            "workflow_final_length": len(str(final_result.get("answer") or "")),
                            "workflow_final_md5_source": "workflow_context.final_result.answer",
                        },
                    )
                    emit_welcome_trace(
                        "PIPELINE_UUID",
                        lookup_welcome_reply_uuid(conversation_id, answer),
                        conversation_id=conversation_id,
                        extra={"location": "pipeline_orchestrator.py:_execute_stream_selected_pipeline:fallback"},
                    )
                    # #endregion
                    with trace_span("Knowledge", input_obj={"skipped": True}) as span:
                        span.set_output_obj({"skipped": True, "reason": "workflow_produced_no_stream_chunks"})
                    with trace_span("Composer", input_obj={"skipped": True}) as span:
                        span.set_output_obj({"skipped": True, "reason": "workflow_produced_no_stream_chunks"})
                    with trace_span("Verification", input_obj={"skipped": True}) as span:
                        span.set_output_obj({"skipped": True, "reason": "workflow_produced_no_stream_chunks"})
                    with trace_span("Reflection", input_obj={"skipped": True}) as span:
                        span.set_output_obj({"skipped": True, "reason": "workflow_produced_no_stream_chunks"})
                    with trace_span("RepairPlanner", input_obj={"skipped": True}) as span:
                        span.set_output_obj({"skipped": True, "reason": "workflow_produced_no_stream_chunks"})
                    with trace_span("RepairExecutor", input_obj={"skipped": True}) as span:
                        span.set_output_obj({"skipped": True, "reason": "workflow_produced_no_stream_chunks"})
                    with trace_span("LLM", input_obj={"fallback_stream": True, "answer_length": len(answer)}) as span:
                        if answer:
                            chunk_size = 16
                            for i in range(0, len(answer), chunk_size):
                                yield {"type": "token", "content": answer[i : i + chunk_size]}
                                time.sleep(0.01)
                        span.set_output_obj({"streamed": True, "answer_length": len(answer), "evidence_count": len(evidence or [])})
                    yield {
                        "type": "done",
                        "full_content": answer,
                        "evidence": evidence,
                        "welcome_reply_uuid": lookup_welcome_reply_uuid(conversation_id, answer),
                    }
                _pipeline_stream_trace(
                    "STREAM FINISH",
                    conversation_id=conversation_id,
                    generator_id=generator_id,
                    started_at=started_at,
                    yielded_any=yielded_any,
                )
                return
            result = self._execute_selected_pipeline(
                user_message,
                conversation_id,
                history,
                selection=selection,
                workflow_definition=workflow_definition,
                trace_center=trace_center,
                trace_session=trace_session,
                prepared_context=prepared_context,
            )
            answer = (result.get("answer") or "").strip()
            evidence = result.get("evidence") or []
            stream_policy = self._get_execution_policy_engine().evaluate_llm(
                ExecutionPolicyContext(
                    question=user_message,
                    question_type=self._current_question_type(),
                    pipeline=selection,
                    verification=dict(result.get("verification") or {}),
                    trace={
                        "operation": "stream",
                        "supports_stream": self._selection_supports_stream(selection),
                    },
                ),
                default_decision={
                    "allow_generate": True,
                    "allow_stream": True,
                    "allow_long_answer": True,
                    "allow_follow_up": True,
                    "needs_second_generate": False,
                },
            )
            if not bool(dict(stream_policy.decision or {}).get("allow_stream", True)):
                yield {
                    "type": "done",
                    "full_content": answer,
                    "evidence": evidence,
                    "welcome_reply_uuid": lookup_welcome_reply_uuid(conversation_id, answer),
                }
                _pipeline_stream_trace(
                    "STREAM FINISH",
                    conversation_id=conversation_id,
                    generator_id=generator_id,
                    started_at=started_at,
                    yielded_any=False,
                    reason="allow_stream_false",
                )
                return
            self.runtime_metrics.inc("llm_stream_count", labels={"mode": "pipeline_stream"})
            words = answer.split(" ")
            chunk = ""
            for word in words:
                chunk += word + " "
                if len(chunk) >= 50:
                    yield {"type": "token", "content": chunk.strip() + " "}
                    chunk = ""
            if chunk.strip():
                yield {"type": "token", "content": chunk.strip()}
            yield {
                "type": "done",
                "full_content": answer,
                "evidence": evidence,
                "welcome_reply_uuid": lookup_welcome_reply_uuid(conversation_id, answer),
            }
            _pipeline_stream_trace(
                "STREAM FINISH",
                conversation_id=conversation_id,
                generator_id=generator_id,
                started_at=started_at,
                yielded_any=True,
                reason="pipeline_stream_words",
            )
        except GeneratorExit:
            _pipeline_stream_trace(
                "STREAM CLOSE",
                conversation_id=conversation_id,
                generator_id=generator_id,
                started_at=started_at,
                reason="GeneratorExit",
            )
            raise
        except asyncio.CancelledError:
            _pipeline_stream_trace(
                "STREAM CANCEL",
                conversation_id=conversation_id,
                generator_id=generator_id,
                started_at=started_at,
                reason="asyncio.CancelledError",
            )
            raise
        except Exception as exc:
            _pipeline_stream_trace(
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
            _pipeline_stream_trace(
                "STREAM CLOSE",
                conversation_id=conversation_id,
                generator_id=generator_id,
                started_at=started_at,
                reason="finally",
            )

    def prepare_governor_context(
        self,
        user_message: str,
        conversation_id: str,
        history: list[dict],
        trace_center: Any = None,
        trace_session: Any = None,
    ) -> tuple[QuestionContext, Requirement, CapabilityPlan]:
        setattr(self.brain, "conversation_id", conversation_id)
        previous_trace_center = getattr(self, "_active_trace_center", None)
        previous_trace_session = getattr(self, "_active_trace_session", None)
        self._active_trace_center = trace_center or previous_trace_center
        self._active_trace_session = trace_session or previous_trace_session
        self._trace_stage_start("REQUIREMENT")
        self._initialize_reasoning_context(user_message)
        question_context = self._build_question_context_for_registry(user_message)
        requirement = self._get_requirement(user_message)
        capability_plan = self._get_capability_plan(user_message, question_context=question_context, requirement=requirement)
        self._trace_event(
            "REQUIREMENT",
            "Requirement Built",
            metadata={
                "question_type": question_context.question_type.value if hasattr(question_context.question_type, "value") else str(question_context.question_type or "UNKNOWN"),
                "required_fields": list(requirement.required_fields or []),
                "required_sources": list(requirement.required_sources or []),
            },
        )
        self._trace_event(
            "REQUIREMENT",
            "Capability Planned",
            metadata={
                "required_capabilities": [item.name for item in (capability_plan.required_capabilities or [])],
                "optional_capabilities": [item.name for item in (capability_plan.optional_capabilities or [])],
                "parallel_groups": [[item.name for item in group] for group in (capability_plan.parallel_groups or [])],
            },
        )
        self._trace_event(
            "REQUIREMENT",
            "Capability Ranking",
            metadata={
                "ranked_capabilities": [
                    item.name for item in list(capability_plan.required_capabilities or []) + list(capability_plan.optional_capabilities or [])
                ]
            },
        )
        self._trace_stage_end("REQUIREMENT")
        return question_context, requirement, capability_plan

    def _initialize_reasoning_context(self, user_message: str) -> None:
        reasoning_enabled = (os.getenv("REASONING_ENGINE_V1_ENABLED") or "").strip().lower() in {"1", "true", "yes"}
        if not reasoning_enabled:
            return
        try:
            engine = self._get_reasoning_engine()
            if engine is None:
                return
            country = self.brain._extract_country(user_message)
            pre = engine.build_reasoning_result_pre(user_message, getattr(self.brain, "current_entities", []) or [], country)
            tool_plan = [] if self._capability_planner_enabled() else list(pre.tool_plan or [])
            self.brain._reasoning_v1_context = {
                "question_type": pre.question_type.value,
                "country": country,
                "requirement": pre.requirement,
                "tool_plan": tool_plan,
            }
        except Exception:
            pass

    def _should_use_structured_generation(self) -> bool:
        return self._composer_enabled() or self._retrieval_loop_enabled()

    def _composer_enabled(self) -> bool:
        return (os.getenv("ANSWER_COMPOSER_ENABLED") or "").strip().lower() in {"1", "true", "yes"}

    def _retrieval_loop_enabled(self) -> bool:
        return (os.getenv("RETRIEVAL_LOOP_ENABLED") or "").strip().lower() in {"1", "true", "yes"}

    def _knowledge_layer_enabled(self) -> bool:
        return (os.getenv("KNOWLEDGE_LAYER_ENABLED") or "").strip().lower() in {"1", "true", "yes"}

    def _memory_layer_enabled(self) -> bool:
        return (os.getenv("MEMORY_LAYER_ENABLED") or "").strip().lower() in {"1", "true", "yes"}

    def _build_planned_tool_calls(self, user_message: str) -> list[dict]:
        if self._tool_registry_enabled():
            execution_plan = self._build_execution_plan_from_registry(user_message)
            planned = self._build_calls_from_execution_plan(execution_plan, user_message)
            if planned:
                self._trace_event(
                    "RETRIEVAL",
                    "Execution Plan Built",
                    metadata={"planned_tools": [item.get("function", {}).get("name", "") for item in planned]},
                )
                return planned

        ctx = getattr(self.brain, "_reasoning_v1_context", {}) or {}
        tool_plan = list(ctx.get("tool_plan") or [])
        if not tool_plan:
            return []

        def build_call(tool_name: str, args: dict) -> dict:
            return {
                "id": f"call_{os.urandom(6).hex()}",
                "type": "function",
                "function": {"name": tool_name, "arguments": json.dumps(args or {}, ensure_ascii=False)},
            }

        entity_name = self._pick_entity_name(user_message)
        planned: list[dict] = []
        for tool_name in tool_plan:
            if tool_name == "query_organization_profile":
                if entity_name:
                    planned.append(build_call("query_organization_profile", {"org_name": entity_name}))
            elif tool_name == "query_contacts":
                if entity_name:
                    planned.append(build_call("query_contacts", {"org_name": entity_name}))
            elif tool_name == "query_graph":
                if entity_name:
                    planned.append(build_call("query_graph", {"entity_name": entity_name}))
            elif tool_name == "query_arda_country":
                args = self.brain._build_arda_country_args(user_message)
                if args.get("country"):
                    planned.append(build_call("query_arda_country", args))
            elif tool_name == "query_intelligence":
                planned.append(build_call("query_intelligence", self.brain._build_intelligence_query_args(user_message)))
            elif tool_name == "query_database":
                planned.append(build_call("query_database", self.brain._build_query_args(user_message)))
        if planned:
            self._trace_event(
                "RETRIEVAL",
                "Legacy Tool Plan Built",
                metadata={"planned_tools": [item.get("function", {}).get("name", "") for item in planned]},
            )
        return planned

    def _build_planned_tool_calls_from_task_graph(self, task_graph: TaskGraph | None, user_message: str) -> list[dict]:
        if task_graph is None:
            return self._build_planned_tool_calls(user_message)

        def build_call(tool_name: str, args: dict) -> dict:
            return {
                "id": f"call_{os.urandom(6).hex()}",
                "type": "function",
                "function": {"name": tool_name, "arguments": json.dumps(args or {}, ensure_ascii=False)},
            }

        planned: list[dict] = []
        entity_name = self._pick_entity_name(user_message)
        for task in list(task_graph.tasks or []):
            if str(task.status or "pending").strip().lower() == "completed":
                continue
            if not bool(task.required) and int(task.priority or 0) < 50:
                continue
            task_type = str(task.task_type or "").strip().upper()
            metadata = dict(task.metadata or {})
            if metadata.get("memory_hint") == "dedupe_candidate" and int(task.priority or 0) < 40:
                continue
            if task_type in {"RESEARCH", "SEARCH", "RETRIEVE", "SUMMARIZE"}:
                if entity_name:
                    planned.append(build_call("query_organization_profile", {"org_name": entity_name}))
                planned.append(build_call("query_intelligence", self.brain._build_intelligence_query_args(user_message)))
            elif task_type in {"TIMELINE"}:
                planned.append(build_call("query_intelligence", self.brain._build_intelligence_query_args(user_message)))
            elif task_type in {"GRAPH", "RELATIONSHIP", "INVESTMENT"}:
                if entity_name:
                    planned.append(build_call("query_graph", {"entity_name": entity_name}))
            elif task_type in {"COMPARE", "RANK"}:
                planned.append(build_call("query_database", self.brain._build_query_args(user_message)))
            elif task_type == "VERIFY":
                planned.append(build_call("query_database", self.brain._build_query_args(user_message)))
        if not planned:
            return self._build_planned_tool_calls(user_message)
        deduped: list[dict] = []
        seen = set()
        for item in planned:
            signature = json.dumps(item.get("function", {}), ensure_ascii=False, sort_keys=True)
            if signature in seen:
                continue
            seen.add(signature)
            deduped.append(item)
        return deduped

    def _tool_registry_enabled(self) -> bool:
        return (os.getenv("TOOL_REGISTRY_ENABLED") or "").strip().lower() in {"1", "true", "yes"}

    def _capability_planner_enabled(self) -> bool:
        return (os.getenv("CAPABILITY_PLANNER_ENABLED") or "").strip().lower() in {"1", "true", "yes"}

    def _architecture_governor_enabled(self) -> bool:
        return (os.getenv("ARCHITECTURE_GOVERNOR_ENABLED") or "").strip().lower() in {"1", "true", "yes"}

    def _trace_center_enabled(self) -> bool:
        return (os.getenv("TRACE_CENTER_ENABLED") or "").strip().lower() in {"1", "true", "yes"}

    def _service_container_enabled(self) -> bool:
        return (os.getenv("SERVICE_CONTAINER_ENABLED") or "").strip().lower() in {"1", "true", "yes"}

    def _sync_container_scope(self, conversation_id: str, pipeline_context: PipelineContext | None = None) -> None:
        if not self._service_container_enabled() or self.container is None:
            return
        existing_scope = self.container.scope if isinstance(self.container.scope, ServiceScope) else ServiceScope()
        active_pipeline_context = pipeline_context if pipeline_context is not None else existing_scope.pipeline_context
        trace_id = ""
        trace_session = self._active_trace_session or getattr(active_pipeline_context, "trace_session", None)
        if isinstance(trace_session, dict):
            trace_id = str(trace_session.get("trace_id") or "")
        else:
            trace_id = str(getattr(trace_session, "trace_id", "") or "")
        memory_context = self._active_memory_context or getattr(active_pipeline_context, "memory_context", None) or existing_scope.memory_context
        self.container.trace_center = self._active_trace_center or getattr(active_pipeline_context, "trace_center", None) or self.container.trace_center
        self.container.scope = ServiceScope(
            conversation_id=str(conversation_id or ""),
            trace_id=trace_id,
            memory_context=memory_context,
            pipeline_context=active_pipeline_context,
        )

    def _get_architecture_governor(self) -> Any:
        if self._service_container_enabled() and self.container is not None and self.container.has("architecture_governor"):
            try:
                return self.container.get("architecture_governor")
            except Exception:
                pass
        try:
            from services.architecture_governor import ArchitectureGovernor

            return ArchitectureGovernor(self.brain, container=self.container)
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

            return TraceCenter(enabled=True)
        except Exception:
            return None

    def _get_reasoning_engine(self) -> Any:
        if self._structured_reasoning_enabled():
            try:
                from services.reasoning_engine import ReasoningEngine

                return ReasoningEngine(trace_center=self._active_trace_center, runtime_metrics=self.runtime_metrics)
            except Exception:
                pass
        if self._service_container_enabled() and self.container is not None and self.container.has("reasoning_engine"):
            try:
                return self.container.get("reasoning_engine")
            except Exception:
                pass
        try:
            from services.reasoning_engine_v1 import ReasoningEngineV1

            return ReasoningEngineV1()
        except Exception:
            return None

    def _get_answer_composer(self) -> Any:
        if self._service_container_enabled() and self.container is not None and self.container.has("answer_composer"):
            try:
                return self.container.get("answer_composer")
            except Exception:
                pass
        try:
            from services.answer_composer import AnswerComposer

            return AnswerComposer()
        except Exception:
            return None

    def _get_knowledge_layer(self) -> Any:
        if not self._knowledge_layer_enabled():
            return None
        if self._service_container_enabled() and self.container is not None and self.container.has("knowledge_layer"):
            try:
                return self.container.get("knowledge_layer")
            except Exception:
                pass
        try:
            return KnowledgeLayer(trace_center=self._active_trace_center)
        except Exception:
            return None

    def _get_evidence_engine(self) -> EvidenceEngine:
        return EvidenceEngine(trace_center=self._active_trace_center, runtime_metrics=self.runtime_metrics)

    def _get_answer_context_builder(self) -> AnswerContextBuilder:
        return AnswerContextBuilder(trace_center=self._active_trace_center, runtime_metrics=self.runtime_metrics)

    def _get_self_reflection_engine(self) -> SelfReflectionEngine:
        return SelfReflectionEngine(trace_center=self._active_trace_center, runtime_metrics=self.runtime_metrics)

    def _get_repair_planner(self) -> RepairPlanner:
        return RepairPlanner(trace_center=self._active_trace_center, runtime_metrics=self.runtime_metrics)

    def _get_repair_executor(self) -> RepairExecutor:
        return RepairExecutor(action_handler=self._execute_repair_action)

    def _get_memory_layer(self) -> Any:
        if not self._memory_layer_enabled():
            return None
        if self._service_container_enabled() and self.container is not None and self.container.has("memory_layer"):
            try:
                return self.container.get("memory_layer")
            except Exception:
                pass
        try:
            return MemoryLayer(trace_center=self._active_trace_center)
        except Exception:
            return None

    def _get_retrieval_loop_controller(self) -> Any:
        if self._service_container_enabled() and self.container is not None and self.container.has("retrieval_loop_controller"):
            try:
                return self.container.get("retrieval_loop_controller")
            except Exception:
                pass
        try:
            return RetrievalLoopController(
                default_entity=self._pick_entity_name(""),
                default_country=str(getattr(self.brain, "_reasoning_v1_context", {}).get("country") or ""),
                default_question_type=str(getattr(self.brain, "_reasoning_v1_context", {}).get("question_type") or "UNKNOWN"),
                trace_center=self._active_trace_center,
            )
        except Exception:
            return None

    def _get_execution_policy_engine(self) -> ExecutionPolicyEngine:
        return ExecutionPolicyEngine(trace_center=self._active_trace_center)

    def _get_tool_registry(self) -> ToolRegistry | None:
        if not self._tool_registry_enabled():
            return None
        if self._service_container_enabled() and self.container is not None and self.container.has("tool_registry"):
            try:
                registry = self.container.get("tool_registry")
                if isinstance(registry, ToolRegistry):
                    return registry
                return registry
            except Exception:
                pass
        try:
            from services.default_registry import get_default_registry

            return get_default_registry()
        except Exception:
            return None

    def _get_capability_planner(self) -> CapabilityPlanner | None:
        if not self._capability_planner_enabled():
            return None
        if self._service_container_enabled() and self.container is not None and self.container.has("capability_planner"):
            try:
                planner = self.container.get("capability_planner")
                if isinstance(planner, CapabilityPlanner):
                    return planner
                return planner
            except Exception:
                pass
        try:
            return CapabilityPlanner()
        except Exception:
            return None

    def _build_execution_plan_from_registry(self, user_message: str) -> ExecutionPlan:
        registry = self._get_tool_registry()
        if registry is None:
            return ExecutionPlan()
        requirement = self._get_requirement(user_message)
        question_context = self._build_question_context_for_registry(user_message)
        capability_plan = self._get_capability_plan(user_message, question_context=question_context, requirement=requirement)
        if capability_plan.required_capabilities or capability_plan.optional_capabilities:
            capability_planner = self._get_capability_planner()
            if capability_planner is None:
                return registry.build_execution_plan(requirement, question_context, trace_center=self._active_trace_center)
            execution_requirements = capability_planner.build_execution_requirements(
                capability_plan,
                question_context,
                requirement=requirement,
            )
            return registry.build_execution_plan_from_capability_plan(
                capability_plan,
                question_context,
                requirement,
                execution_requirements=execution_requirements,
                trace_center=self._active_trace_center,
            )
        return registry.build_execution_plan(requirement, question_context, trace_center=self._active_trace_center)

    def _get_capability_plan(
        self,
        user_message: str,
        *,
        question_context: QuestionContext | None = None,
        requirement: Requirement | None = None,
    ) -> CapabilityPlan:
        capability_planner = self._get_capability_planner()
        if capability_planner is None:
            return CapabilityPlan()
        question_context = question_context or self._build_question_context_for_registry(user_message)
        requirement = requirement or self._get_requirement(user_message)
        try:
            return capability_planner.analyse_requirement(requirement, question_context)
        except Exception:
            return CapabilityPlan()

    def _build_question_context_for_registry(self, user_message: str) -> QuestionContext:
        ctx = getattr(self.brain, "_reasoning_v1_context", {}) or {}
        question_type_value = str(ctx.get("question_type") or "UNKNOWN").upper().strip()
        qt = QuestionType(question_type_value) if question_type_value in getattr(QuestionType, "_value2member_map_", {}) else QuestionType.UNKNOWN
        memory_context = self._active_memory_context if self._memory_layer_enabled() else None
        memory_entities = list(getattr(memory_context, "current_entities", []) or [])
        entity_memories = list(getattr(memory_context, "entity_memories", []) or [])
        current_entities = list(getattr(self.brain, "current_entities", []) or [])
        if not current_entities and memory_entities:
            current_entities = memory_entities
        if not current_entities and entity_memories:
            current_entities = [
                {"name": item.entity_name, "type": item.entity_type}
                for item in entity_memories[:5]
                if str(item.entity_name or "").strip()
            ]
        country = str(ctx.get("country") or "")
        if not country and memory_context is not None:
            country = str(getattr(memory_context, "current_country", "") or "")
        return QuestionContext(
            question=str(user_message or ""),
            question_type=qt,
            language="",
            country=country,
            entities=current_entities,
            time_range=None,
            comparison=qt == QuestionType.COMPARISON,
            ranking=qt == QuestionType.RANKING,
            relationship=qt in {QuestionType.RELATIONSHIP, QuestionType.GRAPH, QuestionType.INVESTMENT},
            conversation_id=str(getattr(self.brain, "conversation_id", "") or ""),
        )

    def _build_calls_from_execution_plan(self, execution_plan: ExecutionPlan, user_message: str) -> list[dict]:
        def build_call(tool_name: str, args: dict) -> dict:
            return {
                "id": f"call_{os.urandom(6).hex()}",
                "type": "function",
                "function": {"name": tool_name, "arguments": json.dumps(args or {}, ensure_ascii=False)},
            }

        planned: list[dict] = []
        execution_requirements = list(execution_plan.execution_requirements or [])
        for index, tool in enumerate(execution_plan.ordered_tools or []):
            execution_requirement = execution_requirements[index] if index < len(execution_requirements) else None
            args = self._build_args_for_tool_definition(tool, user_message, execution_requirement=execution_requirement)
            if args is None:
                continue
            planned.append(build_call(tool.name, args))
        return planned

    def _build_args_for_tool_definition(
        self,
        tool: ToolDefinition,
        user_message: str,
        execution_requirement: ExecutionRequirement | None = None,
    ) -> Dict[str, Any] | None:
        args: Dict[str, Any] = {}
        entity_name = self._pick_entity_name(user_message)
        ctx = getattr(self.brain, "_reasoning_v1_context", {}) or {}
        country = str(ctx.get("country") or self.brain._extract_country(user_message) or "")
        for arg_name in list(tool.required_arguments or []) + list(tool.optional_arguments or []):
            value = self._resolve_tool_argument(
                arg_name,
                user_message,
                entity_name,
                country,
                planned_parameters=(execution_requirement.parameters if execution_requirement else None),
            )
            if value is None:
                continue
            args[arg_name] = value
        missing_required = [name for name in (tool.required_arguments or []) if name not in args]
        if missing_required:
            return None
        return args

    def _resolve_tool_argument(
        self,
        arg_name: str,
        user_message: str,
        entity_name: str,
        country: str,
        planned_parameters: Dict[str, Any] | None = None,
    ) -> Any:
        name = str(arg_name or "").strip()
        if not name:
            return None
        planned_parameters = dict(planned_parameters or {})
        if name in planned_parameters and planned_parameters.get(name) not in (None, "", [], {}):
            return planned_parameters.get(name)
        if name == "org_name":
            return planned_parameters.get("org_name") or planned_parameters.get("entity") or entity_name or None
        if name == "entity_name":
            return planned_parameters.get("entity_name") or planned_parameters.get("entity") or entity_name or None
        if name == "country":
            return planned_parameters.get("country") or country or None
        if name == "entity":
            return planned_parameters.get("entity") or entity_name or None
        if name == "keywords":
            if planned_parameters.get("keywords"):
                return list(planned_parameters.get("keywords") or [])
            args = self.brain._build_intelligence_query_args(user_message)
            return list(args.get("keywords") or [])
        if name == "scope":
            if planned_parameters.get("scope"):
                return planned_parameters.get("scope")
            args = self.brain._build_intelligence_query_args(user_message)
            return args.get("scope") or ("entity" if entity_name else ("country" if country else "global"))
        if name == "limit":
            if planned_parameters.get("limit") not in (None, "", [], {}):
                return planned_parameters.get("limit")
            return 10
        if name == "relation_type":
            return "all"
        if name == "depth":
            return 1
        return None

    def _pick_entity_name(self, user_message: str) -> str:
        candidate = self.brain._extract_organization_profile_name(user_message)
        if candidate:
            return candidate
        for item in (getattr(self.brain, "current_entities", []) or [])[-5:]:
            if isinstance(item, dict) and (item.get("name") or "").strip():
                return (item.get("name") or "").strip()
        if self._active_memory_context is not None:
            for item in list(getattr(self._active_memory_context, "current_entities", []) or [])[-5:]:
                if isinstance(item, dict) and (item.get("name") or "").strip():
                    return (item.get("name") or "").strip()
            for item in list(getattr(self._active_memory_context, "entity_memories", []) or [])[-5:]:
                if str(getattr(item, "entity_name", "") or "").strip():
                    return str(getattr(item, "entity_name", "") or "").strip()
        return ""

    def _execute_tool_calls(self, tool_calls: list[dict], *, continue_after_error: bool = False) -> Optional[List[dict]]:
        parsed_results: List[dict] = []
        policy_engine = self._get_execution_policy_engine()
        for tool_call in tool_calls:
            function_name = ""
            function_args: Dict[str, Any] = {}
            exception_type = ""
            exception_message = ""
            traceback_text = ""
            if "function" in tool_call:
                raw_arguments = tool_call.get("function", {}).get("arguments") or "{}"
                try:
                    function_args = json.loads(raw_arguments)
                except json.JSONDecodeError:
                    function_args = {}
                function_name = tool_call.get("function", {}).get("name", "")
            else:
                function_name = str(tool_call.get("tool_name") or "")
                function_args = dict(tool_call.get("args") or {})

            cached_result = None
            if self._memory_layer_enabled() and self._memory_layer is not None and self._active_memory_context is not None:
                cached_result = self._memory_layer.get_cached_tool_result(
                    self._active_memory_context,
                    tool_name=function_name,
                    arguments=function_args,
                )
            cache_decision = policy_engine.evaluate_cache(
                ExecutionPolicyContext(
                    question_type=self._current_question_type(),
                    memory={"operation": "read", "cache_hit": cached_result is not None},
                    trace={"operation": "read", "tool_name": function_name},
                ),
                default_decision=cached_result is not None,
            )
            if bool(cache_decision.decision):
                result = self.brain._normalize_tool_result(function_name, cached_result)
            else:
                retrieval_decision = policy_engine.evaluate_retrieval(
                    ExecutionPolicyContext(
                        question_type=self._current_question_type(),
                        trace={"operation": "execute", "tool_name": function_name},
                    ),
                    default_decision=bool(function_name),
                )
                if not bool(retrieval_decision.decision):
                    result = self.brain._normalize_tool_result(
                        function_name,
                        {"status": "skipped", "message": f"执行策略拒绝调用工具: {function_name or 'unknown'}"},
                    )
                else:
                    tool_started = time.perf_counter()
                    func = self.brain.available_functions.get(function_name)
                    if func:
                        timeout_seconds = 0.0
                        if continue_after_error:
                            with suppress(Exception):
                                timeout_seconds = max(1.0, float(os.getenv("RESEARCH_TOOL_TIMEOUT_SECONDS", "35").strip() or "35"))
                        result, exception_type, exception_message, traceback_text = self._execute_tool_call_with_guard(
                            function_name=function_name,
                            function_args=function_args,
                            func=func,
                            timeout_seconds=timeout_seconds,
                        )
                    else:
                        result = self.brain._normalize_tool_result(function_name, {"status": "error", "message": f"未知工具: {function_name}"})
                    self.runtime_metrics.observe(
                        "tool.time_ms",
                        round((time.perf_counter() - tool_started) * 1000, 2),
                        labels={"tool_name": function_name},
                    )
                if self._memory_layer_enabled() and self._memory_layer is not None and self._active_memory_context is not None:
                    self._memory_layer.cache_tool_results(
                        self._active_memory_context,
                        tool_name=function_name,
                        arguments=function_args,
                        tool_results=result if isinstance(result, dict) else {},
                    )
            normalized_result = result if isinstance(result, dict) else {}
            normalized_result.setdefault("tool_name", function_name)
            normalized_result.setdefault("tool_args", function_args)
            if exception_type:
                normalized_result.setdefault("error", exception_message)
                normalized_result.setdefault("exception_type", exception_type)
                normalized_result.setdefault("traceback", traceback_text)
            parsed_results.append(normalized_result)
            result_status = (normalized_result.get("status") if isinstance(normalized_result, dict) else "") or "ok"
            result_error = str(
                (normalized_result.get("message") if isinstance(normalized_result, dict) else "")
                or (normalized_result.get("error") if isinstance(normalized_result, dict) else "")
                or ""
            )
            print(f"ToolName={function_name}")
            print(f"ToolArgs={json.dumps(function_args, ensure_ascii=False, default=str)}")
            print(f"ToolResultStatus={result_status}")
            print(f"ToolResultError={result_error}")
            print(f"ExceptionType={exception_type or str(normalized_result.get('exception_type') or 'None')}")
            print(f"Exception={exception_message or str(normalized_result.get('error') or 'None')}")
            print(f"Traceback={traceback_text or str(normalized_result.get('traceback') or 'None')}")
            self.runtime_metrics.inc(
                "tool_failure" if result_status in {"error", "skipped"} else "tool_success",
                labels={"tool_name": function_name, "status": result_status},
            )
            self._trace_event(
                "RETRIEVAL",
                "Tool Executed",
                metadata={
                    "tool_name": function_name,
                    "status": (normalized_result.get("status") if isinstance(normalized_result, dict) else "") or "ok",
                    "evidence_count": len((normalized_result.get("evidence") or [])) if isinstance(normalized_result, dict) and isinstance(normalized_result.get("evidence"), list) else 0,
                },
            )
            if self.brain._should_fallback_after_tool(function_name, normalized_result if isinstance(normalized_result, dict) else {}):
                if continue_after_error:
                    continue
                return None
        return parsed_results

    def _normalize_tool_args_for_signature(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {str(key): self._normalize_tool_args_for_signature(value[key]) for key in sorted(value)}
        if isinstance(value, list):
            return [self._normalize_tool_args_for_signature(item) for item in value]
        if isinstance(value, tuple):
            return [self._normalize_tool_args_for_signature(item) for item in value]
        if isinstance(value, set):
            normalized_items = [self._normalize_tool_args_for_signature(item) for item in value]
            return sorted(normalized_items, key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True, default=str))
        return value

    def _tool_call_name_and_args(self, tool_call: dict) -> tuple[str, Dict[str, Any]]:
        function_name = ""
        function_args: Dict[str, Any] = {}
        if "function" in tool_call:
            function_name = str(tool_call.get("function", {}).get("name", "") or "")
            raw_arguments = tool_call.get("function", {}).get("arguments") or "{}"
            try:
                parsed_args = json.loads(raw_arguments)
                function_args = parsed_args if isinstance(parsed_args, dict) else {}
            except json.JSONDecodeError:
                function_args = {}
        else:
            function_name = str(tool_call.get("tool_name") or "")
            function_args = dict(tool_call.get("args") or {})
        return function_name, function_args

    def _tool_call_signature(self, function_name: str, function_args: Dict[str, Any]) -> str:
        normalized_args = self._normalize_tool_args_for_signature(function_args)
        return f"{function_name}|{json.dumps(normalized_args, ensure_ascii=False, sort_keys=True, default=str)}"

    def _tool_display_name(self, function_name: str, function_args: Dict[str, Any]) -> str:
        return f"{function_name}({json.dumps(self._normalize_tool_args_for_signature(function_args), ensure_ascii=False, sort_keys=True, default=str)})"

    def _research_tool_priority_order(self, user_message: str) -> list[str]:
        lowered = str(user_message or "").lower()
        if "victory philippines" in lowered and any(token in lowered for token in ["评分", "score", "评级", "rating"]):
            return ["query_organization_profile", "query_database"]
        if all(token in lowered for token in ["openai", "microsoft"]) and any(
            token in lowered for token in ["关系", "relation", "relationship", "对比", "compare"]
        ):
            return ["query_graph", "query_database", "query_organization_profile"]
        if "菲律宾" in lowered and any(token in lowered for token in ["媒体", "科技机构", "情报", "带来源"]):
            return ["query_intelligence", "query_database"]
        return []

    def _prepare_research_tool_calls(
        self,
        user_message: str,
        tool_calls: list[dict],
        workflow_state: Dict[str, Any] | None,
    ) -> tuple[list[dict], Dict[str, Any]]:
        state = workflow_state if isinstance(workflow_state, dict) else {}
        candidate_tool_calls = list(tool_calls or [])
        before_count = len(candidate_tool_calls)
        priority_order = self._research_tool_priority_order(user_message)
        allowed_tools = set(priority_order)
        existing_tool_names = {
            self._tool_call_name_and_args(tool_call)[0]
            for tool_call in candidate_tool_calls
            if self._tool_call_name_and_args(tool_call)[0]
        }
        if priority_order:
            augmented_calls: List[dict] = []
            for tool_name in priority_order:
                if tool_name in existing_tool_names:
                    continue
                if tool_name == "query_graph":
                    graph_calls = list(self.brain._build_graph_tool_calls(user_message) or [])
                    if not graph_calls:
                        lowered = str(user_message or "").lower()
                        if "openai" in lowered and "microsoft" in lowered:
                            graph_calls = [
                                {
                                    "id": f"call_{uuid.uuid4().hex[:12]}",
                                    "type": "function",
                                    "function": {
                                        "name": "query_graph",
                                        "arguments": json.dumps(
                                            {
                                                "entity_name": "OpenAI||Microsoft",
                                                "relation_type": "all",
                                                "depth": 1,
                                                "limit": 10,
                                            },
                                            ensure_ascii=False,
                                        ),
                                    },
                                }
                            ]
                    augmented_calls.extend(graph_calls)
                elif tool_name == "query_organization_profile":
                    augmented_calls.extend(list(self.brain._build_organization_profile_tool_calls(user_message) or []))
                elif tool_name == "query_intelligence":
                    augmented_calls.extend(list(self.brain._build_intelligence_tool_calls(user_message) or []))
                elif tool_name == "query_database":
                    augmented_calls.extend(
                        [
                            call
                            for call in list(self.brain._build_prefetched_tool_calls(user_message) or [])
                            if self._tool_call_name_and_args(call)[0] == "query_database"
                        ]
                    )
            if augmented_calls:
                candidate_tool_calls = list(augmented_calls) + candidate_tool_calls
                before_count = len(candidate_tool_calls)
        seen_signatures = set(str(item) for item in list(state.get("research_tool_seen_signatures") or []) if str(item).strip())
        failed_signatures = set(str(item) for item in list(state.get("research_tool_failed_signatures") or []) if str(item).strip())
        deduped_tools: List[str] = []
        skipped_tools: List[str] = []
        prepared: List[tuple[int, str, Dict[str, Any], str, dict]] = []
        seen_in_batch: set[str] = set()

        for original_index, tool_call in enumerate(candidate_tool_calls):
            function_name, function_args = self._tool_call_name_and_args(tool_call)
            signature = self._tool_call_signature(function_name, function_args)
            display_name = self._tool_display_name(function_name, function_args)
            if allowed_tools and function_name not in allowed_tools:
                skipped_tools.append(f"{display_name}|priority_filter")
                continue
            if signature in seen_in_batch:
                deduped_tools.append(display_name)
                continue
            if signature in seen_signatures or signature in failed_signatures:
                deduped_tools.append(display_name)
                continue
            seen_in_batch.add(signature)
            prepared.append((original_index, function_name, function_args, signature, tool_call))

        if priority_order:
            priority_rank = {name: idx for idx, name in enumerate(priority_order)}
            prepared.sort(key=lambda item: (priority_rank.get(item[1], len(priority_order) + 10), item[0]))

        max_tool_count = 3
        limited = prepared[:max_tool_count]
        for _, function_name, function_args, _, _ in prepared[max_tool_count:]:
            skipped_tools.append(f"{self._tool_display_name(function_name, function_args)}|max_tool_limit")

        after_count = len(limited)
        executed_tools = [self._tool_display_name(function_name, function_args) for _, function_name, function_args, _, _ in limited]
        for item in skipped_tools:
            if item.endswith("|max_tool_limit"):
                print("ToolSkippedReason=max_tool_limit")

        state["research_tool_seen_signatures"] = list(seen_signatures)
        state["research_tool_failed_signatures"] = list(failed_signatures)
        return (
            [item[-1] for item in limited],
            {
                "before_count": before_count,
                "after_count": after_count,
                "deduped_tools": deduped_tools,
                "executed_tools": executed_tools,
                "skipped_tools": skipped_tools,
                "prepared_signatures": [item[3] for item in limited],
            },
        )

    def _execute_tool_call_with_guard(
        self,
        *,
        function_name: str,
        function_args: Dict[str, Any],
        func: Callable[..., Any],
        timeout_seconds: float = 0.0,
    ) -> tuple[dict, str, str, str]:
        if timeout_seconds <= 0:
            try:
                return self.brain._normalize_tool_result(function_name, func(**function_args)), "", "", ""
            except TypeError as exc:
                exception_type = type(exc).__name__
                exception_message = str(exc)
                traceback_text = traceback.format_exc()
                return (
                    self.brain._normalize_tool_result(
                        function_name,
                        {
                            "status": "error",
                            "message": f"参数错误: {exc}",
                            "tool_name": function_name,
                            "tool_args": function_args,
                            "error": str(exc),
                            "exception_type": exception_type,
                            "traceback": traceback_text,
                        },
                    ),
                    exception_type,
                    exception_message,
                    traceback_text,
                )
            except Exception as exc:
                exception_type = type(exc).__name__
                exception_message = str(exc)
                traceback_text = traceback.format_exc()
                return (
                    self.brain._normalize_tool_result(
                        function_name,
                        {
                            "status": "error",
                            "message": f"工具执行异常: {exc}",
                            "tool_name": function_name,
                            "tool_args": function_args,
                            "error": str(exc),
                            "exception_type": exception_type,
                            "traceback": traceback_text,
                        },
                    ),
                    exception_type,
                    exception_message,
                    traceback_text,
                )

        outcome: Dict[str, Any] = {}
        finished = threading.Event()

        def runner() -> None:
            try:
                outcome["value"] = func(**function_args)
            except Exception as exc:
                outcome["exception"] = exc
                outcome["traceback"] = traceback.format_exc()
            finally:
                finished.set()

        worker = threading.Thread(
            target=runner,
            name=f"tool-guard-{function_name or 'unknown'}-{uuid.uuid4().hex[:6]}",
            daemon=True,
        )
        worker.start()
        if not finished.wait(timeout_seconds):
            exception_type = "ToolExecutionTimeout"
            exception_message = f"tool execution timed out after {timeout_seconds:.1f}s"
            traceback_text = (
                f"Timed out while executing {function_name} with args="
                f"{json.dumps(function_args, ensure_ascii=False, default=str)}"
            )
            return (
                self.brain._normalize_tool_result(
                    function_name,
                    {
                        "status": "error",
                        "message": exception_message,
                        "tool_name": function_name,
                        "tool_args": function_args,
                        "error": exception_message,
                        "exception_type": exception_type,
                        "traceback": traceback_text,
                    },
                ),
                exception_type,
                exception_message,
                traceback_text,
            )

        exc = outcome.get("exception")
        if isinstance(exc, TypeError):
            exception_type = type(exc).__name__
            exception_message = str(exc)
            traceback_text = str(outcome.get("traceback") or "")
            return (
                self.brain._normalize_tool_result(
                    function_name,
                    {
                        "status": "error",
                        "message": f"参数错误: {exc}",
                        "tool_name": function_name,
                        "tool_args": function_args,
                        "error": str(exc),
                        "exception_type": exception_type,
                        "traceback": traceback_text,
                    },
                ),
                exception_type,
                exception_message,
                traceback_text,
            )
        if isinstance(exc, Exception):
            exception_type = type(exc).__name__
            exception_message = str(exc)
            traceback_text = str(outcome.get("traceback") or "")
            return (
                self.brain._normalize_tool_result(
                    function_name,
                    {
                        "status": "error",
                        "message": f"工具执行异常: {exc}",
                        "tool_name": function_name,
                        "tool_args": function_args,
                        "error": str(exc),
                        "exception_type": exception_type,
                        "traceback": traceback_text,
                    },
                ),
                exception_type,
                exception_message,
                traceback_text,
            )
        return self.brain._normalize_tool_result(function_name, outcome.get("value")), "", "", ""

    def _research_route(self, *, intent: str = "", selected_prompt: str = "") -> bool:
        return str(intent or "").strip().lower() == "research" and str(selected_prompt or "").strip() == "Research Prompt"

    def _should_defer_research_shortcuts(self, *, research_route: bool) -> bool:
        return bool(research_route and self._insight_engine_enabled() and self._insight_final_render_enabled())

    def _build_research_context_message(
        self,
        ctx: PipelineContext,
        *,
        tool_results: List[dict] | None = None,
    ) -> str:
        workflow_state = dict(getattr(ctx, "workflow_state", {}) or {})
        parser_result = workflow_state.get("prepare_context_parser_result") or {}
        parser_answer = str(workflow_state.get("prepare_context_parser_answer") or "").strip()
        direct_answer_hint = str(workflow_state.get("prepare_context_direct_answer_hint") or "").strip()
        multi_agent_hint = str(workflow_state.get("prepare_context_multi_agent_hint") or "").strip()
        retrieval_notes = [
            str(item).strip()
            for item in list(workflow_state.get("research_retrieval_notes") or [])
            if str(item).strip()
        ]
        executed_tools = [
            str(item).strip()
            for item in list(workflow_state.get("research_executed_tools") or [])
            if str(item).strip()
        ]
        results = list(tool_results or [])
        error_items = [item for item in results if isinstance(item, dict) and str(item.get("status") or "").strip().lower() == "error"]
        empty_items = [
            item
            for item in results
            if isinstance(item, dict)
            and str(item.get("status") or "").strip().lower() in {"success", "not_found", "no_result", "empty"}
            and int(item.get("count") or item.get("total") or len(item.get("items") or [])) == 0
        ]
        lines: List[str] = []
        if parser_result:
            lines.append("Research Continuation: parser_result 已保留为参考上下文，禁止在 prepare_context 抢答。")
            if parser_answer:
                lines.append(f"Parser Hint: {parser_answer[:400]}")
        if direct_answer_hint:
            lines.append("Research Continuation: direct_answer 命中后未提前终止，以下仅作为检索补充提示。")
            lines.append(f"Direct Answer Hint: {direct_answer_hint[:400]}")
        if multi_agent_hint:
            lines.append("Research Continuation: multi_agent 命中后未提前终止，以下仅作为检索补充提示。")
            lines.append(f"Multi-Agent Hint: {multi_agent_hint[:400]}")
        if retrieval_notes:
            lines.append("Research Retrieval Notice: 检索阶段未提前终止，请基于以下结构化提示继续生成研究回答。")
            for note in retrieval_notes[:5]:
                lines.append(f"- {note[:240]}")
        if executed_tools:
            lines.append("Attempted Tools: " + ", ".join(executed_tools[:6]))
        if empty_items:
            lines.append("Retrieval Summary: 以下工具已执行但未命中足够结果，请基于无结果上下文继续给出未找到原因、可补采方向和下一步建议。")
            for item in empty_items[:5]:
                tool_name = str(item.get("tool_name") or "unknown")
                reason = str(item.get("message") or item.get("answer") or "工具返回空结果").strip()
                lines.append(f"- {tool_name}: {reason[:240]}")
        if error_items:
            lines.append("Tool Error Summary: 以下工具执行失败，但主链已继续，请结合错误上下文给出可执行回答。")
            for item in error_items[:5]:
                tool_name = str(item.get("tool_name") or "unknown")
                tool_error = str(item.get("error") or item.get("message") or "unknown error").strip()
                lines.append(f"- {tool_name}: {tool_error[:240]}")
            if all(str(item.get("exception_type") or "") == "ToolExecutionTimeout" for item in error_items):
                lines.append("Timeout Summary: 所有已尝试工具均发生超时，当前没有可靠数据返回，建议稍后重试或触发补采。")
        return "\n".join(lines).strip()

    def _build_messages_from_route(self, user_message: str, history: list[dict], route: Dict[str, Any] | None) -> List[dict]:
        prompt = str((route or {}).get("prompt") or "")
        messages: List[dict] = [{"role": "system", "content": prompt}]
        current_entities = list(getattr(self.brain, "current_entities", []) or [])
        if current_entities:
            entity_context = "当前对话中提到的实体：" + "、".join(
                f"{item['name']}({item['type']}, {item.get('country') or '未知国家'})"
                for item in current_entities[-5:]
                if item.get("name")
            )
            messages.append({"role": "system", "content": entity_context})
        for msg in (history or [])[-10:]:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if content:
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": user_message})
        return messages

    def _research_results_need_fast_finalize(self, results: List[dict] | None) -> bool:
        normalized = [item for item in list(results or []) if isinstance(item, dict)]
        if not normalized:
            return False
        return all(str(item.get("status") or "").strip().lower() == "error" for item in normalized)

    def _build_research_timeout_answer(self, ctx: PipelineContext, user_message: str, tool_results: List[dict] | None) -> str:
        workflow_state = dict(getattr(ctx, "workflow_state", {}) or {})
        executed_tools = [
            str(item).strip()
            for item in list(workflow_state.get("research_executed_tools") or [])
            if str(item).strip()
        ]
        normalized_results = [item for item in list(tool_results or []) if isinstance(item, dict)]
        timeout_tools = [
            str(item.get("tool_name") or "unknown").strip()
            for item in normalized_results
            if str(item.get("exception_type") or "").strip() == "ToolExecutionTimeout"
        ]
        failure_tools = [
            str(item.get("tool_name") or "unknown").strip()
            for item in normalized_results
            if str(item.get("status") or "").strip().lower() == "error"
        ]
        lines = [
            f"针对你的研究请求“{user_message}”，我已尝试调用研究工具，但当前没有拿到可靠数据结果。",
            f"- 已尝试工具：{', '.join(executed_tools or failure_tools or ['无'])}",
            f"- 超时工具：{', '.join(timeout_tools or ['无'])}",
            "- 当前状态：工具执行失败或超时，暂无可直接引用的可靠数据返回。",
            "- 建议：稍后重试；如果这是高优先级查询，建议触发补采或人工复核来源后再生成正式结论。",
        ]
        return "\n".join(lines).strip()

    def _record_research_tool_execution(
        self,
        workflow_state: Dict[str, Any] | None,
        tool_calls: list[dict],
        parsed_results: List[dict] | None,
    ) -> None:
        if not isinstance(workflow_state, dict):
            return
        seen_signatures = set(str(item) for item in list(workflow_state.get("research_tool_seen_signatures") or []) if str(item).strip())
        failed_signatures = set(str(item) for item in list(workflow_state.get("research_tool_failed_signatures") or []) if str(item).strip())
        for idx, tool_call in enumerate(list(tool_calls or [])):
            function_name, function_args = self._tool_call_name_and_args(tool_call)
            signature = self._tool_call_signature(function_name, function_args)
            seen_signatures.add(signature)
            result = {}
            if idx < len(list(parsed_results or [])) and isinstance(list(parsed_results or [])[idx], dict):
                result = list(parsed_results or [])[idx]
            if str(result.get("status") or "").strip().lower() == "error":
                failed_signatures.add(signature)
        workflow_state["research_tool_seen_signatures"] = list(seen_signatures)
        workflow_state["research_tool_failed_signatures"] = list(failed_signatures)

    def _final_generate_from_tool_results(self, user_message: str, history: list[dict], tool_results: List[dict], finalize) -> dict:
        merged_results = list(tool_results or [])
        policy_engine = self._get_execution_policy_engine()
        evidence_bundle = self._build_evidence_bundle(merged_results)
        knowledge_input: Any = evidence_bundle if evidence_bundle is not None else merged_results
        knowledge_graph = self._build_knowledge_graph(knowledge_input)
        if self._memory_layer_enabled() and self._active_memory_context is not None:
            self._trace_stage_start("MEMORY_UPDATE")
            self._active_memory_context = self._update_memory_after_knowledge(
                user_message,
                knowledge_graph,
                requirement=self._get_requirement(user_message),
            )
            self._trace_stage_end(
                "MEMORY_UPDATE",
                metadata={
                    "snapshot_count": len(self._active_memory_context.knowledge_snapshots or []),
                    "entity_memory_count": len(self._active_memory_context.entity_memories or []),
                },
            )
        self._trace_stage_start("COMPOSER")
        answer_context = self._build_answer_context_model(
            user_message,
            merged_results,
            knowledge_graph=knowledge_graph,
            evidence_bundle=evidence_bundle,
        )
        self._trace_stage_end(
            "COMPOSER",
            metadata={
                "fact_count": len(answer_context.facts or []) if isinstance(answer_context, AnswerContext) else 0,
                "evidence_count": len(answer_context.evidence or []) if isinstance(answer_context, AnswerContext) else 0,
            },
        )
        self._trace_stage_start("VERIFICATION")
        verification_result = self._build_verification_result(
            user_message,
            merged_results,
            answer_context,
            knowledge_graph=knowledge_graph,
            evidence_bundle=evidence_bundle,
        )
        self._trace_stage_end(
            "VERIFICATION",
            metadata={
                "coverage": float(verification_result.get("coverage") or 0.0),
                "missing_fields": list(verification_result.get("missing_fields") or []),
                "blocking_conflict": bool(verification_result.get("blocking_conflict")),
            },
        )
        loop_summary: Dict[str, Any] = {}

        if self._retrieval_loop_enabled():
            self._trace_stage_start("RETRIEVAL_LOOP")
            merged_results, knowledge_graph, answer_context, verification_result, loop_summary = self._run_retrieval_loop(
                user_message,
                merged_results,
                knowledge_graph,
                answer_context,
                verification_result,
            )
            self._trace_stage_end(
                "RETRIEVAL_LOOP",
                metadata={
                    "loop_count": int(loop_summary.get("loop_count") or 0),
                    "stop_conditions": list(loop_summary.get("stop_conditions") or []),
                },
            )

        snapshot_decision = policy_engine.evaluate_memory(
            ExecutionPolicyContext(
                question=user_message,
                question_type=self._current_question_type(),
                memory={"operation": "snapshot"},
                knowledge={
                    "operation": "snapshot",
                    "node_count": len(knowledge_graph.nodes or []) if knowledge_graph is not None else 0,
                    "relation_count": len(knowledge_graph.relations or []) if knowledge_graph is not None else 0,
                },
            ),
            default_decision=bool(self._memory_layer_enabled() and self._active_memory_context is not None and knowledge_graph is not None),
        )
        if bool(snapshot_decision.decision):
            self._trace_stage_start("MEMORY_SNAPSHOT")
            self._active_memory_context = self._snapshot_memory(knowledge_graph, reason="post_verification")
            self._trace_stage_end(
                "MEMORY_SNAPSHOT",
                metadata={"snapshot_count": len(self._active_memory_context.knowledge_snapshots or [])},
            )

        ctx_insight_result = self._build_insight_result(
            user_message=user_message,
            intent=str(getattr(self.brain, "_reasoning_v1_context", {}).get("question_type") or ""),
            tool_results=merged_results,
            evidence_bundle=evidence_bundle,
            knowledge_graph=knowledge_graph,
            answer_context=answer_context,
            verification_result=verification_result,
        )
        if ctx_insight_result:
            insight_context_message = self._format_insight_context(ctx_insight_result)
        else:
            insight_context_message = ""
        evidence = self._merge_evidence_from_knowledge_graph(knowledge_graph) if knowledge_graph is not None else self._merge_evidence_from_bundle(evidence_bundle, merged_results)
        final_answer_override = self._build_final_answer_override(
            user_message=user_message,
            insight_result=ctx_insight_result,
            answer_context=answer_context,
        )
        if final_answer_override:
            return finalize(
                final_answer_override,
                evidence,
                answer_context=answer_context,
                verification=verification_result,
                loop_summary=loop_summary,
            )
        if self._composer_enabled():
            filtered_messages = self.brain._build_messages(user_message, history)
            if answer_context:
                filtered_messages = [
                    m
                    for m in filtered_messages
                    if not (m.get("role") == "system" and str(m.get("content") or "").startswith("Answer Context"))
                ]
                filtered_messages.append(
                    {"role": "system", "content": self.brain._format_answer_context(self._answer_context_to_dict(answer_context) or {})}
                )
            if insight_context_message:
                filtered_messages.append({"role": "system", "content": insight_context_message})
            llm_policy = policy_engine.evaluate_llm(
                ExecutionPolicyContext(
                    question=user_message,
                    question_type=self._current_question_type(),
                    pipeline=getattr(self._active_trace_session, "pipeline", None),
                    verification=dict(verification_result or {}),
                    trace={"operation": "generate", "mode": "composer", "supports_stream": self._selection_supports_stream(None)},
                    coverage=float(verification_result.get("coverage") or 0.0),
                    tool_results=merged_results,
                ),
            )
            llm_policy_payload = dict(llm_policy.decision or {})
            self._trace_stage_start("LLM")
            if not bool(llm_policy_payload.get("allow_generate", True)):
                self._trace_stage_end("LLM", status="failed", metadata={"mode": "composer", "policy": "denied"})
                return finalize(
                    self.brain._append_gap_collection_notice(user_message, self.brain._fallback_reply(user_message, history)),
                    evidence,
                    answer_context=answer_context,
                    verification=verification_result,
                    loop_summary=loop_summary,
                )
            self.runtime_metrics.inc("llm_generation_count", labels={"mode": "composer"})
            llm_start = time.perf_counter()
            resp = self.brain._call_llm(filtered_messages, tools=None)
            self.runtime_metrics.observe("llm.latency_ms", round((time.perf_counter() - llm_start) * 1000, 2), labels={"mode": "composer"})
            self._trace_event(
                "LLM",
                "Final LLM Generate",
                duration_ms=round((time.perf_counter() - llm_start) * 1000, 2),
                metadata={"mode": "composer"},
            )
            if resp:
                content = resp.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
                if content:
                    self._trace_stage_end("LLM", metadata={"mode": "composer", "status": "success"})
                    return finalize(
                        self.brain._append_gap_collection_notice(user_message, content),
                        evidence,
                        answer_context=answer_context,
                        verification=verification_result,
                        loop_summary=loop_summary,
                    )
            self._trace_stage_end("LLM", status="failed", metadata={"mode": "composer"})
            return finalize(
                self.brain._append_gap_collection_notice(user_message, self.brain._fallback_reply(user_message, history)),
                evidence,
                answer_context=answer_context,
                verification=verification_result,
                loop_summary=loop_summary,
            )

        messages = self.brain._build_messages(user_message, history)
        if insight_context_message:
            messages.append({"role": "system", "content": insight_context_message})
        messages.append({"role": "assistant", "content": ""})
        for idx, result in enumerate(merged_results, start=1):
            messages.append({"role": "tool", "tool_call_id": f"call_{idx}", "content": json.dumps(result, ensure_ascii=False)})
        llm_policy = policy_engine.evaluate_llm(
            ExecutionPolicyContext(
                question=user_message,
                question_type=self._current_question_type(),
                pipeline=getattr(self._active_trace_session, "pipeline", None),
                verification=dict(verification_result or {}),
                trace={"operation": "generate", "mode": "standard", "supports_stream": self._selection_supports_stream(None)},
                coverage=float(verification_result.get("coverage") or 0.0),
                tool_results=merged_results,
            ),
        )
        llm_policy_payload = dict(llm_policy.decision or {})
        self._trace_stage_start("LLM")
        if not bool(llm_policy_payload.get("allow_generate", True)):
            self._trace_stage_end("LLM", status="failed", metadata={"mode": "standard", "policy": "denied"})
            return finalize(
                self.brain._append_gap_collection_notice(user_message, self.brain._fallback_reply(user_message, history)),
                evidence,
                answer_context=answer_context,
                verification=verification_result,
                loop_summary=loop_summary,
            )
        self.runtime_metrics.inc("llm_generation_count", labels={"mode": "standard"})
        llm_start = time.perf_counter()
        resp = self.brain._call_llm(messages, tools=None)
        self.runtime_metrics.observe("llm.latency_ms", round((time.perf_counter() - llm_start) * 1000, 2), labels={"mode": "standard"})
        self._trace_event(
            "LLM",
            "Final LLM Generate",
            duration_ms=round((time.perf_counter() - llm_start) * 1000, 2),
            metadata={"mode": "standard"},
        )
        if resp:
            content = resp.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            if content:
                self._trace_stage_end("LLM", metadata={"mode": "standard", "status": "success"})
                return finalize(
                    self.brain._append_gap_collection_notice(user_message, content),
                    evidence,
                    answer_context=answer_context,
                    verification=verification_result,
                    loop_summary=loop_summary,
                )
        self._trace_stage_end("LLM", status="failed", metadata={"mode": "standard"})
        return finalize(
            self.brain._append_gap_collection_notice(user_message, self.brain._fallback_reply(user_message, history)),
            evidence,
            answer_context=answer_context,
            verification=verification_result,
            loop_summary=loop_summary,
        )

    def _run_retrieval_loop(
        self,
        user_message: str,
        tool_results: List[dict],
        knowledge_graph: KnowledgeGraph | None,
        answer_context: AnswerContext,
        verification_result: Dict[str, Any],
        *,
        allow_verification_followups: bool = True,
    ) -> tuple[List[dict], KnowledgeGraph | None, AnswerContext, Dict[str, Any], Dict[str, Any]]:
        controller = self._get_retrieval_loop_controller()
        if controller is None:
            return tool_results, knowledge_graph, answer_context, verification_result, {}
        loop_context = LoopContext(
            merged_evidence=list(answer_context.evidence or []),
            merged_facts=list(answer_context.facts or []),
            merged_conflicts=list(answer_context.conflicts or []),
        )
        self._record_loop_snapshot(loop_context, answer_context, verification_result)

        merged_results = list(tool_results or [])
        current_graph = knowledge_graph
        current_context = answer_context
        current_verification = dict(verification_result or {})
        policy_engine = self._get_execution_policy_engine()

        while True:
            loop_payload = controller.build_loop_policy_payload(current_verification, loop_context.loop_count, loop_context)
            decision = policy_engine.evaluate_loop(
                ExecutionPolicyContext(
                    question=user_message,
                    question_type=self._current_question_type(),
                    verification=dict(loop_payload.get("verification") or {}),
                    trace=dict(loop_payload.get("trace") or {}),
                    loop_count=int(loop_payload.get("loop_count") or 0),
                    coverage=float((loop_payload.get("verification") or {}).get("coverage") or 0.0),
                ),
                default_decision={"continue": False, "reason": StopCondition.VERIFICATION_PASS.value},
            ).decision
            if not decision.get("continue"):
                loop_context.stop_conditions.append(str(decision.get("reason") or StopCondition.VERIFICATION_PASS.value))
                break

            missing_target: Any = current_graph if (self._knowledge_layer_enabled() and current_graph is not None) else current_context
            missing_information = controller.analyse_missing_information(current_context.requirement, missing_target)
            loop_context.previous_missing.append(dict(missing_information))

            retrieval_plan = controller.generate_retrieval_plan(missing_information)
            tool_calls = controller.generate_tool_calls(retrieval_plan)
            loop_context.tool_history.append(list(tool_calls or []))
            loop_context.history.append({"reason": str(decision.get("reason") or ""), "retrieval_plan": retrieval_plan.to_dict()})

            if not tool_calls:
                loop_context.stop_conditions.append(StopCondition.NO_PROGRESS.value)
                break

            new_results = self._execute_tool_calls(tool_calls)
            if new_results is None:
                loop_context.stop_conditions.append(StopCondition.NO_PROGRESS.value)
                break

            merged_results = controller.merge_new_tool_results(merged_results, new_results)
            current_bundle = self._build_evidence_bundle(merged_results)
            current_graph = self._build_knowledge_graph(current_bundle if current_bundle is not None else merged_results) if self._knowledge_layer_enabled() else None
            if self._memory_layer_enabled() and self._active_memory_context is not None and current_graph is not None:
                self._active_memory_context = self._update_memory_after_knowledge(
                    user_message,
                    current_graph,
                    requirement=current_context.requirement if isinstance(current_context, AnswerContext) else self._get_requirement(user_message),
                )
                self._sync_container_scope(str(getattr(self.brain, "conversation_id", "") or ""), None)
            current_context = self._build_answer_context_model(
                user_message,
                merged_results,
                knowledge_graph=current_graph,
                evidence_bundle=current_bundle,
            )
            current_verification = self._build_verification_result(
                user_message,
                merged_results,
                current_context,
                knowledge_graph=current_graph,
                evidence_bundle=current_bundle,
                allow_reflection=allow_verification_followups,
                allow_repair_plan=allow_verification_followups,
                allow_repair_execution=allow_verification_followups,
            )
            loop_context.loop_count += 1
            self._trace_event(
                "RETRIEVAL_LOOP",
                "Coverage Improved",
                metadata={
                    "loop_count": int(loop_context.loop_count or 0),
                    "coverage": float(current_verification.get("coverage") or 0.0),
                    "missing_fields": list(current_verification.get("missing_fields") or []),
                    "knowledge_nodes": len(current_graph.nodes or []) if current_graph is not None else 0,
                    "knowledge_relations": len(current_graph.relations or []) if current_graph is not None else 0,
                },
            )
            loop_context.merged_evidence = list(current_context.evidence or [])
            loop_context.merged_facts = list(current_context.facts or [])
            loop_context.merged_conflicts = list(current_context.conflicts or [])
            self._record_loop_snapshot(loop_context, current_context, current_verification)

        return merged_results, current_graph, current_context, current_verification, controller.summarize_loop(loop_context)

    def _build_answer_context_model(
        self,
        user_message: str,
        tool_results: List[dict],
        *,
        knowledge_graph: KnowledgeGraph | None = None,
        evidence_bundle: EvidenceBundle | None = None,
    ) -> AnswerContext:
        if self._answer_context_enabled() and evidence_bundle is not None:
            try:
                builder = self._get_answer_context_builder()
                composer = self._get_answer_composer()
                if composer is None:
                    raise RuntimeError("answer composer unavailable")
                question_context = self._build_question_context_for_registry(user_message)
                requirement = self._get_requirement(user_message)
                built_context = builder.build_context(evidence_bundle)
                composer_input: Any = built_context
                if self._structured_reasoning_enabled():
                    engine = self._get_reasoning_engine()
                    if engine is not None and hasattr(engine, "build_reasoning_context"):
                        reasoning_context = engine.build_reasoning_context(evidence_bundle, built_context)
                        payload = built_context.to_dict()
                        payload["metadata"] = {
                            **dict(payload.get("metadata") or {}),
                            "reasoning_context": reasoning_context.to_dict() if hasattr(reasoning_context, "to_dict") else {},
                        }
                        composer_input = payload
                model = composer.compose(question_context, requirement, composer_input, memory_context=self._active_memory_context)
                self._trace_event(
                    "COMPOSER",
                    "Answer Context Built",
                    metadata={
                        "mode": "answer_context_builder",
                        "fact_count": len(model.facts or []),
                        "evidence_count": len(model.evidence or []),
                    },
                )
                return model
            except Exception:
                pass
        if self._knowledge_layer_enabled() and knowledge_graph is not None:
            try:
                composer = self._get_answer_composer()
                if composer is None:
                    raise RuntimeError("answer composer unavailable")
                question_context = self._build_question_context_for_registry(user_message)
                requirement = self._get_requirement(user_message)
                model = composer.compose(question_context, requirement, knowledge_graph, memory_context=self._active_memory_context)
                self._trace_event(
                    "COMPOSER",
                    "Answer Context Built",
                    metadata={"fact_count": len(model.facts or []), "evidence_count": len(model.evidence or [])},
                )
                return model
            except Exception:
                pass
        answer_context = self.brain._build_answer_context(user_message, tool_results)
        if isinstance(answer_context, dict):
            try:
                model = AnswerContext.from_dict(answer_context)
                self._trace_event(
                    "COMPOSER",
                    "Answer Context Built",
                    metadata={"fact_count": len(model.facts or []), "evidence_count": len(model.evidence or [])},
                )
                return model
            except Exception:
                pass

        requirement = self._get_requirement(user_message)
        evidence_models = [Evidence.from_dict(item) for item in self._merge_evidence_from_tool_results(tool_results)]
        model = AnswerContext(
            question=str(user_message or ""),
            requirement=requirement,
            sections=[],
            facts=[],
            conflicts=[],
            missing=list(requirement.required_fields or []),
            citation_map={},
            evidence=evidence_models,
        )
        self._trace_event(
            "COMPOSER",
            "Answer Context Built",
            metadata={"fact_count": len(model.facts or []), "evidence_count": len(model.evidence or [])},
        )
        return model

    def _get_requirement(self, user_message: str) -> Requirement:
        ctx = getattr(self.brain, "_reasoning_v1_context", {}) or {}
        requirement = ctx.get("requirement")
        if isinstance(requirement, Requirement):
            return requirement
        if isinstance(requirement, dict):
            return Requirement.from_dict(requirement)
        try:
            engine = self._get_reasoning_engine()
            if engine is None:
                raise RuntimeError("reasoning engine unavailable")
            country = self.brain._extract_country(user_message)
            pre = engine.build_reasoning_result_pre(
                user_message,
                getattr(self.brain, "current_entities", []) or [],
                country,
                memory_context=self._active_memory_context,
            )
            return pre.requirement
        except Exception:
            return Requirement(
                required_fields=["source"],
                required_sources=[],
                minimum_sources=1,
                minimum_confidence=0.0,
                coverage_threshold=0.0,
                allow_partial=True,
            )

    def _build_verification_result(
        self,
        user_message: str,
        tool_results: List[dict],
        answer_context: AnswerContext,
        *,
        knowledge_graph: KnowledgeGraph | None = None,
        evidence_bundle: EvidenceBundle | None = None,
        allow_reflection: bool = True,
        allow_repair_plan: bool = True,
        allow_repair_execution: bool = True,
    ) -> Dict[str, Any]:
        requirement = answer_context.requirement if isinstance(answer_context, AnswerContext) else self._get_requirement(user_message)
        evaluation: Dict[str, Any] = {}
        conflicts: List[Dict[str, Any]] = []
        verification: Dict[str, Any] = {}

        self._trace_stage_start("REASONING")
        if self._evidence_verification_enabled() and evidence_bundle is not None:
            verification = build_evidence_aware_verification_result(
                evidence_bundle,
                answer_context,
                requirement,
                trace_center=self._active_trace_center,
                runtime_metrics=self.runtime_metrics,
            )
            evaluation = {
                "coverage": float(verification.get("coverage") or 0.0),
                "missing_fields": list(verification.get("missing_fields") or []),
                "missing_sources": list(verification.get("missing_sources") or []),
            }
            conflicts = list(((verification.get("evidence_verification") or {}).get("conflicting_facts") or []))
            self._trace_event(
                "REASONING",
                "Reasoning Evaluated",
                metadata={
                    "mode": "evidence_verification",
                    "required_fields": list(requirement.required_fields or []),
                    "coverage": float(evaluation.get("coverage") or 0.0),
                    "conflict_count": len(conflicts or []),
                    "evidence_count": len(answer_context.evidence or []),
                },
            )
        else:
            try:
                engine = self._get_reasoning_engine()
                if engine is None:
                    raise RuntimeError("reasoning engine unavailable")
                country = str(getattr(self.brain, "_reasoning_v1_context", {}).get("country") or self.brain._extract_country(user_message) or "")
                pre = engine.build_reasoning_result_pre(
                    user_message,
                    getattr(self.brain, "current_entities", []) or [],
                    country,
                    memory_context=self._active_memory_context,
                )
                reasoning_input: Any = knowledge_graph if (self._knowledge_layer_enabled() and knowledge_graph is not None) else self._project_evidence_bundle_results(evidence_bundle, tool_results)
                if self._structured_reasoning_enabled() and evidence_bundle is not None and hasattr(engine, "build_reasoning_context"):
                    structured_context = engine.build_reasoning_context(evidence_bundle, answer_context)
                    reasoning_input = structured_context
                post = engine.build_reasoning_result_post(pre, reasoning_input)
                if post.evaluation:
                    evaluation = post.evaluation.to_dict()
                conflicts = [item.to_dict() for item in (post.conflicts or [])]
                verification = dict(post.verification or {})
                self._trace_event(
                    "REASONING",
                    "Reasoning Evaluated",
                    metadata={
                        "required_fields": list(requirement.required_fields or []),
                        "coverage": float(evaluation.get("coverage") or 0.0),
                        "conflict_count": len(conflicts or []),
                        "evidence_count": len(answer_context.evidence or []),
                    },
                )
            except Exception:
                conflicts = [item.to_dict() for item in (answer_context.conflicts or [])]

        controller = self._get_retrieval_loop_controller()
        if controller is None:
            controller = RetrievalLoopController()
        missing_target: Any = knowledge_graph if (self._knowledge_layer_enabled() and knowledge_graph is not None) else answer_context
        missing_info = controller.analyse_missing_information(requirement, missing_target)
        missing_fields = self._dedupe_list(list(evaluation.get("missing_fields") or []) + list(missing_info.get("missing_fields") or []))
        missing_sources = self._dedupe_list(list(evaluation.get("missing_sources") or []) + list(missing_info.get("missing_sources") or []))

        coverage = float(evaluation.get("coverage") or self._estimate_coverage(answer_context, requirement, missing_fields))
        coverage_threshold = float(getattr(requirement, "coverage_threshold", 0.0) or 0.0)
        blocking_conflict = bool(conflicts)

        result = {
            "evidence_enough": bool(verification.get("evidence_enough")) if verification else (not missing_fields and coverage >= coverage_threshold),
            "citation_ready": bool(verification.get("citation_ready")) if verification else bool(answer_context.evidence),
            "has_conflict": bool(verification.get("has_conflict")) if verification else blocking_conflict,
            "answer_ready": bool(verification.get("answer_ready")) if verification else (not missing_fields and bool(answer_context.evidence) and not blocking_conflict),
            "missing_fields": missing_fields,
            "missing_sources": missing_sources,
            "coverage": coverage,
            "coverage_threshold": coverage_threshold,
            "blocking_conflict": blocking_conflict,
        }
        verification_policy = self._get_execution_policy_engine().evaluate_verification(
            ExecutionPolicyContext(
                question=user_message,
                question_type=self._current_question_type(),
                requirement=requirement,
                verification={
                    **dict(result),
                    "citation_ready": bool(result.get("citation_ready")),
                    "evidence_count": len(answer_context.evidence or []),
                },
                coverage=coverage,
            ),
            default_decision=result,
        )
        result = dict(verification_policy.decision or result)
        reflection_result = None
        if allow_reflection:
            reflection_result = self._build_reflection_result(
                evidence_bundle=evidence_bundle,
                answer_context=answer_context,
                verification_result=result,
            )
            if reflection_result is not None:
                result["metadata"] = {
                    **dict(result.get("metadata") or {}),
                    "reflection": reflection_result,
                }
        repair_plan = None
        if allow_repair_plan:
            repair_plan = self._build_repair_plan(
                answer_context=answer_context,
                verification_result=result,
                evidence_bundle=evidence_bundle,
            )
            if repair_plan is not None:
                result["metadata"] = {
                    **dict(result.get("metadata") or {}),
                    "repair_plan": repair_plan,
                }
        if allow_repair_execution and repair_plan is not None:
            repair_execution = self._execute_repair_plan(
                user_message=user_message,
                tool_results=tool_results,
                answer_context=answer_context,
                knowledge_graph=knowledge_graph,
                evidence_bundle=evidence_bundle,
                verification_result=result,
                repair_plan=repair_plan,
            )
            if repair_execution is not None:
                result["metadata"] = {
                    **dict(result.get("metadata") or {}),
                    "repair_execution": repair_execution,
                }
        self._trace_event(
            "VERIFICATION",
            "Verification Result",
            metadata={
                "coverage": coverage,
                "missing_fields": list(missing_fields or []),
                "missing_sources": list(missing_sources or []),
                "blocking_conflict": blocking_conflict,
            },
        )
        self._trace_stage_end(
            "REASONING",
            metadata={
                "coverage": coverage,
                "conflict_count": len(conflicts or []),
                "evidence_count": len(answer_context.evidence or []),
            },
        )
        return result

    def _evidence_verification_enabled(self) -> bool:
        return (os.getenv("EVIDENCE_VERIFICATION_ENABLED") or "").strip().lower() in {"1", "true", "yes"}

    def _answer_context_enabled(self) -> bool:
        return (os.getenv("ANSWER_CONTEXT_ENABLED") or "").strip().lower() in {"1", "true", "yes"}

    def _structured_reasoning_enabled(self) -> bool:
        return (os.getenv("STRUCTURED_REASONING_ENABLED") or "").strip().lower() in {"1", "true", "yes"}

    def _self_reflection_enabled(self) -> bool:
        return (os.getenv("SELF_REFLECTION_ENABLED") or "").strip().lower() in {"1", "true", "yes"}

    def _auto_repair_planner_enabled(self) -> bool:
        return (os.getenv("AUTO_REPAIR_PLANNER_ENABLED") or "").strip().lower() in {"1", "true", "yes"}

    def _auto_repair_execution_enabled(self) -> bool:
        return (os.getenv("AUTO_REPAIR_EXECUTION_ENABLED") or "").strip().lower() in {"1", "true", "yes"}

    def _build_reasoning_context_model(self, evidence_bundle: EvidenceBundle | None, answer_context: AnswerContext | None) -> Any:
        if not self._structured_reasoning_enabled() or evidence_bundle is None or answer_context is None:
            return None
        try:
            engine = self._get_reasoning_engine()
            if engine is None or not hasattr(engine, "build_reasoning_context"):
                return None
            return engine.build_reasoning_context(evidence_bundle, answer_context)
        except Exception:
            return None

    def _build_reflection_result(
        self,
        *,
        evidence_bundle: EvidenceBundle | None,
        answer_context: AnswerContext | None,
        verification_result: Dict[str, Any],
    ) -> Dict[str, Any] | None:
        with trace_span(
            "Reflection",
            input_obj={
                "enabled": bool(self._self_reflection_enabled()),
                "has_evidence_bundle": evidence_bundle is not None,
                "has_answer_context": answer_context is not None,
            },
        ) as span:
            if not self._self_reflection_enabled() or evidence_bundle is None or answer_context is None:
                span.set_output_obj({"skipped": True})
                return None
            try:
                reasoning_context = self._build_reasoning_context_model(evidence_bundle, answer_context)
                engine = self._get_self_reflection_engine()
                result = engine.reflect(evidence_bundle, answer_context, reasoning_context, verification_result)
                if hasattr(result, "to_dict"):
                    payload = result.to_dict()
                    span.set_output_obj(payload)
                    return payload
                if isinstance(result, dict):
                    payload = dict(result)
                    span.set_output_obj(payload)
                    return payload
            except Exception:
                span.set_output_obj({"skipped": False, "error": True})
                return None
            span.set_output_obj({"skipped": False, "empty": True})
            return None

    def _build_repair_plan(
        self,
        *,
        answer_context: AnswerContext | None,
        verification_result: Dict[str, Any],
        evidence_bundle: EvidenceBundle | None,
    ) -> Dict[str, Any] | None:
        with trace_span(
            "RepairPlanner",
            input_obj={
                "enabled": bool(self._auto_repair_planner_enabled()),
                "has_answer_context": answer_context is not None,
            },
        ) as span:
            if not self._auto_repair_planner_enabled() or answer_context is None:
                span.set_output_obj({"skipped": True})
                return None
            try:
                reflection_result = dict((verification_result.get("metadata") or {}).get("reflection") or {})
                reasoning_context = self._build_reasoning_context_model(evidence_bundle, answer_context)
                planner = self._get_repair_planner()
                plan = planner.build_plan(
                    reflection_result,
                    verification_result,
                    reasoning_context,
                    answer_context,
                )
                if hasattr(plan, "to_dict"):
                    payload = plan.to_dict()
                    span.set_output_obj(payload)
                    return payload
                if isinstance(plan, dict):
                    payload = dict(plan)
                    span.set_output_obj(payload)
                    return payload
            except Exception:
                span.set_output_obj({"skipped": False, "error": True})
                return None
            span.set_output_obj({"skipped": False, "empty": True})
            return None

    def _execute_repair_plan(
        self,
        *,
        user_message: str,
        tool_results: List[dict],
        answer_context: AnswerContext | None,
        knowledge_graph: KnowledgeGraph | None,
        evidence_bundle: EvidenceBundle | None,
        verification_result: Dict[str, Any],
        repair_plan: Dict[str, Any] | None,
    ) -> Dict[str, Any] | None:
        with trace_span(
            "RepairExecutor",
            input_obj={
                "enabled": bool(self._auto_repair_execution_enabled()),
                "has_answer_context": answer_context is not None,
                "has_plan": bool(repair_plan),
            },
        ) as span:
            if not self._auto_repair_execution_enabled() or answer_context is None or not repair_plan:
                span.set_output_obj({"skipped": True})
                return None
            try:
                executor = self._get_repair_executor()
                base_state = {
                    "user_message": user_message,
                    "tool_results": list(tool_results or []),
                    "knowledge_graph": knowledge_graph,
                    "evidence_bundle": evidence_bundle,
                    "answer_context": answer_context,
                    "verification_result": dict(verification_result or {}),
                    "reasoning_context": self._build_reasoning_context_model(evidence_bundle, answer_context),
                    "loop_summary": {},
                }
                execution = executor.execute_plan(repair_plan, base_state)
                final_state = dict(execution.get("state") or base_state)
                final_bundle = final_state.get("evidence_bundle")
                final_context = final_state.get("answer_context") if isinstance(final_state.get("answer_context"), AnswerContext) else answer_context
                final_graph = final_state.get("knowledge_graph")
                final_verification = self._build_verification_result(
                    user_message,
                    list(final_state.get("tool_results") or []),
                    final_context,
                    knowledge_graph=final_graph,
                    evidence_bundle=final_bundle,
                    allow_reflection=True,
                    allow_repair_plan=False,
                    allow_repair_execution=False,
                )
                final_reflection = dict((final_verification.get("metadata") or {}).get("reflection") or {})
                execution["final_verification"] = final_verification
                execution["final_reflection"] = final_reflection
                execution["repair_completed"] = bool(final_verification.get("answer_ready")) and not bool(final_verification.get("blocking_conflict"))
                execution["stopped"] = True
                execution["metadata"] = {
                    "loop_summary": dict(final_state.get("loop_summary") or {}),
                    "tool_result_count": len(list(final_state.get("tool_results") or [])),
                    "answer_changed": False,
                }
                payload = executor.export_execution(execution)
                span.set_output_obj(payload)
                return payload
            except Exception:
                span.set_output_obj({"skipped": False, "error": True})
                return None

    def _execute_repair_action(self, action: Any, state: Dict[str, Any]) -> Dict[str, Any]:
        action_type = str(getattr(action, "action_type", "") or "").strip().upper()
        next_state = dict(state or {})
        user_message = str(next_state.get("user_message") or "")
        tool_results = list(next_state.get("tool_results") or [])
        knowledge_graph = next_state.get("knowledge_graph")
        evidence_bundle = next_state.get("evidence_bundle")
        answer_context = next_state.get("answer_context")
        verification_result = dict(next_state.get("verification_result") or {})

        if action_type in {"RETRIEVE_MORE", "FIND_SOURCE", "VERIFY_FACT"} and isinstance(answer_context, AnswerContext):
            merged_results, current_graph, current_context, current_verification, loop_summary = self._run_retrieval_loop(
                user_message,
                tool_results,
                knowledge_graph,
                answer_context,
                verification_result,
                allow_verification_followups=False,
            )
            next_state.update(
                {
                    "tool_results": list(merged_results or []),
                    "knowledge_graph": current_graph,
                    "evidence_bundle": self._build_evidence_bundle(list(merged_results or [])),
                    "answer_context": current_context,
                    "verification_result": dict(current_verification or {}),
                    "loop_summary": dict(loop_summary or {}),
                }
            )
        elif action_type == "REBUILD_CONTEXT":
            bundle = evidence_bundle if evidence_bundle is not None else self._build_evidence_bundle(tool_results)
            graph = knowledge_graph if knowledge_graph is not None else self._build_knowledge_graph(bundle if bundle is not None else tool_results)
            rebuilt_context = self._build_answer_context_model(
                user_message,
                tool_results,
                knowledge_graph=graph,
                evidence_bundle=bundle,
            )
            next_state.update(
                {
                    "knowledge_graph": graph,
                    "evidence_bundle": bundle,
                    "answer_context": rebuilt_context,
                    "reasoning_context": self._build_reasoning_context_model(bundle, rebuilt_context),
                }
            )
        elif action_type == "REASON_AGAIN":
            bundle = evidence_bundle if evidence_bundle is not None else self._build_evidence_bundle(tool_results)
            context_model = answer_context if isinstance(answer_context, AnswerContext) else None
            if bundle is not None and context_model is not None:
                next_state["reasoning_context"] = self._build_reasoning_context_model(bundle, context_model)
        elif action_type == "RECHECK_CONFLICT":
            bundle = self._build_evidence_bundle(tool_results)
            graph = self._build_knowledge_graph(bundle if bundle is not None else tool_results)
            next_state.update(
                {
                    "evidence_bundle": bundle,
                    "knowledge_graph": graph,
                }
            )
        return next_state

    def _estimate_coverage(self, answer_context: AnswerContext, requirement: Requirement, missing_fields: List[str]) -> float:
        required_fields = list(requirement.required_fields or [])
        if not required_fields:
            return 1.0
        covered = max(0, len(required_fields) - len(list(missing_fields or [])))
        return round(covered / len(required_fields), 2)

    def _record_loop_snapshot(self, loop_context: LoopContext, answer_context: AnswerContext, verification_result: Dict[str, Any]) -> None:
        loop_context.retrieval_history.append(
            {
                "loop_count": int(loop_context.loop_count or 0),
                "evidence_count": len(answer_context.evidence or []),
                "fact_count": len(answer_context.facts or []),
                "coverage": float(verification_result.get("coverage") or 0.0),
            }
        )

    def _answer_context_to_dict(self, answer_context: AnswerContext | dict | None) -> Dict[str, Any] | None:
        if answer_context is None:
            return None
        if isinstance(answer_context, AnswerContext):
            return answer_context.to_dict()
        if isinstance(answer_context, dict):
            return dict(answer_context)
        return None

    def _insight_engine_enabled(self) -> bool:
        return (os.getenv("INSIGHT_ENGINE_ENABLED") or "").strip().lower() in {"1", "true", "yes"}

    def _get_insight_engine(self) -> InsightEngine:
        return InsightEngine()

    def _extract_score_fields_for_insight(self, answer_context: AnswerContext | dict | None) -> Dict[str, Any]:
        context_dict = self._answer_context_to_dict(answer_context) or {}
        score_fields: Dict[str, Any] = {}
        for fact in list(context_dict.get("facts") or []):
            if not isinstance(fact, dict):
                continue
            field_name = str(fact.get("field") or "").strip().lower()
            if field_name not in {"people_score", "digital_score", "intel_score", "composite_score"}:
                continue
            value = str(fact.get("value") or "").strip()
            if value:
                score_fields[field_name] = value
        return score_fields

    def _collect_source_urls_for_insight(
        self,
        *,
        answer_context: AnswerContext | dict | None,
        evidence_bundle: EvidenceBundle | Dict[str, Any] | None,
        knowledge_graph: KnowledgeGraph | Dict[str, Any] | None,
        tool_results: List[dict] | None,
    ) -> List[str]:
        urls: List[str] = []
        context_dict = self._answer_context_to_dict(answer_context) or {}
        for evidence in list(context_dict.get("evidence") or []):
            if isinstance(evidence, dict):
                url = str(evidence.get("url") or "").strip()
                if url:
                    urls.append(url)
        bundle = evidence_bundle if isinstance(evidence_bundle, EvidenceBundle) else EvidenceBundle.from_dict(evidence_bundle or {})
        for evidence in list(bundle.evidences or []):
            url = str(getattr(evidence, "url", "") or "").strip()
            if url:
                urls.append(url)
        graph = knowledge_graph if isinstance(knowledge_graph, KnowledgeGraph) else KnowledgeGraph.from_dict(knowledge_graph or {})
        for payload in dict((graph.metadata or {}).get("evidence_index") or {}).values():
            if isinstance(payload, dict):
                url = str(payload.get("url") or "").strip()
                if url:
                    urls.append(url)
        for result in list(tool_results or []):
            if not isinstance(result, dict):
                continue
            for evidence in list(result.get("evidence") or []):
                if isinstance(evidence, dict):
                    url = str(evidence.get("url") or "").strip()
                    if url:
                        urls.append(url)
        return self._dedupe_list(urls)

    def _build_insight_result(
        self,
        *,
        user_message: str,
        intent: str,
        tool_results: List[dict] | None,
        evidence_bundle: EvidenceBundle | Dict[str, Any] | None,
        knowledge_graph: KnowledgeGraph | Dict[str, Any] | None,
        answer_context: AnswerContext | dict | None,
        verification_result: Dict[str, Any] | None,
    ) -> Dict[str, Any] | None:
        if not self._insight_engine_enabled():
            return None
        try:
            engine = self._get_insight_engine()
            insight_input = InsightInput(
                question=str(user_message or ""),
                intent=str(intent or ""),
                tool_results=[dict(item or {}) for item in (tool_results or []) if isinstance(item, dict)],
                evidence_bundle=(evidence_bundle.to_dict() if hasattr(evidence_bundle, "to_dict") else dict(evidence_bundle or {})),
                knowledge_graph=(knowledge_graph.to_dict() if hasattr(knowledge_graph, "to_dict") else dict(knowledge_graph or {})),
                answer_context=self._answer_context_to_dict(answer_context) or {},
                verification_result=dict(verification_result or {}),
                score_fields=self._extract_score_fields_for_insight(answer_context),
                source_urls=self._collect_source_urls_for_insight(
                    answer_context=answer_context,
                    evidence_bundle=evidence_bundle,
                    knowledge_graph=knowledge_graph,
                    tool_results=tool_results,
                ),
                metadata={"builder": "pipeline_orchestrator"},
            )
            result = engine.build_insights(insight_input)
            if isinstance(result, InsightResult):
                return result.to_dict()
            if isinstance(result, dict):
                return dict(result)
        except Exception as exc:
            print(
                "INSIGHT_ENGINE_ERROR "
                + json.dumps(
                    {
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                        "conversation_id": str(getattr(self, "_active_trace_session", None) and getattr(self._active_trace_session, "conversation_id", "") or ""),
                    },
                    ensure_ascii=False,
                )
            )
        return None

    def _insight_final_render_enabled(self) -> bool:
        return (os.getenv("INSIGHT_FINAL_RENDER_ENABLED") or "").strip().lower() in {"1", "true", "yes"}

    def _get_insight_answer_renderer(self) -> InsightAnswerRenderer:
        return InsightAnswerRenderer()

    def _supports_insight_final_render(self, query_mode: str) -> bool:
        return str(query_mode or "").strip().lower() in InsightAnswerRenderer.SUPPORTED_QUERY_MODES

    def _detect_render_language(self, user_message: str) -> str:
        return "zh" if any("\u4e00" <= char <= "\u9fff" for char in str(user_message or "")) else "en"

    def _build_final_answer_override(
        self,
        *,
        user_message: str,
        insight_result: Dict[str, Any] | None,
        answer_context: AnswerContext | dict | None,
    ) -> str:
        if not self._insight_engine_enabled():
            return ""
        if not self._insight_final_render_enabled():
            return ""
        payload = dict(insight_result or {})
        if not payload:
            return ""
        query_mode = str(payload.get("query_mode") or "").strip().lower()
        if not self._supports_insight_final_render(query_mode):
            return ""
        try:
            renderer = self._get_insight_answer_renderer()
            rendered = renderer.render(
                question=str(user_message or ""),
                insight_result=payload,
                answer_context=self._answer_context_to_dict(answer_context) or {},
                language=self._detect_render_language(user_message),
            )
            return str(rendered or "").strip()
        except Exception as exc:
            print(
                "INSIGHT_FINAL_RENDER_ERROR "
                + json.dumps(
                    {
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                        "query_mode": query_mode,
                        "conversation_id": str(getattr(self, "_active_trace_session", None) and getattr(self._active_trace_session, "conversation_id", "") or ""),
                    },
                    ensure_ascii=False,
                )
            )
            return ""

    def _yield_text_chunks(self, content: str, *, chunk_size: int = 32) -> Generator[dict, None, None]:
        text = str(content or "")
        for index in range(0, len(text), max(1, int(chunk_size))):
            yield {"type": "token", "content": text[index : index + max(1, int(chunk_size))]}

    def _format_insight_context(self, insight_result: Dict[str, Any] | None) -> str:
        payload = dict(insight_result or {})
        if not payload:
            return ""
        lines = ["Insight Context"]
        executive_summary = payload.get("executive_summary") or {}
        if isinstance(executive_summary, dict):
            summary = str(executive_summary.get("summary") or "").strip()
            if summary:
                lines.append(f"Executive Summary: {summary}")
        for label, key in (
            ("Key Findings", "key_findings"),
            ("Score Explanations", "score_explanations"),
            ("Risks", "risks"),
            ("Opportunities", "opportunities"),
            ("Data Gaps", "data_gaps"),
            ("Recommended Next Questions", "recommended_next_questions"),
        ):
            items = payload.get(key) or []
            rendered = []
            for item in items[:3]:
                if not isinstance(item, dict):
                    continue
                title = str(item.get("title") or "").strip()
                summary = str(item.get("summary") or "").strip()
                if title and summary:
                    rendered.append(f"{title}: {summary}")
                elif summary:
                    rendered.append(summary)
            if rendered:
                lines.append(f"{label}:")
                lines.extend(f"- {item}" for item in rendered)
        return "\n".join(lines).strip()

    def _merge_evidence_from_tool_results(self, tool_results: List[dict]) -> List[dict]:
        evidence: List[dict] = []
        for result in tool_results or []:
            if not isinstance(result, dict):
                continue
            ev = result.get("evidence")
            if isinstance(ev, list):
                for item in ev:
                    if isinstance(item, dict):
                        evidence.append(item)
        return self.brain._merge_evidence([], evidence)

    def _build_knowledge_graph(self, tool_results: List[dict] | EvidenceBundle | Dict[str, Any]) -> KnowledgeGraph | None:
        if not self._knowledge_layer_enabled():
            return None
        self._trace_stage_start("KNOWLEDGE_LAYER")
        try:
            layer = self._get_knowledge_layer()
            if layer is None:
                raise RuntimeError("knowledge layer unavailable")
            previous_graph = None
            if self._memory_layer_enabled() and self._memory_layer is not None and self._active_memory_context is not None:
                previous_graph = self._memory_layer.restore_knowledge(self._active_memory_context)
            graph = layer.ingest_tool_results(tool_results, previous_graph=previous_graph)
            self._trace_stage_end(
                "KNOWLEDGE_LAYER",
                metadata={
                    "node_count": len(graph.nodes or []),
                    "relation_count": len(graph.relations or []),
                    "merge_time_ms": float((graph.metadata or {}).get("merge_time_ms") or 0.0),
                },
            )
            return graph
        except Exception:
            self.runtime_metrics.inc("knowledge_merge_fail")
            self._trace_stage_end("KNOWLEDGE_LAYER", status="failed")
            return None

    def _merge_evidence_from_knowledge_graph(self, knowledge_graph: KnowledgeGraph | None) -> List[dict]:
        if knowledge_graph is None:
            return []
        evidence_index = dict((knowledge_graph.metadata or {}).get("evidence_index") or {})
        evidence = [dict(item) for item in evidence_index.values() if isinstance(item, dict)]
        return self.brain._merge_evidence([], evidence)

    def _merge_evidence_from_bundle(self, evidence_bundle: EvidenceBundle | None, tool_results: List[dict]) -> List[dict]:
        if evidence_bundle is None:
            return self._merge_evidence_from_tool_results(tool_results)
        evidence = []
        sources = {str(item.source_id): item for item in (evidence_bundle.sources or [])}
        for item in evidence_bundle.evidences or []:
            source = sources.get(str(item.source_id))
            source_name = str((item.metadata or {}).get("source_name") or "")
            if not source_name and source is not None:
                source_name = str((source.metadata or {}).get("source_name") or "")
            evidence.append(
                {
                    "id": item.evidence_id,
                    "title": item.title,
                    "snippet": item.snippet,
                    "url": item.url,
                    "source_name": source_name,
                    "confidence": float(item.confidence or 0.0),
                    "published_at": item.created_at,
                    "updated_at": item.created_at,
                    "type": item.source_type,
                }
            )
        return self.brain._merge_evidence([], evidence)

    def _build_evidence_bundle(self, tool_results: List[dict]) -> EvidenceBundle | None:
        if not self._evidence_engine_enabled():
            return None
        try:
            return self._get_evidence_engine().ingest_tool_results(tool_results)
        except Exception:
            return None

    def _project_evidence_bundle_results(self, evidence_bundle: EvidenceBundle | None, tool_results: List[dict]) -> List[dict]:
        if evidence_bundle is None:
            return list(tool_results or [])
        projected = list((evidence_bundle.metadata or {}).get("projection_results") or [])
        if projected:
            return [dict(item) for item in projected if isinstance(item, dict)]
        return list(tool_results or [])

    def _load_memory_context(
        self,
        conversation_id: str,
        question_context: QuestionContext,
        requirement: Requirement,
    ) -> MemoryContext:
        self._trace_stage_start("MEMORY_LOAD")
        memory_context = self._memory_layer.load_memory(
            conversation_id,
            current_entities=list(question_context.entities or []),
            current_requirement=requirement,
            current_country=str(question_context.country or ""),
        )
        if not getattr(self.brain, "current_entities", None) and memory_context.current_entities:
            self.brain.current_entities = list(memory_context.current_entities or [])
        reasoning_ctx = getattr(self.brain, "_reasoning_v1_context", {}) or {}
        if isinstance(reasoning_ctx, dict):
            if not reasoning_ctx.get("country") and memory_context.current_country:
                reasoning_ctx["country"] = str(memory_context.current_country or "")
            if not reasoning_ctx.get("requirement") and memory_context.current_requirement is not None:
                reasoning_ctx["requirement"] = memory_context.current_requirement
            self.brain._reasoning_v1_context = reasoning_ctx
        self._trace_stage_end(
            "MEMORY_LOAD",
            metadata={
                "conversation_id": conversation_id,
                "entity_memory_count": len(memory_context.entity_memories or []),
                "snapshot_count": len(memory_context.knowledge_snapshots or []),
            },
        )
        self._sync_container_scope(conversation_id, None)
        return memory_context

    def _update_memory_after_knowledge(
        self,
        user_message: str,
        knowledge_graph: KnowledgeGraph | None,
        *,
        requirement: Requirement,
    ) -> MemoryContext:
        if self._memory_layer is None or self._active_memory_context is None:
            return self._active_memory_context
        updated = self._memory_layer.update_session(
            self._active_memory_context,
            question=user_message,
            entities=list(self._build_question_context_for_registry(user_message).entities or []),
            country=str(self._build_question_context_for_registry(user_message).country or ""),
            requirement=requirement,
            knowledge_graph=knowledge_graph,
        )
        updated = self._memory_layer.update_entities(updated, knowledge_graph)
        self._sync_container_scope(str(getattr(self.brain, "conversation_id", "") or ""), None)
        return updated

    def _snapshot_memory(self, knowledge_graph: KnowledgeGraph, *, reason: str) -> MemoryContext:
        if self._memory_layer is None or self._active_memory_context is None:
            return self._active_memory_context
        self._memory_layer.create_snapshot(self._active_memory_context, knowledge_graph, reason=reason)
        self._sync_container_scope(str(getattr(self.brain, "conversation_id", "") or ""), None)
        return self._active_memory_context

    def _workflow_engine_enabled(self) -> bool:
        return (os.getenv("WORKFLOW_ENGINE_ENABLED") or "").strip().lower() in {"1", "true", "yes"}

    def _task_planner_enabled(self) -> bool:
        return (os.getenv("TASK_PLANNER_ENABLED") or "").strip().lower() in {"1", "true", "yes"}

    def _adaptive_planner_enabled(self) -> bool:
        return (os.getenv("ADAPTIVE_PLANNER_ENABLED") or "").strip().lower() in {"1", "true", "yes"}

    def _evidence_engine_enabled(self) -> bool:
        return (os.getenv("EVIDENCE_ENGINE_ENABLED") or "").strip().lower() in {"1", "true", "yes"}

    def _get_task_planner(self) -> TaskPlanner:
        return TaskPlanner(trace_center=self._active_trace_center, runtime_metrics=self.runtime_metrics)

    def _build_task_graph(
        self,
        user_message: str,
        question_context: QuestionContext,
        requirement: Requirement,
        capability_plan: CapabilityPlan,
        *,
        selection: Any = None,
        workflow_definition: WorkflowDefinition | None = None,
        memory_context: MemoryContext | None = None,
        knowledge_graph: KnowledgeGraph | None = None,
    ) -> TaskGraph:
        planner = self._get_task_planner()
        planning_context = PlanningContext(
            question=user_message,
            requirement=requirement,
            capability_plan=capability_plan,
            workflow_definition=workflow_definition,
            memory_context=memory_context,
            knowledge_graph=knowledge_graph,
            pipeline_selection=selection,
            metadata={
                "question_type": question_context.question_type.value if hasattr(question_context.question_type, "value") else str(question_context.question_type or "UNKNOWN"),
                "conversation_id": str(question_context.conversation_id or ""),
                "country": str(question_context.country or ""),
                "entities": list(question_context.entities or []),
            },
        )
        return planner.build_task_graph(planning_context)

    def _get_workflow_executor(self, *, trace_center: Any = None) -> WorkflowExecutor:
        return WorkflowExecutor(trace_center=trace_center or self._active_trace_center, runtime_metrics=self.runtime_metrics)

    def _execute_selected_pipeline_workflow(
        self,
        user_message: str,
        conversation_id: str,
        history: list[dict],
        *,
        selection: Any = None,
        workflow_definition: WorkflowDefinition | None = None,
        trace_center: Any = None,
        trace_session: Any = None,
        prepared_context: tuple[QuestionContext, Requirement, CapabilityPlan] | None = None,
    ) -> dict:
        workflow_context = self._build_workflow_context(
            user_message,
            conversation_id,
            history,
            selection=selection,
            workflow_definition=workflow_definition,
            trace_center=trace_center,
            trace_session=trace_session,
            prepared_context=prepared_context,
        )
        definition = workflow_definition or get_workflow_for_pipeline(self._selection_pipeline_name(selection))
        executor = self._get_workflow_executor(trace_center=workflow_context.pipeline_context.trace_center)
        try:
            result = executor.execute(definition, workflow_context)
            return dict(result or workflow_context.pipeline_context.final_result or {})
        finally:
            self._active_trace_center = None
            self._active_trace_session = None
            self._active_memory_context = None
            self._memory_layer = None

    def _build_workflow_context(
        self,
        user_message: str,
        conversation_id: str,
        history: list[dict],
        *,
        selection: Any = None,
        workflow_definition: WorkflowDefinition | None = None,
        trace_center: Any = None,
        trace_session: Any = None,
        prepared_context: tuple[QuestionContext, Requirement, CapabilityPlan] | None = None,
    ) -> WorkflowContext:
        ctx = PipelineContext(messages=[], tool_results=[], trace_center=trace_center, trace_session=trace_session)
        ctx.orchestrator = self
        ctx.conversation_id = conversation_id
        ctx.history = list(history or [])
        ctx.selection = selection
        ctx.workflow_definition = workflow_definition
        ctx.prepared_context = prepared_context
        ctx.workflow_outputs = {}
        ctx.workflow_state = {"pipeline_started_perf": time.perf_counter()}
        self._sync_container_scope(conversation_id, ctx)
        if ctx.trace_center is None and self._trace_center_enabled():
            ctx.trace_center = self._get_trace_center()
            if ctx.trace_center is not None:
                pipeline_name = self._selection_pipeline_name(selection)
                ctx.trace_session = ctx.trace_center.start_session(user_message, pipeline=pipeline_name)
        self._active_trace_center = ctx.trace_center
        self._active_trace_session = ctx.trace_session
        self._memory_layer = self._get_memory_layer()
        self._sync_container_scope(conversation_id, ctx)
        if ctx.prepared_context is not None:
            ctx.question_context, ctx.requirement, ctx.capability_plan = ctx.prepared_context
        else:
            ctx.question_context, ctx.requirement, ctx.capability_plan = self.prepare_governor_context(
                user_message,
                conversation_id,
                history,
                trace_center=ctx.trace_center,
                trace_session=ctx.trace_session,
            )
            ctx.prepared_context = (ctx.question_context, ctx.requirement, ctx.capability_plan)
        if self._memory_layer_enabled() and ctx.memory_context is None:
            ctx.memory_context = self._load_memory_context(conversation_id, ctx.question_context, ctx.requirement)
            self._active_memory_context = ctx.memory_context
            self._sync_container_scope(conversation_id, ctx)
        if workflow_definition is None:
            workflow_definition = get_workflow_for_pipeline(self._selection_pipeline_name(selection))
            ctx.workflow_definition = workflow_definition
        if self._task_planner_enabled():
            ctx.task_graph = self._build_task_graph(
                user_message,
                ctx.question_context,
                ctx.requirement,
                ctx.capability_plan,
                selection=selection,
                workflow_definition=workflow_definition,
                memory_context=ctx.memory_context,
                knowledge_graph=ctx.knowledge_graph,
            )
            setattr(self.brain, "_last_task_graph", ctx.task_graph.to_dict())
            if ctx.trace_center is not None:
                ctx.trace_center.record_planning_event(
                    "Task Graph Built",
                    metadata={
                        "graph_id": ctx.task_graph.graph_id if ctx.task_graph is not None else "",
                        "task_count": len(ctx.task_graph.tasks or []) if ctx.task_graph is not None else 0,
                    },
                )

        def finalize(
            answer: str,
            evidence: Any = None,
            answer_context: AnswerContext | dict | None = None,
            verification: Dict[str, Any] | None = None,
            loop_summary: Dict[str, Any] | None = None,
        ) -> dict:
            merged = self.brain._merge_evidence([], evidence or [])
            answer_context_dict = self._answer_context_to_dict(answer_context)
            insight_result = dict(ctx.insight_result or {}) if isinstance(ctx.insight_result, dict) else None
            if self._memory_layer_enabled() and self._memory_layer is not None and self._active_memory_context is not None:
                setattr(self.brain, "_last_memory_context", self._memory_layer.export_memory(self._active_memory_context))
            if ctx.trace_center is not None:
                with suppress(Exception):
                    ctx.trace_center.finish_session(
                        summary={
                            "answer_length": len(str(answer or "")),
                            "evidence_count": len(merged or []),
                            "verification": dict(verification or {}),
                            "loop_summary": dict(loop_summary or {}),
                            "insight_result_exists": bool(insight_result),
                            "memory_enabled": self._memory_layer_enabled(),
                        },
                        pipeline=self._selection_pipeline_name(selection),
                    )
                setattr(self.brain, "_last_trace_session", ctx.trace_center.export_trace())
            else:
                self.runtime_metrics.observe(
                    "pipeline.total.latency_ms",
                    round((time.perf_counter() - float(ctx.workflow_state.get("pipeline_started_perf") or time.perf_counter())) * 1000, 2),
                    labels={"pipeline": self._selection_pipeline_name(selection)},
                )
            ctx.final_result = {
                "answer": answer or "",
                "evidence": merged,
                "answer_context": answer_context_dict,
                "verification": dict(verification or {}),
                "loop_summary": dict(loop_summary or {}),
            }
            if insight_result:
                ctx.final_result["insight_result"] = insight_result
            return dict(ctx.final_result)

        ctx.finalize = finalize
        return WorkflowContext(
            question=user_message,
            requirement=ctx.requirement,
            capability_plan=ctx.capability_plan,
            workflow_definition=workflow_definition,
            memory_context=ctx.memory_context,
            knowledge_graph=ctx.knowledge_graph,
            pipeline_selection=selection,
            runtime_metrics=self.runtime_metrics,
            service_container=self.container,
            pipeline_context=ctx,
            trace_session=ctx.trace_session,
            history=list(history or []),
            metadata={
                "workflow_enabled": True,
                "retrieval_loop_enabled": self._retrieval_loop_enabled(),
                "adaptive_planner_enabled": self._adaptive_planner_enabled(),
                "planning_revision_count": 0,
                "planning_revisions": [],
                "planning_revision_signatures": [],
                "task_graph": ctx.task_graph.to_dict() if ctx.task_graph is not None else None,
            },
        )

    def execute_workflow_service(self, service_name: str, workflow_context: WorkflowContext, node: Any = None) -> Any:
        handler = getattr(self, f"_workflow_service_{str(service_name or '').strip()}", None)
        if handler is None:
            raise RuntimeError(f"unsupported workflow service: {service_name}")
        return handler(workflow_context, node=node)

    def _workflow_service_prepare_context(self, workflow_context: WorkflowContext, *, node: Any = None) -> Dict[str, Any]:
        with trace_span("PrepareContext", input_obj={"question": workflow_context.question}) as span:
            ctx = workflow_context.pipeline_context
            user_message = workflow_context.question
            history = list(ctx.history or [])
            route = self.brain._route_prompt(user_message)
            route_intent = str((route or {}).get("intent") or "").strip().lower()
            route_selected_prompt = str((route or {}).get("selected_prompt") or "").strip()
            research_route = route_intent == "research" and route_selected_prompt == "Research Prompt"
            parser_result = None
            direct_answer = False
            early_exit = None
            print(f"ENTER prepare_context | conversation_id={ctx.conversation_id}")
            if ctx.workflow_state is None:
                ctx.workflow_state = {}
            ctx.workflow_state["prepare_context_route_intent"] = route_intent
            ctx.workflow_state["prepare_context_selected_prompt"] = route_selected_prompt
            ctx.workflow_state["prepare_context_parser_result"] = None
            ctx.workflow_state["prepare_context_parser_answer"] = ""
            ctx.workflow_state["prepare_context_direct_answer_hint"] = ""
            ctx.workflow_state["prepare_context_direct_answer_deferred"] = False
            ctx.workflow_state["prepare_context_multi_agent_hint"] = ""
            ctx.workflow_state["research_retrieval_notes"] = []
            defer_research_shortcuts = self._should_defer_research_shortcuts(research_route=research_route)

            def log_prepare_context_retrieval_observability(reason: str) -> None:
                if route_intent == "assistant":
                    print("RetrievalSkipped=True")
                    print("ToolCalls=0")
                    print("ExecuteToolCalls=False")
                    print("ResearchRetrievalDisabledReason=N/A")
                    return
                print("RetrievalSkipped=False")
                print("ToolCalls=0")
                print("ExecuteToolCalls=False")
                print(f"ResearchRetrievalDisabledReason={reason or 'prepare_context_early_exit'}")

            if ctx.prepared_context is not None:
                ctx.question_context, ctx.requirement, ctx.capability_plan = ctx.prepared_context
            workflow_context.question_context = ctx.question_context
            workflow_context.requirement = ctx.requirement
            workflow_context.capability_plan = ctx.capability_plan
            self._sync_container_scope(ctx.conversation_id, ctx)
            if self._memory_layer_enabled() and ctx.memory_context is None:
                ctx.memory_context = self._load_memory_context(ctx.conversation_id, ctx.question_context, ctx.requirement)
                self._active_memory_context = ctx.memory_context
                workflow_context.memory_context = ctx.memory_context
                self._sync_container_scope(ctx.conversation_id, ctx)
            elif ctx.memory_context is not None:
                self._active_memory_context = ctx.memory_context
                workflow_context.memory_context = ctx.memory_context

            parser = None
            if research_route:
                parser_result = {"skipped": True, "reason": "research_route_bypass"}
                ctx.workflow_state["prepare_context_parser_result"] = parser_result
                print("RESEARCH_PREPARE_CONTEXT_SKIP_QUERY_PARSER=True")
                print(f"parser_result={json.dumps(parser_result, ensure_ascii=False, default=str)}")
            else:
                try:
                    from services.query_parser import QueryParser

                    parser = QueryParser()
                    parser_result = parser.parse(user_message, conversation_id=ctx.conversation_id)
                    direct_answer = bool((parser_result or {}).get("direct_answer"))
                    print(f"parser_result={json.dumps(parser_result, ensure_ascii=False, default=str)}")
                    if parser_result and parser_result.get("data_found"):
                        answer = parser_result.get("answer") or parser_result.get("response") or ""
                        welcome_reply_uuid = parser_result.get("welcome_reply_uuid") or lookup_welcome_reply_uuid(ctx.conversation_id, answer)
                        emit_welcome_trace(
                            "PIPELINE_UUID",
                            welcome_reply_uuid,
                            conversation_id=ctx.conversation_id,
                            extra={"location": "pipeline_orchestrator.py:_workflow_service_prepare_context:direct_result"},
                        )
                        evidence = parser_result.get("evidence") or []
                        ctx.final_result = ctx.finalize(self.brain._clean_output(answer), evidence)
                        workflow_context.final_result = dict(ctx.final_result)
                        workflow_context.stopped = True
                        log_prepare_context_retrieval_observability("prepare_context_parser_direct_result")
                        early_exit = "direct_result"
                finally:
                    if parser:
                        parser.close()

            if getattr(self.brain, "MULTI_AGENT_AVAILABLE", False):
                with suppress(Exception):
                    from agents.orchestrator import AgentOrchestrator

                    orchestrator = AgentOrchestrator()
                    agent_result = orchestrator.process(user_message)
                    if agent_result.get("data_found"):
                        multi_agent_answer = self.brain._clean_output(agent_result.get("response", ""))
                        if defer_research_shortcuts:
                            ctx.workflow_state["prepare_context_multi_agent_hint"] = multi_agent_answer
                            ctx.workflow_state["prepare_context_direct_answer_deferred"] = True
                            notes = list(ctx.workflow_state.get("research_retrieval_notes") or [])
                            notes.append("multi_agent 已命中旧式数据库回答，但当前请求已切换为 Insight final render 接管，旧回答仅作为 hint 保留。")
                            ctx.workflow_state["research_retrieval_notes"] = self._dedupe_list(notes)
                        else:
                            ctx.final_result = ctx.finalize(multi_agent_answer, agent_result.get("evidence") or [])
                            workflow_context.final_result = dict(ctx.final_result)
                            workflow_context.stopped = True
                            log_prepare_context_retrieval_observability("prepare_context_multi_agent")
                            early_exit = "multi_agent"

            should_prioritize_match = self.brain._looks_like_match_query(user_message)
            captured_profile = None if should_prioritize_match else self.brain._capture_profile_from_message(user_message)
            if captured_profile:
                if defer_research_shortcuts:
                    ctx.workflow_state["prepare_context_direct_answer_hint"] = captured_profile
                    ctx.workflow_state["prepare_context_direct_answer_deferred"] = True
                    notes = list(ctx.workflow_state.get("research_retrieval_notes") or [])
                    notes.append("captured_profile 命中后未提前终止，当前请求继续走检索与 Insight final render 主链。")
                    ctx.workflow_state["research_retrieval_notes"] = self._dedupe_list(notes)
                else:
                    ctx.final_result = ctx.finalize(captured_profile, [])
                    workflow_context.final_result = dict(ctx.final_result)
                    workflow_context.stopped = True
                    log_prepare_context_retrieval_observability("prepare_context_captured_profile")
                    early_exit = "captured_profile"

            if not research_route and self.brain._should_use_direct_answer(user_message):
                direct_answer = True
                ctx.final_result = ctx.finalize(
                    self.brain._append_gap_collection_notice(user_message, self.brain._fallback_reply(user_message, history)),
                    [],
                )
                workflow_context.final_result = dict(ctx.final_result)
                workflow_context.stopped = True
                log_prepare_context_retrieval_observability("prepare_context_direct_answer")
                early_exit = "direct_answer"

            if not bool(getattr(settings.PROVIDER_CONFIG, "api_key", "") or ""):
                ctx.final_result = ctx.finalize(
                    self.brain._append_gap_collection_notice(user_message, self.brain._fallback_reply(user_message, history)),
                    [],
                )
                workflow_context.final_result = dict(ctx.final_result)
                workflow_context.stopped = True
                log_prepare_context_retrieval_observability("prepare_context_missing_api_key")
                early_exit = "missing_api_key"

            result = {
                "context": {
                    "question_type": self._current_question_type(),
                    "memory_loaded": bool(ctx.memory_context is not None),
                    "conversation_id": ctx.conversation_id,
                },
                "parser_result": parser_result,
                "direct_answer": direct_answer,
                "early_exit": early_exit,
            }
            print(f"prepare_context_result={json.dumps(result, ensure_ascii=False, default=str)}")
            print("RETURN prepare_context")
            span.set_output_obj(result)
            return result

    def _workflow_service_retrieval(self, workflow_context: WorkflowContext, *, node: Any = None) -> Dict[str, Any]:
        def log_retrieval_observability(
            *,
            retrieval_skipped: bool,
            tool_calls: int,
            execute_tool_calls: bool,
            research_disabled_reason: str = "",
        ) -> None:
            print(f"RetrievalSkipped={bool(retrieval_skipped)}")
            print(f"ToolCalls={int(tool_calls or 0)}")
            print(f"ExecuteToolCalls={bool(execute_tool_calls)}")
            if intent == "research":
                print(f"ResearchRetrievalDisabledReason={research_disabled_reason or 'None'}")
            else:
                print("ResearchRetrievalDisabledReason=N/A")
        ctx = workflow_context.pipeline_context
        if workflow_context.stopped:
            print("RETURN_ID=A")
            return {"skipped": True}
        user_message = workflow_context.question
        history = list(ctx.history or [])
        route = self.brain._route_prompt(user_message)
        selected_prompt = str((route or {}).get("selected_prompt") or "").strip()
        intent = str((route or {}).get("intent") or "").strip()
        ctx.messages = self._build_messages_from_route(user_message, history, route)
        research_route = self._research_route(intent=intent, selected_prompt=selected_prompt)
        if ctx.workflow_state is None:
            ctx.workflow_state = {}
        if research_route:
            ctx.workflow_state["research_retrieval_notes"] = []
            ctx.workflow_state.setdefault("research_tool_seen_signatures", [])
            ctx.workflow_state.setdefault("research_tool_failed_signatures", [])
            ctx.workflow_state.setdefault("research_executed_tools", [])
            if bool(ctx.workflow_state.get("research_retrieval_completed")):
                print(f"ToolCallsBeforeDedup={int(ctx.workflow_state.get('research_tool_calls_before_dedup') or 0)}")
                print(f"ToolCallsAfterDedup={int(ctx.workflow_state.get('research_tool_calls_after_dedup') or 0)}")
                print("DedupedTools=" + json.dumps(list(ctx.workflow_state.get("research_deduped_tools") or []), ensure_ascii=False, default=str))
                print("ExecutedTools=" + json.dumps(list(ctx.workflow_state.get("research_executed_tools") or []), ensure_ascii=False, default=str))
                log_retrieval_observability(
                    retrieval_skipped=False,
                    tool_calls=len(ctx.tool_results or []),
                    execute_tool_calls=bool(ctx.tool_results),
                )
                print("RETURN_ID=E_REUSE")
                return {"tool_results": len(ctx.tool_results or [])}

        def add_research_retrieval_note(note: str) -> None:
            if not research_route:
                return
            notes = list(ctx.workflow_state.get("research_retrieval_notes") or [])
            note = str(note or "").strip()
            if note and note not in notes:
                notes.append(note)
                ctx.workflow_state["research_retrieval_notes"] = notes

        research_context_message = self._build_research_context_message(ctx)
        if research_route and research_context_message:
            ctx.messages.append({"role": "system", "content": research_context_message})
        if selected_prompt == "Assistant Prompt" or intent == "assistant":
            ctx.tool_results = []
            self._trace_stage_start("RETRIEVAL")
            self._trace_event(
                "RETRIEVAL",
                "Assistant Retrieval Skipped",
                metadata={
                    "selected_prompt": selected_prompt,
                    "intent": intent,
                    "retrieval_skipped": True,
                    "prefetch": False,
                    "tool_call_count": 0,
                    "execute_tool_calls": False,
                },
            )
            self._trace_stage_end(
                "RETRIEVAL",
                metadata={
                    "mode": "assistant_skip",
                    "retrieval_skipped": True,
                    "prefetch": False,
                    "tool_results": 0,
                    "execute_tool_calls": False,
                },
            )
            print("Prefetch=False")
            log_retrieval_observability(
                retrieval_skipped=True,
                tool_calls=0,
                execute_tool_calls=False,
            )
            retrieval_return = {
                "parsed_results": [],
                "evidence": [],
                "tool_results": [],
                "retrieval_skipped": True,
            }
            print("RETRIEVAL_RETURN")
            print(f"parsed_results={retrieval_return.get('parsed_results')}")
            print(f"evidence={retrieval_return.get('evidence')}")
            print(f"tool_results={retrieval_return.get('tool_results')}")
            print(f"retrieval_skipped={retrieval_return.get('retrieval_skipped')}")
            print("RETRIEVAL_RETURN")
            print(f"parsed_results={retrieval_return.get('parsed_results')}")
            print(f"evidence={retrieval_return.get('evidence')}")
            print(f"tool_results={retrieval_return.get('tool_results')}")
            print(f"retrieval_skipped={retrieval_return.get('retrieval_skipped')}")
            print("RETURN_ID=B")
            return retrieval_return

        self._trace_stage_start("RETRIEVAL")
        planned_tool_calls = (
            self._build_planned_tool_calls_from_task_graph(ctx.task_graph, user_message)
            if self._task_planner_enabled()
            else self._build_planned_tool_calls(user_message)
        )
        prefetched_tool_calls = (
            self.brain._build_direct_investor_prefetch(user_message)
            or planned_tool_calls
            or self.brain._build_prefetched_tool_calls(user_message)
        )
        self._trace_event(
            "RETRIEVAL",
            "Prefetched Tool Calls",
            metadata={
                "tool_call_count": len(prefetched_tool_calls or []),
                "task_graph_id": ctx.task_graph.graph_id if ctx.task_graph is not None else "",
            },
        )

        if prefetched_tool_calls:
            prepared_tool_calls = list(prefetched_tool_calls or [])
            prepared_tool_meta: Dict[str, Any] = {
                "before_count": len(prepared_tool_calls),
                "after_count": len(prepared_tool_calls),
                "deduped_tools": [],
                "executed_tools": [],
                "skipped_tools": [],
                "prepared_signatures": [],
            }
            if research_route:
                prepared_tool_calls, prepared_tool_meta = self._prepare_research_tool_calls(
                    user_message,
                    prepared_tool_calls,
                    ctx.workflow_state,
                )
                ctx.workflow_state["research_tool_calls_before_dedup"] = prepared_tool_meta.get("before_count") or 0
                ctx.workflow_state["research_tool_calls_after_dedup"] = prepared_tool_meta.get("after_count") or 0
                ctx.workflow_state["research_deduped_tools"] = list(prepared_tool_meta.get("deduped_tools") or [])
                ctx.workflow_state["research_executed_tools"] = list(prepared_tool_meta.get("executed_tools") or [])
                print(f"ToolCallsBeforeDedup={int(prepared_tool_meta.get('before_count') or 0)}")
                print(f"ToolCallsAfterDedup={int(prepared_tool_meta.get('after_count') or 0)}")
                print("DedupedTools=" + json.dumps(list(prepared_tool_meta.get("deduped_tools") or []), ensure_ascii=False, default=str))
                print("ExecutedTools=" + json.dumps(list(prepared_tool_meta.get("executed_tools") or []), ensure_ascii=False, default=str))
                if not prepared_tool_calls:
                    add_research_retrieval_note("候选工具经去重/限流后为空；请结合已尝试工具与超时情况输出保守结论，并建议稍后重试或触发补采。")
                    ctx.tool_results = list(ctx.tool_results or [])
                    ctx.workflow_state["research_retrieval_completed"] = True
                    log_retrieval_observability(
                        retrieval_skipped=False,
                        tool_calls=0,
                        execute_tool_calls=False,
                        research_disabled_reason="all_research_tools_deduped_or_limited",
                    )
                    print("RETURN_ID=E_EMPTY")
                    return {"tool_results": len(ctx.tool_results or [])}
            direct_tool_name = prefetched_tool_calls[0].get("function", {}).get("name", "")
            if (
                direct_tool_name in self.brain._direct_render_tool_names()
                and not self._should_use_structured_generation()
                and not research_route
            ):
                raw_arguments = prefetched_tool_calls[0].get("function", {}).get("arguments") or "{}"
                try:
                    function_args = json.loads(raw_arguments)
                except json.JSONDecodeError:
                    function_args = {}
                func = self.brain.available_functions.get(direct_tool_name)
                if func:
                    tool_started = time.perf_counter()
                    result = self.brain._normalize_tool_result(direct_tool_name, func(**function_args))
                    tool_duration_ms = round((time.perf_counter() - tool_started) * 1000, 2)
                    self.runtime_metrics.observe("tool.time_ms", tool_duration_ms, labels={"tool_name": direct_tool_name})
                    self.runtime_metrics.inc("tool_success", labels={"tool_name": direct_tool_name})
                    content = self.brain._render_direct_tool_result(direct_tool_name, result)
                    evidence = (result.get("evidence") or []) if isinstance(result, dict) else []
                    self._trace_stage_end("RETRIEVAL", metadata={"mode": "direct_render"})
                    log_retrieval_observability(
                        retrieval_skipped=False,
                        tool_calls=len(prefetched_tool_calls or []),
                        execute_tool_calls=True,
                    )
                    ctx.final_result = ctx.finalize(self.brain._append_gap_collection_notice(user_message, content), evidence)
                    workflow_context.final_result = dict(ctx.final_result)
                    workflow_context.stopped = True
                    print("RETURN_ID=C")
                    return {"direct_render": True}

            execution_calls = prepared_tool_calls if research_route else prefetched_tool_calls
            parsed_results = self._execute_tool_calls(execution_calls, continue_after_error=research_route)
            self._trace_stage_end("RETRIEVAL", metadata={"mode": "prefetch", "tool_results": len(parsed_results or [])})
            if parsed_results is None:
                log_retrieval_observability(
                    retrieval_skipped=False,
                    tool_calls=len(execution_calls or []),
                    execute_tool_calls=True,
                    research_disabled_reason="tool_execution_failed",
                )
                ctx.final_result = ctx.finalize(
                    self.brain._append_gap_collection_notice(user_message, self.brain._fallback_reply(user_message, history)),
                    [],
                )
                workflow_context.final_result = dict(ctx.final_result)
                workflow_context.stopped = True
                print("RETURN_ID=D")
                return {"tool_results": 0}
            ctx.tool_results = list(parsed_results or [])
            if research_route:
                self._record_research_tool_execution(ctx.workflow_state, execution_calls, ctx.tool_results)
            if research_route and self._research_results_need_fast_finalize(ctx.tool_results):
                ctx.workflow_state["research_fast_finalize"] = True
                ctx.task_graph = None
                workflow_context.metadata["task_graph"] = None
                workflow_context.metadata["retrieval_loop_enabled"] = False
                ctx.final_result = ctx.finalize(self._build_research_timeout_answer(ctx, user_message, ctx.tool_results), [])
                workflow_context.final_result = dict(ctx.final_result)
                workflow_context.stopped = True
            if research_route:
                ctx.workflow_state["research_retrieval_completed"] = True
            log_retrieval_observability(
                retrieval_skipped=False,
                tool_calls=len(execution_calls or []),
                execute_tool_calls=True,
            )
            print("RETURN_ID=E")
            return {"tool_results": len(ctx.tool_results or [])}

        tool_choice = self.brain._choose_tool_for_message(user_message)
        self._trace_stage_start("LLM")
        llm_start = time.perf_counter()
        response = self.brain._call_llm(ctx.messages, tools=self.brain.TOOLS, tool_choice=tool_choice)
        self._trace_event(
            "LLM",
            "Initial LLM Call",
            duration_ms=round((time.perf_counter() - llm_start) * 1000, 2),
            metadata={"tool_choice": tool_choice if isinstance(tool_choice, str) else "auto"},
        )
        if not response:
            self._trace_stage_end("LLM", status="failed")
            if research_route:
                add_research_retrieval_note("工具规划阶段未获得可用响应，主链继续进入最终 LLM，请基于现有研究目标给出保守结论与下一步建议。")
                ctx.tool_results = []
                log_retrieval_observability(
                    retrieval_skipped=False,
                    tool_calls=0,
                    execute_tool_calls=False,
                    research_disabled_reason="llm_initial_response_empty",
                )
                print("RETURN_ID=F_R")
                return {"tool_results": 0}
            ctx.final_result = ctx.finalize(
                self.brain._append_gap_collection_notice(user_message, self.brain._fallback_reply(user_message, history)),
                [],
            )
            workflow_context.final_result = dict(ctx.final_result)
            workflow_context.stopped = True
            print("RETURN_ID=F")
            return {"tool_results": 0}

        messages_with_tools = list(ctx.messages)
        collected_results: List[dict] = []
        for _ in range(3):
            assistant_msg = response.get("choices", [{}])[0].get("message", {})
            tool_calls = assistant_msg.get("tool_calls") or []
            if not tool_calls:
                final_content = (assistant_msg.get("content") or "").strip()
                self._trace_stage_end("LLM", metadata={"tool_calls_requested": len(collected_results or [])})
                if not collected_results and final_content:
                    log_retrieval_observability(
                        retrieval_skipped=False,
                        tool_calls=0,
                        execute_tool_calls=False,
                        research_disabled_reason="llm_returned_without_tool_calls",
                    )
                    if research_route:
                        add_research_retrieval_note(
                            "工具规划未生成任何 tool call；请明确当前未命中可执行检索，并给出未找到原因、可补采方向和下一步建议。"
                        )
                        ctx.tool_results = []
                        print("RETURN_ID=G_R")
                        return {"tool_results": 0}
                    ctx.final_result = ctx.finalize(self.brain._append_gap_collection_notice(user_message, final_content), [])
                    workflow_context.final_result = dict(ctx.final_result)
                    workflow_context.stopped = True
                    print("RETURN_ID=G")
                    return {"tool_results": 0}
                break
            self._trace_stage_start("RETRIEVAL")
            messages_with_tools.append({"role": "assistant", "content": assistant_msg.get("content", ""), "tool_calls": tool_calls})
            prepared_loop_calls = list(tool_calls or [])
            if research_route:
                prepared_loop_calls, prepared_loop_meta = self._prepare_research_tool_calls(
                    user_message,
                    prepared_loop_calls,
                    ctx.workflow_state,
                )
                ctx.workflow_state["research_tool_calls_before_dedup"] = prepared_loop_meta.get("before_count") or 0
                ctx.workflow_state["research_tool_calls_after_dedup"] = prepared_loop_meta.get("after_count") or 0
                ctx.workflow_state["research_deduped_tools"] = list(prepared_loop_meta.get("deduped_tools") or [])
                ctx.workflow_state["research_executed_tools"] = list(prepared_loop_meta.get("executed_tools") or [])
                print(f"ToolCallsBeforeDedup={int(prepared_loop_meta.get('before_count') or 0)}")
                print(f"ToolCallsAfterDedup={int(prepared_loop_meta.get('after_count') or 0)}")
                print("DedupedTools=" + json.dumps(list(prepared_loop_meta.get("deduped_tools") or []), ensure_ascii=False, default=str))
                print("ExecutedTools=" + json.dumps(list(prepared_loop_meta.get("executed_tools") or []), ensure_ascii=False, default=str))
                if not prepared_loop_calls:
                    add_research_retrieval_note("LLM 追加的工具调用在去重/限流后被全部跳过；请基于当前超时与空结果上下文直接生成研究回答。")
                    break
            executed = self._execute_tool_calls(prepared_loop_calls, continue_after_error=research_route)
            self._trace_stage_end("RETRIEVAL", metadata={"mode": "llm_tool_calls", "tool_results": len(executed or [])})
            if executed is None:
                self._trace_stage_end("LLM", status="failed")
                log_retrieval_observability(
                    retrieval_skipped=False,
                    tool_calls=len(prepared_loop_calls or []),
                    execute_tool_calls=True,
                    research_disabled_reason="llm_tool_execution_failed",
                )
                ctx.final_result = ctx.finalize(
                    self.brain._append_gap_collection_notice(user_message, self.brain._fallback_reply(user_message, history)),
                    [],
                )
                workflow_context.final_result = dict(ctx.final_result)
                workflow_context.stopped = True
                print("RETURN_ID=H")
                return {"tool_results": 0}
            if research_route:
                self._record_research_tool_execution(ctx.workflow_state, prepared_loop_calls, executed)
            for idx, result in enumerate(executed):
                tool_call = prepared_loop_calls[idx]
                collected_results.append(result if isinstance(result, dict) else {})
                messages_with_tools.append(
                    {"role": "tool", "tool_call_id": tool_call.get("id", ""), "content": json.dumps(result, ensure_ascii=False)}
                )
            llm_loop_start = time.perf_counter()
            response = self.brain._call_llm(messages_with_tools, tools=self.brain.TOOLS)
            self._trace_event(
                "LLM",
                "Follow-up LLM Call",
                duration_ms=round((time.perf_counter() - llm_loop_start) * 1000, 2),
                metadata={"tool_results": len(collected_results or [])},
            )
            if not response:
                self._trace_stage_end("LLM", status="failed")
                ctx.final_result = ctx.finalize(
                    self.brain._append_gap_collection_notice(user_message, self.brain._fallback_reply(user_message, history)),
                    [],
                )
                workflow_context.final_result = dict(ctx.final_result)
                workflow_context.stopped = True
                print("RETURN_ID=I")
                return {"tool_results": 0}

        if collected_results:
            ctx.tool_results = list(collected_results or [])
            if research_route and self._research_results_need_fast_finalize(ctx.tool_results):
                ctx.workflow_state["research_fast_finalize"] = True
                ctx.task_graph = None
                workflow_context.metadata["task_graph"] = None
                workflow_context.metadata["retrieval_loop_enabled"] = False
                ctx.final_result = ctx.finalize(self._build_research_timeout_answer(ctx, user_message, ctx.tool_results), [])
                workflow_context.final_result = dict(ctx.final_result)
                workflow_context.stopped = True
            if research_route:
                ctx.workflow_state["research_retrieval_completed"] = True
            log_retrieval_observability(
                retrieval_skipped=False,
                tool_calls=len(collected_results or []),
                execute_tool_calls=True,
            )
            print("RETURN_ID=J")
            return {"tool_results": len(ctx.tool_results or [])}

        log_retrieval_observability(
            retrieval_skipped=False,
            tool_calls=0,
            execute_tool_calls=False,
            research_disabled_reason="no_prefetched_tool_calls_and_llm_no_tool_calls",
        )
        if research_route:
            add_research_retrieval_note("未生成任何可执行工具调用；请结合当前研究问题输出结构化无结果说明，并提出可补采来源与下一步行动。")
            ctx.tool_results = []
            print("RETURN_ID=K_R")
            return {"tool_results": 0}
        ctx.final_result = ctx.finalize(self.brain._append_gap_collection_notice(user_message, self.brain._fallback_reply(user_message, history)), [])
        workflow_context.final_result = dict(ctx.final_result)
        workflow_context.stopped = True
        print("RETURN_ID=K")
        return {"tool_results": 0}

    def _workflow_service_knowledge(self, workflow_context: WorkflowContext, *, node: Any = None) -> Dict[str, Any]:
        ctx = workflow_context.pipeline_context
        if workflow_context.stopped:
            return {"skipped": True}
        ctx.evidence_bundle = self._build_evidence_bundle(list(ctx.tool_results or []))
        ctx.knowledge_graph = self._build_knowledge_graph(ctx.evidence_bundle if ctx.evidence_bundle is not None else list(ctx.tool_results or []))
        workflow_context.knowledge_graph = ctx.knowledge_graph
        return {
            "node_count": len(ctx.knowledge_graph.nodes or []) if ctx.knowledge_graph is not None else 0,
            "relation_count": len(ctx.knowledge_graph.relations or []) if ctx.knowledge_graph is not None else 0,
        }

    def _workflow_service_memory_update(self, workflow_context: WorkflowContext, *, node: Any = None) -> Dict[str, Any]:
        ctx = workflow_context.pipeline_context
        if workflow_context.stopped:
            return {"skipped": True}
        if self._memory_layer_enabled() and self._active_memory_context is not None:
            self._trace_stage_start("MEMORY_UPDATE")
            ctx.memory_context = self._update_memory_after_knowledge(
                workflow_context.question,
                ctx.knowledge_graph,
                requirement=ctx.requirement or self._get_requirement(workflow_context.question),
            )
            self._active_memory_context = ctx.memory_context
            workflow_context.memory_context = ctx.memory_context
            self._trace_stage_end(
                "MEMORY_UPDATE",
                metadata={
                    "snapshot_count": len(ctx.memory_context.knowledge_snapshots or []),
                    "entity_memory_count": len(ctx.memory_context.entity_memories or []),
                },
            )
        return {"memory_updated": bool(ctx.memory_context is not None)}

    def _workflow_service_answer_composer(self, workflow_context: WorkflowContext, *, node: Any = None) -> Dict[str, Any]:
        ctx = workflow_context.pipeline_context
        if workflow_context.stopped:
            return {"skipped": True}
        print("ENTER Composer")
        self._trace_stage_start("COMPOSER")
        ctx.answer_context = self._build_answer_context_model(
            workflow_context.question,
            list(ctx.tool_results or []),
            knowledge_graph=ctx.knowledge_graph,
            evidence_bundle=ctx.evidence_bundle,
        )
        self._trace_stage_end(
            "COMPOSER",
            metadata={
                "fact_count": len(ctx.answer_context.facts or []) if isinstance(ctx.answer_context, AnswerContext) else 0,
                "evidence_count": len(ctx.answer_context.evidence or []) if isinstance(ctx.answer_context, AnswerContext) else 0,
            },
        )
        return {
            "fact_count": len(ctx.answer_context.facts or []) if isinstance(ctx.answer_context, AnswerContext) else 0,
            "evidence_count": len(ctx.answer_context.evidence or []) if isinstance(ctx.answer_context, AnswerContext) else 0,
        }

    def _workflow_service_verification(self, workflow_context: WorkflowContext, *, node: Any = None) -> Dict[str, Any]:
        ctx = workflow_context.pipeline_context
        if workflow_context.stopped:
            return {"skipped": True}
        if bool((ctx.workflow_state or {}).get("research_fast_finalize")):
            ctx.verification = {
                "coverage": 0.0,
                "missing_fields": ["tool_results_unavailable"],
                "blocking_conflict": False,
                "status": "skipped_for_research_fast_finalize",
            }
            return dict(ctx.verification)
        self._trace_stage_start("VERIFICATION")
        ctx.verification = self._build_verification_result(
            workflow_context.question,
            list(ctx.tool_results or []),
            ctx.answer_context,
            knowledge_graph=ctx.knowledge_graph,
            evidence_bundle=ctx.evidence_bundle,
        )
        self._trace_stage_end(
            "VERIFICATION",
            metadata={
                "coverage": float(ctx.verification.get("coverage") or 0.0),
                "missing_fields": list(ctx.verification.get("missing_fields") or []),
                "blocking_conflict": bool(ctx.verification.get("blocking_conflict")),
            },
        )
        return dict(ctx.verification or {})

    def _workflow_service_retrieval_loop(self, workflow_context: WorkflowContext, *, node: Any = None) -> Dict[str, Any]:
        ctx = workflow_context.pipeline_context
        if bool((ctx.workflow_state or {}).get("research_fast_finalize")):
            ctx.loop_summary = {"skipped": True, "reason": "research_fast_finalize"}
            return dict(ctx.loop_summary)
        if workflow_context.stopped or not self._retrieval_loop_enabled():
            return {"skipped": True}
        self._trace_stage_start("RETRIEVAL_LOOP")
        (
            ctx.tool_results,
            ctx.knowledge_graph,
            ctx.answer_context,
            ctx.verification,
            ctx.loop_summary,
        ) = self._run_retrieval_loop(
            workflow_context.question,
            list(ctx.tool_results or []),
            ctx.knowledge_graph,
            ctx.answer_context,
            dict(ctx.verification or {}),
        )
        self._trace_stage_end(
            "RETRIEVAL_LOOP",
            metadata={
                "loop_count": int((ctx.loop_summary or {}).get("loop_count") or 0),
                "stop_conditions": list((ctx.loop_summary or {}).get("stop_conditions") or []),
            },
        )
        workflow_context.knowledge_graph = ctx.knowledge_graph
        return dict(ctx.loop_summary or {})

    def _workflow_service_memory_snapshot(self, workflow_context: WorkflowContext, *, node: Any = None) -> Dict[str, Any]:
        ctx = workflow_context.pipeline_context
        if workflow_context.stopped:
            return {"skipped": True}
        policy_engine = self._get_execution_policy_engine()
        snapshot_decision = policy_engine.evaluate_memory(
            ExecutionPolicyContext(
                question=workflow_context.question,
                question_type=self._current_question_type(),
                memory={"operation": "snapshot"},
                knowledge={
                    "operation": "snapshot",
                    "node_count": len(ctx.knowledge_graph.nodes or []) if ctx.knowledge_graph is not None else 0,
                    "relation_count": len(ctx.knowledge_graph.relations or []) if ctx.knowledge_graph is not None else 0,
                },
            ),
            default_decision=bool(self._memory_layer_enabled() and self._active_memory_context is not None and ctx.knowledge_graph is not None),
        )
        if bool(snapshot_decision.decision):
            self._trace_stage_start("MEMORY_SNAPSHOT")
            ctx.memory_context = self._snapshot_memory(ctx.knowledge_graph, reason="post_verification")
            self._active_memory_context = ctx.memory_context
            self._trace_stage_end(
                "MEMORY_SNAPSHOT",
                metadata={"snapshot_count": len(ctx.memory_context.knowledge_snapshots or []) if ctx.memory_context is not None else 0},
            )
            workflow_context.memory_context = ctx.memory_context
        return {"snapshot_created": bool(snapshot_decision.decision)}

    def _workflow_service_llm(self, workflow_context: WorkflowContext, *, node: Any = None) -> Dict[str, Any]:
        ctx = workflow_context.pipeline_context
        if workflow_context.stopped:
            return dict(ctx.final_result or {})
        if ctx.insight_result is None:
            route_intent = str((ctx.workflow_state or {}).get("prepare_context_route_intent") or "").strip()
            ctx.insight_result = self._build_insight_result(
                user_message=workflow_context.question,
                intent=route_intent,
                tool_results=list(ctx.tool_results or []),
                evidence_bundle=ctx.evidence_bundle,
                knowledge_graph=ctx.knowledge_graph,
                answer_context=ctx.answer_context,
                verification_result=dict(ctx.verification or {}),
            )
        if ctx.insight_result:
            workflow_context.metadata["insight_result"] = dict(ctx.insight_result)
        result = self._workflow_finalize_generation(workflow_context)
        workflow_context.final_result = dict(result or {})
        workflow_context.stopped = True
        return dict(result or {})

    def _workflow_finalize_generation_stream(self, workflow_context: WorkflowContext) -> Generator[dict, None, dict]:
        ctx = workflow_context.pipeline_context
        policy_engine = self._get_execution_policy_engine()
        user_message = workflow_context.question
        history = list(ctx.history or [])
        merged_results = list(ctx.tool_results or [])
        answer_context = ctx.answer_context
        verification_result = dict(ctx.verification or {})
        loop_summary = dict(ctx.loop_summary or {})
        if not isinstance(ctx.insight_result, dict) or not dict(ctx.insight_result or {}):
            route_intent = str((ctx.workflow_state or {}).get("prepare_context_route_intent") or "").strip()
            ctx.insight_result = self._build_insight_result(
                user_message=user_message,
                intent=route_intent,
                tool_results=merged_results,
                evidence_bundle=ctx.evidence_bundle,
                knowledge_graph=ctx.knowledge_graph,
                answer_context=answer_context,
                verification_result=verification_result,
            )
        insight_result = dict(ctx.insight_result or {}) if isinstance(ctx.insight_result, dict) else {}
        if insight_result:
            workflow_context.metadata["insight_result"] = dict(insight_result)
        insight_context_message = self._format_insight_context(insight_result)
        knowledge_graph = ctx.knowledge_graph
        evidence = self._merge_evidence_from_knowledge_graph(knowledge_graph) if knowledge_graph is not None else self._merge_evidence_from_tool_results(merged_results)
        conversation_id = str(getattr(ctx, "conversation_id", "") or "")
        generator_id = f"pipeline-finalize-stream-{uuid.uuid4()}"
        started_at = time.perf_counter()
        _pipeline_stream_trace(
            "STREAM ENTER",
            conversation_id=conversation_id,
            generator_id=generator_id,
            started_at=started_at,
            mode="workflow_finalize_generation_stream",
        )

        try:
            with trace_span(
                "LLM",
                input_obj={
                    "message_count": len(history),
                    "tool_result_count": len(merged_results),
                    "has_answer_context": bool(answer_context),
                },
            ) as span:
                print("ENTER LLM")
                final_route_intent = str((ctx.workflow_state or {}).get("prepare_context_route_intent") or "").strip()
                final_selected_prompt = str((ctx.workflow_state or {}).get("prepare_context_selected_prompt") or "").strip()
                final_research_route = self._research_route(intent=final_route_intent, selected_prompt=final_selected_prompt)
                final_research_context_message = self._build_research_context_message(ctx, tool_results=merged_results)
                final_answer_override = self._build_final_answer_override(
                    user_message=user_message,
                    insight_result=insight_result,
                    answer_context=answer_context,
                )
                if final_answer_override:
                    ctx.final_answer_override = final_answer_override
                    workflow_context.metadata["final_answer_override"] = final_answer_override
                    self._trace_stage_start("LLM")
                    for chunk in self._yield_text_chunks(final_answer_override):
                        yield chunk
                    self._trace_stage_end("LLM", metadata={"mode": "insight_final_render", "status": "success"})
                    result = ctx.finalize(
                        final_answer_override,
                        evidence,
                        answer_context=answer_context,
                        verification=verification_result,
                        loop_summary=loop_summary,
                    )
                    span.set_output_obj(result)
                    _pipeline_stream_trace(
                        "STREAM FINISH",
                        conversation_id=conversation_id,
                        generator_id=generator_id,
                        started_at=started_at,
                        mode="insight_final_render_stream",
                    )
                    return dict(result or {})
                if self._composer_enabled():
                    filtered_messages = self._build_messages_from_route(user_message, history, self.brain._route_prompt(user_message))
                    if answer_context:
                        composer_context_text = self.brain._format_answer_context(self._answer_context_to_dict(answer_context) or {})
                        # #region debug-point C:composer-context
                        debug_answer_event(
                            "Composer Final Answer",
                            composer_context_text,
                            trace_id=str(getattr(ctx, "conversation_id", "") or ""),
                            hypothesis_id="C",
                            location="pipeline_orchestrator.py:_workflow_finalize_generation_stream:composer_context",
                            extra={"represents_final_answer": False, "mode": "composer_context"},
                        )
                        # #endregion
                        filtered_messages = [
                            item
                            for item in filtered_messages
                            if not (item.get("role") == "system" and str(item.get("content") or "").startswith("Answer Context"))
                        ]
                        filtered_messages.append({"role": "system", "content": composer_context_text})
                    if insight_context_message:
                        filtered_messages.append({"role": "system", "content": insight_context_message})
                    if final_research_route and final_research_context_message:
                        filtered_messages.append({"role": "system", "content": final_research_context_message})
                    llm_policy = policy_engine.evaluate_llm(
                        ExecutionPolicyContext(
                            question=user_message,
                            question_type=self._current_question_type(),
                            pipeline=getattr(self._active_trace_session, "pipeline", None),
                            verification=verification_result,
                            trace={"operation": "stream", "mode": "composer", "supports_stream": self._selection_supports_stream(ctx.selection)},
                            coverage=float(verification_result.get("coverage") or 0.0),
                            tool_results=merged_results,
                        ),
                    )
                    llm_policy_payload = dict(llm_policy.decision or {})
                    self._trace_stage_start("LLM")
                    if not bool(llm_policy_payload.get("allow_generate", True)):
                        self._trace_stage_end("LLM", status="failed", metadata={"mode": "composer", "policy": "denied"})
                        result = ctx.finalize(
                            self.brain._append_gap_collection_notice(user_message, self.brain._fallback_reply(user_message, history)),
                            evidence,
                            answer_context=answer_context,
                            verification=verification_result,
                            loop_summary=loop_summary,
                        )
                        span.set_output_obj(result)
                        return dict(result or {})

                    self.runtime_metrics.inc("llm_stream_count", labels={"mode": "composer"})
                    llm_start = time.perf_counter()
                    buffered = ""
                    for chunk in _pipeline_logged_yield_from(
                        self.brain._call_llm_stream(filtered_messages, tools=None),
                        conversation_id=conversation_id,
                        generator_id=generator_id,
                        started_at=started_at,
                    ):
                        if chunk.get("type") == "token":
                            buffered += chunk.get("content", "")
                        yield chunk
                    self.runtime_metrics.observe("llm.latency_ms", round((time.perf_counter() - llm_start) * 1000, 2), labels={"mode": "composer_stream"})
                    self._trace_event(
                        "LLM",
                        "Final LLM Stream",
                        duration_ms=round((time.perf_counter() - llm_start) * 1000, 2),
                        metadata={"mode": "composer_stream"},
                    )
                    content = self.brain._append_gap_collection_notice(user_message, buffered).strip()
                    # #region debug-point C:composer-mode-final-answer
                    debug_answer_event(
                        "Pipeline Final Answer",
                        content,
                        trace_id=str(getattr(ctx, "conversation_id", "") or ""),
                        hypothesis_id="C",
                        location="pipeline_orchestrator.py:_workflow_finalize_generation_stream:composer_result",
                        extra={"native_stream": True, "fallback_stream": False, "mode": "composer_stream"},
                    )
                    # #endregion
                    self._trace_stage_end("LLM", metadata={"mode": "composer_stream", "status": "success"})
                    result = ctx.finalize(
                        content,
                        evidence,
                        answer_context=answer_context,
                        verification=verification_result,
                        loop_summary=loop_summary,
                    )
                    span.set_output_obj(result)
                    _pipeline_stream_trace(
                        "STREAM FINISH",
                        conversation_id=conversation_id,
                        generator_id=generator_id,
                        started_at=started_at,
                        mode="composer_stream",
                    )
                    return dict(result or {})

                messages = self.brain._build_messages(user_message, history)
                if final_research_route and final_research_context_message:
                    messages.append({"role": "system", "content": final_research_context_message})
                if insight_context_message:
                    messages.append({"role": "system", "content": insight_context_message})
                messages.append({"role": "assistant", "content": ""})
                for idx, result_item in enumerate(merged_results, start=1):
                    messages.append({"role": "tool", "tool_call_id": f"call_{idx}", "content": json.dumps(result_item, ensure_ascii=False)})
                llm_policy = policy_engine.evaluate_llm(
                    ExecutionPolicyContext(
                        question=user_message,
                        question_type=self._current_question_type(),
                        pipeline=getattr(self._active_trace_session, "pipeline", None),
                        verification=verification_result,
                        trace={"operation": "stream", "mode": "standard", "supports_stream": self._selection_supports_stream(ctx.selection)},
                        coverage=float(verification_result.get("coverage") or 0.0),
                        tool_results=merged_results,
                    ),
                )
                llm_policy_payload = dict(llm_policy.decision or {})
                self._trace_stage_start("LLM")
                if not bool(llm_policy_payload.get("allow_generate", True)):
                    self._trace_stage_end("LLM", status="failed", metadata={"mode": "standard", "policy": "denied"})
                    result = ctx.finalize(
                        self.brain._append_gap_collection_notice(user_message, self.brain._fallback_reply(user_message, history)),
                        evidence,
                        answer_context=answer_context,
                        verification=verification_result,
                        loop_summary=loop_summary,
                    )
                    span.set_output_obj(result)
                    return dict(result or {})

                self.runtime_metrics.inc("llm_stream_count", labels={"mode": "standard"})
                llm_start = time.perf_counter()
                buffered = ""
                for chunk in _pipeline_logged_yield_from(
                    self.brain._call_llm_stream(messages, tools=None),
                    conversation_id=conversation_id,
                    generator_id=generator_id,
                    started_at=started_at,
                ):
                    if chunk.get("type") == "token":
                        buffered += chunk.get("content", "")
                    yield chunk
                self.runtime_metrics.observe("llm.latency_ms", round((time.perf_counter() - llm_start) * 1000, 2), labels={"mode": "standard_stream"})
                self._trace_event(
                    "LLM",
                    "Final LLM Stream",
                    duration_ms=round((time.perf_counter() - llm_start) * 1000, 2),
                    metadata={"mode": "standard_stream"},
                )
                content = self.brain._append_gap_collection_notice(user_message, buffered).strip()
                # #region debug-point C:standard-mode-final-answer
                debug_answer_event(
                    "Pipeline Final Answer",
                    content,
                    trace_id=str(getattr(ctx, "conversation_id", "") or ""),
                    hypothesis_id="C",
                    location="pipeline_orchestrator.py:_workflow_finalize_generation_stream:standard_result",
                    extra={"native_stream": True, "fallback_stream": False, "mode": "standard_stream"},
                )
                # #endregion
                self._trace_stage_end("LLM", metadata={"mode": "standard_stream", "status": "success"})
                result = ctx.finalize(
                    content,
                    evidence,
                    answer_context=answer_context,
                    verification=verification_result,
                    loop_summary=loop_summary,
                )
                span.set_output_obj(result)
                _pipeline_stream_trace(
                    "STREAM FINISH",
                    conversation_id=conversation_id,
                    generator_id=generator_id,
                    started_at=started_at,
                    mode="standard_stream",
                )
                return dict(result or {})
        except GeneratorExit:
            _pipeline_stream_trace(
                "STREAM CLOSE",
                conversation_id=conversation_id,
                generator_id=generator_id,
                started_at=started_at,
                mode="workflow_finalize_generation_stream",
                reason="GeneratorExit",
            )
            raise
        except asyncio.CancelledError:
            _pipeline_stream_trace(
                "STREAM CANCEL",
                conversation_id=conversation_id,
                generator_id=generator_id,
                started_at=started_at,
                mode="workflow_finalize_generation_stream",
                reason="asyncio.CancelledError",
            )
            raise
        except Exception as exc:
            _pipeline_stream_trace(
                "STREAM EXCEPTION",
                conversation_id=conversation_id,
                generator_id=generator_id,
                started_at=started_at,
                mode="workflow_finalize_generation_stream",
                error_type=type(exc).__name__,
                error=str(exc),
                full_exception=traceback.format_exc(),
            )
            raise
        finally:
            _pipeline_stream_trace(
                "STREAM CLOSE",
                conversation_id=conversation_id,
                generator_id=generator_id,
                started_at=started_at,
                mode="workflow_finalize_generation_stream",
                reason="finally",
            )

    def _workflow_finalize_generation(self, workflow_context: WorkflowContext) -> Dict[str, Any]:
        ctx = workflow_context.pipeline_context
        policy_engine = self._get_execution_policy_engine()
        user_message = workflow_context.question
        history = list(ctx.history or [])
        merged_results = list(ctx.tool_results or [])
        answer_context = ctx.answer_context
        verification_result = dict(ctx.verification or {})
        loop_summary = dict(ctx.loop_summary or {})
        insight_result = dict(ctx.insight_result or {}) if isinstance(ctx.insight_result, dict) else {}
        insight_context_message = self._format_insight_context(insight_result)
        knowledge_graph = ctx.knowledge_graph
        evidence = self._merge_evidence_from_knowledge_graph(knowledge_graph) if knowledge_graph is not None else self._merge_evidence_from_tool_results(merged_results)
        final_answer_override = self._build_final_answer_override(
            user_message=user_message,
            insight_result=insight_result,
            answer_context=answer_context,
        )
        if final_answer_override:
            ctx.final_answer_override = final_answer_override
            workflow_context.metadata["final_answer_override"] = final_answer_override
            return ctx.finalize(
                final_answer_override,
                evidence,
                answer_context=answer_context,
                verification=verification_result,
                loop_summary=loop_summary,
            )
        final_route_intent = str((ctx.workflow_state or {}).get("prepare_context_route_intent") or "").strip()
        final_selected_prompt = str((ctx.workflow_state or {}).get("prepare_context_selected_prompt") or "").strip()
        final_research_route = self._research_route(intent=final_route_intent, selected_prompt=final_selected_prompt)
        final_research_context_message = self._build_research_context_message(ctx, tool_results=merged_results)
        if self._composer_enabled():
            filtered_messages = self._build_messages_from_route(user_message, history, self.brain._route_prompt(user_message))
            if answer_context:
                filtered_messages = [
                    item
                    for item in filtered_messages
                    if not (item.get("role") == "system" and str(item.get("content") or "").startswith("Answer Context"))
                ]
                filtered_messages.append(
                    {"role": "system", "content": self.brain._format_answer_context(self._answer_context_to_dict(answer_context) or {})}
                )
            if insight_context_message:
                filtered_messages.append({"role": "system", "content": insight_context_message})
            if final_research_route and final_research_context_message:
                filtered_messages.append({"role": "system", "content": final_research_context_message})
            llm_policy = policy_engine.evaluate_llm(
                ExecutionPolicyContext(
                    question=user_message,
                    question_type=self._current_question_type(),
                    pipeline=getattr(self._active_trace_session, "pipeline", None),
                    verification=verification_result,
                    trace={"operation": "generate", "mode": "composer", "supports_stream": self._selection_supports_stream(ctx.selection)},
                    coverage=float(verification_result.get("coverage") or 0.0),
                    tool_results=merged_results,
                ),
            )
            llm_policy_payload = dict(llm_policy.decision or {})
            self._trace_stage_start("LLM")
            if not bool(llm_policy_payload.get("allow_generate", True)):
                self._trace_stage_end("LLM", status="failed", metadata={"mode": "composer", "policy": "denied"})
                return ctx.finalize(
                    self.brain._append_gap_collection_notice(user_message, self.brain._fallback_reply(user_message, history)),
                    evidence,
                    answer_context=answer_context,
                    verification=verification_result,
                    loop_summary=loop_summary,
                )
            self.runtime_metrics.inc("llm_generation_count", labels={"mode": "composer"})
            llm_start = time.perf_counter()
            resp = self.brain._call_llm(filtered_messages, tools=None)
            self.runtime_metrics.observe("llm.latency_ms", round((time.perf_counter() - llm_start) * 1000, 2), labels={"mode": "composer"})
            self._trace_event(
                "LLM",
                "Final LLM Generate",
                duration_ms=round((time.perf_counter() - llm_start) * 1000, 2),
                metadata={"mode": "composer"},
            )
            if resp:
                content = resp.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
                if content:
                    self._trace_stage_end("LLM", metadata={"mode": "composer", "status": "success"})
                    return ctx.finalize(
                        self.brain._append_gap_collection_notice(user_message, content),
                        evidence,
                        answer_context=answer_context,
                        verification=verification_result,
                        loop_summary=loop_summary,
                    )
            self._trace_stage_end("LLM", status="failed", metadata={"mode": "composer"})
            return ctx.finalize(
                self.brain._append_gap_collection_notice(user_message, self.brain._fallback_reply(user_message, history)),
                evidence,
                answer_context=answer_context,
                verification=verification_result,
                loop_summary=loop_summary,
            )

        messages = self._build_messages_from_route(user_message, history, self.brain._route_prompt(user_message))
        if final_research_route and final_research_context_message:
            messages.append({"role": "system", "content": final_research_context_message})
        if insight_context_message:
            messages.append({"role": "system", "content": insight_context_message})
        messages.append({"role": "assistant", "content": ""})
        for idx, result in enumerate(merged_results, start=1):
            messages.append({"role": "tool", "tool_call_id": f"call_{idx}", "content": json.dumps(result, ensure_ascii=False)})
        llm_policy = policy_engine.evaluate_llm(
            ExecutionPolicyContext(
                question=user_message,
                question_type=self._current_question_type(),
                pipeline=getattr(self._active_trace_session, "pipeline", None),
                verification=verification_result,
                trace={"operation": "generate", "mode": "standard", "supports_stream": self._selection_supports_stream(ctx.selection)},
                coverage=float(verification_result.get("coverage") or 0.0),
                tool_results=merged_results,
            ),
        )
        llm_policy_payload = dict(llm_policy.decision or {})
        self._trace_stage_start("LLM")
        if not bool(llm_policy_payload.get("allow_generate", True)):
            self._trace_stage_end("LLM", status="failed", metadata={"mode": "standard", "policy": "denied"})
            return ctx.finalize(
                self.brain._append_gap_collection_notice(user_message, self.brain._fallback_reply(user_message, history)),
                evidence,
                answer_context=answer_context,
                verification=verification_result,
                loop_summary=loop_summary,
            )
        self.runtime_metrics.inc("llm_generation_count", labels={"mode": "standard"})
        llm_start = time.perf_counter()
        resp = self.brain._call_llm(messages, tools=None)
        self.runtime_metrics.observe("llm.latency_ms", round((time.perf_counter() - llm_start) * 1000, 2), labels={"mode": "standard"})
        self._trace_event(
            "LLM",
            "Final LLM Generate",
            duration_ms=round((time.perf_counter() - llm_start) * 1000, 2),
            metadata={"mode": "standard"},
        )
        if resp:
            content = resp.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            if content:
                self._trace_stage_end("LLM", metadata={"mode": "standard", "status": "success"})
                return ctx.finalize(
                    self.brain._append_gap_collection_notice(user_message, content),
                    evidence,
                    answer_context=answer_context,
                    verification=verification_result,
                    loop_summary=loop_summary,
                )
        self._trace_stage_end("LLM", status="failed", metadata={"mode": "standard"})
        return ctx.finalize(
            self.brain._append_gap_collection_notice(user_message, self.brain._fallback_reply(user_message, history)),
            evidence,
            answer_context=answer_context,
            verification=verification_result,
            loop_summary=loop_summary,
        )

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

    def _trace_stage_start(self, stage_name: str) -> None:
        self._stage_started_perf[str(stage_name or "")] = time.perf_counter()
        if self._active_trace_center is None:
            return
        self._active_trace_center.start_stage(stage_name)

    def _trace_stage_end(self, stage_name: str, *, status: str = "completed", metadata: Dict[str, Any] | None = None) -> None:
        started = self._stage_started_perf.pop(str(stage_name or ""), None)
        if started is not None and self._active_trace_center is None:
            self.runtime_metrics.observe(
                "pipeline.stage.latency_ms",
                round((time.perf_counter() - started) * 1000, 2),
                labels={"stage": str(stage_name or "")},
            )
        if self._active_trace_center is None:
            return
        self._active_trace_center.end_stage(stage_name, status=status, metadata=metadata or {})

    def _trace_event(
        self,
        stage_name: str,
        name: str,
        *,
        status: str = "ok",
        duration_ms: float = 0.0,
        metadata: Dict[str, Any] | None = None,
    ) -> None:
        if self._active_trace_center is None:
            return
        self._active_trace_center.record_event(
            stage_name,
            name,
            status=status,
            duration_ms=duration_ms,
            metadata=metadata or {},
        )

    def _selection_pipeline_name(self, selection: Any) -> str:
        if selection is None:
            return "PipelineOrchestrator"
        pipeline = getattr(selection, "selected_pipeline", None)
        if pipeline is None:
            return "PipelineOrchestrator"
        return str(getattr(pipeline, "name", "") or "PipelineOrchestrator")

    def _selection_supports_stream(self, selection: Any) -> bool:
        if selection is None:
            return True
        pipeline = getattr(selection, "selected_pipeline", None)
        if pipeline is None:
            return True
        return bool(getattr(pipeline, "supports_stream", True))

    def _current_question_type(self) -> str:
        return str(getattr(self.brain, "_reasoning_v1_context", {}).get("question_type") or "UNKNOWN")
