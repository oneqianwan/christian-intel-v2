from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass(frozen=True)
class EvidenceNode:
    id: str
    evidence_id: str
    node_type: str
    confidence: float
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "evidence_id": self.evidence_id,
            "node_type": self.node_type,
            "confidence": float(self.confidence),
            "metadata": dict(self.metadata or {}),
        }


@dataclass(frozen=True)
class EvidenceEdge:
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
class EvidenceGraph:
    nodes: List[EvidenceNode] = field(default_factory=list)
    edges: List[EvidenceEdge] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def add_node(self, node: EvidenceNode) -> None:
        existing_ids = {item.id for item in (self.nodes or [])}
        if node.id in existing_ids:
            return
        self.nodes.append(node)

    def add_edge(self, edge: EvidenceEdge) -> None:
        signature = (edge.source, edge.target, edge.relation)
        existing = {(item.source, item.target, item.relation) for item in (self.edges or [])}
        if signature in existing:
            return
        self.edges.append(edge)

    def merge(self, other: "EvidenceGraph" | Dict[str, Any] | None) -> "EvidenceGraph":
        if other is None:
            return self
        other_graph = other if isinstance(other, EvidenceGraph) else EvidenceGraph.from_dict(other or {})
        merged = EvidenceGraph(
            nodes=list(self.nodes or []),
            edges=list(self.edges or []),
            metadata={**dict(self.metadata or {}), **dict(other_graph.metadata or {})},
        )
        for node in other_graph.nodes or []:
            merged.add_node(node)
        for edge in other_graph.edges or []:
            merged.add_edge(edge)
        return merged

    def export(self) -> Dict[str, Any]:
        return self.to_dict()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "nodes": [item.to_dict() for item in (self.nodes or [])],
            "edges": [item.to_dict() for item in (self.edges or [])],
            "metadata": dict(self.metadata or {}),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EvidenceGraph":
        payload = data or {}
        return cls(
            nodes=[
                EvidenceNode(
                    id=str(item.get("id") or ""),
                    evidence_id=str(item.get("evidence_id") or ""),
                    node_type=str(item.get("node_type") or ""),
                    confidence=float(item.get("confidence") or 0.0),
                    metadata=dict(item.get("metadata") or {}),
                )
                for item in (payload.get("nodes") or [])
                if isinstance(item, dict)
            ],
            edges=[
                EvidenceEdge(
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
