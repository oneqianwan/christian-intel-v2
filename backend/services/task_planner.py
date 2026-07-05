from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List

from services.planning_revision import PlanningRevision, RevisionReason
from services.capability_planner import Capability, CapabilityPlan
from services.default_task_templates import get_task_template
from services.runtime_metrics import get_runtime_metrics
from services.task_graph import PlanningContext, TaskEdge, TaskGraph, TaskNode


class TaskPlanner:
    def __init__(self, *, trace_center: Any = None, runtime_metrics: Any = None):
        self.trace_center = trace_center
        self.runtime_metrics = runtime_metrics or get_runtime_metrics()

    def analyse_goal(self, planning_context: PlanningContext) -> Dict[str, Any]:
        requirement = planning_context.requirement
        selection = planning_context.pipeline_selection
        capabilities = self._capability_names(planning_context.capability_plan)
        goal = {
            "question": str(planning_context.question or ""),
            "question_type": str((planning_context.metadata or {}).get("question_type") or "UNKNOWN"),
            "pipeline": self._pipeline_name(selection),
            "required_fields": list(getattr(requirement, "required_fields", []) or []),
            "capabilities": capabilities,
        }
        self._trace("Goal Analysed", metadata=goal)
        return goal

    def generate_tasks(self, planning_context: PlanningContext) -> List[TaskNode]:
        goal = self.analyse_goal(planning_context)
        template_name = self._pick_template(planning_context, goal)
        tasks = [TaskNode.from_dict(item.to_dict()) for item in get_task_template(template_name)]
        tasks = self._apply_capability_overrides(tasks, planning_context.capability_plan)
        tasks = self._apply_memory_hints(tasks, planning_context.memory_context)
        tasks = self._apply_knowledge_hints(tasks, planning_context.knowledge_graph)
        for task in tasks:
            self._trace("Task Generated", metadata={"task_id": task.id, "task_type": task.task_type, "template": template_name})
        return tasks

    def merge_duplicate_tasks(self, tasks: List[TaskNode]) -> tuple[List[TaskNode], int]:
        merged: Dict[str, TaskNode] = {}
        merge_count = 0
        for task in tasks or []:
            key = self._task_merge_key(task)
            existing = merged.get(key)
            if existing is None:
                merged[key] = task
                continue
            merge_count += 1
            merged[key] = TaskNode(
                id=existing.id,
                name=existing.name,
                description=existing.description or task.description,
                task_type=existing.task_type,
                priority=max(int(existing.priority or 0), int(task.priority or 0)),
                required=bool(existing.required or task.required),
                status=self._merge_task_status(existing.status, task.status),
                inputs=self._dedupe_list(list(existing.inputs or []) + list(task.inputs or [])),
                outputs=self._dedupe_list(list(existing.outputs or []) + list(task.outputs or [])),
                dependencies=self._dedupe_list(list(existing.dependencies or []) + list(task.dependencies or [])),
                estimated_cost=max(float(existing.estimated_cost or 0.0), float(task.estimated_cost or 0.0)),
                estimated_latency=max(float(existing.estimated_latency or 0.0), float(task.estimated_latency or 0.0)),
                parallel_group=str(existing.parallel_group or task.parallel_group or ""),
                metadata={**dict(existing.metadata or {}), **dict(task.metadata or {})},
            )
            self._trace("Task Merged", metadata={"task_id": existing.id, "task_type": existing.task_type})
        return list(merged.values()), merge_count

    def build_task_graph(self, planning_context: PlanningContext) -> TaskGraph:
        started = time.perf_counter()
        self.runtime_metrics.inc("planning_count")
        if self.trace_center is not None and hasattr(self.trace_center, "start_planning"):
            self.trace_center.start_planning(metadata={"question": planning_context.question})
        self._trace("Planning Started", metadata={"question": planning_context.question})
        try:
            tasks = self.generate_tasks(planning_context)
            tasks, merge_count = self.merge_duplicate_tasks(tasks)
            tasks = self._estimate_task_cost_latency(tasks)
            parallel_candidates = self.detect_parallel_tasks(tasks)
            edges = self._build_edges(tasks)
            entry_tasks = [task.id for task in tasks if not task.dependencies]
            exit_tasks = [task.id for task in tasks if not any(edge.source == task.id for edge in edges)]
            graph = TaskGraph(
                graph_id=uuid.uuid4().hex,
                goal=str(self.analyse_goal(planning_context).get("question") or planning_context.question or ""),
                tasks=tasks,
                edges=edges,
                entry_tasks=entry_tasks,
                exit_tasks=exit_tasks,
                metadata={
                    "pipeline": self._pipeline_name(planning_context.pipeline_selection),
                    "task_count": len(tasks),
                    "task_merge_count": merge_count,
                    "parallel_candidate_count": len(parallel_candidates),
                    "estimated_cost": self.estimate_cost(tasks),
                    "estimated_latency": self.estimate_latency(tasks),
                    "graph_depth": self._graph_depth(tasks),
                    "parallelism": self._parallelism(tasks),
                    "merge_rate": round((merge_count / max(len(tasks) + merge_count, 1)) * 100.0, 2),
                },
            )
            self.runtime_metrics.inc("planning_success")
            self.runtime_metrics.inc("task_count", value=float(len(tasks)))
            self.runtime_metrics.inc("task_merge_count", value=float(merge_count))
            self.runtime_metrics.inc("task_parallel_count", value=float(len(parallel_candidates)))
            latency_ms = round((time.perf_counter() - started) * 1000, 2)
            self.runtime_metrics.observe("planning_latency_ms", latency_ms)
            self._trace(
                "Task Graph Built",
                metadata={
                    "graph_id": graph.graph_id,
                    "task_count": len(tasks),
                    "merge_count": merge_count,
                    "parallel_candidate_count": len(parallel_candidates),
                    "latency_ms": latency_ms,
                },
            )
            self._trace("Planning Finished", metadata={"graph_id": graph.graph_id})
            if self.trace_center is not None and hasattr(self.trace_center, "finish_planning"):
                self.trace_center.finish_planning(status="completed", metadata={"graph_id": graph.graph_id})
            return graph
        except Exception as exc:
            self.runtime_metrics.inc("planning_failure")
            self._trace("Planning Failed", metadata={"error": str(exc)})
            if self.trace_center is not None and hasattr(self.trace_center, "finish_planning"):
                self.trace_center.finish_planning(status="failed", metadata={"error": str(exc)})
            raise

    def estimate_cost(self, tasks: List[TaskNode] | TaskGraph) -> float:
        items = tasks.tasks if isinstance(tasks, TaskGraph) else list(tasks or [])
        return round(sum(float(item.estimated_cost or 0.0) for item in items), 2)

    def estimate_latency(self, tasks: List[TaskNode] | TaskGraph) -> float:
        items = tasks.tasks if isinstance(tasks, TaskGraph) else list(tasks or [])
        levels = self._level_map(items)
        level_max: Dict[int, float] = {}
        for task in items:
            level = int(levels.get(task.id, 0))
            level_max[level] = max(float(level_max.get(level, 0.0)), float(task.estimated_latency or 0.0))
        return round(sum(level_max.values()), 2)

    def detect_parallel_tasks(self, tasks: List[TaskNode]) -> List[List[str]]:
        levels = self._level_map(tasks)
        grouped: Dict[int, List[TaskNode]] = {}
        for task in tasks or []:
            grouped.setdefault(int(levels.get(task.id, 0)), []).append(task)
        parallel_groups: List[List[str]] = []
        for level, items in grouped.items():
            candidates = [task for task in items if task.task_type in {"SEARCH", "RETRIEVE", "GRAPH", "TIMELINE", "INVESTMENT", "RELATIONSHIP"}]
            if len(candidates) < 2:
                continue
            group_id = f"parallel_{level}"
            for task in candidates:
                task.metadata["parallel_candidate"] = True
                task.metadata["parallel_level"] = level
                task.metadata["parallel_group"] = group_id
            parallel_groups.append([task.id for task in candidates])
            self._trace("Task Parallel Detected", metadata={"level": level, "tasks": [task.id for task in candidates]})
        return parallel_groups

    def export_graph(self, graph: TaskGraph) -> Dict[str, Any]:
        return graph.to_dict()

    def revise_task_graph(
        self,
        task_graph: TaskGraph,
        planning_context: PlanningContext,
        revision: PlanningRevision,
    ) -> TaskGraph:
        revised_candidates = self._build_revision_tasks(task_graph, planning_context, revision)
        merged_tasks, merge_count = self.merge_duplicate_tasks(revised_candidates)
        merged_tasks = self._estimate_task_cost_latency(merged_tasks)
        parallel_candidates = self.detect_parallel_tasks(merged_tasks)
        revised_edges = self._build_edges(merged_tasks)
        metadata = {
            **dict(task_graph.metadata or {}),
            "task_count": len(merged_tasks),
            "task_merge_count": int((task_graph.metadata or {}).get("task_merge_count") or 0) + merge_count,
            "parallel_candidate_count": len(parallel_candidates),
            "estimated_cost": self.estimate_cost(merged_tasks),
            "estimated_latency": self.estimate_latency(merged_tasks),
            "graph_depth": self._graph_depth(merged_tasks),
            "parallelism": self._parallelism(merged_tasks),
            "merge_rate": round(((int((task_graph.metadata or {}).get("task_merge_count") or 0) + merge_count) / max(len(merged_tasks) + int((task_graph.metadata or {}).get("task_merge_count") or 0) + merge_count, 1)) * 100.0, 2),
            "revision_applied": True,
            "revision_id": revision.revision_id,
            "revision_reason": revision.reason,
        }
        return TaskGraph(
            graph_id=task_graph.graph_id,
            goal=task_graph.goal,
            tasks=merged_tasks,
            edges=revised_edges,
            entry_tasks=[task.id for task in merged_tasks if not task.dependencies],
            exit_tasks=[task.id for task in merged_tasks if not any(edge.source == task.id for edge in revised_edges)],
            metadata=metadata,
        )

    def _build_revision_tasks(
        self,
        task_graph: TaskGraph,
        planning_context: PlanningContext,
        revision: PlanningRevision,
    ) -> List[TaskNode]:
        question_type = str((planning_context.metadata or {}).get("question_type") or "UNKNOWN")
        existing_tasks = [TaskNode.from_dict(item.to_dict()) for item in list(task_graph.tasks or [])]
        existing_by_type = {str(task.task_type or "").upper(): task for task in existing_tasks}
        revision_specs = self._revision_specs(revision)
        reprioritized: List[Dict[str, Any]] = []
        created: List[TaskNode] = []

        for index, spec in enumerate(revision_specs, start=1):
            task_type = str(spec.get("task_type") or "").upper()
            existing = existing_by_type.get(task_type)
            if existing is not None:
                new_priority = max(int(existing.priority or 0), int(spec.get("priority") or 0))
                updated = TaskNode.from_dict(
                    {
                        **existing.to_dict(),
                        "priority": new_priority,
                        "metadata": {
                            **dict(existing.metadata or {}),
                            "revision_id": revision.revision_id,
                            "revision_reason": revision.reason,
                        },
                    }
                )
                existing_by_type[task_type] = updated
                if new_priority != int(existing.priority or 0):
                    reprioritized.append(
                        {"task_id": existing.id, "from_priority": int(existing.priority or 0), "to_priority": new_priority}
                    )
                    self._trace(
                        "Task Reprioritized",
                        metadata={
                            "task_id": existing.id,
                            "from_priority": int(existing.priority or 0),
                            "to_priority": new_priority,
                            "revision_id": revision.revision_id,
                        },
                    )
                continue

            task = TaskNode(
                id=f"{revision.revision_id}.{index}.{task_type.lower()}",
                name=str(spec.get("name") or task_type.title()),
                description=f"Adaptive revision task for {revision.reason}",
                task_type=task_type,
                priority=int(spec.get("priority") or 60),
                required=True,
                status="pending",
                inputs=list(spec.get("inputs") or []),
                outputs=list(spec.get("outputs") or []),
                dependencies=self._revision_dependencies(task_type, task_graph),
                estimated_cost=0.0,
                estimated_latency=0.0,
                parallel_group="",
                metadata={
                    "revision_id": revision.revision_id,
                    "revision_reason": revision.reason,
                    "scope": "adaptive_revision",
                    "question_type": question_type,
                },
            )
            created.append(task)
            self._trace(
                "Task Added",
                metadata={"task_id": task.id, "task_type": task.task_type, "revision_id": revision.revision_id},
            )

        object.__setattr__(revision, "added_tasks", [task.to_dict() for task in created])
        object.__setattr__(revision, "reprioritized_tasks", list(reprioritized))
        updated_existing = [existing_by_type.get(str(task.task_type or "").upper(), task) for task in existing_tasks]
        return updated_existing + created

    def _revision_specs(self, revision: PlanningRevision) -> List[Dict[str, Any]]:
        reason = str(revision.reason or "")
        if reason == RevisionReason.MISSING_ENTITY.value:
            return [
                {"task_type": "SEARCH", "name": "Revision Search", "outputs": ["entity_candidates"], "priority": 98},
                {"task_type": "RETRIEVE", "name": "Revision Retrieve", "outputs": ["retrieved_evidence"], "priority": 95},
                {"task_type": "VERIFY", "name": "Revision Verify", "outputs": ["verification_result"], "priority": 72},
            ]
        if reason == RevisionReason.MISSING_EVIDENCE.value:
            return [
                {"task_type": "RETRIEVE", "name": "Evidence Retrieve", "outputs": ["retrieved_evidence"], "priority": 96},
                {"task_type": "VERIFY", "name": "Evidence Verify", "outputs": ["verification_result"], "priority": 78},
            ]
        if reason == RevisionReason.KNOWLEDGE_GAP.value:
            return [
                {"task_type": "GRAPH", "name": "Knowledge Graph Fill", "outputs": ["knowledge_graph"], "priority": 94},
                {"task_type": "RELATIONSHIP", "name": "Knowledge Relationship Fill", "outputs": ["relationship_data"], "priority": 88},
                {"task_type": "VERIFY", "name": "Knowledge Verify", "outputs": ["verification_result"], "priority": 76},
            ]
        if reason == RevisionReason.VERIFICATION_FAILED.value:
            return [
                {"task_type": "REASON", "name": "Revision Reason", "outputs": ["reasoning_result"], "priority": 82},
                {"task_type": "VERIFY", "name": "Revision Verify", "outputs": ["verification_result"], "priority": 84},
                {"task_type": "FINAL_GENERATE", "name": "Revision Final Generate", "outputs": ["final_answer"], "priority": 62},
            ]
        if reason == RevisionReason.POLICY_RETRY.value:
            return [
                {"task_type": "RETRIEVE", "name": "Policy Retry Retrieve", "outputs": ["retrieved_evidence"], "priority": 86},
                {"task_type": "VERIFY", "name": "Policy Retry Verify", "outputs": ["verification_result"], "priority": 66},
            ]
        if reason == RevisionReason.LOOP_CONTINUE.value:
            return [
                {"task_type": "RETRIEVE", "name": "Loop Continue Retrieve", "outputs": ["retrieved_evidence"], "priority": 90},
                {"task_type": "VERIFY", "name": "Loop Continue Verify", "outputs": ["verification_result"], "priority": 75},
            ]
        return []

    def _build_edges(self, tasks: List[TaskNode]) -> List[TaskEdge]:
        edges: List[TaskEdge] = []
        for task in tasks or []:
            for dependency in list(task.dependencies or []):
                edges.append(
                    TaskEdge(
                        source=str(dependency or ""),
                        target=task.id,
                        dependency_type="hard",
                        condition="",
                        metadata={"task_type": task.task_type},
                    )
                )
        return edges

    def _estimate_task_cost_latency(self, tasks: List[TaskNode]) -> List[TaskNode]:
        cost_map = {
            "RESEARCH": 3.0,
            "SEARCH": 1.0,
            "RETRIEVE": 2.0,
            "REASON": 1.5,
            "VERIFY": 1.0,
            "SUMMARIZE": 0.8,
            "GRAPH": 1.8,
            "TIMELINE": 1.8,
            "RELATIONSHIP": 1.8,
            "INVESTMENT": 1.8,
            "COMPARE": 1.2,
            "RANK": 1.2,
            "FINAL_GENERATE": 1.0,
        }
        latency_map = {
            "RESEARCH": 220.0,
            "SEARCH": 120.0,
            "RETRIEVE": 180.0,
            "REASON": 90.0,
            "VERIFY": 70.0,
            "SUMMARIZE": 60.0,
            "GRAPH": 150.0,
            "TIMELINE": 150.0,
            "RELATIONSHIP": 150.0,
            "INVESTMENT": 160.0,
            "COMPARE": 90.0,
            "RANK": 95.0,
            "FINAL_GENERATE": 140.0,
        }
        updated: List[TaskNode] = []
        for task in tasks or []:
            updated.append(
                TaskNode(
                    id=task.id,
                    name=task.name,
                    description=task.description,
                    task_type=task.task_type,
                    priority=task.priority,
                    required=task.required,
                    status=task.status,
                    inputs=list(task.inputs or []),
                    outputs=list(task.outputs or []),
                    dependencies=list(task.dependencies or []),
                    estimated_cost=float(task.estimated_cost or cost_map.get(task.task_type, 1.0)),
                    estimated_latency=float(task.estimated_latency or latency_map.get(task.task_type, 80.0)),
                    parallel_group=str(task.parallel_group or task.metadata.get("parallel_group") or ""),
                    metadata=dict(task.metadata or {}),
                )
            )
        return updated

    def _pick_template(self, planning_context: PlanningContext, goal: Dict[str, Any]) -> str:
        question_type = str(goal.get("question_type") or "").upper()
        pipeline = self._pipeline_name(planning_context.pipeline_selection)
        capabilities = set(self._capability_names(planning_context.capability_plan))
        if question_type in {"COMPARISON", "RANKING"} or {"RANKING"} & capabilities:
            return "comparison"
        if pipeline == "OrganizationPipeline" or "PROFILE" in capabilities:
            return "organization"
        if pipeline == "TimelinePipeline" or question_type in {"TIMELINE", "NEWS"} or "TIMELINE" in capabilities:
            return "timeline"
        if pipeline == "InvestmentPipeline" or "INVESTMENT" in capabilities:
            return "investment"
        if pipeline in {"RelationshipPipeline", "GraphPipeline"} or {"RELATIONSHIP", "GRAPH"} & capabilities:
            return "relationship"
        return "research"

    def _apply_capability_overrides(self, tasks: List[TaskNode], capability_plan: CapabilityPlan | Any) -> List[TaskNode]:
        capability_names = set(self._capability_names(capability_plan))
        updated: List[TaskNode] = []
        for task in tasks or []:
            if task.task_type == "RELATIONSHIP" and "RELATIONSHIP" not in capability_names and "GRAPH" not in capability_names:
                updated.append(TaskNode.from_dict({**task.to_dict(), "required": False, "priority": min(task.priority, 45)}))
                continue
            if task.task_type == "GRAPH" and "GRAPH" not in capability_names:
                updated.append(TaskNode.from_dict({**task.to_dict(), "required": False, "priority": min(task.priority, 40)}))
                continue
            updated.append(task)
        return updated

    def _apply_memory_hints(self, tasks: List[TaskNode], memory_context: Any) -> List[TaskNode]:
        if memory_context is None:
            return tasks
        snapshots = list(getattr(memory_context, "knowledge_snapshots", []) or [])
        entity_memories = list(getattr(memory_context, "entity_memories", []) or [])
        updated: List[TaskNode] = []
        for task in tasks or []:
            metadata = dict(task.metadata or {})
            priority = int(task.priority or 0)
            if task.task_type in {"RETRIEVE", "TIMELINE", "GRAPH", "RELATIONSHIP", "INVESTMENT"} and (snapshots or entity_memories):
                metadata["memory_hint"] = "dedupe_candidate"
                priority = max(25, priority - 12)
            updated.append(TaskNode.from_dict({**task.to_dict(), "priority": priority, "metadata": metadata}))
        return updated

    def _apply_knowledge_hints(self, tasks: List[TaskNode], knowledge_graph: Any) -> List[TaskNode]:
        if knowledge_graph is None:
            return tasks
        has_nodes = bool(getattr(knowledge_graph, "nodes", []) or [])
        updated: List[TaskNode] = []
        for task in tasks or []:
            metadata = dict(task.metadata or {})
            priority = int(task.priority or 0)
            if has_nodes and task.task_type == "RETRIEVE":
                metadata["knowledge_hint"] = "existing_nodes"
                priority = max(20, priority - 10)
            if has_nodes and task.task_type == "RELATIONSHIP":
                priority = min(99, priority + 8)
            updated.append(TaskNode.from_dict({**task.to_dict(), "priority": priority, "metadata": metadata}))
        return updated

    def _pipeline_name(self, selection: Any) -> str:
        pipeline = getattr(selection, "selected_pipeline", None)
        if pipeline is None:
            return str(getattr(selection, "name", "") or "")
        return str(getattr(pipeline, "name", "") or "")

    def _capability_names(self, capability_plan: CapabilityPlan | Any) -> List[str]:
        if isinstance(capability_plan, CapabilityPlan):
            capabilities = list(capability_plan.required_capabilities or []) + list(capability_plan.optional_capabilities or [])
            return [str(item.name or "").strip().upper() for item in capabilities if str(item.name or "").strip()]
        payload = dict(capability_plan or {})
        output: List[str] = []
        for section in ["required_capabilities", "optional_capabilities"]:
            for item in list(payload.get(section) or []):
                if isinstance(item, Capability):
                    output.append(str(item.name or "").strip().upper())
                elif isinstance(item, dict):
                    output.append(str(item.get("name") or "").strip().upper())
        return [item for item in output if item]

    def _task_merge_key(self, task: TaskNode) -> str:
        metadata = dict(task.metadata or {})
        scope = str(metadata.get("scope") or metadata.get("template") or "")
        return f"{task.task_type}:{scope}:{','.join(sorted(task.outputs or []))}"

    def _level_map(self, tasks: List[TaskNode]) -> Dict[str, int]:
        level_map: Dict[str, int] = {}
        task_map = {task.id: task for task in tasks or []}

        def level(task_id: str) -> int:
            if task_id in level_map:
                return level_map[task_id]
            task = task_map.get(task_id)
            if task is None or not task.dependencies:
                level_map[task_id] = 0
                return 0
            value = 1 + max(level(dep) for dep in task.dependencies if dep in task_map)
            level_map[task_id] = value
            return value

        for task in tasks or []:
            level(task.id)
        return level_map

    def _graph_depth(self, tasks: List[TaskNode]) -> int:
        levels = self._level_map(tasks)
        return max(levels.values(), default=0) + (1 if tasks else 0)

    def _parallelism(self, tasks: List[TaskNode]) -> float:
        levels = self._level_map(tasks)
        grouped: Dict[int, int] = {}
        for task_id, level in levels.items():
            grouped[level] = grouped.get(level, 0) + 1
        if not grouped:
            return 0.0
        return round(max(grouped.values()) / max(len(tasks), 1), 2)

    def _revision_dependencies(self, task_type: str, task_graph: TaskGraph) -> List[str]:
        exit_tasks = list(task_graph.exit_tasks or [])
        if task_type in {"VERIFY", "FINAL_GENERATE"} and exit_tasks:
            return self._dedupe_list(exit_tasks)
        retrieval_like = []
        for task in list(task_graph.tasks or []):
            if str(task.task_type or "").upper() in {"RETRIEVE", "SEARCH", "GRAPH", "TIMELINE", "RELATIONSHIP", "INVESTMENT"}:
                retrieval_like.append(task.id)
        return self._dedupe_list(retrieval_like[:2])

    def _dedupe_list(self, values: List[str]) -> List[str]:
        seen = set()
        output: List[str] = []
        for value in values or []:
            text = str(value or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            output.append(text)
        return output

    def _merge_task_status(self, left: str, right: str) -> str:
        order = {"completed": 4, "in_progress": 3, "pending": 2, "skipped": 1, "failed": 0}
        left_value = str(left or "pending").strip().lower()
        right_value = str(right or "pending").strip().lower()
        return left_value if order.get(left_value, 2) >= order.get(right_value, 2) else right_value

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
