from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List

from services.feature_flags import feature_flag_enabled
from services.reasoning_context import ReasoningContext
from services.reasoning_graph import ReasoningEdge, ReasoningGraph, ReasoningNode
from services.reasoning_engine_v1 import Conflict, EvidenceEvaluation, ReasoningEngineV1, ReasoningResult
from services.runtime_metrics import get_runtime_metrics


class ReasoningEngine(ReasoningEngineV1):
    def __init__(self, trace_center: Any = None, runtime_metrics: Any = None):
        super().__init__()
        self.trace_center = trace_center
        self.runtime_metrics = runtime_metrics or get_runtime_metrics()

    def build_reasoning_context(self, evidence_bundle: Any, answer_context: Any) -> ReasoningContext:
        self._trace("Reasoning Context Started", metadata={})
        bundle = self._coerce_evidence_bundle(evidence_bundle)
        context_payload = self._coerce_answer_context(answer_context)
        facts = [dict(item or {}) for item in (bundle.get("facts") or []) if isinstance(item, dict)]
        evidence = [dict(item or {}) for item in (bundle.get("evidences") or []) if isinstance(item, dict)]
        reasoning_graph = self.build_reasoning_graph(facts, evidence, context_payload, bundle)
        reasoning_context = ReasoningContext(
            facts=facts,
            evidence=evidence,
            answer_context=context_payload,
            reasoning_graph=reasoning_graph.export(),
            metadata={
                "reasoning_confidence": float(self.compute_reasoning_confidence(reasoning_graph)),
                "derived_conclusion_count": int((reasoning_graph.metadata or {}).get("derived_conclusion_count") or 0),
            },
        )
        self._record_metrics(reasoning_graph)
        self._trace(
            "Reasoning Context Finished",
            metadata={
                "fact_count": len(facts),
                "evidence_count": len(evidence),
                "node_count": len(reasoning_graph.nodes or []),
                "edge_count": len(reasoning_graph.edges or []),
            },
        )
        return reasoning_context

    def build_reasoning_graph(
        self,
        facts: List[Dict[str, Any]],
        evidence: List[Dict[str, Any]],
        answer_context: Dict[str, Any],
        bundle: Dict[str, Any] | None = None,
    ) -> ReasoningGraph:
        graph = ReasoningGraph(metadata={"derived_conclusion_count": 0})
        evidence_lookup = {str(item.get("evidence_id") or item.get("id") or ""): item for item in (evidence or []) if isinstance(item, dict)}
        fact_nodes: Dict[str, str] = {}
        for item in facts or []:
            fact_id = str(item.get("fact_id") or item.get("id") or "")
            if not fact_id:
                continue
            subject = str(item.get("subject") or item.get("predicate") or "")
            node_id = f"RF::{fact_id}"
            fact_nodes[fact_id] = node_id
            graph.add_node(
                ReasoningNode(
                    node_id=node_id,
                    node_type="fact",
                    subject=subject,
                    confidence=float(item.get("confidence") or 0.0),
                    metadata=dict(item),
                )
            )
        for item in evidence or []:
            evidence_id = str(item.get("evidence_id") or item.get("id") or "")
            if not evidence_id:
                continue
            graph.add_node(
                ReasoningNode(
                    node_id=f"RE::{evidence_id}",
                    node_type="evidence",
                    subject=str(item.get("title") or item.get("source_id") or ""),
                    confidence=float(item.get("confidence") or 0.0),
                    metadata=dict(item),
                )
            )
        for item in facts or []:
            fact_id = str(item.get("fact_id") or item.get("id") or "")
            target_id = fact_nodes.get(fact_id)
            if not target_id:
                continue
            for evidence_id in (item.get("evidence_ids") or []):
                source_node = f"RE::{str(evidence_id)}"
                if str(evidence_id) not in evidence_lookup:
                    continue
                graph.add_edge(ReasoningEdge(source=source_node, target=target_id, relation="supports", confidence=0.82))
        self.infer_dependencies(graph, facts, fact_nodes)
        self.infer_comparisons(graph, facts, fact_nodes)
        self._infer_contradictions(graph, bundle, fact_nodes)
        self.infer_conclusions(graph, facts, fact_nodes, answer_context)
        graph.metadata.update(
            {
                "reasoning_confidence": float(self.compute_reasoning_confidence(graph)),
                "reasoning_depth": int(self._reasoning_depth(graph)),
            }
        )
        self._trace(
            "Reasoning Graph Built",
            metadata={"node_count": len(graph.nodes or []), "edge_count": len(graph.edges or [])},
        )
        return graph

    def infer_dependencies(self, graph: ReasoningGraph, facts: List[Dict[str, Any]], fact_nodes: Dict[str, str] | None = None) -> ReasoningGraph:
        fact_nodes = fact_nodes or {str(item.get("fact_id") or item.get("id") or ""): f"RF::{str(item.get('fact_id') or item.get('id') or '')}" for item in (facts or [])}
        by_subject: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for item in facts or []:
            by_subject[str(item.get("subject") or "").strip().lower()].append(item)
        for subject_items in by_subject.values():
            base_ids = [str(item.get("fact_id") or item.get("id") or "") for item in subject_items if str(item.get("predicate") or "").strip().lower() == "name"]
            if not base_ids:
                continue
            base_node = fact_nodes.get(base_ids[0])
            if not base_node:
                continue
            for item in subject_items:
                fact_id = str(item.get("fact_id") or item.get("id") or "")
                predicate = str(item.get("predicate") or "").strip().lower()
                if not fact_id or predicate == "name":
                    continue
                target_node = fact_nodes.get(fact_id)
                if not target_node:
                    continue
                graph.add_edge(ReasoningEdge(source=target_node, target=base_node, relation="depends_on", confidence=0.72))
                self._trace("Reasoning Dependency", metadata={"source": fact_id, "target": base_ids[0], "relation": "depends_on"})
        return graph

    def infer_comparisons(self, graph: ReasoningGraph, facts: List[Dict[str, Any]], fact_nodes: Dict[str, str] | None = None) -> ReasoningGraph:
        fact_nodes = fact_nodes or {str(item.get("fact_id") or item.get("id") or ""): f"RF::{str(item.get('fact_id') or item.get('id') or '')}" for item in (facts or [])}
        by_predicate: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for item in facts or []:
            by_predicate[str(item.get("predicate") or "").strip().lower()].append(item)
        for items in by_predicate.values():
            if len(items) < 2:
                continue
            for idx, left in enumerate(items):
                left_id = str(left.get("fact_id") or left.get("id") or "")
                left_subject = str(left.get("subject") or "").strip().lower()
                for right in items[idx + 1 :]:
                    right_id = str(right.get("fact_id") or right.get("id") or "")
                    right_subject = str(right.get("subject") or "").strip().lower()
                    if not left_id or not right_id or not left_subject or not right_subject or left_subject == right_subject:
                        continue
                    graph.add_edge(
                        ReasoningEdge(
                            source=fact_nodes.get(left_id, f"RF::{left_id}"),
                            target=fact_nodes.get(right_id, f"RF::{right_id}"),
                            relation="compares",
                            confidence=0.64,
                        )
                    )
        return graph

    def infer_conclusions(
        self,
        graph: ReasoningGraph,
        facts: List[Dict[str, Any]],
        fact_nodes: Dict[str, str] | None = None,
        answer_context: Dict[str, Any] | None = None,
    ) -> ReasoningGraph:
        fact_nodes = fact_nodes or {str(item.get("fact_id") or item.get("id") or ""): f"RF::{str(item.get('fact_id') or item.get('id') or '')}" for item in (facts or [])}
        by_subject: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for item in facts or []:
            by_subject[str(item.get("subject") or "").strip()].append(item)
        derived_count = 0
        for subject, items in by_subject.items():
            usable = [item for item in items if str(item.get("fact_id") or item.get("id") or "").strip()]
            if len(usable) < 2:
                continue
            derived_count += 1
            conclusion_node_id = f"RC::{derived_count}"
            graph.add_node(
                ReasoningNode(
                    node_id=conclusion_node_id,
                    node_type="conclusion",
                    subject=subject or "Conclusion",
                    confidence=round(sum(float(item.get("confidence") or 0.0) for item in usable) / len(usable), 3),
                    metadata={
                        "fact_ids": [str(item.get("fact_id") or item.get("id") or "") for item in usable],
                        "section_count": len((answer_context or {}).get("sections") or []),
                    },
                )
            )
            for item in usable:
                fact_id = str(item.get("fact_id") or item.get("id") or "")
                source_node = fact_nodes.get(fact_id)
                if not source_node:
                    continue
                graph.add_edge(ReasoningEdge(source=source_node, target=conclusion_node_id, relation="derives", confidence=0.7))
            self._trace("Reasoning Conclusion", metadata={"subject": subject, "fact_count": len(usable)})
        graph.metadata["derived_conclusion_count"] = derived_count
        return graph

    def compute_reasoning_confidence(self, graph: ReasoningGraph | Dict[str, Any]) -> float:
        reasoning_graph = graph if isinstance(graph, ReasoningGraph) else ReasoningGraph.from_dict(graph or {})
        if not reasoning_graph.nodes:
            return 0.0
        base = sum(float(item.confidence or 0.0) for item in (reasoning_graph.nodes or [])) / len(reasoning_graph.nodes)
        support_edges = len([edge for edge in (reasoning_graph.edges or []) if edge.relation == "supports"])
        contradiction_edges = len([edge for edge in (reasoning_graph.edges or []) if edge.relation == "contradicts"])
        adjustment = min(0.15, support_edges * 0.01) - min(0.25, contradiction_edges * 0.05)
        return round(max(0.0, min(base + adjustment, 1.0)), 3)

    def export_reasoning(self, reasoning_context: ReasoningContext | Dict[str, Any]) -> Dict[str, Any]:
        if isinstance(reasoning_context, ReasoningContext):
            return reasoning_context.to_dict()
        return ReasoningContext.from_dict(reasoning_context or {}).to_dict()

    def build_reasoning_result_post(self, pre: ReasoningResult, knowledge_input: Any) -> ReasoningResult:
        if not self._structured_enabled():
            return super().build_reasoning_result_post(pre, knowledge_input)
        reasoning_context = self._coerce_reasoning_context(knowledge_input)
        if reasoning_context is None:
            return super().build_reasoning_result_post(pre, knowledge_input)
        graph = ReasoningGraph.from_dict(dict(reasoning_context.reasoning_graph or {}))
        evaluation = self._evaluate_reasoning_context(pre.requirement, reasoning_context)
        conflicts = self._conflicts_from_reasoning_context(reasoning_context)
        ranked = self._rank_reasoning_evidence(reasoning_context)
        merged = self._merge_reasoning_facts(reasoning_context)
        outline = self.build_answer_outline(pre.question_type, pre.requirement, reasoning_context.answer_context)
        verification = self.verification(evaluation.to_dict(), [item.to_dict() for item in conflicts], ranked)
        verification["reasoning_confidence"] = float(self.compute_reasoning_confidence(graph))
        return ReasoningResult(
            question_type=pre.question_type,
            country=pre.country,
            requirement=pre.requirement,
            tool_plan=pre.tool_plan,
            evaluation=evaluation,
            conflicts=conflicts,
            ranked_evidence=ranked,
            merged_facts=merged,
            outline=outline,
            verification=verification,
        )

    def _evaluate_reasoning_context(self, requirement: Any, reasoning_context: ReasoningContext) -> EvidenceEvaluation:
        fact_fields = {str(item.get("predicate") or item.get("field") or "").strip().lower() for item in (reasoning_context.facts or [])}
        evidence = list(reasoning_context.evidence or [])
        missing_fields: List[str] = []
        field_coverage: Dict[str, bool] = {}
        effective_fields = [str(field) for field in (requirement.required_fields or []) if str(field or "").strip().lower() not in {"ranking", "graph"}]
        for field in effective_fields:
            normalized = str(field or "").strip().lower()
            covered = False
            if normalized in fact_fields:
                covered = True
            elif normalized == "source" and any(str((item.get("metadata") or {}).get("source_name") or item.get("source_id") or "").strip() for item in evidence):
                covered = True
            elif normalized in {"title", "url", "snippet", "confidence", "published_at", "updated_at", "type"} and any(
                str(item.get(normalized) or item.get("created_at") or "").strip() for item in evidence
            ):
                covered = True
            field_coverage[field] = covered
            if not covered:
                missing_fields.append(field)
        unique_sources = {
            str((item.get("metadata") or {}).get("source_name") or item.get("source_id") or "").strip().lower()
            for item in evidence
            if isinstance(item, dict)
        }
        unique_sources = {item for item in unique_sources if item}
        minimum_sources = int(getattr(requirement, "minimum_sources", 1) or 1)
        missing_sources = []
        if len(unique_sources) < minimum_sources:
            missing_sources.append(f"need_{minimum_sources}_sources_have_{len(unique_sources)}")
        coverage = 0.0
        if effective_fields:
            coverage = round(sum(1 for value in field_coverage.values() if value) / len(effective_fields), 2)
        return EvidenceEvaluation(
            sufficient=(not missing_fields) and len(unique_sources) >= minimum_sources,
            coverage=coverage,
            missing_fields=missing_fields,
            missing_sources=missing_sources,
            field_coverage=field_coverage,
        )

    def _conflicts_from_reasoning_context(self, reasoning_context: ReasoningContext) -> List[Conflict]:
        graph = ReasoningGraph.from_dict(dict(reasoning_context.reasoning_graph or {}))
        conflicts: List[Conflict] = []
        for edge in graph.edges or []:
            if str(edge.relation or "").strip().lower() != "contradicts":
                continue
            source = self._node_metadata(graph, edge.source)
            target = self._node_metadata(graph, edge.target)
            values = self._dedupe_list([str(source.get("object") or source.get("subject") or ""), str(target.get("object") or target.get("subject") or "")])
            evidence = [{"source": edge.source}, {"target": edge.target}]
            conflicts.append(
                Conflict(
                    field=str(source.get("predicate") or target.get("predicate") or "reasoning_conflict"),
                    severity="medium",
                    type="reasoning_conflict",
                    values=values,
                    sources=[],
                    evidence=evidence,
                )
            )
        return conflicts

    def _rank_reasoning_evidence(self, reasoning_context: ReasoningContext) -> List[Dict[str, Any]]:
        evidence = [dict(item) for item in (reasoning_context.evidence or []) if isinstance(item, dict)]
        return sorted(
            evidence,
            key=lambda item: (
                float(item.get("confidence") or 0.0),
                float(item.get("relevance") or 0.0),
                self._source_trust_score(str((item.get("metadata") or {}).get("source_name") or item.get("source_id") or "")),
            ),
            reverse=True,
        )

    def _merge_reasoning_facts(self, reasoning_context: ReasoningContext) -> List[Dict[str, Any]]:
        merged: List[Dict[str, Any]] = []
        for fact in reasoning_context.facts or []:
            merged.append(
                {
                    "key": f"{str(fact.get('subject') or '')}:{str(fact.get('predicate') or '')}:{str(fact.get('object') or '')}",
                    "representative": dict(fact),
                    "evidence": list(fact.get("evidence_ids") or []),
                }
            )
        return merged

    def _infer_contradictions(self, graph: ReasoningGraph, bundle: Dict[str, Any] | None, fact_nodes: Dict[str, str]) -> None:
        if not bundle:
            return
        for item in (bundle.get("conflicts") or []):
            if not isinstance(item, dict):
                continue
            evidence_ids = [str(value) for value in (item.get("evidence_ids") or []) if str(value or "").strip()]
            linked_fact_ids = []
            for fact in (bundle.get("facts") or []):
                if not isinstance(fact, dict):
                    continue
                fact_evidence = {str(value) for value in (fact.get("evidence_ids") or []) if str(value or "").strip()}
                if fact_evidence & set(evidence_ids):
                    linked_fact_ids.append(str(fact.get("fact_id") or fact.get("id") or ""))
            for idx, left in enumerate(linked_fact_ids):
                for right in linked_fact_ids[idx + 1 :]:
                    if not left or not right:
                        continue
                    graph.add_edge(
                        ReasoningEdge(
                            source=fact_nodes.get(left, f"RF::{left}"),
                            target=fact_nodes.get(right, f"RF::{right}"),
                            relation="contradicts",
                            confidence=0.9,
                        )
                    )

    def _coerce_reasoning_context(self, value: Any) -> ReasoningContext | None:
        if isinstance(value, ReasoningContext):
            return value
        if isinstance(value, dict) and {"facts", "evidence", "answer_context"}.issubset(set(value.keys())):
            return ReasoningContext.from_dict(value)
        return None

    def _coerce_evidence_bundle(self, value: Any) -> Dict[str, Any]:
        if isinstance(value, dict) and {"evidences", "facts"}.issubset(set(value.keys())):
            return dict(value)
        if hasattr(value, "to_dict"):
            try:
                return dict(value.to_dict())
            except Exception:
                return {}
        return {}

    def _coerce_answer_context(self, value: Any) -> Dict[str, Any]:
        if isinstance(value, dict):
            return dict(value)
        if hasattr(value, "to_dict"):
            try:
                return dict(value.to_dict())
            except Exception:
                return {}
        return {}

    def _node_metadata(self, graph: ReasoningGraph, node_id: str) -> Dict[str, Any]:
        for node in graph.nodes or []:
            if node.node_id == node_id:
                return dict(node.metadata or {})
        return {}

    def _reasoning_depth(self, graph: ReasoningGraph) -> int:
        derived = len([edge for edge in (graph.edges or []) if edge.relation == "derives"])
        depends = len([edge for edge in (graph.edges or []) if edge.relation == "depends_on"])
        if derived > 0 and depends > 0:
            return 3
        if derived > 0 or depends > 0:
            return 2
        return 1 if graph.nodes else 0

    def _record_metrics(self, graph: ReasoningGraph) -> None:
        self.runtime_metrics.set("reasoning_graph_nodes", float(len(graph.nodes or [])))
        self.runtime_metrics.set("reasoning_graph_edges", float(len(graph.edges or [])))
        self.runtime_metrics.set("reasoning_depth", float(self._reasoning_depth(graph)))
        self.runtime_metrics.set("reasoning_confidence", float(self.compute_reasoning_confidence(graph)))
        self.runtime_metrics.set("derived_conclusion_count", float((graph.metadata or {}).get("derived_conclusion_count") or 0.0))

    def _structured_enabled(self) -> bool:
        return feature_flag_enabled("STRUCTURED_REASONING_ENABLED")

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

    def _trace(self, name: str, metadata: Dict[str, Any] | None = None) -> None:
        if self.trace_center is None:
            return
        self.trace_center.record_event("REASONING", name, metadata=metadata or {})
