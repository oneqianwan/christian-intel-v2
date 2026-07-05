from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Tuple

from services.answer_models import AnswerContext as BuiltAnswerContext
from services.answer_models import AnswerFact as BuiltAnswerFact
from services.answer_models import AnswerSection as BuiltAnswerSection
from services.core_models import AnswerContext, Conflict, Evidence, Fact, QuestionContext, QuestionType, Requirement, Section
from services.knowledge_layer import KnowledgeGraph, KnowledgeNode, KnowledgeRelation


class AnswerComposer:
    def __init__(self):
        self._authority_scores = {
            "arda": 0.95,
            "pew": 0.95,
            "pew research": 0.95,
            "joshua": 0.90,
            "joshua project": 0.90,
            "manual_seed": 0.95,
            "official": 0.90,
            "official_website": 0.90,
            "wikidata": 0.85,
            "wikipedia": 0.75,
            "reuters": 0.70,
            "ap": 0.70,
            "bbc": 0.70,
            "cnn": 0.70,
            "rss": 0.60,
            "newsapi": 0.55,
            "unknown": 0.30,
        }

    def compose(
        self,
        question_context: QuestionContext,
        requirement: Requirement,
        knowledge_input: Any,
        memory_context: Any = None,
    ) -> AnswerContext:
        built_context = self._ensure_built_context(knowledge_input)
        if built_context is not None:
            return self._compose_from_built_context(question_context, requirement, built_context, memory_context=memory_context)

        graph = self._ensure_graph(knowledge_input)
        if graph is not None:
            evidence = self._rank_evidence(self._evidence_from_graph(graph), requirement)
            facts = self._facts_from_graph(graph, requirement)
            facts = self._enrich_facts_with_evidence(facts, evidence)
            facts = self._apply_memory_ordering(facts, memory_context)
            conflicts = self._conflicts_from_graph(graph)
            missing = self._detect_missing_from_graph(requirement, graph, facts, evidence)
            sections = self._plan_sections(question_context.question_type, facts, conflicts, missing)
            sections = self._attach_evidence_sections(sections, facts)
            citation_map = {fact.id: list(fact.evidence_ids or []) for fact in facts}
            return AnswerContext(
                question=question_context.question,
                requirement=requirement,
                sections=sections,
                facts=facts,
                conflicts=conflicts,
                missing=missing,
                citation_map=citation_map,
                evidence=evidence,
            )

        evidence_models = self._normalize_evidence_ids(list(knowledge_input or []))
        ranked_evidence = self._rank_evidence(self._dedupe_evidence(evidence_models), requirement)
        facts = self._merge_facts_from_evidence(ranked_evidence, requirement)
        facts = self._enrich_facts_with_evidence(facts, ranked_evidence)
        facts = self._apply_memory_ordering(facts, memory_context)
        conflicts = self._merge_conflicts(facts)
        missing = self._detect_missing_from_legacy(requirement, ranked_evidence, facts)
        sections = self._plan_sections(question_context.question_type, facts, conflicts, missing)
        sections = self._attach_evidence_sections(sections, facts)
        citation_map = {fact.id: list(fact.evidence_ids or []) for fact in facts}
        return AnswerContext(
            question=question_context.question,
            requirement=requirement,
            sections=sections,
            facts=facts,
            conflicts=conflicts,
            missing=missing,
            citation_map=citation_map,
            evidence=ranked_evidence,
        )

    def _ensure_built_context(self, knowledge_input: Any) -> BuiltAnswerContext | None:
        if isinstance(knowledge_input, BuiltAnswerContext):
            return knowledge_input
        if isinstance(knowledge_input, dict) and {"facts", "sections", "citations"}.issubset(set(knowledge_input.keys())):
            return BuiltAnswerContext.from_dict(knowledge_input)
        return None

    def _ensure_graph(self, knowledge_input: Any) -> KnowledgeGraph | None:
        if isinstance(knowledge_input, KnowledgeGraph):
            return knowledge_input
        if isinstance(knowledge_input, dict) and ("nodes" in knowledge_input or "relations" in knowledge_input):
            return KnowledgeGraph.from_dict(knowledge_input)
        return None

    def _compose_from_built_context(
        self,
        question_context: QuestionContext,
        requirement: Requirement,
        built_context: BuiltAnswerContext,
        *,
        memory_context: Any = None,
    ) -> AnswerContext:
        evidence = self._core_evidence_from_citations(list(built_context.citations or []))
        facts = self._core_facts_from_built_context(built_context)
        facts = self._enrich_facts_with_evidence(facts, evidence)
        facts = self._apply_memory_ordering(facts, memory_context)
        conflicts = self._core_conflicts_from_built_context(built_context)
        sections = self._core_sections_from_built_context(built_context)
        sections = self._attach_evidence_sections(sections, facts)
        missing = self._detect_missing_from_built_context(requirement, facts, evidence)
        citation_map = {fact.id: list(fact.evidence_ids or []) for fact in (facts or [])}
        return AnswerContext(
            question=question_context.question,
            requirement=requirement,
            sections=sections,
            facts=facts,
            conflicts=conflicts,
            missing=missing,
            citation_map=citation_map,
            evidence=evidence,
        )

    def _evidence_from_graph(self, graph: KnowledgeGraph) -> List[Evidence]:
        evidence_index = dict((graph.metadata or {}).get("evidence_index") or {})
        evidence: List[Evidence] = []
        for idx, item in enumerate(evidence_index.values(), start=1):
            if not isinstance(item, dict):
                continue
            evidence.append(
                Evidence(
                    id=str(item.get("id") or f"E{idx}"),
                    title=str(item.get("title") or ""),
                    snippet=str(item.get("snippet") or ""),
                    url=str(item.get("url") or ""),
                    source_name=str(item.get("source_name") or ""),
                    authority=float(item.get("authority") or self._authority_score(str(item.get("source_name") or ""))),
                    confidence=float(item.get("confidence") or 0.0),
                    published_at=str(item.get("published_at") or ""),
                    updated_at=str(item.get("updated_at") or ""),
                    type=str(item.get("type") or ""),
                )
            )
        return evidence

    def _core_evidence_from_citations(self, citations: List[Dict[str, Any]]) -> List[Evidence]:
        out: List[Evidence] = []
        seen = set()
        for item in citations or []:
            if not isinstance(item, dict):
                continue
            evidence_id = str(item.get("evidence_id") or "").strip()
            if not evidence_id or evidence_id in seen:
                continue
            seen.add(evidence_id)
            source_name = str(item.get("source_name") or "").strip()
            out.append(
                Evidence(
                    id=evidence_id,
                    title=str(item.get("title") or ""),
                    snippet=str(item.get("snippet") or ""),
                    url=str(item.get("url") or ""),
                    source_name=source_name,
                    authority=self._authority_score(source_name),
                    confidence=float(item.get("confidence") or 0.0),
                    published_at=str(item.get("published_at") or ""),
                    updated_at=str(item.get("updated_at") or ""),
                    type=str(item.get("type") or ""),
                )
            )
        return out

    def _core_facts_from_built_context(self, built_context: BuiltAnswerContext) -> List[Fact]:
        sources_by_fact = self._sources_from_citations(list(built_context.citations or []))
        facts: List[Fact] = []
        for item in built_context.facts or []:
            if not isinstance(item, BuiltAnswerFact):
                continue
            facts.append(
                Fact(
                    id=str(item.fact_id or ""),
                    field=str(item.predicate or ""),
                    value=str(item.object or ""),
                    confidence=float(item.confidence or 0.0),
                    evidence_ids=list(item.evidence_ids or []),
                    sources=list(sources_by_fact.get(str(item.fact_id or ""), [])),
                )
            )
        return facts

    def _core_conflicts_from_built_context(self, built_context: BuiltAnswerContext) -> List[Conflict]:
        sources_by_evidence = {
            str(item.get("evidence_id") or ""): str(item.get("source_name") or "").strip()
            for item in (built_context.citations or [])
            if isinstance(item, dict)
        }
        conflicts: List[Conflict] = []
        for item in built_context.conflicts or []:
            if not isinstance(item, dict):
                continue
            evidence_ids = self._dedupe_list([str(x) for x in (item.get("evidence_ids") or []) if str(x or "").strip()])
            sources = self._dedupe_list([sources_by_evidence[eid] for eid in evidence_ids if eid in sources_by_evidence and sources_by_evidence[eid]])
            conflicts.append(
                Conflict(
                    field=str(item.get("predicate") or item.get("field") or ""),
                    values=self._dedupe_list([str(x) for x in (item.get("values") or []) if str(x or "").strip()]),
                    sources=sources,
                    evidence_ids=evidence_ids,
                    severity=str(item.get("severity") or "medium"),
                )
            )
        return conflicts

    def _core_sections_from_built_context(self, built_context: BuiltAnswerContext) -> List[Section]:
        sections: List[Section] = []
        for item in built_context.sections or []:
            if not isinstance(item, BuiltAnswerSection):
                continue
            sections.append(
                Section(
                    title=str(item.title or ""),
                    purpose=str((item.metadata or {}).get("subject") or item.title or ""),
                    fact_ids=[str(fact.fact_id or "") for fact in (item.facts or []) if str(fact.fact_id or "").strip()],
                    citation_ids=[str(citation.get("citation_id") or "") for citation in (item.citations or []) if isinstance(citation, dict) and str(citation.get("citation_id") or "").strip()],
                )
            )
        return sections

    def _detect_missing_from_built_context(
        self,
        requirement: Requirement,
        facts: List[Fact],
        evidence: List[Evidence],
    ) -> List[str]:
        fact_fields = {str(fact.field or "").strip().lower() for fact in (facts or [])}
        missing: List[str] = []
        for field in list(requirement.required_fields or []):
            normalized = str(field or "").strip().lower()
            if normalized in fact_fields:
                continue
            if normalized == "source" and any((item.source_name or "").strip() for item in (evidence or [])):
                continue
            if normalized in {"title", "snippet", "url", "confidence", "published_at", "updated_at", "type"}:
                if any(str(getattr(item, normalized, "") or "").strip() for item in (evidence or []) if hasattr(item, normalized)):
                    continue
            missing.append(str(field))
        return self._dedupe_list(missing)

    def _sources_from_citations(self, citations: List[Dict[str, Any]]) -> Dict[str, List[str]]:
        mapping: Dict[str, List[str]] = {}
        for item in citations or []:
            if not isinstance(item, dict):
                continue
            fact_id = str(item.get("fact_id") or "").strip()
            source_name = str(item.get("source_name") or "").strip()
            if not fact_id or not source_name:
                continue
            mapping.setdefault(fact_id, []).append(source_name)
        return {key: self._dedupe_list(values) for key, values in mapping.items()}

    def _facts_from_graph(self, graph: KnowledgeGraph, requirement: Requirement) -> List[Fact]:
        facts: List[Fact] = []
        seen = set()
        idx = 1
        nodes_by_id = {node.id: node for node in (graph.nodes or [])}
        for node in graph.nodes or []:
            base_field = self._default_field_for_node(node)
            if base_field:
                key = (base_field, node.name)
                if key not in seen and str(node.name or "").strip():
                    seen.add(key)
                    facts.append(
                        Fact(
                            id=f"F{idx}",
                            field=base_field,
                            value=node.name,
                            confidence=float(node.confidence or 0.0),
                            evidence_ids=list(node.evidence_ids or []),
                            sources=list(node.sources or []),
                        )
                    )
                    idx += 1
            for field, value in (node.properties or {}).items():
                if field == "_conflicts" or value in (None, "", [], {}):
                    continue
                key = (str(field), str(value))
                if key in seen:
                    continue
                seen.add(key)
                facts.append(
                    Fact(
                        id=f"F{idx}",
                        field=str(field),
                        value=str(value),
                        confidence=float(node.confidence or 0.0),
                        evidence_ids=list(node.evidence_ids or []),
                        sources=list(node.sources or []),
                    )
                )
                idx += 1
        for relation in graph.relations or []:
            source = nodes_by_id.get(relation.source_node)
            target = nodes_by_id.get(relation.target_node)
            if source is None or target is None:
                continue
            field = "relationship"
            value = f"{source.name} {relation.relation} {target.name}"
            if relation.relation == "LED_BY":
                field = "leader_name"
                value = target.name
            elif relation.relation == "LOCATED_IN":
                field = "country"
                value = target.name
            key = (field, value)
            if key in seen:
                continue
            seen.add(key)
            facts.append(
                Fact(
                    id=f"F{idx}",
                    field=field,
                    value=value,
                    confidence=float(relation.confidence or 0.0),
                    evidence_ids=list(relation.evidence_ids or []),
                    sources=self._sources_from_graph_evidence(graph, relation.evidence_ids),
                )
            )
            idx += 1

        required_fields = set(requirement.required_fields or [])
        return sorted(
            facts,
            key=lambda item: (
                1 if item.field in required_fields else 0,
                float(item.confidence or 0.0),
                len(item.evidence_ids or []),
                item.field,
            ),
            reverse=True,
        )

    def _conflicts_from_graph(self, graph: KnowledgeGraph) -> List[Conflict]:
        conflicts: List[Conflict] = []
        for node in graph.nodes or []:
            node_conflicts = dict((node.properties or {}).get("_conflicts") or {})
            for field, values in node_conflicts.items():
                normalized_values = self._dedupe_list([str(item) for item in (values or []) if str(item or "").strip()])
                if len(normalized_values) < 2:
                    continue
                conflicts.append(
                    Conflict(
                        field=str(field),
                        values=normalized_values,
                        sources=list(node.sources or []),
                        evidence_ids=list(node.evidence_ids or []),
                        severity="medium",
                    )
                )
        return conflicts

    def _detect_missing_from_graph(
        self,
        requirement: Requirement,
        graph: KnowledgeGraph,
        facts: List[Fact],
        evidence: List[Evidence],
    ) -> List[str]:
        fact_fields = {fact.field for fact in (facts or [])}
        missing: List[str] = []
        for field in list(requirement.required_fields or []):
            normalized = str(field or "").strip().lower()
            if normalized in fact_fields:
                continue
            if normalized == "source" and any((item.source_name or "").strip() for item in (evidence or [])):
                continue
            if normalized in {"title", "snippet", "url", "confidence", "published_at", "updated_at", "type"}:
                if any(str(getattr(item, normalized, "") or "").strip() for item in (evidence or []) if hasattr(item, normalized)):
                    continue
            if normalized in {"graph", "relationship"} and list(graph.relations or []):
                continue
            missing.append(str(field))
        return self._dedupe_list(missing)

    def _sources_from_graph_evidence(self, graph: KnowledgeGraph, evidence_ids: List[str]) -> List[str]:
        evidence_index = dict((graph.metadata or {}).get("evidence_index") or {})
        return self._dedupe_list(
            [
                str(evidence_index[eid].get("source_name") or "").strip()
                for eid in (evidence_ids or [])
                if eid in evidence_index and str(evidence_index[eid].get("source_name") or "").strip()
            ]
        )

    def _default_field_for_node(self, node: KnowledgeNode) -> str:
        node_type = str(node.type or "").strip().lower()
        if node_type == "organization":
            return "name"
        if node_type == "person":
            return "leader_name"
        if node_type == "country":
            return "country"
        return ""

    def _apply_memory_ordering(self, facts: List[Fact], memory_context: Any = None) -> List[Fact]:
        if memory_context is None:
            return facts
        historical_facts = self._historical_fact_keys(memory_context)
        if not historical_facts:
            return facts
        return sorted(
            facts,
            key=lambda item: (
                0 if f"{item.field}:{str(item.value or '').strip().lower()}" in historical_facts else 1,
                float(item.confidence or 0.0),
                len(item.evidence_ids or []),
            ),
            reverse=True,
        )

    def _historical_fact_keys(self, memory_context: Any) -> set[str]:
        snapshots = list(getattr(memory_context, "knowledge_snapshots", []) or [])
        historical: set[str] = set()
        for snapshot in snapshots[-5:]:
            graph = getattr(snapshot, "knowledge_graph", None)
            if graph is None:
                continue
            knowledge_graph = graph if isinstance(graph, KnowledgeGraph) else KnowledgeGraph.from_dict(graph.to_dict() if hasattr(graph, "to_dict") else graph)
            for node in knowledge_graph.nodes or []:
                field = self._default_field_for_node(node)
                if field and str(node.name or "").strip():
                    historical.add(f"{field}:{str(node.name or '').strip().lower()}")
                for key, value in (node.properties or {}).items():
                    if key == "_conflicts" or value in (None, "", [], {}):
                        continue
                    historical.add(f"{str(key)}:{str(value).strip().lower()}")
            nodes_by_id = {node.id: node for node in (knowledge_graph.nodes or [])}
            for relation in knowledge_graph.relations or []:
                source = nodes_by_id.get(relation.source_node)
                target = nodes_by_id.get(relation.target_node)
                if source is None or target is None:
                    continue
                if relation.relation == "LED_BY":
                    historical.add(f"leader_name:{str(target.name or '').strip().lower()}")
                elif relation.relation == "LOCATED_IN":
                    historical.add(f"country:{str(target.name or '').strip().lower()}")
                else:
                    historical.add(f"relationship:{(str(source.name or '') + ' ' + str(relation.relation or '') + ' ' + str(target.name or '')).strip().lower()}")
        return historical

    def _normalize_evidence_ids(self, evidence: List[Evidence]) -> List[Evidence]:
        out: List[Evidence] = []
        idx = 1
        for item in evidence or []:
            if not isinstance(item, Evidence):
                continue
            evidence_id = (item.id or "").strip() or f"E{idx}"
            idx += 1
            authority = float(item.authority or 0.0) or self._authority_score(item.source_name)
            out.append(
                Evidence(
                    id=evidence_id,
                    title=item.title,
                    snippet=item.snippet,
                    url=item.url,
                    source_name=item.source_name,
                    authority=authority,
                    confidence=float(item.confidence or 0.0),
                    published_at=item.published_at,
                    updated_at=item.updated_at,
                    type=item.type,
                )
            )
        return out

    def _dedupe_evidence(self, evidence: List[Evidence]) -> List[Evidence]:
        out: List[Evidence] = []
        seen = set()
        for item in evidence or []:
            key = (item.url or "").strip() or "|".join(
                [(item.title or "").strip(), (item.source_name or "").strip(), (item.published_at or "").strip()]
            ).strip("|")
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(item)
        return out

    def _rank_evidence(self, evidence: List[Evidence], requirement: Requirement) -> List[Evidence]:
        required_fields = set(requirement.required_fields or []) if requirement else set()

        def match_score(item: Evidence) -> float:
            score = 0.0
            if "url" in required_fields and item.url:
                score += 0.3
            if "source" in required_fields and item.source_name:
                score += 0.2
            if "updated_at" in required_fields and (item.updated_at or item.published_at):
                score += 0.2
            if "published_at" in required_fields and item.published_at:
                score += 0.2
            if "snippet" in required_fields and item.snippet:
                score += 0.1
            return score

        return sorted(
            evidence,
            key=lambda item: (
                match_score(item),
                float(item.authority or 0.0),
                float(item.confidence or 0.0),
                self._best_timestamp(item.published_at, item.updated_at),
            ),
            reverse=True,
        )

    def _merge_facts_from_evidence(self, evidence: List[Evidence], requirement: Requirement) -> List[Fact]:
        extracted: Dict[Tuple[str, str], List[str]] = {}
        field_patterns = {
            "leader_name": [r"(?:leader|pastor|负责人|主任牧师|牧师)[:：]\s*([A-Za-z .'-]{2,64}|[\u4e00-\u9fff]{2,16})"],
            "member_count": [r"(?:member(?:s)?|attendance|会众|会员|人数)[:：]?\s*([0-9][0-9,]{0,12})"],
            "official_website": [r"(https?://[^\s\]]{8,})"],
            "country": [r"(?:country|国家)[:：]\s*([A-Za-z ]{2,48}|[\u4e00-\u9fff]{2,16})"],
            "denomination": [r"(?:denomination|宗派)[:：]\s*([A-Za-z .'-]{2,64}|[\u4e00-\u9fff]{2,24})"],
        }
        for ev in evidence or []:
            text = " ".join([ev.title or "", ev.snippet or ""]).strip()
            if not text:
                continue
            for field, patterns in field_patterns.items():
                for pattern in patterns:
                    match = re.search(pattern, text, flags=re.IGNORECASE)
                    if not match:
                        continue
                    value = str(match.group(1) or "").strip()
                    if value:
                        extracted.setdefault((field, value), []).append(ev.id)
        for ev in evidence or []:
            if ev.title and (("title" in (requirement.required_fields or [])) or not extracted):
                extracted.setdefault(("title", ev.title.strip()), []).append(ev.id)

        id_to_evidence = {item.id: item for item in (evidence or [])}
        facts: List[Fact] = []
        idx = 1
        for (field, value), evidence_ids in extracted.items():
            linked_ids = self._dedupe_list(evidence_ids)
            sources = sorted(
                {
                    (id_to_evidence[eid].source_name or "").strip()
                    for eid in linked_ids
                    if eid in id_to_evidence and (id_to_evidence[eid].source_name or "").strip()
                }
            )
            confidence = max([float(id_to_evidence[eid].confidence or 0.0) for eid in linked_ids if eid in id_to_evidence] or [0.0])
            facts.append(
                Fact(
                    id=f"F{idx}",
                    field=field,
                    value=value,
                    confidence=round(confidence, 3),
                    evidence_ids=linked_ids,
                    sources=sources,
                )
            )
            idx += 1
        return sorted(facts, key=lambda item: (float(item.confidence or 0.0), len(item.evidence_ids or [])), reverse=True)

    def _enrich_facts_with_evidence(self, facts: List[Fact], evidence: List[Evidence]) -> List[Fact]:
        out = list(facts or [])
        seen_keys = {
            (str(item.field or "").strip().lower(), str(item.value or "").strip())
            for item in out
            if str(item.field or "").strip() and str(item.value or "").strip()
        }
        next_index = self._next_fact_index(out)
        seen_reference_labels = set()

        for ev in evidence or []:
            url = str(ev.url or "").strip()
            label = self._reference_label_for_evidence(ev)
            if url:
                reference_key = ((label or str(ev.source_name or "").strip()).lower(), url)
                if reference_key not in seen_reference_labels:
                    reference_value = f"{label}\n来源：{url}" if label else f"来源：{url}"
                    key = ("source_reference", reference_value)
                    if key not in seen_keys:
                        out.append(
                            Fact(
                                id=f"F{next_index}",
                                field="source_reference",
                                value=reference_value,
                                confidence=round(float(ev.confidence or 0.0), 3),
                                evidence_ids=[ev.id] if ev.id else [],
                                sources=self._dedupe_list([str(ev.source_name or "").strip(), label]),
                            )
                        )
                        next_index += 1
                        seen_keys.add(key)
                    seen_reference_labels.add(reference_key)

            score_payload = self._score_payload_from_text(" ".join([str(ev.title or ""), str(ev.snippet or "")]).strip())
            for field_name, display_name in (
                ("people_score", "People Score"),
                ("digital_score", "Digital Score"),
                ("intel_score", "Intel Score"),
                ("composite_score", "Composite Score"),
            ):
                value = score_payload.get(field_name)
                if value is None:
                    continue
                key = (field_name, str(value))
                if key in seen_keys:
                    continue
                out.append(
                    Fact(
                        id=f"F{next_index}",
                        field=field_name,
                        value=str(value),
                        confidence=round(float(ev.confidence or 0.0), 3),
                        evidence_ids=[ev.id] if ev.id else [],
                        sources=self._dedupe_list([str(ev.source_name or "").strip(), display_name]),
                    )
                )
                next_index += 1
                seen_keys.add(key)

        return out

    def _attach_evidence_sections(self, sections: List[Section], facts: List[Fact]) -> List[Section]:
        source_fact_ids = [item.id for item in (facts or []) if str(item.field or "").strip() == "source_reference" and item.id]
        if not source_fact_ids:
            return list(sections or [])

        out: List[Section] = []
        evidence_section_found = False
        for section in sections or []:
            if str(section.title or "").strip().lower() == "evidence":
                evidence_section_found = True
                out.append(
                    Section(
                        title=section.title,
                        purpose=section.purpose or "List supporting evidence with direct URLs.",
                        fact_ids=source_fact_ids[:6],
                        citation_ids=list(section.citation_ids or []),
                    )
                )
                continue
            out.append(section)

        if not evidence_section_found:
            out.append(
                Section(
                    title="Evidence",
                    purpose="List supporting evidence with direct URLs.",
                    fact_ids=source_fact_ids[:6],
                    citation_ids=[],
                )
            )
        return out

    def _reference_label_for_evidence(self, evidence: Evidence) -> str:
        source_name = str(evidence.source_name or "").strip()
        if "/" in source_name:
            label = source_name.rsplit("/", 1)[-1].strip()
            if label:
                return label
        title = str(evidence.title or "").strip()
        if title.lower().endswith(" scorecard"):
            return title[:-10].strip()
        if title:
            return title
        return source_name

    def _score_payload_from_text(self, text: str) -> Dict[str, str]:
        payload: Dict[str, str] = {}
        normalized = str(text or "")
        for field_name in ("people_score", "digital_score", "intel_score", "composite_score"):
            match = re.search(rf"{field_name}\s*=\s*([0-9]+(?:\.[0-9]+)?)", normalized, flags=re.IGNORECASE)
            if match:
                payload[field_name] = str(match.group(1) or "").strip()
        return payload

    def _next_fact_index(self, facts: List[Fact]) -> int:
        max_index = 0
        for item in facts or []:
            match = re.match(r"F(\d+)$", str(item.id or "").strip())
            if match:
                max_index = max(max_index, int(match.group(1)))
        return max_index + 1

    def _merge_conflicts(self, facts: List[Fact]) -> List[Conflict]:
        grouped: Dict[str, List[Fact]] = {}
        for fact in facts or []:
            grouped.setdefault(fact.field, []).append(fact)
        conflicts: List[Conflict] = []
        for field, items in grouped.items():
            values = sorted({(item.value or "").strip() for item in items if (item.value or "").strip()})
            if len(values) < 2:
                continue
            evidence_ids: List[str] = []
            sources: List[str] = []
            for item in items:
                evidence_ids.extend(list(item.evidence_ids or []))
                sources.extend(list(item.sources or []))
            conflicts.append(
                Conflict(
                    field=field,
                    values=values,
                    sources=sorted({source for source in sources if source}),
                    evidence_ids=self._dedupe_list(evidence_ids),
                    severity="medium",
                )
            )
        return conflicts

    def _detect_missing_from_legacy(self, requirement: Requirement, evidence: List[Evidence], facts: List[Fact]) -> List[str]:
        fact_fields = {fact.field for fact in (facts or [])}
        missing: List[str] = []
        for field in list(requirement.required_fields or []):
            normalized = str(field or "").strip().lower()
            if normalized in fact_fields:
                continue
            if normalized == "source" and any((item.source_name or "").strip() for item in (evidence or [])):
                continue
            if normalized in {"title", "snippet", "url", "confidence", "published_at", "updated_at", "type"}:
                if any(str(getattr(item, normalized, "") or "").strip() for item in (evidence or []) if hasattr(item, normalized)):
                    continue
            if normalized in {"ranking", "graph"}:
                continue
            missing.append(str(field))
        return self._dedupe_list(missing)

    def _plan_sections(self, question_type: QuestionType, facts: List[Fact], conflicts: List[Conflict], missing: List[str]) -> List[Section]:
        question_type_value = question_type.value if isinstance(question_type, QuestionType) else str(question_type or "UNKNOWN").upper().strip()
        templates: Dict[str, List[Tuple[str, str]]] = {
            "RANKING": [("Overview", "State what is being ranked and by which metric."), ("Top List", "Provide the ranked list."), ("Evidence", "List supporting evidence."), ("Limitations", "State missing or uncertain parts.")],
            "TIMELINE": [("Summary", "High-level summary."), ("Timeline", "Chronology ordered by time."), ("Impact", "What it implies."), ("Evidence", "List supporting evidence.")],
            "PROFILE": [("Overview", "Organization overview."), ("Leadership", "Leadership facts."), ("Investment", "Investment facts."), ("News", "Recent signals."), ("Evidence", "List supporting evidence.")],
            "GRAPH": [("Graph Overview", "Summarize key entities and links."), ("Key Relationships", "List relationships."), ("Evidence", "List supporting evidence."), ("Limitations", "State missing or uncertain parts.")],
            "COMPARISON": [("Overview", "What is being compared."), ("Differences", "Key differences."), ("Evidence", "List supporting evidence."), ("Summary", "Brief summary.")],
            "INVESTMENT": [("Overview", "Investment summary."), ("Investment Facts", "Key investment facts."), ("Conflicts", "Conflicts if any."), ("Evidence", "List supporting evidence."), ("Limitations", "State missing or uncertain parts.")],
            "RELATIONSHIP": [("Overview", "Relationship summary."), ("Relationship Facts", "Key relationship facts."), ("Conflicts", "Conflicts if any."), ("Evidence", "List supporting evidence."), ("Limitations", "State missing or uncertain parts.")],
            "NEWS": [("Summary", "High-level summary."), ("Key Items", "Key retrieved items."), ("Evidence", "List supporting evidence."), ("Limitations", "State missing or uncertain parts.")],
            "CONTACT": [("Contact", "Contact facts."), ("Evidence", "List supporting evidence."), ("Limitations", "State missing or uncertain parts.")],
            "COUNTRY": [("Overview", "Country baseline."), ("Key Facts", "Key facts."), ("Evidence", "List supporting evidence."), ("Limitations", "State missing or uncertain parts.")],
            "UNKNOWN": [("Answer", "Best-effort answer from evidence."), ("Evidence", "List supporting evidence."), ("Limitations", "State missing or uncertain parts.")],
        }
        template = templates.get(question_type_value, templates["UNKNOWN"])
        fact_ids = [fact.id for fact in (facts or []) if fact.id]
        sections: List[Section] = []
        for title, purpose in template:
            if title in {"Evidence", "Limitations", "Conflicts"}:
                sections.append(Section(title=title, purpose=purpose, fact_ids=[], citation_ids=[]))
            else:
                sections.append(Section(title=title, purpose=purpose, fact_ids=fact_ids[:12], citation_ids=[]))
        return sections

    def _authority_score(self, source_name: str) -> float:
        lowered = (source_name or "").strip().lower()
        if not lowered:
            return self._authority_scores.get("unknown", 0.30)
        for key, value in self._authority_scores.items():
            if key != "unknown" and key in lowered:
                return float(value)
        return self._authority_scores.get("unknown", 0.30)

    def _best_timestamp(self, published_at: str, updated_at: str) -> float:
        return max(self._parse_time(published_at), self._parse_time(updated_at))

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
