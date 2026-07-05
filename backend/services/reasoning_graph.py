from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass(frozen=True)
class ReasoningNode:
    node_id: str
    node_type: str
    subject: str
    confidence: float
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "node_type": self.node_type,
            "subject": self.subject,
            "confidence": float(self.confidence),
            "metadata": dict(self.metadata or {}),
        }


@dataclass(frozen=True)
class ReasoningEdge:
    source: str
    target: str
    relation: str
    confidence: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "relation": self.relation,
            "confidence": float(self.confidence),
        }


@dataclass
class ReasoningGraph:
    nodes: List[ReasoningNode] = field(default_factory=list)
    edges: List[ReasoningEdge] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def add_node(self, node: ReasoningNode) -> None:
        if node.node_id in {item.node_id for item in (self.nodes or [])}:
            return
        self.nodes.append(node)

    def add_edge(self, edge: ReasoningEdge) -> None:
        signature = (edge.source, edge.target, edge.relation)
        if signature in {(item.source, item.target, item.relation) for item in (self.edges or [])}:
            return
        self.edges.append(edge)

    def export(self) -> Dict[str, Any]:
        return {
            "nodes": [item.to_dict() for item in (self.nodes or [])],
            "edges": [item.to_dict() for item in (self.edges or [])],
            "metadata": dict(self.metadata or {}),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ReasoningGraph":
        payload = data or {}
        return cls(
            nodes=[
                ReasoningNode(
                    node_id=str(item.get("node_id") or ""),
                    node_type=str(item.get("node_type") or ""),
                    subject=str(item.get("subject") or ""),
                    confidence=float(item.get("confidence") or 0.0),
                    metadata=dict(item.get("metadata") or {}),
                )
                for item in (payload.get("nodes") or [])
                if isinstance(item, dict)
            ],
            edges=[
                ReasoningEdge(
                    source=str(item.get("source") or ""),
                    target=str(item.get("target") or ""),
                    relation=str(item.get("relation") or ""),
                    confidence=float(item.get("confidence") or 0.0),
                )
                for item in (payload.get("edges") or [])
                if isinstance(item, dict)
            ],
            metadata=dict(payload.get("metadata") or {}),
        )
