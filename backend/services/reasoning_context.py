from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from services.reasoning_graph import ReasoningGraph


@dataclass(frozen=True)
class ReasoningContext:
    facts: List[Dict[str, Any]] = field(default_factory=list)
    evidence: List[Dict[str, Any]] = field(default_factory=list)
    answer_context: Dict[str, Any] = field(default_factory=dict)
    reasoning_graph: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "facts": [dict(item or {}) for item in (self.facts or []) if isinstance(item, dict)],
            "evidence": [dict(item or {}) for item in (self.evidence or []) if isinstance(item, dict)],
            "answer_context": dict(self.answer_context or {}),
            "reasoning_graph": dict(self.reasoning_graph or {}),
            "metadata": dict(self.metadata or {}),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ReasoningContext":
        payload = data or {}
        graph_payload = dict(payload.get("reasoning_graph") or {})
        graph = ReasoningGraph.from_dict(graph_payload).export() if graph_payload else {}
        return cls(
            facts=[dict(item or {}) for item in (payload.get("facts") or []) if isinstance(item, dict)],
            evidence=[dict(item or {}) for item in (payload.get("evidence") or []) if isinstance(item, dict)],
            answer_context=dict(payload.get("answer_context") or {}),
            reasoning_graph=graph,
            metadata=dict(payload.get("metadata") or {}),
        )
