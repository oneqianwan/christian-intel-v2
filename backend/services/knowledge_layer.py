from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

from services.evidence_models import EvidenceBundle
from services.execution_policy import ExecutionPolicyContext, ExecutionPolicyEngine
from services.runtime_metrics import get_runtime_metrics


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class KnowledgeNode:
    id: str
    type: str
    name: str
    properties: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    sources: List[str] = field(default_factory=list)
    evidence_ids: List[str] = field(default_factory=list)
    updated_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "name": self.name,
            "properties": dict(self.properties or {}),
            "confidence": float(self.confidence),
            "sources": list(self.sources or []),
            "evidence_ids": list(self.evidence_ids or []),
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "KnowledgeNode":
        payload = data or {}
        return cls(
            id=str(payload.get("id") or ""),
            type=str(payload.get("type") or ""),
            name=str(payload.get("name") or ""),
            properties=dict(payload.get("properties") or {}),
            confidence=float(payload.get("confidence") or 0.0),
            sources=list(payload.get("sources") or []),
            evidence_ids=list(payload.get("evidence_ids") or []),
            updated_at=str(payload.get("updated_at") or ""),
        )


@dataclass(frozen=True)
class KnowledgeRelation:
    id: str
    source_node: str
    target_node: str
    relation: str
    confidence: float = 0.0
    evidence_ids: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "source_node": self.source_node,
            "target_node": self.target_node,
            "relation": self.relation,
            "confidence": float(self.confidence),
            "evidence_ids": list(self.evidence_ids or []),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "KnowledgeRelation":
        payload = data or {}
        return cls(
            id=str(payload.get("id") or ""),
            source_node=str(payload.get("source_node") or ""),
            target_node=str(payload.get("target_node") or ""),
            relation=str(payload.get("relation") or ""),
            confidence=float(payload.get("confidence") or 0.0),
            evidence_ids=list(payload.get("evidence_ids") or []),
        )


@dataclass(frozen=True)
class KnowledgeGraph:
    nodes: List[KnowledgeNode] = field(default_factory=list)
    relations: List[KnowledgeRelation] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "nodes": [item.to_dict() for item in (self.nodes or [])],
            "relations": [item.to_dict() for item in (self.relations or [])],
            "metadata": dict(self.metadata or {}),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "KnowledgeGraph":
        payload = data or {}
        return cls(
            nodes=[KnowledgeNode.from_dict(item) for item in (payload.get("nodes") or []) if isinstance(item, dict)],
            relations=[KnowledgeRelation.from_dict(item) for item in (payload.get("relations") or []) if isinstance(item, dict)],
            metadata=dict(payload.get("metadata") or {}),
        )


class KnowledgeLayer:
    def __init__(self, trace_center: Any = None):
        self.trace_center = trace_center
        self.runtime_metrics = get_runtime_metrics()

    def ingest_tool_results(
        self,
        tool_results: List[Dict[str, Any]] | EvidenceBundle | Dict[str, Any],
        previous_graph: KnowledgeGraph | Dict[str, Any] | None = None,
    ) -> KnowledgeGraph:
        started = time.perf_counter()
        restored_graph = self.load_previous_graph(previous_graph)
        evidence_bundle = self._coerce_evidence_bundle(tool_results)
        projected_results = self._projected_results(tool_results, evidence_bundle)
        evidence_index = self._build_evidence_index(projected_results, previous_graph=restored_graph, evidence_bundle=evidence_bundle)
        nodes = self._extract_nodes(projected_results, evidence_index)
        relations = self._extract_relations(projected_results, evidence_index, nodes)
        merge_decision = self._get_execution_policy_engine().evaluate_knowledge_merge(
            ExecutionPolicyContext(
                question_type="KNOWLEDGE",
                knowledge={
                    "operation": "merge",
                    "has_previous_graph": bool(restored_graph.nodes or restored_graph.relations),
                    "node_count": len(nodes or []),
                    "relation_count": len(relations or []),
                },
                tool_results=list(projected_results or []),
            ),
            default_decision=True,
        )
        previous_nodes = list(restored_graph.nodes or []) if bool(merge_decision.decision) else []
        previous_relations = list(restored_graph.relations or []) if bool(merge_decision.decision) else []

        merge_started = time.perf_counter()
        merged_nodes, node_merge_count, node_aliases = self.merge_nodes(previous_nodes + nodes)
        merged_relations, relation_merge_count = self.merge_relations(previous_relations + relations, node_aliases=node_aliases)
        merge_duration_ms = round((time.perf_counter() - merge_started) * 1000, 2)

        graph = self.calculate_confidence(
            KnowledgeGraph(
                nodes=merged_nodes,
                relations=merged_relations,
                metadata={
                    "restored_from_memory": bool(restored_graph.nodes or restored_graph.relations),
                    "previous_node_count": len(previous_nodes),
                    "previous_relation_count": len(previous_relations),
                    "tool_result_count": int((evidence_bundle.metadata or {}).get("tool_result_count") or len(projected_results or []))
                    if evidence_bundle is not None
                    else len(projected_results or []),
                    "evidence_count": len(evidence_index),
                    "fact_count": len(evidence_bundle.facts or []) if evidence_bundle is not None else 0,
                    "source_count": len(evidence_bundle.sources or []) if evidence_bundle is not None else 0,
                    "node_count": len(merged_nodes),
                    "relation_count": len(merged_relations),
                    "node_merge_count": node_merge_count,
                    "relation_merge_count": relation_merge_count,
                    "merge_time_ms": merge_duration_ms,
                    "updated_at": _utc_now_iso(),
                    "evidence_index": {key: dict(value) for key, value in evidence_index.items()},
                },
            ),
            evidence_index=evidence_index,
        )

        total_duration_ms = round((time.perf_counter() - started) * 1000, 2)
        graph = KnowledgeGraph(
            nodes=list(graph.nodes or []),
            relations=list(graph.relations or []),
            metadata={
                **dict(graph.metadata or {}),
                "ingest_time_ms": total_duration_ms,
            },
        )
        self.runtime_metrics.inc("knowledge_merge_count")
        self.runtime_metrics.observe("knowledge.merge.time_ms", merge_duration_ms)
        self.runtime_metrics.set("knowledge_node_count", float(len(graph.nodes or [])))
        self.runtime_metrics.set("knowledge_relation_count", float(len(graph.relations or [])))

        self._trace(
            "KNOWLEDGE_LAYER",
            "Knowledge Nodes",
            metadata={"count": len(graph.nodes or [])},
        )
        self._trace(
            "KNOWLEDGE_LAYER",
            "Knowledge Relations",
            metadata={"count": len(graph.relations or [])},
        )
        self._trace(
            "KNOWLEDGE_LAYER",
            "Merge Count",
            metadata={"node_merge_count": node_merge_count, "relation_merge_count": relation_merge_count},
        )
        self._trace(
            "KNOWLEDGE_LAYER",
            "Merge Time",
            metadata={"duration_ms": merge_duration_ms},
        )
        self._trace(
            "KNOWLEDGE_LAYER",
            "Confidence Updated",
            metadata={
                "node_count": len(graph.nodes or []),
                "relation_count": len(graph.relations or []),
            },
        )
        return graph

    def load_previous_graph(self, previous_graph: KnowledgeGraph | Dict[str, Any] | None) -> KnowledgeGraph:
        if isinstance(previous_graph, KnowledgeGraph):
            return previous_graph
        if isinstance(previous_graph, dict) and ("nodes" in previous_graph or "relations" in previous_graph):
            return KnowledgeGraph.from_dict(previous_graph)
        return KnowledgeGraph()

    def merge_nodes(self, nodes: List[KnowledgeNode]) -> Tuple[List[KnowledgeNode], int, Dict[str, str]]:
        grouped: Dict[Tuple[str, str], KnowledgeNode] = {}
        aliases: Dict[str, str] = {}
        merge_count = 0
        for node in nodes or []:
            key = (self._normalize_node_type(node.type), self._normalize_name(node.name))
            if key[1] == "":
                key = (self._normalize_node_type(node.type), node.id)
            existing = grouped.get(key)
            if existing is None:
                grouped[key] = node
                aliases[node.id] = node.id
                continue
            merge_count += 1
            aliases[node.id] = existing.id
            grouped[key] = KnowledgeNode(
                id=existing.id,
                type=existing.type or node.type,
                name=existing.name if len(existing.name or "") >= len(node.name or "") else node.name,
                properties=self._merge_properties(existing.properties, node.properties),
                confidence=max(float(existing.confidence or 0.0), float(node.confidence or 0.0)),
                sources=self._dedupe_list([*existing.sources, *node.sources]),
                evidence_ids=self._dedupe_list([*existing.evidence_ids, *node.evidence_ids]),
                updated_at=self._latest_timestamp(existing.updated_at, node.updated_at),
            )
        return list(grouped.values()), merge_count, aliases

    def merge_relations(
        self,
        relations: List[KnowledgeRelation],
        *,
        node_aliases: Dict[str, str] | None = None,
    ) -> Tuple[List[KnowledgeRelation], int]:
        node_aliases = dict(node_aliases or {})
        grouped: Dict[Tuple[str, str, str], KnowledgeRelation] = {}
        merge_count = 0
        for relation in relations or []:
            source_node = node_aliases.get(relation.source_node, relation.source_node)
            target_node = node_aliases.get(relation.target_node, relation.target_node)
            key = (source_node, target_node, self._normalize_relation_name(relation.relation))
            existing = grouped.get(key)
            current = KnowledgeRelation(
                id=relation.id,
                source_node=source_node,
                target_node=target_node,
                relation=self._normalize_relation_name(relation.relation),
                confidence=float(relation.confidence or 0.0),
                evidence_ids=self._dedupe_list(list(relation.evidence_ids or [])),
            )
            if existing is None:
                grouped[key] = current
                continue
            merge_count += 1
            grouped[key] = KnowledgeRelation(
                id=existing.id,
                source_node=existing.source_node,
                target_node=existing.target_node,
                relation=existing.relation,
                confidence=max(float(existing.confidence or 0.0), float(current.confidence or 0.0)),
                evidence_ids=self._dedupe_list([*existing.evidence_ids, *current.evidence_ids]),
            )
        return list(grouped.values()), merge_count

    def calculate_confidence(
        self,
        graph: KnowledgeGraph,
        *,
        evidence_index: Dict[str, Dict[str, Any]] | None = None,
    ) -> KnowledgeGraph:
        evidence_index = dict(evidence_index or {})
        recalculated_nodes: List[KnowledgeNode] = []
        for node in graph.nodes or []:
            recalculated_nodes.append(
                KnowledgeNode(
                    id=node.id,
                    type=node.type,
                    name=node.name,
                    properties=dict(node.properties or {}),
                    confidence=self._calculate_from_evidence(node.evidence_ids, evidence_index, fallback=node.confidence),
                    sources=list(node.sources or []),
                    evidence_ids=list(node.evidence_ids or []),
                    updated_at=node.updated_at,
                )
            )
        recalculated_relations: List[KnowledgeRelation] = []
        for relation in graph.relations or []:
            recalculated_relations.append(
                KnowledgeRelation(
                    id=relation.id,
                    source_node=relation.source_node,
                    target_node=relation.target_node,
                    relation=relation.relation,
                    confidence=self._calculate_from_evidence(relation.evidence_ids, evidence_index, fallback=relation.confidence),
                    evidence_ids=list(relation.evidence_ids or []),
                )
            )
        return KnowledgeGraph(
            nodes=recalculated_nodes,
            relations=recalculated_relations,
            metadata=dict(graph.metadata or {}),
        )

    def export_graph(self, graph: KnowledgeGraph | Dict[str, Any]) -> Dict[str, Any]:
        if isinstance(graph, KnowledgeGraph):
            return graph.to_dict()
        if isinstance(graph, dict):
            return KnowledgeGraph.from_dict(graph).to_dict()
        return KnowledgeGraph().to_dict()

    def _build_evidence_index(
        self,
        tool_results: List[Dict[str, Any]],
        *,
        previous_graph: KnowledgeGraph | None = None,
        evidence_bundle: EvidenceBundle | None = None,
    ) -> Dict[str, Dict[str, Any]]:
        index: Dict[str, Dict[str, Any]] = {}
        if previous_graph is not None:
            previous_index = dict((previous_graph.metadata or {}).get("evidence_index") or {})
            for evidence_id, item in previous_index.items():
                if isinstance(item, dict) and evidence_id not in index:
                    index[str(evidence_id)] = dict(item)
        counter = len(index) + 1
        if evidence_bundle is not None:
            sources = {str(item.source_id): item for item in (evidence_bundle.sources or [])}
            for item in evidence_bundle.evidences or []:
                source = sources.get(str(item.source_id))
                source_name = ""
                authority = 0.0
                if source is not None:
                    source_name = str((source.metadata or {}).get("source_name") or "")
                    authority = float(source.authority or 0.0)
                if not source_name:
                    source_name = str((item.metadata or {}).get("source_name") or "")
                if authority <= 0.0:
                    authority = float((item.metadata or {}).get("authority") or 0.0)
                evidence_id = str(item.evidence_id or "").strip() or f"E{counter}"
                counter += 1
                if evidence_id in index:
                    continue
                index[evidence_id] = {
                    "id": evidence_id,
                    "source_id": str(item.source_id or ""),
                    "source_name": source_name,
                    "title": str(item.title or ""),
                    "snippet": str(item.snippet or ""),
                    "url": str(item.url or ""),
                    "type": str(item.source_type or ""),
                    "confidence": self._to_float(item.confidence),
                    "authority": self._to_float(authority),
                    "updated_at": str(item.created_at or ""),
                    "published_at": str(item.created_at or ""),
                    "raw_content": str(item.raw_content or ""),
                }
            return index
        for result in tool_results or []:
            if not isinstance(result, dict):
                continue
            evidence_list = result.get("evidence")
            if not isinstance(evidence_list, list):
                continue
            for item in evidence_list:
                if not isinstance(item, dict):
                    continue
                evidence_id = str(item.get("id") or "").strip() or f"E{counter}"
                counter += 1
                if evidence_id in index:
                    continue
                index[evidence_id] = {
                    **item,
                    "id": evidence_id,
                    "source_name": str(item.get("source_name") or ""),
                    "confidence": self._to_float(item.get("confidence")),
                    "updated_at": str(item.get("updated_at") or item.get("published_at") or ""),
                }
        return index

    def _coerce_evidence_bundle(self, value: Any) -> EvidenceBundle | None:
        if isinstance(value, EvidenceBundle):
            return value
        if isinstance(value, dict) and ("evidences" in value or "facts" in value or "sources" in value):
            return EvidenceBundle.from_dict(value)
        return None

    def _projected_results(
        self,
        value: List[Dict[str, Any]] | EvidenceBundle | Dict[str, Any],
        evidence_bundle: EvidenceBundle | None,
    ) -> List[Dict[str, Any]]:
        if evidence_bundle is not None:
            projected = list((evidence_bundle.metadata or {}).get("projection_results") or [])
            return [dict(item) for item in projected if isinstance(item, dict)]
        return [dict(item) for item in (value or []) if isinstance(item, dict)]

    def _extract_nodes(self, tool_results: List[Dict[str, Any]], evidence_index: Dict[str, Dict[str, Any]]) -> List[KnowledgeNode]:
        nodes: List[KnowledgeNode] = []
        counter = 1
        for result in tool_results or []:
            if not isinstance(result, dict):
                continue
            evidence_ids = self._collect_result_evidence_ids(result, evidence_index)
            sources = self._sources_from_evidence_ids(evidence_ids, evidence_index)
            updated_at = self._latest_evidence_timestamp(evidence_ids, evidence_index)

            for node_type, name, properties in self._node_candidates_from_result(result):
                if not str(name or "").strip():
                    continue
                nodes.append(
                    KnowledgeNode(
                        id=f"KN{counter}",
                        type=node_type,
                        name=str(name or "").strip(),
                        properties=dict(properties or {}),
                        confidence=0.0,
                        sources=sources,
                        evidence_ids=evidence_ids,
                        updated_at=updated_at,
                    )
                )
                counter += 1
        return nodes

    def _extract_relations(
        self,
        tool_results: List[Dict[str, Any]],
        evidence_index: Dict[str, Dict[str, Any]],
        nodes: List[KnowledgeNode],
    ) -> List[KnowledgeRelation]:
        node_lookup = {(self._normalize_node_type(node.type), self._normalize_name(node.name)): node.id for node in (nodes or [])}
        relations: List[KnowledgeRelation] = []
        counter = 1
        for result in tool_results or []:
            if not isinstance(result, dict):
                continue
            evidence_ids = self._collect_result_evidence_ids(result, evidence_index)
            candidates = self._relation_candidates_from_result(result)
            for source_type, source_name, relation_name, target_type, target_name in candidates:
                source_id = node_lookup.get((self._normalize_node_type(source_type), self._normalize_name(source_name)))
                target_id = node_lookup.get((self._normalize_node_type(target_type), self._normalize_name(target_name)))
                if not source_id or not target_id:
                    continue
                relations.append(
                    KnowledgeRelation(
                        id=f"KR{counter}",
                        source_node=source_id,
                        target_node=target_id,
                        relation=relation_name,
                        confidence=0.0,
                        evidence_ids=list(evidence_ids or []),
                    )
                )
                counter += 1
        return relations

    def _node_candidates_from_result(self, result: Dict[str, Any]) -> List[Tuple[str, str, Dict[str, Any]]]:
        candidates: List[Tuple[str, str, Dict[str, Any]]] = []
        org_name = self._first_text(result, ["org_name", "organization_name", "entity", "entity_name", "name"])
        if org_name:
            candidates.append(
                (
                    "organization",
                    org_name,
                    {
                        "country": self._first_text(result, ["country"]),
                        "leader_name": self._first_text(result, ["leader_name", "leader"]),
                        "official_website": self._first_text(result, ["official_website", "website"]),
                        "member_count": self._first_text(result, ["member_count", "member_estimate"]),
                        "denomination": self._first_text(result, ["denomination"]),
                    },
                )
            )
        leader_name = self._first_text(result, ["leader_name", "leader"])
        if leader_name:
            candidates.append(("person", leader_name, {}))
        country_name = self._first_text(result, ["country"])
        if country_name:
            candidates.append(("country", country_name, {}))
        source_name = self._first_text(result, ["source_name", "source"])
        if source_name:
            candidates.append(("source", source_name, {}))
        return candidates

    def _relation_candidates_from_result(self, result: Dict[str, Any]) -> List[Tuple[str, str, str, str, str]]:
        candidates: List[Tuple[str, str, str, str, str]] = []
        org_name = self._first_text(result, ["org_name", "organization_name", "entity", "entity_name", "name"])
        leader_name = self._first_text(result, ["leader_name", "leader"])
        country_name = self._first_text(result, ["country"])
        if org_name and leader_name:
            candidates.append(("organization", org_name, "LED_BY", "person", leader_name))
        if org_name and country_name:
            candidates.append(("organization", org_name, "LOCATED_IN", "country", country_name))
        return candidates

    def _collect_result_evidence_ids(self, result: Dict[str, Any], evidence_index: Dict[str, Dict[str, Any]]) -> List[str]:
        evidence_ids: List[str] = []
        evidence_list = result.get("evidence")
        if isinstance(evidence_list, list):
            for item in evidence_list:
                if not isinstance(item, dict):
                    continue
                candidate_id = str(item.get("id") or "").strip()
                if candidate_id and candidate_id in evidence_index:
                    evidence_ids.append(candidate_id)
                    continue
                for known_id, evidence in evidence_index.items():
                    if (
                        str(item.get("url") or "") == str(evidence.get("url") or "")
                        and str(item.get("title") or "") == str(evidence.get("title") or "")
                    ):
                        evidence_ids.append(known_id)
                        break
        return self._dedupe_list(evidence_ids)

    def _sources_from_evidence_ids(self, evidence_ids: List[str], evidence_index: Dict[str, Dict[str, Any]]) -> List[str]:
        return self._dedupe_list(
            [
                str(evidence_index[eid].get("source_name") or "").strip()
                for eid in (evidence_ids or [])
                if eid in evidence_index and str(evidence_index[eid].get("source_name") or "").strip()
            ]
        )

    def _latest_evidence_timestamp(self, evidence_ids: List[str], evidence_index: Dict[str, Dict[str, Any]]) -> str:
        timestamps = [
            str(evidence_index[eid].get("updated_at") or "")
            for eid in (evidence_ids or [])
            if eid in evidence_index and str(evidence_index[eid].get("updated_at") or "")
        ]
        latest = ""
        latest_value = 0.0
        for item in timestamps:
            current = self._parse_time(item)
            if current >= latest_value:
                latest = item
                latest_value = current
        return latest

    def _calculate_from_evidence(
        self,
        evidence_ids: List[str],
        evidence_index: Dict[str, Dict[str, Any]],
        *,
        fallback: float = 0.0,
    ) -> float:
        scores = []
        for evidence_id in evidence_ids or []:
            evidence = evidence_index.get(evidence_id)
            if not evidence:
                continue
            scores.append(self._to_float(evidence.get("confidence")))
        if not scores:
            return round(float(fallback or 0.0), 3)
        return round(max(scores) * 0.6 + (sum(scores) / len(scores)) * 0.4, 3)

    def _merge_properties(self, left: Dict[str, Any], right: Dict[str, Any]) -> Dict[str, Any]:
        merged = dict(left or {})
        conflicts = dict(merged.get("_conflicts") or {})
        for key, value in (right or {}).items():
            if value in (None, "", [], {}):
                continue
            if key == "_conflicts":
                continue
            if key not in merged or merged.get(key) in (None, "", [], {}):
                merged[key] = value
                continue
            existing = merged.get(key)
            if existing != value and not isinstance(existing, (dict, list)) and not isinstance(value, (dict, list)):
                conflict_decision = self._get_execution_policy_engine().evaluate_conflict(
                    ExecutionPolicyContext(
                        question_type="KNOWLEDGE",
                        knowledge={
                            "operation": "conflict",
                            "field": str(key or ""),
                            "existing_value": existing,
                            "new_value": value,
                        },
                    ),
                    default_decision={"preserve_existing": True, "overwrite": False},
                )
                values = [str(existing), str(value)]
                historical = [str(item) for item in (conflicts.get(key) or []) if str(item)]
                conflicts[key] = self._dedupe_list([*historical, *values])
                decision_payload = dict(conflict_decision.decision or {})
                if bool(decision_payload.get("overwrite")):
                    merged[key] = value
        if conflicts:
            merged["_conflicts"] = conflicts
        return merged

    def _first_text(self, payload: Any, keys: List[str]) -> str:
        values = self._collect_values(payload, keys)
        return values[0] if values else ""

    def _collect_values(self, payload: Any, keys: List[str]) -> List[str]:
        collected: List[str] = []
        if isinstance(payload, dict):
            for key in keys:
                if key in payload and payload.get(key) not in (None, ""):
                    collected.append(str(payload.get(key)).strip())
            for value in payload.values():
                if isinstance(value, (dict, list)):
                    collected.extend(self._collect_values(value, keys))
        elif isinstance(payload, list):
            for item in payload[:50]:
                collected.extend(self._collect_values(item, keys))
        return [item for item in self._dedupe_list(collected) if item]

    def _normalize_name(self, value: str) -> str:
        return " ".join(str(value or "").strip().lower().split())

    def _normalize_node_type(self, value: str) -> str:
        lowered = str(value or "").strip().lower()
        aliases = {
            "org": "organization",
            "organisation": "organization",
            "person": "person",
            "people": "person",
            "country": "country",
            "source": "source",
        }
        return aliases.get(lowered, lowered or "entity")

    def _normalize_relation_name(self, value: str) -> str:
        return str(value or "").strip().upper() or "RELATED_TO"

    def _latest_timestamp(self, left: str, right: str) -> str:
        return left if self._parse_time(left) >= self._parse_time(right) else right

    def _parse_time(self, value: Any) -> float:
        if not value:
            return 0.0
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value).strip()
        if not text:
            return 0.0
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
        except Exception:
            return 0.0

    def _to_float(self, value: Any) -> float:
        try:
            return float(value or 0.0)
        except Exception:
            return 0.0

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

    def _trace(self, stage: str, event_name: str, metadata: Dict[str, Any] | None = None) -> None:
        if self.trace_center is None:
            return
        self.trace_center.record_event(stage, event_name, metadata=metadata or {})

    def _get_execution_policy_engine(self) -> ExecutionPolicyEngine:
        return ExecutionPolicyEngine(trace_center=self.trace_center)
