from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


def _serialize(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        try:
            return value.to_dict()
        except Exception:
            return value
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _serialize(item) for key, item in value.items()}
    return value


@dataclass(frozen=True)
class TaskNode:
    id: str
    name: str
    description: str
    task_type: str
    priority: int = 0
    required: bool = True
    status: str = "pending"
    inputs: List[str] = field(default_factory=list)
    outputs: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    estimated_cost: float = 0.0
    estimated_latency: float = 0.0
    parallel_group: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "task_type": self.task_type,
            "priority": int(self.priority or 0),
            "required": bool(self.required),
            "status": self.status,
            "inputs": list(self.inputs or []),
            "outputs": list(self.outputs or []),
            "dependencies": list(self.dependencies or []),
            "estimated_cost": float(self.estimated_cost or 0.0),
            "estimated_latency": float(self.estimated_latency or 0.0),
            "parallel_group": self.parallel_group,
            "metadata": dict(self.metadata or {}),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskNode":
        payload = data or {}
        return cls(
            id=str(payload.get("id") or ""),
            name=str(payload.get("name") or ""),
            description=str(payload.get("description") or ""),
            task_type=str(payload.get("task_type") or ""),
            priority=int(payload.get("priority") or 0),
            required=bool(payload.get("required", True)),
            status=str(payload.get("status") or "pending"),
            inputs=list(payload.get("inputs") or []),
            outputs=list(payload.get("outputs") or []),
            dependencies=list(payload.get("dependencies") or []),
            estimated_cost=float(payload.get("estimated_cost") or 0.0),
            estimated_latency=float(payload.get("estimated_latency") or 0.0),
            parallel_group=str(payload.get("parallel_group") or ""),
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass(frozen=True)
class TaskEdge:
    source: str
    target: str
    dependency_type: str = "hard"
    condition: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "dependency_type": self.dependency_type,
            "condition": self.condition,
            "metadata": dict(self.metadata or {}),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskEdge":
        payload = data or {}
        return cls(
            source=str(payload.get("source") or ""),
            target=str(payload.get("target") or ""),
            dependency_type=str(payload.get("dependency_type") or "hard"),
            condition=str(payload.get("condition") or ""),
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass(frozen=True)
class TaskGraph:
    graph_id: str
    goal: str
    tasks: List[TaskNode] = field(default_factory=list)
    edges: List[TaskEdge] = field(default_factory=list)
    entry_tasks: List[str] = field(default_factory=list)
    exit_tasks: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "graph_id": self.graph_id,
            "goal": self.goal,
            "tasks": [item.to_dict() for item in (self.tasks or [])],
            "edges": [item.to_dict() for item in (self.edges or [])],
            "entry_tasks": list(self.entry_tasks or []),
            "exit_tasks": list(self.exit_tasks or []),
            "metadata": dict(self.metadata or {}),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskGraph":
        payload = data or {}
        return cls(
            graph_id=str(payload.get("graph_id") or ""),
            goal=str(payload.get("goal") or ""),
            tasks=[TaskNode.from_dict(item) for item in (payload.get("tasks") or []) if isinstance(item, dict)],
            edges=[TaskEdge.from_dict(item) for item in (payload.get("edges") or []) if isinstance(item, dict)],
            entry_tasks=list(payload.get("entry_tasks") or []),
            exit_tasks=list(payload.get("exit_tasks") or []),
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass
class PlanningContext:
    question: str = ""
    requirement: Any = None
    capability_plan: Any = None
    workflow_definition: Any = None
    memory_context: Any = None
    knowledge_graph: Any = None
    pipeline_selection: Any = None
    policy_decision: Any = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "question": self.question,
            "requirement": _serialize(self.requirement),
            "capability_plan": _serialize(self.capability_plan),
            "workflow_definition": _serialize(self.workflow_definition),
            "memory_context": _serialize(self.memory_context),
            "knowledge_graph": _serialize(self.knowledge_graph),
            "pipeline_selection": _serialize(self.pipeline_selection),
            "policy_decision": _serialize(self.policy_decision),
            "metadata": dict(self.metadata or {}),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PlanningContext":
        payload = data or {}
        return cls(
            question=str(payload.get("question") or ""),
            requirement=payload.get("requirement"),
            capability_plan=payload.get("capability_plan"),
            workflow_definition=payload.get("workflow_definition"),
            memory_context=payload.get("memory_context"),
            knowledge_graph=payload.get("knowledge_graph"),
            pipeline_selection=payload.get("pipeline_selection"),
            policy_decision=payload.get("policy_decision"),
            metadata=dict(payload.get("metadata") or {}),
        )
