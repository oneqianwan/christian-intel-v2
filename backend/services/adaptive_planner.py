from __future__ import annotations

from typing import Any, Dict, List

from services.feature_flags import feature_flag_enabled
from services.planning_revision import PlanningRevision, RevisionReason
from services.runtime_metrics import get_runtime_metrics
from services.task_graph import PlanningContext, TaskGraph
from services.task_planner import TaskPlanner


class AdaptivePlanner:
    def __init__(self, *, task_planner: TaskPlanner | None = None, trace_center: Any = None, runtime_metrics: Any = None):
        self.task_planner = task_planner or TaskPlanner(trace_center=trace_center, runtime_metrics=runtime_metrics)
        self.trace_center = trace_center
        self.runtime_metrics = runtime_metrics or get_runtime_metrics()

    def analyse_execution_result(self, node: Any, workflow_context: Any, node_result: Any) -> Dict[str, Any]:
        pipeline_context = getattr(workflow_context, "pipeline_context", None)
        verification = dict(getattr(pipeline_context, "verification", {}) or {})
        knowledge_graph = getattr(pipeline_context, "knowledge_graph", None)
        task_graph = getattr(pipeline_context, "task_graph", None)
        tool_results = list(getattr(pipeline_context, "tool_results", []) or [])
        loop_summary = dict(getattr(pipeline_context, "loop_summary", {}) or {})
        question_context = getattr(pipeline_context, "question_context", None)
        entities = list(getattr(question_context, "entities", []) or [])
        node_service = str(getattr(node, "service", "") or "").strip()
        node_type = str(getattr(node, "node_type", "") or "").strip()
        payload = dict(node_result or {}) if isinstance(node_result, dict) else {}

        reasons: List[str] = []
        if node_service == "retrieval" and not tool_results and not bool(getattr(workflow_context, "final_result", None)):
            reasons.append(RevisionReason.MISSING_EVIDENCE.value)
        if node_service == "retrieval" and not entities:
            reasons.append(RevisionReason.MISSING_ENTITY.value)
        if node_service == "knowledge":
            node_count = len(getattr(knowledge_graph, "nodes", []) or []) if knowledge_graph is not None else 0
            relation_count = len(getattr(knowledge_graph, "relations", []) or []) if knowledge_graph is not None else 0
            if not node_count and not relation_count and tool_results:
                reasons.append(RevisionReason.KNOWLEDGE_GAP.value)
        if node_service == "verification":
            if list(verification.get("missing_fields") or []) or not bool(verification.get("answer_ready")):
                reasons.append(RevisionReason.VERIFICATION_FAILED.value)
            if not bool(verification.get("citation_ready")) or not bool(verification.get("evidence_enough")):
                reasons.append(RevisionReason.MISSING_EVIDENCE.value)
        if node_service == "retrieval_loop":
            if bool(loop_summary.get("loop_count")) and list(loop_summary.get("stop_conditions") or []):
                reasons.append(RevisionReason.LOOP_CONTINUE.value)
        if payload.get("status") in {"skipped", "error"} and "policy" in str(payload.get("message") or "").lower():
            reasons.append(RevisionReason.POLICY_RETRY.value)

        current_graph = task_graph.to_dict() if hasattr(task_graph, "to_dict") else dict(task_graph or {})
        return {
            "node_id": str(getattr(node, "id", "") or ""),
            "node_type": node_type,
            "node_service": node_service,
            "reasons": self._dedupe_list(reasons),
            "tool_result_count": len(tool_results),
            "knowledge_node_count": len(getattr(knowledge_graph, "nodes", []) or []) if knowledge_graph is not None else 0,
            "knowledge_relation_count": len(getattr(knowledge_graph, "relations", []) or []) if knowledge_graph is not None else 0,
            "missing_fields": list(verification.get("missing_fields") or []),
            "coverage": float(verification.get("coverage") or 0.0),
            "loop_summary": loop_summary,
            "task_graph": current_graph,
        }

    def decide_revision(self, analysis: Dict[str, Any], workflow_context: Any) -> PlanningRevision | None:
        if not self._enabled():
            return None
        reasons = list(analysis.get("reasons") or [])
        if not reasons:
            return None
        metadata = dict(getattr(workflow_context, "metadata", {}) or {})
        revision_count = int(metadata.get("planning_revision_count") or 0)
        if revision_count >= 2:
            return None
        signatures = set(list(metadata.get("planning_revision_signatures") or []))
        priority = [
            RevisionReason.MISSING_ENTITY.value,
            RevisionReason.MISSING_EVIDENCE.value,
            RevisionReason.KNOWLEDGE_GAP.value,
            RevisionReason.VERIFICATION_FAILED.value,
            RevisionReason.POLICY_RETRY.value,
            RevisionReason.LOOP_CONTINUE.value,
        ]
        chosen = next((reason for reason in priority if reason in reasons), reasons[0])
        signature = f"{analysis.get('node_id')}::{chosen}::{revision_count}"
        if signature in signatures:
            return None
        revision = PlanningRevision.create(
            chosen,
            metadata={
                **dict(analysis or {}),
                "revision_count_before": revision_count,
                "signature": signature,
            },
        )
        self._trace("Planning Revision Started", metadata={"revision_id": revision.revision_id, "reason": revision.reason, "node_id": analysis.get("node_id")})
        return revision

    def revise_task_graph(
        self,
        task_graph: TaskGraph,
        planning_context: PlanningContext,
        revision: PlanningRevision,
    ) -> TaskGraph:
        revised_graph = self.task_planner.revise_task_graph(task_graph, planning_context, revision)
        merged_graph = self.merge_revision(task_graph, revised_graph, revision)
        return merged_graph

    def merge_revision(self, base_graph: TaskGraph, revised_graph: TaskGraph, revision: PlanningRevision) -> TaskGraph:
        history = list((base_graph.metadata or {}).get("revision_history") or [])
        history.append(revision.to_dict())
        metadata = {
            **dict(revised_graph.metadata or {}),
            "revision_history": history,
            "revision_count": len(history),
            "last_revision_id": revision.revision_id,
            "last_revision_reason": revision.reason,
        }
        return TaskGraph(
            graph_id=revised_graph.graph_id,
            goal=revised_graph.goal,
            tasks=list(revised_graph.tasks or []),
            edges=list(revised_graph.edges or []),
            entry_tasks=list(revised_graph.entry_tasks or []),
            exit_tasks=list(revised_graph.exit_tasks or []),
            metadata=metadata,
        )

    def export_revision(self, revision: PlanningRevision) -> Dict[str, Any]:
        return revision.to_dict()

    def _enabled(self) -> bool:
        return feature_flag_enabled("ADAPTIVE_PLANNER_ENABLED")

    def _trace(self, event_name: str, *, metadata: Dict[str, Any] | None = None) -> None:
        if self.trace_center is None:
            return
        try:
            if hasattr(self.trace_center, "record_planning_event"):
                self.trace_center.record_planning_event(event_name, metadata=metadata or {})
            else:
                self.trace_center.record_event("PLANNING", event_name, metadata=metadata or {})
        except Exception:
            pass

    def _dedupe_list(self, items: List[str]) -> List[str]:
        seen = set()
        output: List[str] = []
        for item in items or []:
            value = str(item or "").strip()
            if not value or value in seen:
                continue
            seen.add(value)
            output.append(value)
        return output
