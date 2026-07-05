from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

from services.default_evidence_rules import (
    default_confidence,
    default_relevance,
    default_source_authority,
    normalize_domain,
    normalize_source_type,
)
from services.feature_flags import feature_flag_enabled
from services.evidence_graph import EvidenceGraph
from services.evidence_models import Evidence, EvidenceBundle, Fact, Source
from services.evidence_reasoner import EvidenceReasoner
from services.runtime_metrics import get_runtime_metrics


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class EvidenceEngine:
    def __init__(self, trace_center: Any = None, runtime_metrics: Any = None):
        self.trace_center = trace_center
        self.runtime_metrics = runtime_metrics or get_runtime_metrics()

    def ingest_tool_results(
        self,
        tool_results: List[Dict[str, Any]],
        previous_bundle: EvidenceBundle | Dict[str, Any] | None = None,
    ) -> EvidenceBundle:
        self._trace("Evidence Started", metadata={"tool_result_count": len(tool_results or [])})
        evidences, sources = self.extract_evidence(tool_results)
        evidence_graph = self._build_evidence_graph(evidences)
        facts = self.extract_facts(tool_results)
        linked_facts, link_rate = self.link_fact_evidence(facts, evidences)
        conflicts = self.detect_conflicts(linked_facts)
        if evidence_graph is not None:
            reasoner = self._get_evidence_reasoner()
            evidence_graph = reasoner.detect_support_relations(evidence_graph, linked_facts)
            evidence_graph = reasoner.detect_contradictions(evidence_graph, linked_facts)
            evidence_graph = reasoner.detect_extend_relations(evidence_graph, linked_facts)
            evidence_graph.metadata.update(reasoner.compute_confidence(evidence_graph))
            self._record_reasoner_metrics(evidence_graph)
        current_bundle = EvidenceBundle(
            evidences=evidences,
            facts=linked_facts,
            sources=sources,
            conflicts=conflicts,
            metadata={
                "tool_result_count": len(tool_results or []),
                "evidence_link_rate": float(link_rate),
                "created_at": _utc_now_iso(),
                "projection_results": self._project_tool_results(linked_facts, evidences, sources),
                "evidence_graph": evidence_graph.export() if evidence_graph is not None else None,
            },
        )
        merged = self.merge_bundle(previous_bundle, current_bundle)
        self._record_metrics(merged, link_rate)
        self._trace(
            "Evidence Finished",
            metadata={
                "evidence_count": len(merged.evidences or []),
                "fact_count": len(merged.facts or []),
                "source_count": len(merged.sources or []),
                "conflict_count": len(merged.conflicts or []),
            },
        )
        return merged

    def extract_evidence(self, tool_results: List[Dict[str, Any]]) -> Tuple[List[Evidence], List[Source]]:
        evidences: List[Evidence] = []
        sources: List[Source] = []
        seen_evidence_ids = set()
        seen_source_ids = set()
        evidence_counter = 1
        source_counter = 1
        for result_index, result in enumerate(tool_results or [], start=1):
            if not isinstance(result, dict):
                continue
            evidence_items = result.get("evidence")
            if not isinstance(evidence_items, list):
                continue
            for item_index, item in enumerate(evidence_items, start=1):
                if not isinstance(item, dict):
                    continue
                source_name = str(item.get("source_name") or result.get("source_name") or result.get("source") or "").strip()
                source_type = normalize_source_type(str(item.get("type") or source_name or "unknown"))
                url = str(item.get("url") or "").strip()
                domain = normalize_domain(url)
                source_id = str(item.get("source_id") or "").strip() or f"S{source_counter}"
                source_counter += 1
                authority = default_source_authority(source_type, domain)
                if source_id not in seen_source_ids:
                    sources.append(
                        Source(
                            source_id=source_id,
                            source_type=source_type,
                            authority=authority,
                            domain=domain,
                            retrieved_at=str(item.get("updated_at") or item.get("published_at") or _utc_now_iso()),
                            metadata={
                                "source_name": source_name,
                                "title": str(item.get("title") or ""),
                            },
                        )
                    )
                    seen_source_ids.add(source_id)

                evidence_id = str(item.get("id") or item.get("evidence_id") or "").strip() or f"E{evidence_counter}"
                evidence_counter += 1
                if evidence_id in seen_evidence_ids:
                    continue
                snippet = str(item.get("snippet") or item.get("summary") or item.get("text") or "").strip()
                raw_content = str(item.get("raw_content") or item.get("content") or snippet or "").strip()
                confidence = default_confidence(item.get("confidence"), authority)
                relevance = float(item.get("relevance") or default_relevance(str(item.get("title") or ""), snippet, raw_content))
                evidences.append(
                    Evidence(
                        evidence_id=evidence_id,
                        source_id=source_id,
                        source_type=source_type,
                        url=url,
                        title=str(item.get("title") or ""),
                        snippet=snippet,
                        raw_content=raw_content,
                        confidence=confidence,
                        relevance=relevance,
                        created_at=str(item.get("updated_at") or item.get("published_at") or _utc_now_iso()),
                        metadata={
                            "source_name": source_name,
                            "authority": authority,
                            "result_index": result_index,
                            "item_index": item_index,
                        },
                    )
                )
                seen_evidence_ids.add(evidence_id)
                self._trace(
                    "Evidence Extracted",
                    metadata={"evidence_id": evidence_id, "source_id": source_id, "source_type": source_type},
                )
        return evidences, sources

    def extract_facts(self, tool_results: List[Dict[str, Any]]) -> List[Fact]:
        facts: List[Fact] = []
        counter = 1
        seen = set()
        for result in tool_results or []:
            if not isinstance(result, dict):
                continue
            evidence_ids = self._extract_result_evidence_ids(result)
            subject = self._first_text(result, ["org_name", "organization_name", "entity", "entity_name", "name"])
            if subject:
                counter = self._append_fact(
                    facts,
                    seen,
                    counter,
                    subject=subject,
                    predicate="name",
                    object_value=subject,
                    evidence_ids=evidence_ids,
                    metadata={"entity_type": "organization"},
                )
            for predicate, keys in {
                "leader_name": ["leader_name", "leader"],
                "country": ["country"],
                "official_website": ["official_website", "website"],
                "member_count": ["member_count", "member_estimate"],
                "denomination": ["denomination"],
            }.items():
                value = self._first_text(result, keys)
                if not subject or not value:
                    continue
                counter = self._append_fact(
                    facts,
                    seen,
                    counter,
                    subject=subject,
                    predicate=predicate,
                    object_value=value,
                    evidence_ids=evidence_ids,
                    metadata={"field": predicate},
                )
        return facts

    def link_fact_evidence(self, facts: List[Fact], evidences: List[Evidence]) -> Tuple[List[Fact], float]:
        evidence_lookup = {item.evidence_id: item for item in (evidences or [])}
        linked: List[Fact] = []
        linked_count = 0
        for fact in facts or []:
            evidence_ids = [eid for eid in (fact.evidence_ids or []) if eid in evidence_lookup]
            if not evidence_ids:
                matches = self._match_evidence_ids(fact, evidences)
                evidence_ids = list(matches or [])
            if evidence_ids:
                linked_count += 1
                self._trace(
                    "Evidence Linked",
                    metadata={"fact_id": fact.fact_id, "evidence_ids": list(evidence_ids or [])},
                )
            linked.append(
                Fact(
                    fact_id=fact.fact_id,
                    subject=fact.subject,
                    predicate=fact.predicate,
                    object=fact.object,
                    evidence_ids=list(evidence_ids or []),
                    confidence=max(float(fact.confidence or 0.0), self._linked_confidence(evidence_ids, evidence_lookup)),
                    metadata=dict(fact.metadata or {}),
                )
            )
        rate = round(linked_count / len(facts), 3) if facts else 0.0
        return linked, rate

    def detect_conflicts(self, facts: List[Fact]) -> List[Dict[str, Any]]:
        grouped: Dict[Tuple[str, str], List[Fact]] = {}
        for fact in facts or []:
            key = (str(fact.subject or "").strip().lower(), str(fact.predicate or "").strip().lower())
            grouped.setdefault(key, []).append(fact)
        conflicts: List[Dict[str, Any]] = []
        for (_subject_key, predicate_key), items in grouped.items():
            values = sorted({str(item.object or "").strip() for item in items if str(item.object or "").strip()})
            if len(values) < 2:
                continue
            subject = items[0].subject if items else ""
            conflict = {
                "subject": subject,
                "predicate": predicate_key,
                "values": values,
                "fact_ids": [item.fact_id for item in items],
                "evidence_ids": self._dedupe_list([evidence_id for item in items for evidence_id in (item.evidence_ids or [])]),
            }
            conflicts.append(conflict)
            self._trace("Conflict Detected", metadata=conflict)
        return conflicts

    def merge_bundle(
        self,
        previous_bundle: EvidenceBundle | Dict[str, Any] | None,
        current_bundle: EvidenceBundle | Dict[str, Any],
    ) -> EvidenceBundle:
        current = current_bundle if isinstance(current_bundle, EvidenceBundle) else EvidenceBundle.from_dict(current_bundle or {})
        previous = previous_bundle if isinstance(previous_bundle, EvidenceBundle) else EvidenceBundle.from_dict(previous_bundle or {})
        evidence_map: Dict[str, Evidence] = {}
        for item in [*list(previous.evidences or []), *list(current.evidences or [])]:
            evidence_map[str(item.evidence_id)] = item
        fact_map: Dict[str, Fact] = {}
        for item in [*list(previous.facts or []), *list(current.facts or [])]:
            fact_map[str(item.fact_id)] = item
        source_map: Dict[str, Source] = {}
        for item in [*list(previous.sources or []), *list(current.sources or [])]:
            source_map[str(item.source_id)] = item
        merged_conflicts = self._dedupe_dict_list([*list(previous.conflicts or []), *list(current.conflicts or [])])
        merged_graph = self._merge_evidence_graphs(previous, current)
        return EvidenceBundle(
            evidences=list(evidence_map.values()),
            facts=list(fact_map.values()),
            sources=list(source_map.values()),
            conflicts=merged_conflicts,
            metadata={
                **dict(previous.metadata or {}),
                **dict(current.metadata or {}),
                "projection_results": self._project_tool_results(list(fact_map.values()), list(evidence_map.values()), list(source_map.values())),
                "evidence_graph": merged_graph.export() if merged_graph is not None else None,
            },
        )

    def export_bundle(self, bundle: EvidenceBundle | Dict[str, Any]) -> Dict[str, Any]:
        if isinstance(bundle, EvidenceBundle):
            return bundle.to_dict()
        return EvidenceBundle.from_dict(bundle or {}).to_dict()

    def _append_fact(
        self,
        facts: List[Fact],
        seen: set,
        counter: int,
        *,
        subject: str,
        predicate: str,
        object_value: str,
        evidence_ids: List[str],
        metadata: Dict[str, Any] | None = None,
    ) -> int:
        key = (str(subject or "").strip().lower(), str(predicate or "").strip().lower(), str(object_value or "").strip().lower())
        if key in seen or not key[0] or not key[1] or not key[2]:
            return counter
        seen.add(key)
        fact = Fact(
            fact_id=f"F{counter}",
            subject=subject,
            predicate=predicate,
            object=object_value,
            evidence_ids=list(evidence_ids or []),
            confidence=0.0,
            metadata=dict(metadata or {}),
        )
        facts.append(fact)
        self._trace(
            "Fact Extracted",
            metadata={"fact_id": fact.fact_id, "subject": fact.subject, "predicate": fact.predicate},
        )
        return counter + 1

    def _extract_result_evidence_ids(self, result: Dict[str, Any]) -> List[str]:
        ids: List[str] = []
        evidence_items = result.get("evidence")
        if not isinstance(evidence_items, list):
            return []
        for item in evidence_items:
            if not isinstance(item, dict):
                continue
            evidence_id = str(item.get("id") or item.get("evidence_id") or "").strip()
            if evidence_id:
                ids.append(evidence_id)
        return self._dedupe_list(ids)

    def _match_evidence_ids(self, fact: Fact, evidences: List[Evidence]) -> List[str]:
        matches: List[str] = []
        subject = str(fact.subject or "").strip().lower()
        object_value = str(fact.object or "").strip().lower()
        for item in evidences or []:
            haystack = " ".join(
                [
                    str(item.title or ""),
                    str(item.snippet or ""),
                    str(item.raw_content or ""),
                    str((item.metadata or {}).get("source_name") or ""),
                ]
            ).lower()
            if subject and subject in haystack:
                matches.append(item.evidence_id)
                continue
            if object_value and object_value in haystack:
                matches.append(item.evidence_id)
        return self._dedupe_list(matches)

    def _linked_confidence(self, evidence_ids: List[str], evidence_lookup: Dict[str, Evidence]) -> float:
        scores = [float(evidence_lookup[eid].confidence or 0.0) for eid in (evidence_ids or []) if eid in evidence_lookup]
        if not scores:
            return 0.0
        return round(sum(scores) / len(scores), 3)

    def _project_tool_results(
        self,
        facts: List[Fact],
        evidences: List[Evidence],
        sources: List[Source],
    ) -> List[Dict[str, Any]]:
        evidence_lookup = {item.evidence_id: item for item in (evidences or [])}
        source_lookup = {item.source_id: item for item in (sources or [])}
        grouped: Dict[str, Dict[str, Any]] = {}
        for evidence in evidences or []:
            source = source_lookup.get(evidence.source_id)
            grouped[evidence.evidence_id] = {
                "source_name": str((evidence.metadata or {}).get("source_name") or (source.metadata or {}).get("source_name") or ""),
                "source": str((evidence.metadata or {}).get("source_name") or (source.metadata or {}).get("source_name") or ""),
                "title": evidence.title,
                "url": evidence.url,
                "type": evidence.source_type,
                "evidence": [
                    {
                        "id": evidence.evidence_id,
                        "title": evidence.title,
                        "snippet": evidence.snippet,
                        "url": evidence.url,
                        "source_name": str((evidence.metadata or {}).get("source_name") or ""),
                        "confidence": float(evidence.confidence),
                        "published_at": evidence.created_at,
                        "updated_at": evidence.created_at,
                        "type": evidence.source_type,
                        "authority": float((source.authority if source is not None else (evidence.metadata or {}).get("authority") or 0.0)),
                    }
                ],
            }
        for fact in facts or []:
            for evidence_id in (fact.evidence_ids or []):
                projected = grouped.get(evidence_id)
                if projected is None:
                    continue
                if fact.predicate == "name":
                    projected["org_name"] = fact.subject
                    projected["name"] = fact.object
                elif fact.predicate in {"leader_name", "country", "official_website", "member_count", "denomination"}:
                    projected[fact.predicate] = fact.object
                    projected.setdefault("org_name", fact.subject)
                projected.setdefault("_fact_ids", []).append(fact.fact_id)
        return list(grouped.values())

    def _record_metrics(self, bundle: EvidenceBundle, link_rate: float) -> None:
        self.runtime_metrics.inc("evidence_count", value=float(len(bundle.evidences or [])))
        self.runtime_metrics.inc("fact_count", value=float(len(bundle.facts or [])))
        self.runtime_metrics.inc("source_count", value=float(len(bundle.sources or [])))
        self.runtime_metrics.inc("conflict_count", value=float(len(bundle.conflicts or [])))
        self.runtime_metrics.set("evidence_link_rate", float(link_rate or 0.0))
        for fact in bundle.facts or []:
            self.runtime_metrics.observe("fact_confidence", float(fact.confidence or 0.0))
        for source in bundle.sources or []:
            self.runtime_metrics.observe("source_authority", float(source.authority or 0.0))

    def _build_evidence_graph(self, evidences: List[Evidence]) -> EvidenceGraph | None:
        if not self._evidence_reasoner_enabled():
            return None
        return self._get_evidence_reasoner().build_graph(evidences)

    def _get_evidence_reasoner(self) -> EvidenceReasoner:
        return EvidenceReasoner(trace_center=self.trace_center, runtime_metrics=self.runtime_metrics)

    def _merge_evidence_graphs(self, previous: EvidenceBundle, current: EvidenceBundle) -> EvidenceGraph | None:
        if not self._evidence_reasoner_enabled():
            return None
        previous_graph_payload = dict((previous.metadata or {}).get("evidence_graph") or {})
        current_graph_payload = dict((current.metadata or {}).get("evidence_graph") or {})
        if not previous_graph_payload and not current_graph_payload:
            return None
        previous_graph = EvidenceGraph.from_dict(previous_graph_payload) if previous_graph_payload else EvidenceGraph()
        current_graph = EvidenceGraph.from_dict(current_graph_payload) if current_graph_payload else EvidenceGraph()
        merged_graph = previous_graph.merge(current_graph)
        merged_graph.metadata.update(self._get_evidence_reasoner().compute_confidence(merged_graph))
        return merged_graph

    def _record_reasoner_metrics(self, graph: EvidenceGraph) -> None:
        metrics = dict(graph.metadata or {})
        self.runtime_metrics.set("evidence_graph_nodes", float(metrics.get("node_count") or len(graph.nodes or [])))
        self.runtime_metrics.set("evidence_graph_edges", float(metrics.get("edge_count") or len(graph.edges or [])))
        self.runtime_metrics.set("duplicate_evidence", float(metrics.get("duplicate_evidence") or 0.0))
        self.runtime_metrics.set("supported_facts", float(metrics.get("supported_facts") or 0.0))
        self.runtime_metrics.set("contradicted_facts", float(metrics.get("contradicted_facts") or 0.0))
        self.runtime_metrics.set("average_evidence_confidence", float(metrics.get("average_evidence_confidence") or 0.0))

    def _evidence_reasoner_enabled(self) -> bool:
        return feature_flag_enabled("EVIDENCE_REASONER_ENABLED")

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
        return self._dedupe_list(collected)

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

    def _dedupe_dict_list(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        seen = set()
        out: List[Dict[str, Any]] = []
        for item in items or []:
            if not isinstance(item, dict):
                continue
            key = (
                str(item.get("subject") or "").strip().lower(),
                str(item.get("predicate") or "").strip().lower(),
                "|".join(sorted(str(value or "").strip().lower() for value in (item.get("values") or []))),
            )
            if key in seen:
                continue
            seen.add(key)
            out.append(dict(item))
        return out

    def _trace(self, name: str, metadata: Dict[str, Any] | None = None) -> None:
        if self.trace_center is None:
            return
        self.trace_center.record_event("EVIDENCE", name, metadata=metadata or {})
