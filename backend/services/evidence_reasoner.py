from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Tuple

from services.evidence_graph import EvidenceEdge, EvidenceGraph, EvidenceNode
from services.evidence_models import Evidence, Fact


class EvidenceReasoner:
    def __init__(self, trace_center: Any = None, runtime_metrics: Any = None):
        self.trace_center = trace_center
        self.runtime_metrics = runtime_metrics

    def build_graph(self, evidences: List[Evidence]) -> EvidenceGraph:
        graph = EvidenceGraph(
            metadata={
                "node_count": 0,
                "edge_count": 0,
                "duplicate_evidence": 0,
                "supported_facts": 0,
                "contradicted_facts": 0,
                "average_evidence_confidence": 0.0,
            }
        )
        for evidence in evidences or []:
            graph.add_node(
                EvidenceNode(
                    id=self._node_id(evidence.evidence_id),
                    evidence_id=str(evidence.evidence_id or ""),
                    node_type="evidence",
                    confidence=float(evidence.confidence or 0.0),
                    metadata={
                        "title": str(evidence.title or ""),
                        "url": str(evidence.url or ""),
                        "source_id": str(evidence.source_id or ""),
                        "source_type": str(evidence.source_type or ""),
                    },
                )
            )
        duplicate_pairs = self.merge_duplicate_evidence(evidences)
        duplicate_source_pairs = self.detect_duplicate_sources(evidences)
        for source_id, target_id, relation, confidence in [*duplicate_pairs, *duplicate_source_pairs]:
            graph.add_edge(
                EvidenceEdge(
                    source=self._node_id(source_id),
                    target=self._node_id(target_id),
                    relation=relation,
                    confidence=float(confidence),
                )
            )
            self._trace("Evidence Duplicate", metadata={"source": source_id, "target": target_id, "relation": relation})
        graph.metadata.update(self.compute_confidence(graph))
        self._record_graph_metrics(graph)
        self._trace(
            "Evidence Graph Built",
            metadata={
                "node_count": len(graph.nodes or []),
                "edge_count": len(graph.edges or []),
            },
        )
        return graph

    def merge_duplicate_evidence(self, evidences: List[Evidence]) -> List[Tuple[str, str, str, float]]:
        pairs: List[Tuple[str, str, str, float]] = []
        for index, left in enumerate(evidences or []):
            for right in (evidences or [])[index + 1 :]:
                relation, confidence = self._duplicate_relation(left, right)
                if relation:
                    pairs.append((left.evidence_id, right.evidence_id, relation, confidence))
        return pairs

    def detect_support_relations(self, graph: EvidenceGraph, facts: List[Fact]) -> EvidenceGraph:
        by_fact: Dict[str, List[Fact]] = defaultdict(list)
        for fact in facts or []:
            key = self._fact_key(fact)
            by_fact[key].append(fact)
        supported_facts = 0
        for items in by_fact.values():
            evidence_ids = self._dedupe_list([eid for fact in items for eid in (fact.evidence_ids or [])])
            if len(evidence_ids) < 2:
                continue
            supported_facts += 1
            for index, source_id in enumerate(evidence_ids):
                for target_id in evidence_ids[index + 1 :]:
                    graph.add_edge(
                        EvidenceEdge(
                            source=self._node_id(source_id),
                            target=self._node_id(target_id),
                            relation="supports",
                            confidence=0.8,
                        )
                    )
                    self._trace("Evidence Support", metadata={"source": source_id, "target": target_id})
        graph.metadata["supported_facts"] = int(supported_facts)
        return graph

    def detect_contradictions(self, graph: EvidenceGraph, facts: List[Fact]) -> EvidenceGraph:
        grouped: Dict[Tuple[str, str], List[Fact]] = defaultdict(list)
        for fact in facts or []:
            grouped[(str(fact.subject or "").strip().lower(), str(fact.predicate or "").strip().lower())].append(fact)
        contradicted_facts = 0
        for items in grouped.values():
            values = sorted({str(item.object or "").strip().lower() for item in items if str(item.object or "").strip()})
            if len(values) < 2:
                continue
            contradicted_facts += 1
            for index, left in enumerate(items):
                for right in items[index + 1 :]:
                    if str(left.object or "").strip().lower() == str(right.object or "").strip().lower():
                        continue
                    for source_id in (left.evidence_ids or []):
                        for target_id in (right.evidence_ids or []):
                            if source_id == target_id:
                                continue
                            graph.add_edge(
                                EvidenceEdge(
                                    source=self._node_id(source_id),
                                    target=self._node_id(target_id),
                                    relation="contradicts",
                                    confidence=0.9,
                                )
                            )
                            self._trace("Evidence Conflict", metadata={"source": source_id, "target": target_id})
        graph.metadata["contradicted_facts"] = int(contradicted_facts)
        return graph

    def detect_duplicate_sources(self, evidences: List[Evidence]) -> List[Tuple[str, str, str, float]]:
        pairs: List[Tuple[str, str, str, float]] = []
        for index, left in enumerate(evidences or []):
            for right in (evidences or [])[index + 1 :]:
                left_source = str((left.metadata or {}).get("source_name") or left.source_id or "").strip().lower()
                right_source = str((right.metadata or {}).get("source_name") or right.source_id or "").strip().lower()
                if not left_source or left_source != right_source:
                    continue
                if str(left.url or "").strip() and str(left.url or "").strip() == str(right.url or "").strip():
                    continue
                if self._text_similarity(left.title, right.title) >= 0.92:
                    pairs.append((left.evidence_id, right.evidence_id, "references", 0.72))
        return pairs

    def compute_confidence(self, graph: EvidenceGraph) -> Dict[str, Any]:
        node_count = len(graph.nodes or [])
        edge_count = len(graph.edges or [])
        duplicate_evidence = len([edge for edge in (graph.edges or []) if edge.relation == "duplicates"])
        average_confidence = 0.0
        if node_count > 0:
            average_confidence = round(sum(float(node.confidence or 0.0) for node in (graph.nodes or [])) / node_count, 3)
        return {
            "node_count": node_count,
            "edge_count": edge_count,
            "duplicate_evidence": duplicate_evidence,
            "average_evidence_confidence": average_confidence,
        }

    def export_graph(self, graph: EvidenceGraph | Dict[str, Any]) -> Dict[str, Any]:
        if isinstance(graph, EvidenceGraph):
            return graph.export()
        return EvidenceGraph.from_dict(graph or {}).export()

    def detect_extend_relations(self, graph: EvidenceGraph, facts: List[Fact]) -> EvidenceGraph:
        by_subject: Dict[str, List[Fact]] = defaultdict(list)
        for fact in facts or []:
            by_subject[str(fact.subject or "").strip().lower()].append(fact)
        for items in by_subject.values():
            if len(items) < 2:
                continue
            predicate_to_evidence: Dict[str, List[str]] = defaultdict(list)
            for fact in items:
                predicate_to_evidence[str(fact.predicate or "").strip().lower()].extend(list(fact.evidence_ids or []))
            if len([key for key in predicate_to_evidence.keys() if key]) < 2:
                continue
            evidence_ids = self._dedupe_list([eid for ids in predicate_to_evidence.values() for eid in ids])
            for index, source_id in enumerate(evidence_ids):
                for target_id in evidence_ids[index + 1 :]:
                    graph.add_edge(
                        EvidenceEdge(
                            source=self._node_id(source_id),
                            target=self._node_id(target_id),
                            relation="extends",
                            confidence=0.68,
                        )
                    )
                    self._trace("Evidence Extended", metadata={"source": source_id, "target": target_id})
        return graph

    def _duplicate_relation(self, left: Evidence, right: Evidence) -> Tuple[str, float]:
        left_url = str(left.url or "").strip()
        right_url = str(right.url or "").strip()
        if left_url and right_url and left_url == right_url:
            return "duplicates", 0.98
        if self._text_similarity(left.title, right.title) >= 0.95 and str(left.title or "").strip():
            return "duplicates", 0.93
        if self._text_similarity(left.snippet, right.snippet) >= 0.94 and str(left.snippet or "").strip():
            return "duplicates", 0.88
        return "", 0.0

    def _fact_key(self, fact: Fact) -> str:
        return "::".join(
            [
                str(fact.subject or "").strip().lower(),
                str(fact.predicate or "").strip().lower(),
                str(fact.object or "").strip().lower(),
            ]
        )

    def _node_id(self, evidence_id: str) -> str:
        return f"EN::{str(evidence_id or '').strip()}"

    def _text_similarity(self, left: str, right: str) -> float:
        left_tokens = set(str(left or "").strip().lower().split())
        right_tokens = set(str(right or "").strip().lower().split())
        if not left_tokens or not right_tokens:
            return 0.0
        overlap = len(left_tokens & right_tokens)
        total = len(left_tokens | right_tokens)
        if total <= 0:
            return 0.0
        return overlap / total

    def _dedupe_list(self, items: List[str]) -> List[str]:
        seen = set()
        out: List[str] = []
        for item in items or []:
            text = str(item or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            out.append(text)
        return out

    def _record_graph_metrics(self, graph: EvidenceGraph) -> None:
        if self.runtime_metrics is None:
            return
        graph_confidence = self.compute_confidence(graph)
        self.runtime_metrics.set("evidence_graph_nodes", float(graph_confidence.get("node_count") or 0.0))
        self.runtime_metrics.set("evidence_graph_edges", float(graph_confidence.get("edge_count") or 0.0))
        self.runtime_metrics.set("duplicate_evidence", float(graph_confidence.get("duplicate_evidence") or 0.0))
        self.runtime_metrics.set("average_evidence_confidence", float(graph_confidence.get("average_evidence_confidence") or 0.0))

    def _trace(self, name: str, metadata: Dict[str, Any] | None = None) -> None:
        if self.trace_center is None:
            return
        self.trace_center.record_event("EVIDENCE", name, metadata=metadata or {})
