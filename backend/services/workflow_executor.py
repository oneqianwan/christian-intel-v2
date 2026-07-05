from __future__ import annotations

import asyncio
import json
import threading
import time
import traceback
import uuid
from typing import Any, Dict, List

from services.adaptive_planner import AdaptivePlanner
from services.task_graph import PlanningContext, TaskGraph, TaskNode
from services.task_planner import TaskPlanner
from services.runtime_metrics import get_runtime_metrics
from services.trace_center import trace_span
from services.workflow_engine import WorkflowContext, WorkflowDefinition, WorkflowNode


def _workflow_stream_trace(event: str, *, conversation_id: str, generator_id: str, started_at: float, **payload: Any) -> None:
    print(
        "WORKFLOW_STREAM_TRACE "
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


def _workflow_logged_yield_from(iterator, *, conversation_id: str, generator_id: str, started_at: float):
    token_count = 0
    last_token = ""
    try:
        while True:
            try:
                chunk = next(iterator)
            except StopIteration as stop:
                if token_count > 0:
                    _workflow_stream_trace(
                        "STREAM LAST TOKEN",
                        conversation_id=conversation_id,
                        generator_id=generator_id,
                        started_at=started_at,
                        token_count=token_count,
                        last_token_length=len(last_token),
                    )
                _workflow_stream_trace(
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
                    _workflow_stream_trace(
                        "STREAM FIRST TOKEN",
                        conversation_id=conversation_id,
                        generator_id=generator_id,
                        started_at=started_at,
                        token_length=len(token),
                    )
                _workflow_stream_trace(
                    "STREAM TOKEN",
                    conversation_id=conversation_id,
                    generator_id=generator_id,
                    started_at=started_at,
                    token_index=token_count,
                    token_length=len(token),
                )
            yield chunk
    except GeneratorExit:
        _workflow_who_close_stream("backend/services/workflow_executor.py", "_workflow_logged_yield_from")
        _workflow_stream_trace(
            "STREAM CLOSE",
            conversation_id=conversation_id,
            generator_id=generator_id,
            started_at=started_at,
            token_count=token_count,
            reason="GeneratorExit",
        )
        raise
    except asyncio.CancelledError:
        _workflow_who_close_stream("backend/services/workflow_executor.py", "_workflow_logged_yield_from")
        _workflow_stream_trace(
            "STREAM CANCEL",
            conversation_id=conversation_id,
            generator_id=generator_id,
            started_at=started_at,
            token_count=token_count,
            reason="asyncio.CancelledError",
        )
        raise
    except Exception as exc:
        _workflow_stream_trace(
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


def _workflow_stop_trace(
    event: str,
    *,
    conversation_id: str,
    generator_id: str,
    started_at: float,
    node: str,
    stopped: bool,
    finished: bool,
    next_node: str = "",
    set_stopped: str = "",
    stop_reason: str = "",
    final_node: bool = False,
    queue_snapshot: list[str] | None = None,
    call_stack: str = "",
) -> None:
    _workflow_stream_trace(
        event,
        conversation_id=conversation_id,
        generator_id=generator_id,
        started_at=started_at,
        NODE=node,
        CURRENT_NODE=node,
        SET_STOPPED=set_stopped,
        STOP_REASON=stop_reason,
        NEXT_NODE=next_node,
        STOPPED=stopped,
        FINISHED=finished,
        final_node=final_node,
        queue_snapshot=list(queue_snapshot or []),
        call_stack=call_stack,
    )


def _workflow_who_close_stream(file_name: str, function_name: str) -> None:
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


def _workflow_finished_flag(*payloads: Any) -> bool:
    for payload in payloads:
        if isinstance(payload, dict) and bool(payload.get("finished")):
            return True
    return False


class WorkflowExecutor:
    def __init__(self, *, trace_center: Any = None, runtime_metrics: Any = None):
        self.trace_center = trace_center
        self.runtime_metrics = runtime_metrics or get_runtime_metrics()
        self.task_planner = TaskPlanner(trace_center=trace_center, runtime_metrics=self.runtime_metrics)
        self.adaptive_planner = AdaptivePlanner(
            task_planner=self.task_planner,
            trace_center=trace_center,
            runtime_metrics=self.runtime_metrics,
        )

    def execute(self, workflow: WorkflowDefinition, context: WorkflowContext) -> Dict[str, Any]:
        with trace_span("Workflow", input_obj={"workflow": workflow.name, "version": workflow.version}) as span:
            context.workflow_definition = workflow
            context.runtime_metrics = context.runtime_metrics or self.runtime_metrics
            self.runtime_metrics.inc("workflow_count", labels={"workflow": workflow.name})
            task_graph = self._task_graph_payload(context)
            if task_graph:
                self._trace(
                    context,
                    "Task Graph Built",
                    metadata={
                        "graph_id": str(task_graph.get("graph_id") or ""),
                        "task_count": len(task_graph.get("tasks") or []),
                    },
                )
            self._trace(context, "Workflow Started", metadata={"workflow": workflow.name, "version": workflow.version})

            nodes = {node.id: node for node in (workflow.nodes or [])}
            outgoing = self._build_outgoing_edges(workflow)
            queue: List[str] = list(workflow.entry_nodes or [])
            if not queue:
                ordered = self.build_execution_order(workflow)
                queue = list(ordered[:1])
            completed: set[str] = set()
            failed = False

            while queue:
                node_id = queue.pop(0)
                node = nodes.get(node_id)
                if node is None or not node.enabled:
                    continue
                if not self._node_required_by_task_graph(node, context):
                    service = str(node.service or "").strip().lower()
                    name_map = {
                        "prepare_context": "PrepareContext",
                        "retrieval": "Retrieval",
                        "knowledge": "Knowledge",
                        "verification": "Verification",
                        "memory_update": "Memory",
                        "memory_snapshot": "Memory",
                        "retrieval_loop": "RetrievalLoop",
                        "answer_composer": "Composer",
                        "llm": "LLM",
                    }
                    label = name_map.get(service, str(node.service or node.id or "Service"))
                    with trace_span(label, input_obj=getattr(context, "pipeline_context", None)) as span:
                        span.set_output_obj({"skipped_by_task_graph": True})
                    completed.add(node_id)
                    context.node_results[node.id] = {"skipped_by_task_graph": True}
                    context.node_sequence.append(node.id)
                    context.node_status[node.id] = "skipped"
                    for edge in outgoing.get(node.id, []):
                        if self.check_condition(edge.get("condition") or "", context, {"skipped_by_task_graph": True}):
                            queue.append(edge["target"])
                    continue
                if node.node_type != "LOOP" and node_id in completed:
                    continue
                if not self._dependencies_met(node, context):
                    queue.append(node_id)
                    continue
                result = self.execute_node(node, context)
                context.node_results[node.id] = result
                context.node_sequence.append(node.id)
                context.node_status[node.id] = "failed" if context.failed else "completed"
                self._mark_task_progress(node, context)
                completed.add(node.id)
                if context.failed:
                    failed = True
                    break
                revision_applied = self._maybe_apply_revision(node, context, result, queue, completed)
                if revision_applied:
                    continue
                if context.stopped and node.node_type != "END":
                    break
                for edge in outgoing.get(node.id, []):
                    if self.check_condition(edge.get("condition") or "", context, result):
                        queue.append(edge["target"])

            if failed:
                self.runtime_metrics.inc("workflow_failure", labels={"workflow": workflow.name})
                self._trace(context, "Workflow Failed", metadata={"workflow": workflow.name, "errors": list(context.errors or [])})
            else:
                self.runtime_metrics.inc("workflow_success", labels={"workflow": workflow.name})
                self._trace(context, "Workflow Finished", metadata={"workflow": workflow.name, "stopped": bool(context.stopped)})
            result = dict(context.final_result or {})
            span.set_output_obj(result)
            return result

    def execute_stream(self, workflow: WorkflowDefinition, context: WorkflowContext):
        conversation_id = str(getattr(getattr(context, "pipeline_context", None), "conversation_id", "") or "")
        generator_id = f"workflow-execute-stream-{uuid.uuid4()}"
        started_at = time.perf_counter()
        _workflow_stream_trace(
            "STREAM ENTER",
            conversation_id=conversation_id,
            generator_id=generator_id,
            started_at=started_at,
            workflow=getattr(workflow, "name", ""),
        )
        try:
            with trace_span("Workflow", input_obj={"workflow": workflow.name, "version": workflow.version}) as span:
                context.workflow_definition = workflow
                context.runtime_metrics = context.runtime_metrics or self.runtime_metrics
                self.runtime_metrics.inc("workflow_count", labels={"workflow": workflow.name})
                task_graph = self._task_graph_payload(context)
                if task_graph:
                    self._trace(
                        context,
                        "Task Graph Built",
                        metadata={
                            "graph_id": str(task_graph.get("graph_id") or ""),
                            "task_count": len(task_graph.get("tasks") or []),
                        },
                    )
                self._trace(context, "Workflow Started", metadata={"workflow": workflow.name, "version": workflow.version})

                nodes = {node.id: node for node in (workflow.nodes or [])}
                outgoing = self._build_outgoing_edges(workflow)
                queue: List[str] = list(workflow.entry_nodes or [])
                if not queue:
                    ordered = self.build_execution_order(workflow)
                    queue = list(ordered[:1])
                completed: set[str] = set()
                failed = False

                while queue:
                    node_id = queue.pop(0)
                    node = nodes.get(node_id)
                    if node is None or not node.enabled:
                        continue
                    if not self._node_required_by_task_graph(node, context):
                        service = str(node.service or "").strip().lower()
                        name_map = {
                            "prepare_context": "PrepareContext",
                            "retrieval": "Retrieval",
                            "knowledge": "Knowledge",
                            "verification": "Verification",
                            "memory_update": "Memory",
                            "memory_snapshot": "Memory",
                            "retrieval_loop": "RetrievalLoop",
                            "answer_composer": "Composer",
                            "llm": "LLM",
                        }
                        label = name_map.get(service, str(node.service or node.id or "Service"))
                        with trace_span(label, input_obj=getattr(context, "pipeline_context", None)) as span:
                            span.set_output_obj({"skipped_by_task_graph": True})
                        completed.add(node_id)
                        context.node_results[node.id] = {"skipped_by_task_graph": True}
                        context.node_sequence.append(node.id)
                        context.node_status[node.id] = "skipped"
                        for edge in outgoing.get(node.id, []):
                            if self.check_condition(edge.get("condition") or "", context, {"skipped_by_task_graph": True}):
                                queue.append(edge["target"])
                        continue
                    if node.node_type != "LOOP" and node_id in completed:
                        continue
                    if not self._dependencies_met(node, context):
                        queue.append(node_id)
                        continue

                    next_candidates = [edge["target"] for edge in outgoing.get(node.id, [])]
                    stopped_before = bool(getattr(context, "stopped", False))
                    finished_before = bool((context.final_result or {}).get("finished")) if isinstance(context.final_result, dict) else False
                    _workflow_stop_trace(
                        "WORKFLOW_NODE_ENTER",
                        conversation_id=conversation_id,
                        generator_id=generator_id,
                        started_at=started_at,
                        node=node.id,
                        stopped=stopped_before,
                        finished=finished_before,
                        next_node=",".join(next_candidates),
                        final_node=(node.node_type == "END"),
                        queue_snapshot=list(queue),
                    )

                    if str(node.service or "").strip().lower() == "llm":
                        orchestrator = getattr(getattr(context, "pipeline_context", None), "orchestrator", None)
                        if orchestrator is not None and hasattr(orchestrator, "_workflow_finalize_generation_stream"):
                            print("ENTER_LLM_NODE")
                            print("LLM_NODE_ENTER")
                            llm_iterator = _workflow_logged_yield_from(
                                orchestrator._workflow_finalize_generation_stream(context),
                                conversation_id=conversation_id,
                                generator_id=generator_id,
                                started_at=started_at,
                            )
                            llm_first = True
                            try:
                                while True:
                                    try:
                                        chunk = next(llm_iterator)
                                    except StopIteration as stop:
                                        result = stop.value
                                        print("LLM_STREAM_FINISHED")
                                        break
                                    if llm_first:
                                        print("LLM_FIRST_TOKEN")
                                        llm_first = False
                                    yield chunk
                            except asyncio.CancelledError:
                                print("LLM_CANCELLED")
                                _workflow_who_close_stream("backend/services/workflow_executor.py", "execute_stream.llm")
                                raise
                            except GeneratorExit:
                                print("LLM_GENERATOR_EXIT")
                                _workflow_who_close_stream("backend/services/workflow_executor.py", "execute_stream.llm")
                                raise
                            except Exception as e:
                                print("LLM_STREAM_EXCEPTION", repr(e))
                                _workflow_who_close_stream("backend/services/workflow_executor.py", "execute_stream.llm")
                                raise
                            finally:
                                print("LLM_STREAM_FINALLY")
                            context.final_result = dict(result or {})
                            context.stopped = True
                            _workflow_stop_trace(
                                "WORKFLOW_STOP_SET",
                                conversation_id=conversation_id,
                                generator_id=generator_id,
                                started_at=started_at,
                                node=node.id,
                                stopped=bool(getattr(context, "stopped", False)),
                                finished=bool((context.final_result or {}).get("finished")) if isinstance(context.final_result, dict) else False,
                                next_node=",".join(next_candidates),
                                set_stopped="workflow_executor.py:execute_stream:llm_done",
                                stop_reason="llm_stream_completed",
                                final_node=(node.node_type == "END"),
                                queue_snapshot=list(queue),
                                call_stack="".join(traceback.format_stack(limit=12)),
                            )
                            context.node_results[node.id] = dict(result or {})
                            context.node_sequence.append(node.id)
                            context.node_status[node.id] = "failed" if context.failed else "completed"
                            self._mark_task_progress(node, context)
                            completed.add(node.id)
                            answer = str((result or {}).get("answer") or "").strip()
                            evidence = (result or {}).get("evidence") or []
                            yield {"type": "done", "full_content": answer, "evidence": evidence}
                            break

                    result = self.execute_node(node, context)
                    stopped_after_execute = bool(getattr(context, "stopped", False))
                    finished_after_execute = bool((context.final_result or {}).get("finished")) if isinstance(context.final_result, dict) else False
                    if stopped_after_execute and not stopped_before:
                        _workflow_stop_trace(
                            "WORKFLOW_STOP_SET",
                            conversation_id=conversation_id,
                            generator_id=generator_id,
                            started_at=started_at,
                            node=node.id,
                            stopped=stopped_after_execute,
                            finished=finished_after_execute,
                            next_node=",".join(next_candidates),
                            set_stopped="execute_node_return",
                            stop_reason=f"node_result_type={type(result).__name__}",
                            final_node=(node.node_type == "END"),
                            queue_snapshot=list(queue),
                            call_stack="".join(traceback.format_stack(limit=12)),
                        )
                    context.node_results[node.id] = result
                    context.node_sequence.append(node.id)
                    context.node_status[node.id] = "failed" if context.failed else "completed"
                    self._mark_task_progress(node, context)
                    completed.add(node.id)
                    if context.failed:
                        _workflow_stop_trace(
                            "WORKFLOW_BREAK",
                            conversation_id=conversation_id,
                            generator_id=generator_id,
                            started_at=started_at,
                            node=node.id,
                            stopped=bool(getattr(context, "stopped", False)),
                            finished=bool((context.final_result or {}).get("finished")) if isinstance(context.final_result, dict) else False,
                            next_node=",".join(next_candidates),
                            stop_reason="context.failed",
                            final_node=(node.node_type == "END"),
                            queue_snapshot=list(queue),
                        )
                        failed = True
                        break
                    revision_applied = self._maybe_apply_revision(node, context, result, queue, completed)
                    if revision_applied:
                        _workflow_stop_trace(
                            "WORKFLOW_CONTINUE",
                            conversation_id=conversation_id,
                            generator_id=generator_id,
                            started_at=started_at,
                            node=node.id,
                            stopped=bool(getattr(context, "stopped", False)),
                            finished=bool((context.final_result or {}).get("finished")) if isinstance(context.final_result, dict) else False,
                            next_node=",".join(list(queue)),
                            stop_reason="revision_applied",
                            final_node=(node.node_type == "END"),
                            queue_snapshot=list(queue),
                        )
                        continue
                    for edge in outgoing.get(node.id, []):
                        if self.check_condition(edge.get("condition") or "", context, result):
                            queue.append(edge["target"])
                    final_node = node.node_type == "END"
                    finished_now = _workflow_finished_flag(result, context.final_result)
                    workflow_last_node = not bool(queue)
                    allow_stop = final_node or finished_now or workflow_last_node
                    if context.stopped:
                        if allow_stop:
                            _workflow_stop_trace(
                                "WORKFLOW_BREAK",
                                conversation_id=conversation_id,
                                generator_id=generator_id,
                                started_at=started_at,
                                node=node.id,
                                stopped=bool(getattr(context, "stopped", False)),
                                finished=finished_now,
                                next_node=",".join(list(queue)),
                                stop_reason="allowed_stopped_exit",
                                final_node=final_node,
                                queue_snapshot=list(queue),
                            )
                            break
                        _workflow_stop_trace(
                            "WORKFLOW_CONTINUE",
                            conversation_id=conversation_id,
                            generator_id=generator_id,
                            started_at=started_at,
                            node=node.id,
                            stopped=bool(getattr(context, "stopped", False)),
                            finished=finished_now,
                            next_node=",".join(list(queue)),
                            stop_reason="stopped_ignored_before_workflow_finish",
                            final_node=final_node,
                            queue_snapshot=list(queue),
                        )
                    _workflow_stop_trace(
                        "WORKFLOW_CONTINUE",
                        conversation_id=conversation_id,
                        generator_id=generator_id,
                        started_at=started_at,
                        node=node.id,
                        stopped=bool(getattr(context, "stopped", False)),
                        finished=finished_now,
                        next_node=",".join(list(queue)),
                        stop_reason="advance_to_next_node",
                        final_node=final_node,
                        queue_snapshot=list(queue),
                    )

                if failed:
                    self.runtime_metrics.inc("workflow_failure", labels={"workflow": workflow.name})
                    self._trace(context, "Workflow Failed", metadata={"workflow": workflow.name, "errors": list(context.errors or [])})
                else:
                    self.runtime_metrics.inc("workflow_success", labels={"workflow": workflow.name})
                    self._trace(context, "Workflow Finished", metadata={"workflow": workflow.name, "stopped": bool(context.stopped)})
                span.set_output_obj(dict(context.final_result or {}))
                _workflow_stream_trace(
                    "STREAM FINISH",
                    conversation_id=conversation_id,
                    generator_id=generator_id,
                    started_at=started_at,
                    workflow=getattr(workflow, "name", ""),
                    stopped=bool(context.stopped),
                )
        except GeneratorExit:
            _workflow_who_close_stream("backend/services/workflow_executor.py", "execute_stream")
            _workflow_stream_trace(
                "STREAM CLOSE",
                conversation_id=conversation_id,
                generator_id=generator_id,
                started_at=started_at,
                workflow=getattr(workflow, "name", ""),
                reason="GeneratorExit",
            )
            raise
        except asyncio.CancelledError:
            _workflow_who_close_stream("backend/services/workflow_executor.py", "execute_stream")
            _workflow_stream_trace(
                "STREAM CANCEL",
                conversation_id=conversation_id,
                generator_id=generator_id,
                started_at=started_at,
                workflow=getattr(workflow, "name", ""),
            )
            raise
        except Exception as exc:
            _workflow_stream_trace(
                "STREAM EXCEPTION",
                conversation_id=conversation_id,
                generator_id=generator_id,
                started_at=started_at,
                workflow=getattr(workflow, "name", ""),
                error_type=type(exc).__name__,
                error=str(exc),
                full_exception=traceback.format_exc(),
            )
            raise
        finally:
            _workflow_stream_trace(
                "STREAM CLOSE",
                conversation_id=conversation_id,
                generator_id=generator_id,
                started_at=started_at,
                workflow=getattr(workflow, "name", ""),
                reason="finally",
            )

    def execute_node(self, node: WorkflowNode, context: WorkflowContext) -> Any:
        started = time.perf_counter()
        print(f"EXECUTE_NODE_ENTER {node.id}")
        self._trace(context, "Workflow Node Started", metadata={"node_id": node.id, "node_type": node.node_type, "service": node.service})
        try:
            if node.node_type == "START":
                result: Any = {"started": True}
            elif node.node_type == "END":
                result = {"ended": True}
            elif node.node_type == "JOIN":
                result = {"joined": True}
            elif node.node_type == "CONDITION":
                result = self.check_condition(node.condition, context)
                self.runtime_metrics.inc("workflow_condition_count", labels={"workflow": self._workflow_name(context), "condition": node.condition or "unknown"})
                self._trace(context, "Workflow Condition", metadata={"node_id": node.id, "condition": node.condition, "result": bool(result)})
            elif node.node_type == "PARALLEL":
                result = self.execute_parallel(node, context)
            else:
                service = str(node.service or "").strip().lower()
                name_map = {
                    "prepare_context": "PrepareContext",
                    "retrieval": "Retrieval",
                    "knowledge": "Knowledge",
                    "verification": "Verification",
                    "memory_update": "Memory",
                    "memory_snapshot": "Memory",
                    "retrieval_loop": "RetrievalLoop",
                    "answer_composer": "Composer",
                    "llm": "LLM",
                }
                label = name_map.get(service, str(node.service or node.id or "Service"))
                with trace_span(label, input_obj=getattr(context, "pipeline_context", None)) as span:
                    result = self.retry_node(node, context)
                    if service == "retrieval":
                        retrieval_value = result if isinstance(result, dict) else {"raw": result}
                        print("RETRIEVAL_NODE_RETURN")
                        print(f"keys={list(retrieval_value.keys())}")
                        print(f"value={retrieval_value}")
                    span.set_output_obj(result)
            return result
        except Exception as exc:
            context.failed = True
            context.errors.append(f"{node.id}:{exc}")
            self._trace(context, "Workflow Failed", metadata={"node_id": node.id, "error": str(exc)})
            return {"error": str(exc)}
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            self.runtime_metrics.observe("workflow_node_latency", duration_ms, labels={"workflow": self._workflow_name(context), "node_id": node.id})
            self._trace(
                context,
                "Workflow Node Finished",
                metadata={"node_id": node.id, "duration_ms": duration_ms, "failed": bool(context.failed)},
            )

    def execute_parallel(self, node: WorkflowNode, context: WorkflowContext) -> Dict[str, Any]:
        self.runtime_metrics.inc("workflow_parallel_count", labels={"workflow": self._workflow_name(context), "node_id": node.id})
        self._trace(context, "Workflow Parallel Begin", metadata={"node_id": node.id, "parallel_group": node.parallel_group})
        result = {"parallel_group": node.parallel_group or node.id, "executed": True}
        self._trace(context, "Workflow Parallel End", metadata=result)
        return result

    def retry_node(self, node: WorkflowNode, context: WorkflowContext) -> Any:
        attempts = max(0, int(node.retry or 0)) + 1
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                print(f"RETRY_NODE_ENTER {node.id} attempt={attempt}")
                return self._call_service(node, context)
            except Exception as exc:
                last_error = exc
                if attempt < attempts:
                    self.runtime_metrics.inc("workflow_retry_count", labels={"workflow": self._workflow_name(context), "node_id": node.id})
                    self._trace(context, "Workflow Retry", metadata={"node_id": node.id, "attempt": attempt, "error": str(exc)})
        if last_error is not None:
            raise last_error
        return {}

    def check_condition(self, condition: str, context: WorkflowContext, node_result: Any = None) -> bool:
        normalized = str(condition or "").strip().lower()
        if normalized in {"", "always"}:
            return True
        if normalized == "true":
            return bool(node_result if node_result is not None else context.node_results.get("loop_condition"))
        if normalized == "false":
            return not bool(node_result if node_result is not None else context.node_results.get("loop_condition"))

        verification = dict(getattr(context.pipeline_context, "verification", {}) or {})
        knowledge_graph = getattr(context.pipeline_context, "knowledge_graph", None)
        tool_results = list(getattr(context.pipeline_context, "tool_results", []) or [])
        memory_context = getattr(context.pipeline_context, "memory_context", None)
        metadata = dict(context.metadata or {})

        if normalized == "verification pass":
            return bool(verification.get("answer_ready")) and bool(verification.get("evidence_enough"))
        if normalized == "knowledge empty":
            if knowledge_graph is None:
                return True
            return not bool(getattr(knowledge_graph, "nodes", []) or getattr(knowledge_graph, "relations", []))
        if normalized == "need retrieval":
            return not bool(tool_results) and not bool(context.final_result)
        if normalized == "loop continue":
            if not bool(metadata.get("retrieval_loop_enabled", False)):
                return False
            missing_fields = list(verification.get("missing_fields") or [])
            coverage = float(verification.get("coverage") or 0.0)
            threshold = float(verification.get("coverage_threshold") or 0.0)
            blocking_conflict = bool(verification.get("blocking_conflict"))
            return bool(missing_fields or coverage < threshold or blocking_conflict)
        if normalized == "policy reject":
            return bool(metadata.get("policy_reject", False))
        if normalized == "cache hit":
            return bool(metadata.get("cache_hit", False))
        if normalized == "memory hit":
            if memory_context is None:
                return False
            return bool(getattr(memory_context, "knowledge_snapshots", []) or getattr(memory_context, "entity_memories", []))
        if normalized == "workflow enabled":
            return bool(metadata.get("workflow_enabled", False))
        return False

    def build_execution_order(self, workflow: WorkflowDefinition) -> List[str]:
        nodes = {node.id: node for node in (workflow.nodes or [])}
        indegree: Dict[str, int] = {node.id: 0 for node in (workflow.nodes or [])}
        for edge in workflow.edges or []:
            if edge.target in indegree:
                indegree[edge.target] += 1
        queue = list(workflow.entry_nodes or [node_id for node_id, degree in indegree.items() if degree == 0])
        ordered: List[str] = []
        seen: set[str] = set()
        while queue:
            node_id = queue.pop(0)
            if node_id in seen or node_id not in nodes:
                continue
            seen.add(node_id)
            ordered.append(node_id)
            for edge in workflow.edges or []:
                if edge.source != node_id or edge.target not in indegree:
                    continue
                indegree[edge.target] -= 1
                if indegree[edge.target] <= 0:
                    queue.append(edge.target)
        for node_id in nodes:
            if node_id not in seen:
                ordered.append(node_id)
        return ordered

    def _maybe_apply_revision(
        self,
        node: WorkflowNode,
        context: WorkflowContext,
        node_result: Any,
        queue: List[str],
        completed: set[str],
    ) -> bool:
        if not self._adaptive_planner_enabled(context) or context.failed or context.stopped:
            return False
        try:
            analysis = self.adaptive_planner.analyse_execution_result(node, context, node_result)
            revision = self.adaptive_planner.decide_revision(analysis, context)
            if revision is None:
                return False
            task_graph = self._task_graph_object(context)
            planning_context = self._build_planning_context(context)
            revised_graph = self.adaptive_planner.revise_task_graph(task_graph, planning_context, revision)
        except Exception as exc:
            self.runtime_metrics.inc("planning_revision_failure", labels={"node_id": str(node.id or "")})
            self._trace_planning(
                context,
                "Planning Failed",
                metadata={"node_id": node.id, "error": str(exc), "phase": "adaptive_revision"},
            )
            return False

        revision_payload = revision.to_dict()
        self.runtime_metrics.inc("planning_revision_count", labels={"reason": revision.reason})
        self.runtime_metrics.inc("planning_revision_success", labels={"reason": revision.reason})
        self.runtime_metrics.inc("task_added_count", value=float(len(revision.added_tasks or [])), labels={"reason": revision.reason})
        self.runtime_metrics.inc("task_removed_count", value=float(len(revision.removed_tasks or [])), labels={"reason": revision.reason})
        self.runtime_metrics.inc(
            "task_reprioritized_count",
            value=float(len(revision.reprioritized_tasks or [])),
            labels={"reason": revision.reason},
        )

        metadata = dict(context.metadata or {})
        revision_history = list(metadata.get("planning_revisions") or [])
        revision_history.append(revision_payload)
        revision_signatures = list(metadata.get("planning_revision_signatures") or [])
        signature = str((revision.metadata or {}).get("signature") or "")
        if signature:
            revision_signatures.append(signature)
        metadata["planning_revision_count"] = int(metadata.get("planning_revision_count") or 0) + 1
        metadata["planning_revisions"] = revision_history
        metadata["planning_revision_signatures"] = revision_signatures
        metadata["task_graph"] = revised_graph.to_dict()
        context.metadata = metadata

        pipeline_context = context.pipeline_context
        pipeline_context.task_graph = revised_graph
        if getattr(pipeline_context, "workflow_state", None) is None:
            pipeline_context.workflow_state = {}
        pipeline_context.workflow_state["last_revision"] = revision_payload
        if getattr(pipeline_context, "orchestrator", None) is not None:
            try:
                setattr(pipeline_context.orchestrator.brain, "_last_task_graph", revised_graph.to_dict())
                setattr(pipeline_context.orchestrator.brain, "_last_planning_revision", revision_payload)
            except Exception:
                pass

        self._trace_planning(
            context,
            "Planning Revision Finished",
            metadata={
                "revision_id": revision.revision_id,
                "reason": revision.reason,
                "added_count": len(revision.added_tasks or []),
                "removed_count": len(revision.removed_tasks or []),
                "reprioritized_count": len(revision.reprioritized_tasks or []),
            },
        )
        for item in list(revision.added_tasks or []):
            self._trace_planning(context, "Task Added", metadata={"revision_id": revision.revision_id, **dict(item or {})})
        for item in list(revision.removed_tasks or []):
            self._trace_planning(context, "Task Removed", metadata={"revision_id": revision.revision_id, **dict(item or {})})
        for item in list(revision.reprioritized_tasks or []):
            self._trace_planning(context, "Task Reprioritized", metadata={"revision_id": revision.revision_id, **dict(item or {})})

        revisit_nodes = self._revision_revisit_nodes(node, revision)
        for node_id in revisit_nodes:
            completed.discard(node_id)
            if node_id in context.node_status:
                context.node_status[node_id] = "pending"
        queue[:0] = [node_id for node_id in revisit_nodes if node_id not in queue]
        return bool(revisit_nodes)

    def _task_graph_payload(self, context: WorkflowContext) -> Dict[str, Any]:
        payload = (context.metadata or {}).get("task_graph")
        if hasattr(payload, "to_dict"):
            try:
                payload = payload.to_dict()
            except Exception:
                payload = {}
        return dict(payload or {}) if isinstance(payload, dict) else {}

    def _task_graph_object(self, context: WorkflowContext) -> TaskGraph:
        pipeline_context = context.pipeline_context
        if isinstance(getattr(pipeline_context, "task_graph", None), TaskGraph):
            return getattr(pipeline_context, "task_graph")
        payload = self._task_graph_payload(context)
        return TaskGraph.from_dict(payload)

    def _node_required_by_task_graph(self, node: WorkflowNode, context: WorkflowContext) -> bool:
        if node.node_type in {"START", "END", "CONDITION", "JOIN"}:
            return True
        task_graph = self._task_graph_payload(context)
        tasks = list(task_graph.get("tasks") or [])
        if not tasks:
            return True
        service = str(node.service or "").strip()
        mapping: Dict[str, set[str]] = {
            "prepare_context": set(),
            "retrieval": {"RESEARCH", "SEARCH", "RETRIEVE", "GRAPH", "TIMELINE", "RELATIONSHIP", "INVESTMENT", "COMPARE", "RANK"},
            "knowledge": {"REASON"},
            "memory_update": {"RESEARCH", "SEARCH", "RETRIEVE", "GRAPH", "TIMELINE", "RELATIONSHIP", "INVESTMENT", "COMPARE", "RANK"},
            "answer_composer": {"FINAL_GENERATE"},
            "verification": {"VERIFY"},
            "retrieval_loop": {"VERIFY", "RETRIEVE", "SEARCH"},
            "memory_snapshot": {"VERIFY", "FINAL_GENERATE"},
            "llm": {"FINAL_GENERATE"},
        }
        relevant = mapping.get(service, None)
        if relevant is None:
            decision = True
            reason = "no_mapping"
            matched: List[str] = []
            print(f"Node={service} Mapped TaskTypes=[] Matched Tasks=[] Decision=True Reason={reason}")
            return decision
        if service == "prepare_context":
            decision = True
            reason = "core_node"
            print(f"Node={service} Mapped TaskTypes=[] Matched Tasks=[] Decision=True Reason={reason}")
            return decision
        normalized_relevant = [item for item in [str(x or "").strip().upper() for x in (relevant or set())] if item]
        matched_tasks: List[str] = []
        for task in tasks:
            if not isinstance(task, dict):
                continue
            task_type = str(task.get("task_type") or "").strip().upper()
            if not task_type or task_type not in relevant:
                continue
            status = str(task.get("status") or "pending").strip().lower()
            if status == "completed":
                continue
            matched_tasks.append(str(task.get("id") or "").strip() or task_type)
        decision = bool(matched_tasks)
        reason = "matched_tasks" if decision else "no_matching_tasks"
        print(
            f"Node={service} "
            f"Mapped TaskTypes={normalized_relevant} "
            f"Matched Tasks={matched_tasks} "
            f"Decision={'True' if decision else 'False'} "
            f"Reason={reason}"
        )
        return decision

    def _mark_task_progress(self, node: WorkflowNode, context: WorkflowContext) -> None:
        task_graph = self._task_graph_object(context)
        mapping = {
            "retrieval": {"RESEARCH", "SEARCH", "RETRIEVE", "GRAPH", "TIMELINE", "RELATIONSHIP", "INVESTMENT", "COMPARE", "RANK"},
            "knowledge": {"GRAPH", "RELATIONSHIP", "INVESTMENT"},
            "answer_composer": {"REASON", "SUMMARIZE", "COMPARE", "RANK"},
            "verification": {"VERIFY"},
            "llm": {"FINAL_GENERATE"},
        }
        relevant = mapping.get(str(node.service or "").strip(), set())
        if not relevant:
            return
        updated_tasks: List[TaskNode] = []
        for task in list(task_graph.tasks or []):
            if str(task.task_type or "").strip().upper() in relevant:
                updated_tasks.append(TaskNode.from_dict({**task.to_dict(), "status": "completed"}))
            else:
                updated_tasks.append(task)
        updated_graph = TaskGraph(
            graph_id=task_graph.graph_id,
            goal=task_graph.goal,
            tasks=updated_tasks,
            edges=list(task_graph.edges or []),
            entry_tasks=list(task_graph.entry_tasks or []),
            exit_tasks=list(task_graph.exit_tasks or []),
            metadata=dict(task_graph.metadata or {}),
        )
        context.pipeline_context.task_graph = updated_graph
        metadata = dict(context.metadata or {})
        metadata["task_graph"] = updated_graph.to_dict()
        context.metadata = metadata

    def _build_planning_context(self, context: WorkflowContext) -> PlanningContext:
        pipeline_context = context.pipeline_context
        return PlanningContext(
            question=str(context.question or ""),
            requirement=getattr(pipeline_context, "requirement", None),
            capability_plan=getattr(pipeline_context, "capability_plan", None),
            workflow_definition=context.workflow_definition,
            memory_context=getattr(pipeline_context, "memory_context", None),
            knowledge_graph=getattr(pipeline_context, "knowledge_graph", None),
            pipeline_selection=getattr(pipeline_context, "selection", None),
            metadata={
                "question_type": str(getattr(getattr(pipeline_context, "question_context", None), "question_type", "") or ""),
                "task_graph": self._task_graph_payload(context),
            },
        )

    def _revision_revisit_nodes(self, node: WorkflowNode, revision: Any) -> List[str]:
        service = str(node.service or "").strip()
        if service in {"verification", "retrieval_loop", "llm", "memory_snapshot"}:
            return ["retrieval", "knowledge", "memory_update", "answer_composer", "verification", "loop_condition", "retrieval_loop", "memory_snapshot", "llm", "end"]
        if service in {"knowledge", "answer_composer"}:
            return ["retrieval", "knowledge", "memory_update", "answer_composer", "verification", "loop_condition", "retrieval_loop", "memory_snapshot", "llm", "end"]
        if service == "retrieval":
            return ["retrieval", "knowledge", "memory_update", "answer_composer", "verification", "loop_condition", "retrieval_loop", "memory_snapshot", "llm", "end"]
        return []

    def _adaptive_planner_enabled(self, context: WorkflowContext) -> bool:
        metadata = dict(context.metadata or {})
        return bool(metadata.get("adaptive_planner_enabled"))

    def _call_service(self, node: WorkflowNode, context: WorkflowContext) -> Any:
        pipeline_context = context.pipeline_context
        orchestrator = getattr(pipeline_context, "orchestrator", None)
        if orchestrator is not None and hasattr(orchestrator, "execute_workflow_service"):
            return orchestrator.execute_workflow_service(node.service, context, node)
        container = context.service_container
        if container is not None and hasattr(container, "has") and container.has(node.service):
            service = container.get(node.service)
            if hasattr(service, "execute"):
                return service.execute(context)
            if callable(service):
                return service(context)
        raise RuntimeError(f"workflow service unavailable: {node.service}")

    def _dependencies_met(self, node: WorkflowNode, context: WorkflowContext) -> bool:
        return all(dependency in context.node_results for dependency in (node.depends_on or []))

    def _build_outgoing_edges(self, workflow: WorkflowDefinition) -> Dict[str, List[Dict[str, Any]]]:
        mapping: Dict[str, List[Dict[str, Any]]] = {}
        for edge in workflow.edges or []:
            mapping.setdefault(edge.source, []).append(
                {"target": edge.target, "condition": edge.condition, "metadata": dict(edge.metadata or {})}
            )
        return mapping

    def _trace(self, context: WorkflowContext, event_name: str, *, metadata: Dict[str, Any] | None = None) -> None:
        trace_center = self.trace_center or getattr(context.pipeline_context, "trace_center", None) or getattr(context, "trace_session", None)
        if trace_center is None:
            return
        try:
            if hasattr(trace_center, "record_workflow_event"):
                trace_center.record_workflow_event(event_name, metadata=metadata or {})
            else:
                trace_center.record_event("WORKFLOW", event_name, metadata=metadata or {})
        except Exception:
            pass

    def _trace_planning(self, context: WorkflowContext, event_name: str, *, metadata: Dict[str, Any] | None = None) -> None:
        trace_center = self.trace_center or getattr(context.pipeline_context, "trace_center", None) or getattr(context, "trace_session", None)
        if trace_center is None:
            return
        try:
            if hasattr(trace_center, "record_planning_event"):
                trace_center.record_planning_event(event_name, metadata=metadata or {})
            else:
                trace_center.record_event("PLANNING", event_name, metadata=metadata or {})
        except Exception:
            pass

    def _workflow_name(self, context: WorkflowContext) -> str:
        if context.workflow_definition is None:
            return "Workflow"
        return str(context.workflow_definition.name or "Workflow")
