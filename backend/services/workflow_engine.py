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
class WorkflowNode:
    id: str
    name: str
    description: str
    node_type: str
    service: str = ""
    inputs: List[str] = field(default_factory=list)
    outputs: List[str] = field(default_factory=list)
    depends_on: List[str] = field(default_factory=list)
    condition: str = ""
    parallel_group: str = ""
    retry: int = 0
    timeout: float = 0.0
    enabled: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "node_type": self.node_type,
            "service": self.service,
            "inputs": list(self.inputs or []),
            "outputs": list(self.outputs or []),
            "depends_on": list(self.depends_on or []),
            "condition": self.condition,
            "parallel_group": self.parallel_group,
            "retry": int(self.retry or 0),
            "timeout": float(self.timeout or 0.0),
            "enabled": bool(self.enabled),
            "metadata": dict(self.metadata or {}),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorkflowNode":
        payload = data or {}
        return cls(
            id=str(payload.get("id") or ""),
            name=str(payload.get("name") or ""),
            description=str(payload.get("description") or ""),
            node_type=str(payload.get("node_type") or "SERVICE"),
            service=str(payload.get("service") or ""),
            inputs=list(payload.get("inputs") or []),
            outputs=list(payload.get("outputs") or []),
            depends_on=list(payload.get("depends_on") or []),
            condition=str(payload.get("condition") or ""),
            parallel_group=str(payload.get("parallel_group") or ""),
            retry=int(payload.get("retry") or 0),
            timeout=float(payload.get("timeout") or 0.0),
            enabled=bool(payload.get("enabled", True)),
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass(frozen=True)
class WorkflowEdge:
    source: str
    target: str
    condition: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "condition": self.condition,
            "metadata": dict(self.metadata or {}),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorkflowEdge":
        payload = data or {}
        return cls(
            source=str(payload.get("source") or ""),
            target=str(payload.get("target") or ""),
            condition=str(payload.get("condition") or ""),
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass(frozen=True)
class WorkflowDefinition:
    name: str
    description: str
    nodes: List[WorkflowNode] = field(default_factory=list)
    edges: List[WorkflowEdge] = field(default_factory=list)
    entry_nodes: List[str] = field(default_factory=list)
    exit_nodes: List[str] = field(default_factory=list)
    version: str = "v1"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "nodes": [item.to_dict() for item in (self.nodes or [])],
            "edges": [item.to_dict() for item in (self.edges or [])],
            "entry_nodes": list(self.entry_nodes or []),
            "exit_nodes": list(self.exit_nodes or []),
            "version": self.version,
            "metadata": dict(self.metadata or {}),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorkflowDefinition":
        payload = data or {}
        return cls(
            name=str(payload.get("name") or ""),
            description=str(payload.get("description") or ""),
            nodes=[WorkflowNode.from_dict(item) for item in (payload.get("nodes") or []) if isinstance(item, dict)],
            edges=[WorkflowEdge.from_dict(item) for item in (payload.get("edges") or []) if isinstance(item, dict)],
            entry_nodes=list(payload.get("entry_nodes") or []),
            exit_nodes=list(payload.get("exit_nodes") or []),
            version=str(payload.get("version") or "v1"),
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass
class WorkflowContext:
    question: str = ""
    requirement: Any = None
    pipeline_selection: Any = None
    memory_context: Any = None
    knowledge_graph: Any = None
    trace_session: Any = None
    execution_policy_context: Any = None
    runtime_metrics: Any = None
    service_container: Any = None
    pipeline_context: Any = None
    question_context: Any = None
    capability_plan: Any = None
    history: List[Dict[str, Any]] = field(default_factory=list)
    workflow_definition: WorkflowDefinition | None = None
    node_results: Dict[str, Any] = field(default_factory=dict)
    node_status: Dict[str, str] = field(default_factory=dict)
    node_sequence: List[str] = field(default_factory=list)
    final_result: Dict[str, Any] | None = None
    stopped: bool = False
    failed: bool = False
    errors: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "question": self.question,
            "requirement": _serialize(self.requirement),
            "pipeline_selection": _serialize(self.pipeline_selection),
            "memory_context": _serialize(self.memory_context),
            "knowledge_graph": _serialize(self.knowledge_graph),
            "trace_session": _serialize(self.trace_session),
            "execution_policy_context": _serialize(self.execution_policy_context),
            "runtime_metrics": _serialize(self.runtime_metrics.export() if hasattr(self.runtime_metrics, "export") else self.runtime_metrics),
            "service_container": _serialize(self.service_container),
            "pipeline_context": _serialize(self.pipeline_context),
            "question_context": _serialize(self.question_context),
            "capability_plan": _serialize(self.capability_plan),
            "history": list(self.history or []),
            "workflow_definition": self.workflow_definition.to_dict() if self.workflow_definition is not None else None,
            "node_results": _serialize(self.node_results),
            "node_status": dict(self.node_status or {}),
            "node_sequence": list(self.node_sequence or []),
            "final_result": _serialize(self.final_result),
            "stopped": bool(self.stopped),
            "failed": bool(self.failed),
            "errors": list(self.errors or []),
            "metadata": dict(self.metadata or {}),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorkflowContext":
        payload = data or {}
        workflow_definition = payload.get("workflow_definition")
        return cls(
            question=str(payload.get("question") or ""),
            requirement=payload.get("requirement"),
            pipeline_selection=payload.get("pipeline_selection"),
            memory_context=payload.get("memory_context"),
            knowledge_graph=payload.get("knowledge_graph"),
            trace_session=payload.get("trace_session"),
            execution_policy_context=payload.get("execution_policy_context"),
            runtime_metrics=payload.get("runtime_metrics"),
            service_container=payload.get("service_container"),
            pipeline_context=payload.get("pipeline_context"),
            question_context=payload.get("question_context"),
            capability_plan=payload.get("capability_plan"),
            history=list(payload.get("history") or []),
            workflow_definition=WorkflowDefinition.from_dict(workflow_definition) if isinstance(workflow_definition, dict) else None,
            node_results=dict(payload.get("node_results") or {}),
            node_status=dict(payload.get("node_status") or {}),
            node_sequence=list(payload.get("node_sequence") or []),
            final_result=dict(payload.get("final_result") or {}) if isinstance(payload.get("final_result"), dict) else None,
            stopped=bool(payload.get("stopped", False)),
            failed=bool(payload.get("failed", False)),
            errors=list(payload.get("errors") or []),
            metadata=dict(payload.get("metadata") or {}),
        )
