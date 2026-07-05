from __future__ import annotations

import time
from collections import defaultdict
from typing import Any, Dict, List

from services.answer_models import AnswerContext, AnswerFact, AnswerSection
from services.evidence_models import EvidenceBundle, Fact
from services.runtime_metrics import get_runtime_metrics


class AnswerContextBuilder:
    def __init__(self, trace_center: Any = None, runtime_metrics: Any = None):
        self.trace_center = trace_center
        self.runtime_metrics = runtime_metrics or get_runtime_metrics()

    def build_context(self, bundle: EvidenceBundle | Dict[str, Any]) -> AnswerContext:
        started = time.perf_counter()
        evidence_bundle = bundle if isinstance(bundle, EvidenceBundle) else EvidenceBundle.from_dict(bundle or {})
        self._trace(
            "Answer Context Started",
            metadata={
                "fact_count": len(evidence_bundle.facts or []),
                "evidence_count": len(evidence_bundle.evidences or []),
            },
        )
        facts = self.rank_facts(evidence_bundle)
        sections = self.build_sections(facts, evidence_bundle)
        citations = self.build_citations(sections, evidence_bundle)
        section_citations: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for item in citations or []:
            if not isinstance(item, dict):
                continue
            section_id = str(item.get("section_id") or "").strip()
            if not section_id:
                continue
            section_citations[section_id].append(dict(item))
        materialized_sections: List[AnswerSection] = []
        for section in sections or []:
            section_items = list(section_citations.get(section.section_id) or [])
            confidence = self._section_confidence(section.facts)
            materialized_sections.append(
                AnswerSection(
                    section_id=section.section_id,
                    title=section.title,
                    facts=list(section.facts or []),
                    citations=section_items,
                    confidence=confidence,
                    metadata=dict(section.metadata or {}),
                )
            )
        context = AnswerContext(
            facts=facts,
            sections=materialized_sections,
            citations=citations,
            conflicts=[dict(item or {}) for item in (evidence_bundle.conflicts or []) if isinstance(item, dict)],
            summary=self._build_summary(materialized_sections),
            metadata={
                "fact_count": len(facts or []),
                "section_count": len(materialized_sections or []),
                "citation_count": len(citations or []),
                "build_time_ms": round((time.perf_counter() - started) * 1000, 2),
            },
        )
        self._record_metrics(context)
        self._trace(
            "Answer Context Finished",
            metadata={
                "fact_count": len(context.facts or []),
                "section_count": len(context.sections or []),
                "citation_count": len(context.citations or []),
            },
        )
        return context

    def build_sections(self, facts: List[AnswerFact], bundle: EvidenceBundle | Dict[str, Any]) -> List[AnswerSection]:
        evidence_bundle = bundle if isinstance(bundle, EvidenceBundle) else EvidenceBundle.from_dict(bundle or {})
        grouped = self.group_by_subject(facts)
        sections: List[AnswerSection] = []
        index = 1
        for subject, subject_facts in grouped.items():
            title = subject or "Answer"
            section = AnswerSection(
                section_id=f"S{index}",
                title=title,
                facts=list(subject_facts or []),
                citations=[],
                confidence=self._section_confidence(subject_facts),
                metadata={
                    "subject": subject,
                    "fact_ids": [item.fact_id for item in (subject_facts or [])],
                    "source_count": len(self._section_sources(subject_facts, evidence_bundle)),
                },
            )
            sections.append(section)
            self._trace(
                "Answer Section Built",
                metadata={"section_id": section.section_id, "title": section.title, "fact_count": len(section.facts or [])},
            )
            index += 1
        if not sections:
            sections.append(
                AnswerSection(
                    section_id="S1",
                    title="Answer",
                    facts=[],
                    citations=[],
                    confidence=0.0,
                    metadata={"subject": ""},
                )
            )
        return sections

    def rank_facts(self, bundle: EvidenceBundle | Dict[str, Any]) -> List[AnswerFact]:
        evidence_bundle = bundle if isinstance(bundle, EvidenceBundle) else EvidenceBundle.from_dict(bundle or {})
        evidence_lookup = {str(item.evidence_id): item for item in (evidence_bundle.evidences or [])}
        ranked: List[AnswerFact] = []
        for fact in evidence_bundle.facts or []:
            score = self._priority_score(fact, evidence_lookup)
            answer_fact = AnswerFact(
                fact_id=str(fact.fact_id or ""),
                subject=str(fact.subject or ""),
                predicate=str(fact.predicate or ""),
                object=str(fact.object or ""),
                confidence=float(fact.confidence or 0.0),
                evidence_ids=list(fact.evidence_ids or []),
                priority=score,
            )
            ranked.append(answer_fact)
        ranked = sorted(
            ranked,
            key=lambda item: (float(item.priority or 0.0), float(item.confidence or 0.0), len(item.evidence_ids or [])),
            reverse=True,
        )
        for fact in ranked:
            self._trace(
                "Fact Ranked",
                metadata={"fact_id": fact.fact_id, "priority": float(fact.priority or 0.0), "subject": fact.subject},
            )
        return ranked

    def group_by_subject(self, facts: List[AnswerFact]) -> Dict[str, List[AnswerFact]]:
        grouped: Dict[str, List[AnswerFact]] = defaultdict(list)
        for fact in facts or []:
            grouped[str(fact.subject or "").strip()].append(fact)
        ordered: Dict[str, List[AnswerFact]] = {}
        for subject, subject_facts in grouped.items():
            ordered[subject] = sorted(subject_facts, key=lambda item: (float(item.priority or 0.0), item.predicate), reverse=True)
        return ordered

    def build_citations(self, sections: List[AnswerSection], bundle: EvidenceBundle | Dict[str, Any]) -> List[Dict[str, Any]]:
        evidence_bundle = bundle if isinstance(bundle, EvidenceBundle) else EvidenceBundle.from_dict(bundle or {})
        evidence_lookup = {str(item.evidence_id): item for item in (evidence_bundle.evidences or [])}
        source_lookup = {str(item.source_id): item for item in (evidence_bundle.sources or [])}
        citations: List[Dict[str, Any]] = []
        seen = set()
        for section in sections or []:
            section_citations: List[Dict[str, Any]] = []
            for fact in section.facts or []:
                for evidence_id in (fact.evidence_ids or []):
                    evidence = evidence_lookup.get(str(evidence_id))
                    if evidence is None:
                        continue
                    source = source_lookup.get(str(evidence.source_id))
                    citation_id = f"C::{section.section_id}::{evidence.evidence_id}"
                    if citation_id in seen:
                        continue
                    seen.add(citation_id)
                    item = {
                        "citation_id": citation_id,
                        "section_id": section.section_id,
                        "fact_id": fact.fact_id,
                        "evidence_id": evidence.evidence_id,
                        "source_name": str((evidence.metadata or {}).get("source_name") or (source.metadata or {}).get("source_name") or ""),
                        "title": evidence.title,
                        "snippet": evidence.snippet,
                        "url": evidence.url,
                        "confidence": float(evidence.confidence or 0.0),
                        "type": evidence.source_type,
                    }
                    citations.append(item)
                    section_citations.append(item)
            self._trace(
                "Answer Citation Built",
                metadata={"section_id": section.section_id, "citation_count": len(section_citations or [])},
            )
        return citations

    def export_context(self, context: AnswerContext | Dict[str, Any]) -> Dict[str, Any]:
        if isinstance(context, AnswerContext):
            return context.to_dict()
        return AnswerContext.from_dict(context or {}).to_dict()

    def _priority_score(self, fact: Fact, evidence_lookup: Dict[str, Any]) -> float:
        evidence_ids = [str(item) for item in (fact.evidence_ids or []) if str(item or "").strip()]
        evidence_count = len(evidence_ids)
        source_names = {
            str((evidence_lookup[eid].metadata or {}).get("source_name") or evidence_lookup[eid].source_id or "").strip()
            for eid in evidence_ids
            if eid in evidence_lookup
        }
        source_diversity = len([item for item in source_names if item])
        score = float(fact.confidence or 0.0) * 0.6 + min(1.0, evidence_count / 5.0) * 0.25 + min(1.0, source_diversity / 3.0) * 0.15
        return round(score, 3)

    def _section_sources(self, facts: List[AnswerFact], bundle: EvidenceBundle) -> List[str]:
        evidence_lookup = {str(item.evidence_id): item for item in (bundle.evidences or [])}
        sources = set()
        for fact in facts or []:
            for evidence_id in (fact.evidence_ids or []):
                evidence = evidence_lookup.get(str(evidence_id))
                if evidence is None:
                    continue
                source_name = str((evidence.metadata or {}).get("source_name") or evidence.source_id or "").strip()
                if source_name:
                    sources.add(source_name)
        return sorted(sources)

    def _section_confidence(self, facts: List[AnswerFact]) -> float:
        if not facts:
            return 0.0
        return round(sum(float(item.confidence or 0.0) for item in (facts or [])) / len(facts), 3)

    def _build_summary(self, sections: List[AnswerSection]) -> str:
        titles = [str(item.title or "").strip() for item in (sections or []) if str(item.title or "").strip()]
        return ", ".join(titles[:5])

    def _record_metrics(self, context: AnswerContext) -> None:
        self.runtime_metrics.set("answer_fact_count", float(len(context.facts or [])))
        self.runtime_metrics.set("answer_section_count", float(len(context.sections or [])))
        citation_per_section = round(len(context.citations or []) / len(context.sections or []), 3) if context.sections else 0.0
        self.runtime_metrics.set("citation_per_section", float(citation_per_section))
        for fact in context.facts or []:
            self.runtime_metrics.observe("fact_rank_score", float(fact.priority or 0.0))
        self.runtime_metrics.observe("answer_context_build_time", float((context.metadata or {}).get("build_time_ms") or 0.0))

    def _trace(self, name: str, metadata: Dict[str, Any] | None = None) -> None:
        if self.trace_center is None:
            return
        self.trace_center.record_event("COMPOSER", name, metadata=metadata or {})
