from __future__ import annotations

import re
import uuid
from typing import Any, Dict, List, Tuple

from services.core_models import AnswerContext, Fact as CoreFact
from services.evidence_models import EvidenceBundle
from services.insight_models import (
    InsightFinding,
    InsightInput,
    InsightOpportunity,
    InsightRecommendation,
    InsightResult,
    InsightRisk,
    InsightSection,
)
from services.knowledge_layer import KnowledgeGraph


SCORE_FIELD_TITLES = {
    "people_score": "People Score",
    "digital_score": "Digital Score",
    "intel_score": "Intel Score",
    "composite_score": "Composite Score",
}

SCORE_FIELD_EXPLANATIONS = {
    "people_score": "People Score reflects visible leadership, team, community, or personnel-related organizational signals.",
    "digital_score": "Digital Score reflects visible digital footprint, official web presence, and discoverability signals.",
    "intel_score": "Intel Score reflects the breadth of structured, externally verifiable intelligence currently visible in the system.",
    "composite_score": "Composite Score is an aggregated display of the currently visible component scores and should not be read as a hidden scoring formula.",
}

GENERIC_SOURCE_PREFIXES = {
    "website crawler",
    "youtube",
    "rss",
    "news",
    "manual_bulk",
    "arda_denomination",
}

STOPWORDS = {
    "query",
    "analyze",
    "analysis",
    "about",
    "the",
    "a",
    "an",
    "of",
    "for",
    "vs",
    "versus",
    "compare",
    "comparison",
    "score",
    "scores",
    "rating",
    "ratings",
    "查询",
    "分析",
    "对比",
    "比较",
    "评分",
    "分数",
    "机构",
    "数据库",
    "缺失",
    "媒体",
}


class InsightEngine:
    def build_insights(self, input_data: InsightInput | Dict[str, Any]) -> InsightResult:
        normalized = self.normalize_input(input_data)
        evidence_index = self.build_evidence_index(normalized)
        context = self._build_query_context(normalized, evidence_index)
        score_signals = self.extract_score_signals(normalized, evidence_index, context)
        context["score_signals"] = score_signals

        mismatch_guard = bool(context.get("mismatch_guard"))
        if mismatch_guard:
            executive_summary = None
            key_findings: List[InsightFinding] = []
            score_explanations = self.build_score_explanations(normalized, score_signals, context)
            risks: List[InsightRisk] = []
            opportunities: List[InsightOpportunity] = []
            data_gaps = self.build_data_gaps(normalized, evidence_index, context)
            recommendations = self.build_recommended_next_questions(normalized, data_gaps, context)
        else:
            key_findings = self.build_key_findings(normalized, evidence_index, score_signals, context)
            score_explanations = self.build_score_explanations(normalized, score_signals, context)
            risks = self.build_risk_signals(normalized, evidence_index, context)
            opportunities = self.build_opportunity_signals(normalized, score_signals, evidence_index, context)
            data_gaps = self.build_data_gaps(normalized, evidence_index, context)
            recommendations = self.build_recommended_next_questions(normalized, data_gaps, context)
            executive_summary = self.build_executive_summary(
                normalized,
                key_findings=key_findings,
                risks=risks,
                opportunities=opportunities,
                data_gaps=data_gaps,
                score_explanations=score_explanations,
                evidence_index=evidence_index,
                context=context,
            )

        evidence_backed_insights = [
            item
            for item in [*key_findings, *score_explanations]
            if list(item.evidence_ids or []) and list(item.source_urls or [])
        ]
        overall_confidence = self._overall_confidence(
            normalized.verification_result,
            [executive_summary] if executive_summary is not None else [],
            key_findings,
            score_explanations,
            risks,
            opportunities,
            data_gaps,
        )
        all_evidence_ids, all_source_urls = self._collect_links(
            executive_summary,
            key_findings,
            score_explanations,
            risks,
            opportunities,
            data_gaps,
            recommendations,
        )
        return InsightResult(
            id=self._new_id("insight_result"),
            title=self._build_title(normalized, context),
            summary=self._build_result_summary(executive_summary, key_findings, data_gaps),
            confidence=overall_confidence,
            target_entities=list(context.get("target_entities") or []),
            target_scope=str(context.get("target_scope") or ""),
            query_mode=str(context.get("query_mode") or ""),
            evidence_ids=all_evidence_ids,
            source_urls=all_source_urls,
            priority="high" if overall_confidence >= 0.75 else "medium",
            executive_summary=executive_summary,
            key_findings=key_findings,
            score_explanations=score_explanations,
            risks=risks,
            opportunities=opportunities,
            evidence_backed_insights=evidence_backed_insights,
            data_gaps=data_gaps,
            recommended_next_questions=recommendations,
            metadata=self._build_metadata(
                normalized,
                evidence_index,
                key_findings,
                score_explanations,
                risks,
                opportunities,
                data_gaps,
                recommendations,
                context,
            ),
        )

    def normalize_input(self, input_data: InsightInput | Dict[str, Any]) -> InsightInput:
        payload = input_data.to_dict() if isinstance(input_data, InsightInput) else dict(input_data or {})
        answer_context = payload.get("answer_context")
        if isinstance(answer_context, AnswerContext):
            payload["answer_context"] = answer_context.to_dict()
        elif not isinstance(answer_context, dict):
            payload["answer_context"] = {}
        evidence_bundle = payload.get("evidence_bundle")
        if isinstance(evidence_bundle, EvidenceBundle):
            payload["evidence_bundle"] = evidence_bundle.to_dict()
        elif not isinstance(evidence_bundle, dict):
            payload["evidence_bundle"] = {}
        knowledge_graph = payload.get("knowledge_graph")
        if isinstance(knowledge_graph, KnowledgeGraph):
            payload["knowledge_graph"] = knowledge_graph.to_dict()
        elif not isinstance(knowledge_graph, dict):
            payload["knowledge_graph"] = {}
        payload["verification_result"] = dict(payload.get("verification_result") or {})
        payload["score_fields"] = dict(payload.get("score_fields") or {})
        payload["metadata"] = dict(payload.get("metadata") or {})
        payload["tool_results"] = [dict(item or {}) for item in (payload.get("tool_results") or []) if isinstance(item, dict)]
        payload["source_urls"] = self._filter_source_urls(payload.get("source_urls") or [])
        return InsightInput.from_dict(payload)

    def build_evidence_index(self, input_data: InsightInput) -> Dict[str, Dict[str, Any]]:
        index: Dict[str, Dict[str, Any]] = {}
        answer_context = self._coerce_answer_context(input_data.answer_context)
        evidence_bundle = self._coerce_evidence_bundle(input_data.evidence_bundle)
        knowledge_graph = self._coerce_knowledge_graph(input_data.knowledge_graph)

        for evidence in list(answer_context.evidence or []):
            self._register_evidence(
                index,
                evidence_id=str(evidence.id or ""),
                title=evidence.title,
                snippet=evidence.snippet,
                url=evidence.url,
                source_name=evidence.source_name,
                confidence=float(evidence.confidence or 0.0),
                authority=float(evidence.authority or 0.0),
            )
        for evidence in list(evidence_bundle.evidences or []):
            self._register_evidence(
                index,
                evidence_id=str(evidence.evidence_id or ""),
                title=evidence.title,
                snippet=evidence.snippet or evidence.raw_content,
                url=evidence.url,
                source_name=evidence.source_id or evidence.source_type,
                confidence=float(evidence.confidence or 0.0),
                authority=float(evidence.relevance or 0.0),
            )
        graph_index = dict((knowledge_graph.metadata or {}).get("evidence_index") or {})
        for evidence_id, payload in graph_index.items():
            if not isinstance(payload, dict):
                continue
            self._register_evidence(
                index,
                evidence_id=str(evidence_id or payload.get("id") or ""),
                title=str(payload.get("title") or ""),
                snippet=str(payload.get("snippet") or payload.get("raw_content") or ""),
                url=str(payload.get("url") or ""),
                source_name=str(payload.get("source_name") or payload.get("source_id") or ""),
                confidence=float(payload.get("confidence") or 0.0),
                authority=float(payload.get("authority") or payload.get("relevance") or 0.0),
            )
        return index

    def extract_score_signals(
        self,
        input_data: InsightInput,
        evidence_index: Dict[str, Dict[str, Any]],
        context: Dict[str, Any],
    ) -> Dict[str, Dict[str, Any]]:
        answer_context = self._coerce_answer_context(input_data.answer_context)
        facts_by_field: Dict[str, List[CoreFact]] = {}
        for fact in list(answer_context.facts or []):
            field_name = str(fact.field or "").strip().lower()
            if field_name:
                facts_by_field.setdefault(field_name, []).append(fact)

        support = self._score_support_profile(input_data, evidence_index, context)
        signals: Dict[str, Dict[str, Any]] = {}
        for field_name in SCORE_FIELD_TITLES:
            raw_value = input_data.score_fields.get(field_name)
            fact_items = list(facts_by_field.get(field_name) or [])
            if raw_value in (None, "") and fact_items:
                raw_value = fact_items[0].value
            if raw_value in (None, ""):
                continue
            evidence_ids: List[str] = []
            source_urls: List[str] = []
            confidence_values: List[float] = []
            for fact in fact_items:
                evidence_ids.extend(list(fact.evidence_ids or []))
                source_urls.extend(self._filter_source_urls(list(fact.sources or [])))
                confidence_values.append(float(fact.confidence or 0.0))
            evidence_ids = self._dedupe_list([*evidence_ids, *support.get(field_name, {}).get("evidence_ids", [])])
            source_urls = self._filter_source_urls([*source_urls, *self._urls_from_evidence(evidence_ids, evidence_index)])
            signals[field_name] = {
                "field": field_name,
                "title": SCORE_FIELD_TITLES[field_name],
                "value": str(raw_value).strip(),
                "summary": SCORE_FIELD_EXPLANATIONS[field_name],
                "evidence_ids": evidence_ids,
                "source_urls": source_urls,
                "confidence": round(sum(confidence_values) / len(confidence_values), 2) if confidence_values else self._base_confidence(input_data.verification_result),
                "visible_support": list(support.get(field_name, {}).get("visible_support", [])),
                "missing_support": list(support.get(field_name, {}).get("missing_support", [])),
            }
        return signals

    def build_executive_summary(
        self,
        input_data: InsightInput,
        *,
        key_findings: List[InsightFinding],
        risks: List[InsightRisk],
        opportunities: List[InsightOpportunity],
        data_gaps: List[InsightFinding],
        score_explanations: List[InsightFinding],
        evidence_index: Dict[str, Dict[str, Any]],
        context: Dict[str, Any],
    ) -> InsightSection | None:
        mode = str(context.get("query_mode") or "")
        coverage = float(input_data.verification_result.get("coverage") or 0.0)
        target_entities = list(context.get("target_entities") or [])
        matched_entities = list(context.get("matched_target_entities") or [])
        target_scope = str(context.get("target_scope") or "")
        summary = ""

        if mode == "score_query":
            parts = []
            strongest = context.get("strongest_score_label")
            weakest = context.get("weakest_score_label")
            if target_entities:
                parts.append(f"{target_entities[0]} currently shows a visible score profile")
            if strongest and weakest:
                parts.append(f"with stronger {strongest} support than {weakest}.")
            if data_gaps:
                parts.append("The current reading is limited by missing supporting fields rather than a disclosed scoring formula.")
            else:
                parts.append("The interpretation is based on visible evidence only and not on any hidden scoring formula.")
            summary = " ".join(parts).strip()
        elif mode == "organization":
            entity_name = target_entities[0] if target_entities else target_scope
            strongest = context.get("strongest_score_label")
            weakest = context.get("weakest_score_label")
            summary_parts = [
                f"{entity_name} is currently represented by matched public evidence as an identifiable organization with named leadership, public web presence, and basic profile coverage."
            ]
            if strongest and weakest:
                summary_parts.append(f"Visible strength is relatively better in {strongest}, while {weakest} remains the thinner part of the current profile.")
            if data_gaps:
                summary_parts.append("The profile still carries data gaps and should be read as public-source diligence rather than a final institutional assessment.")
            else:
                summary_parts.append("The reading still reflects visible public evidence rather than exhaustive due diligence.")
            summary = " ".join(summary_parts[:3]).strip()
        elif mode == "media_list":
            media_entities = list(context.get("media_entities") or [])
            coverage_count = len(self._filter_source_urls(context.get("relevant_urls") or []))
            if media_entities:
                lead_names = ", ".join(media_entities[:4])
                summary = (
                    f"The query returns {len(media_entities)} Philippine Christian media-related entities, led by {lead_names}. "
                    f"Coverage spans {coverage_count} matched public URLs across website, news, and channel sources."
                )
            else:
                summary = "The current media query returns only partial outlet coverage, so the result should be treated as discovery-oriented rather than complete."
        elif mode == "comparison":
            if len(target_entities) >= 2:
                if len(matched_entities) == len(target_entities):
                    summary = (
                        f"The system has matched evidence for both {target_entities[0]} and {target_entities[1]}, "
                        f"but the comparison remains only as strong as the weaker side's evidence coverage."
                    )
                else:
                    missing = [entity for entity in target_entities if entity not in matched_entities]
                    summary = (
                        f"A balanced comparison cannot be completed because matched evidence is incomplete for {', '.join(missing)}. "
                        "The current result should be treated as a coverage-imbalance case rather than a finished comparison."
                    )
        elif mode == "source_query":
            entity_name = target_entities[0] if target_entities else target_scope
            source_count = len(self._filter_source_urls(context.get("relevant_urls") or []))
            if source_count:
                summary = f"Matched evidence for {entity_name} currently exposes {source_count} traceable source URL(s)."
            else:
                summary = f"No stable source URL is currently matched to {entity_name}, so the answer should stay at source-gap level."
        elif mode == "missing_entity":
            entity_name = target_entities[0] if target_entities else target_scope
            summary = (
                f"No matched evidence currently supports a confident entity reading for {entity_name}. "
                "To avoid misattribution, the engine withholds organization-level conclusions and treats this as a data-gap case."
            )

        summary = summary.strip()
        if not summary:
            return None
        evidence_ids, source_urls = self._collect_links(key_findings, score_explanations, risks, opportunities, data_gaps)
        source_urls = self._filter_source_urls(source_urls)
        return InsightSection(
            id=self._new_id("insight_section"),
            title="Executive Summary",
            summary=summary,
            confidence=max(self._base_confidence(input_data.verification_result), 0.45),
            evidence_ids=evidence_ids,
            source_urls=source_urls,
            priority="high" if coverage >= 0.7 else "medium",
            findings=list(key_findings[:3]),
        )

    def build_key_findings(
        self,
        input_data: InsightInput,
        evidence_index: Dict[str, Dict[str, Any]],
        score_signals: Dict[str, Dict[str, Any]],
        context: Dict[str, Any],
    ) -> List[InsightFinding]:
        mode = str(context.get("query_mode") or "")
        answer_context = self._coerce_answer_context(input_data.answer_context)
        findings: List[InsightFinding] = []
        relevant_ids = list(context.get("relevant_evidence_ids") or [])

        if mode in {"organization", "score_query"}:
            for field_name, title, template in (
                ("leader_name", "Identified Leadership", "{entity} is publicly tied to leadership under {value}."),
                ("official_website", "Official Website", "{entity} has an identifiable public website at {value}."),
                ("member_count", "Reported Scale", "{entity} is associated with a reported member or audience figure of {value}."),
                ("country", "Geographic Footprint", "{entity} is currently tied to {value} in the matched evidence."),
            ):
                fact = self._first_fact(answer_context, field_name, relevant_ids)
                if fact is None:
                    continue
                entity_name = self._primary_entity(context)
                findings.append(
                    InsightFinding(
                        id=self._new_id("insight_finding"),
                        title=title,
                        summary=template.format(entity=entity_name or "The organization", value=str(fact.value or "").strip()),
                        confidence=max(float(fact.confidence or 0.0), self._base_confidence(input_data.verification_result)),
                        evidence_ids=self._dedupe_list(list(fact.evidence_ids or [])),
                        source_urls=self._filter_source_urls([*list(fact.sources or []), *self._urls_from_evidence(fact.evidence_ids, evidence_index)]),
                        severity="info",
                    )
                )
            if not findings:
                relevant_evidence = self._relevant_evidence(context)
                for evidence in relevant_evidence[:3]:
                    label = self._display_entity_from_evidence(evidence)
                    findings.append(
                        InsightFinding(
                            id=self._new_id("insight_finding"),
                            title="Matched Public Evidence",
                            summary=f"{label} is directly referenced in matched public evidence for this query.",
                            confidence=max(float(evidence.get("confidence") or 0.0), self._base_confidence(input_data.verification_result)),
                            evidence_ids=[str(evidence.get("id") or "")],
                            source_urls=self._filter_source_urls([str(evidence.get("url") or "")]),
                            severity="info",
                        )
                    )

        elif mode == "media_list":
            for media_item in list(context.get("media_entity_summaries") or [])[:4]:
                findings.append(
                    InsightFinding(
                        id=self._new_id("insight_finding"),
                        title=f"Media Entity: {media_item['name']}",
                        summary=f"{media_item['name']} is represented by {media_item['source_count']} matched source URL(s) in the current result set.",
                        confidence=max(float(media_item.get("confidence") or 0.0), self._base_confidence(input_data.verification_result)),
                        evidence_ids=list(media_item.get("evidence_ids") or []),
                        source_urls=self._filter_source_urls(list(media_item.get("source_urls") or [])),
                        severity="info",
                    )
                )

        elif mode == "comparison":
            target_entities = list(context.get("target_entities") or [])
            entity_matches = dict(context.get("entity_matches") or {})
            if len(target_entities) >= 2 and all(entity_matches.get(entity) for entity in target_entities):
                for entity in target_entities[:2]:
                    payload = entity_matches.get(entity) or {}
                    findings.append(
                        InsightFinding(
                            id=self._new_id("insight_finding"),
                            title=f"Coverage For {entity}",
                            summary=f"{entity} is supported by {len(payload.get('evidence_ids') or [])} matched evidence item(s) and {len(self._filter_source_urls(payload.get('source_urls') or []))} source URL(s).",
                            confidence=max(float(payload.get("confidence") or 0.0), self._base_confidence(input_data.verification_result)),
                            evidence_ids=list(payload.get("evidence_ids") or []),
                            source_urls=self._filter_source_urls(list(payload.get("source_urls") or [])),
                            severity="info",
                        )
                    )
        elif mode == "source_query":
            for evidence in self._relevant_evidence(context)[:4]:
                url = str(evidence.get("url") or "").strip()
                if not self._is_valid_url(url):
                    continue
                label = self._display_entity_from_evidence(evidence) or self._primary_entity(context)
                findings.append(
                    InsightFinding(
                        id=self._new_id("insight_finding"),
                        title=f"Source For {label}",
                        summary=f"Matched public evidence for {label} is available at {url}.",
                        confidence=max(float(evidence.get("confidence") or 0.0), self._base_confidence(input_data.verification_result)),
                        evidence_ids=[str(evidence.get("id") or "")],
                        source_urls=[url],
                        severity="info",
                    )
                )
        return findings[:4]

    def build_score_explanations(
        self,
        input_data: InsightInput,
        score_signals: Dict[str, Dict[str, Any]],
        context: Dict[str, Any],
    ) -> List[InsightFinding]:
        explanations: List[InsightFinding] = []
        for field_name in SCORE_FIELD_TITLES:
            signal = score_signals.get(field_name)
            if signal is None:
                continue
            visible_support = "; ".join(signal.get("visible_support") or []) or "no clear visible support was isolated"
            missing_support = "; ".join(signal.get("missing_support") or []) or "no specific missing support was flagged"
            summary = (
                f"{signal['title']} is currently {signal['value']}. {signal['summary']} "
                f"Visible support: {visible_support}. Missing support: {missing_support}. "
                "This explanation describes currently visible evidence only and should not be read as a hidden scoring formula."
            )
            explanations.append(
                InsightFinding(
                    id=self._new_id("score_explanation"),
                    title=signal["title"],
                    summary=summary,
                    confidence=float(signal.get("confidence") or 0.0),
                    evidence_ids=list(signal.get("evidence_ids") or []),
                    source_urls=self._filter_source_urls(list(signal.get("source_urls") or [])),
                    severity="info",
                )
            )
        return explanations

    def build_risk_signals(
        self,
        input_data: InsightInput,
        evidence_index: Dict[str, Dict[str, Any]],
        context: Dict[str, Any],
    ) -> List[InsightRisk]:
        verification = dict(input_data.verification_result or {})
        risks: List[InsightRisk] = []
        coverage = float(verification.get("coverage") or 0.0)
        missing_fields = self._dedupe_list(verification.get("missing_fields") or [])
        missing_sources = self._dedupe_list(verification.get("missing_sources") or [])
        mode = str(context.get("query_mode") or "")

        if mode == "comparison" and context.get("coverage_imbalance"):
            missing_entities = [entity for entity in (context.get("target_entities") or []) if entity not in (context.get("matched_target_entities") or [])]
            risks.append(
                InsightRisk(
                    id=self._new_id("insight_risk"),
                    title="Coverage Imbalance",
                    summary=f"The comparison cannot be treated as balanced because evidence is incomplete for {', '.join(missing_entities)}.",
                    confidence=max(self._base_confidence(verification), 0.7),
                    evidence_ids=[],
                    source_urls=[],
                    severity="high",
                )
            )
            return risks

        if bool(verification.get("blocking_conflict")):
            risks.append(
                InsightRisk(
                    id=self._new_id("insight_risk"),
                    title="Evidence Conflict",
                    summary="Some matched evidence points in conflicting directions, so the final interpretation should stay conservative.",
                    confidence=max(self._base_confidence(verification), 0.7),
                    evidence_ids=[],
                    source_urls=[],
                    severity="high",
                )
            )
        if coverage < 0.65:
            risks.append(
                InsightRisk(
                    id=self._new_id("insight_risk"),
                    title="Low Coverage",
                    summary="The matched evidence coverage is too thin to support a full-confidence business conclusion.",
                    confidence=max(0.55, self._base_confidence(verification)),
                    evidence_ids=[],
                    source_urls=[],
                    severity="high",
                )
            )
        if missing_fields:
            risks.append(
                InsightRisk(
                    id=self._new_id("insight_risk"),
                    title="Missing Critical Fields",
                    summary=f"Important validation fields remain missing: {', '.join(missing_fields[:5])}.",
                    confidence=max(0.6, self._base_confidence(verification)),
                    evidence_ids=[],
                    source_urls=[],
                    severity="medium",
                )
            )
        if missing_sources:
            risks.append(
                InsightRisk(
                    id=self._new_id("insight_risk"),
                    title="Limited Source Diversity",
                    summary=f"Source-type coverage is still uneven across: {', '.join(missing_sources[:4])}.",
                    confidence=max(0.55, self._base_confidence(verification)),
                    evidence_ids=[],
                    source_urls=[],
                    severity="medium",
                )
            )
        return risks[:4]

    def build_opportunity_signals(
        self,
        input_data: InsightInput,
        score_signals: Dict[str, Dict[str, Any]],
        evidence_index: Dict[str, Dict[str, Any]],
        context: Dict[str, Any],
    ) -> List[InsightOpportunity]:
        opportunities: List[InsightOpportunity] = []
        mode = str(context.get("query_mode") or "")
        if mode == "media_list":
            media_entities = list(context.get("media_entities") or [])
            if len(media_entities) >= 3:
                opportunities.append(
                    InsightOpportunity(
                        id=self._new_id("insight_opportunity"),
                        title="Multi-Outlet Discovery Base",
                        summary="The matched sources already surface several distinct media entities, which is enough to support a deeper outlet-mapping pass.",
                        confidence=max(0.6, self._base_confidence(input_data.verification_result)),
                        evidence_ids=list(context.get("relevant_evidence_ids") or [])[:4],
                        source_urls=self._filter_source_urls(list(context.get("relevant_urls") or [])[:6]),
                        priority="medium",
                    )
                )
            return opportunities
        if mode == "source_query":
            return opportunities

        for field_name in ("people_score", "digital_score", "intel_score"):
            signal = score_signals.get(field_name)
            numeric_value = self._safe_number(signal.get("value")) if signal else None
            if signal is None or numeric_value is None or numeric_value < 60:
                continue
            if field_name == "people_score":
                summary = "Leadership and people-related signals are strong enough to support further diligence on organizational structure and scale."
            elif field_name == "digital_score":
                summary = "Digital visibility is strong enough to support faster public verification and channel mapping."
            else:
                summary = "Intel visibility is strong enough to support deeper source-based analysis and follow-up research."
            opportunities.append(
                InsightOpportunity(
                    id=self._new_id("insight_opportunity"),
                    title=f"Opportunity In {signal['title']}",
                    summary=summary,
                    confidence=max(float(signal.get("confidence") or 0.0), 0.6),
                    evidence_ids=list(signal.get("evidence_ids") or []),
                    source_urls=self._filter_source_urls(list(signal.get("source_urls") or [])),
                    priority="high" if numeric_value >= 75 else "medium",
                )
            )
        return opportunities[:3]

    def build_data_gaps(
        self,
        input_data: InsightInput,
        evidence_index: Dict[str, Dict[str, Any]],
        context: Dict[str, Any],
    ) -> List[InsightFinding]:
        verification = dict(input_data.verification_result or {})
        gaps: List[InsightFinding] = []
        missing_fields = self._dedupe_list(verification.get("missing_fields") or [])
        missing_sources = self._dedupe_list(verification.get("missing_sources") or [])
        mode = str(context.get("query_mode") or "")
        primary_entity = self._primary_entity(context)

        if context.get("mismatch_guard"):
            if mode == "missing_entity":
                gaps.append(
                    InsightFinding(
                        id=self._new_id("data_gap"),
                        title="No Matched Entity Evidence",
                        summary=f"The current result set does not contain evidence that can be confidently tied to {primary_entity}, so the engine suppresses entity conclusions.",
                        confidence=max(0.75, 1.0 - self._base_confidence(verification)),
                        evidence_ids=[],
                        source_urls=[],
                        severity="high",
                    )
                )
                gaps.append(
                    InsightFinding(
                        id=self._new_id("data_gap"),
                        title="Targeted Source Collection Needed",
                        summary=f"Additional official, denominational, or trusted third-party sources are needed before {primary_entity} can be assessed.",
                        confidence=0.75,
                        evidence_ids=[],
                        source_urls=[],
                        severity="high",
                    )
                )
                return gaps
            if mode == "source_query":
                gaps.append(
                    InsightFinding(
                        id=self._new_id("data_gap"),
                        title="No Matched Source Evidence",
                        summary=f"No source URL can be confidently tied to {primary_entity} in the current result set.",
                        confidence=0.75,
                        evidence_ids=[],
                        source_urls=[],
                        severity="high",
                    )
                )
                return gaps
            if mode == "comparison":
                missing_entities = [entity for entity in (context.get("target_entities") or []) if entity not in (context.get("matched_target_entities") or [])]
                gaps.append(
                    InsightFinding(
                        id=self._new_id("data_gap"),
                        title="Coverage Imbalance",
                        summary=f"A valid side-by-side comparison is blocked because matched evidence is missing for {', '.join(missing_entities)}.",
                        confidence=0.75,
                        evidence_ids=[],
                        source_urls=[],
                        severity="high",
                    )
                )
                return gaps

        if mode == "media_list" and context.get("media_entity_count", 0) < 3:
            gaps.append(
                InsightFinding(
                    id=self._new_id("data_gap"),
                    title="Incomplete Outlet Coverage",
                    summary="The current result set identifies only a small number of media entities, so it should not be treated as a complete market map.",
                    confidence=0.7,
                    evidence_ids=[],
                    source_urls=[],
                    severity="medium",
                )
            )
        if mode == "source_query" and not self._filter_source_urls(context.get("relevant_urls") or []):
            gaps.append(
                InsightFinding(
                    id=self._new_id("data_gap"),
                    title="No Traceable Source URL",
                    summary="The current matched evidence does not yet expose a stable source URL for the requested entity.",
                    confidence=0.75,
                    evidence_ids=[],
                    source_urls=[],
                    severity="high",
                )
            )

        for field_name in missing_fields[:4]:
            gaps.append(
                InsightFinding(
                    id=self._new_id("data_gap"),
                    title=f"Missing Field: {self._humanize_field(field_name)}",
                    summary=f"The current analysis still lacks a reliable value for {self._humanize_field(field_name).lower()}, which limits confidence in the output.",
                    confidence=max(0.6, 1.0 - float(verification.get("coverage") or 0.0)),
                    evidence_ids=[],
                    source_urls=[],
                    severity="medium",
                )
            )
        for source_name in missing_sources[:3]:
            gaps.append(
                InsightFinding(
                    id=self._new_id("data_gap"),
                    title=f"Missing Source Type: {source_name}",
                    summary=f"The answer would be stronger with an additional source of type '{source_name}'.",
                    confidence=max(0.55, 1.0 - float(verification.get("coverage") or 0.0)),
                    evidence_ids=[],
                    source_urls=[],
                    severity="medium",
                )
            )

        if mode in {"organization", "score_query"}:
            digital_score = self._safe_number((context.get("score_signals") or {}).get("digital_score", {}).get("value"))
            if digital_score is not None and digital_score < 40:
                gaps.append(
                    InsightFinding(
                        id=self._new_id("data_gap"),
                        title="Thin Digital Support",
                        summary="Visible website, social, or channel evidence remains thin relative to the rest of the profile, which limits the digital interpretation.",
                        confidence=0.7,
                        evidence_ids=[],
                        source_urls=[],
                        severity="medium",
                    )
                )
        if not gaps and not self._filter_source_urls(input_data.source_urls):
            gaps.append(
                InsightFinding(
                    id=self._new_id("data_gap"),
                    title="Sparse Public URLs",
                    summary="The current result set contains too few clean public URLs to fully support source-traceable insight generation.",
                    confidence=0.65,
                    evidence_ids=[],
                    source_urls=[],
                    severity="medium",
                )
            )
        return gaps[:6]

    def build_recommended_next_questions(
        self,
        input_data: InsightInput,
        data_gaps: List[InsightFinding],
        context: Dict[str, Any],
    ) -> List[InsightRecommendation]:
        primary_entity = self._primary_entity(context)
        mode = str(context.get("query_mode") or "")
        recommendations: List[InsightRecommendation] = []
        if mode == "media_list":
            recommendations.append(
                InsightRecommendation(
                    id=self._new_id("insight_recommendation"),
                    title="Recommended Next Question",
                    summary=f"Which Philippine Christian media entities should be added beyond {', '.join((context.get('media_entities') or [])[:3])} to improve outlet coverage?",
                    confidence=0.65,
                    evidence_ids=[],
                    source_urls=self._filter_source_urls(list(context.get("relevant_urls") or [])[:6]),
                    priority="high",
                )
            )
            return recommendations
        if mode == "source_query" and data_gaps:
            recommendations.append(
                InsightRecommendation(
                    id=self._new_id("insight_recommendation"),
                    title="Recommended Next Question",
                    summary=f"What official website, primary source, or trusted registry can verify the sources for {primary_entity}?",
                    confidence=0.7,
                    evidence_ids=[],
                    source_urls=[],
                    priority="high",
                )
            )
            return recommendations

        for gap in data_gaps[:4]:
            lowered = gap.title.lower()
            if "coverage imbalance" in lowered and len(context.get("target_entities") or []) >= 2:
                missing_entities = [entity for entity in (context.get("target_entities") or []) if entity not in (context.get("matched_target_entities") or [])]
                missing_entity = missing_entities[0] if missing_entities else context["target_entities"][0]
                present_entities = [entity for entity in (context.get("target_entities") or []) if entity != missing_entity]
                present_entity = present_entities[0] if present_entities else context["target_entities"][0]
                question = f"What verified sources can be collected for {missing_entity} to balance the comparison with {present_entity}?"
            elif "no matched entity evidence" in lowered:
                question = f"What official website, registry, or denominational references can verify whether {primary_entity} exists in the target dataset?"
            elif "leader" in lowered:
                question = f"What verified leadership information is publicly available for {primary_entity}?"
            elif "website" in lowered or "source type" in lowered or "source" in lowered:
                question = f"What official website or primary-source references can verify {primary_entity}?"
            elif "country" in lowered:
                question = f"What country or regional operating information can confirm {primary_entity}'s footprint?"
            else:
                question = f"What additional verified data can fill the gap: {gap.title}?"
            recommendations.append(
                InsightRecommendation(
                    id=self._new_id("insight_recommendation"),
                    title="Recommended Next Question",
                    summary=question,
                    confidence=max(float(gap.confidence or 0.0), 0.55),
                    evidence_ids=list(gap.evidence_ids or []),
                    source_urls=self._filter_source_urls(list(gap.source_urls or [])),
                    priority="high" if "missing" in lowered or "coverage imbalance" in lowered else "medium",
                )
            )
        if not recommendations and primary_entity:
            recommendations.append(
                InsightRecommendation(
                    id=self._new_id("insight_recommendation"),
                    title="Recommended Next Question",
                    summary=f"What are the most recent high-confidence public updates about {primary_entity}?",
                    confidence=0.55,
                    evidence_ids=[],
                    source_urls=self._filter_source_urls(input_data.source_urls or []),
                    priority="medium",
                )
            )
        return recommendations[:5]

    def export_result(self, result: InsightResult | Dict[str, Any]) -> Dict[str, Any]:
        if isinstance(result, InsightResult):
            return result.to_dict()
        return dict(result or {})

    def _build_query_context(self, input_data: InsightInput, evidence_index: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        answer_context = self._coerce_answer_context(input_data.answer_context)
        explicit_entities = list(input_data.target_entities or [])
        query_mode = str(input_data.query_mode or self._infer_query_mode(input_data.question))
        target_entities = explicit_entities or self._extract_target_entities(input_data.question, query_mode)
        target_scope = str(input_data.target_scope or self._infer_target_scope(input_data.question, query_mode, target_entities))

        if query_mode == "missing_entity" and not target_entities:
            target_entities = [self._clean_question_target(input_data.question)]
            target_scope = target_entities[0]

        relevant_ids, entity_matches = self._match_relevant_evidence(target_entities, query_mode, evidence_index)
        matched_target_entities = [entity for entity, payload in entity_matches.items() if list(payload.get("evidence_ids") or [])]
        coverage_imbalance = query_mode == "comparison" and len(target_entities) >= 2 and len(matched_target_entities) < len(target_entities)
        if query_mode == "organization" and target_entities and not matched_target_entities:
            query_mode = "missing_entity"
        if query_mode == "score_query" and target_entities and not matched_target_entities:
            query_mode = "missing_entity"
        source_query_mismatch = query_mode == "source_query" and target_entities and not matched_target_entities

        relevant_evidence = [dict(evidence_index[evidence_id]) for evidence_id in relevant_ids if evidence_id in evidence_index]
        media_summaries = self._media_entity_summaries(relevant_evidence)
        media_entities = [item["name"] for item in media_summaries]
        mismatch_guard = False
        if query_mode == "missing_entity":
            mismatch_guard = True
        elif query_mode == "comparison" and coverage_imbalance:
            mismatch_guard = True
        elif query_mode in {"organization", "score_query"} and target_entities and not matched_target_entities:
            mismatch_guard = True
        elif source_query_mismatch:
            mismatch_guard = True

        facts_lookup = self._facts_lookup(answer_context)
        score_high_low = self._score_strength_labels(input_data, answer_context)
        context = {
            "query_mode": query_mode,
            "target_entities": target_entities,
            "target_scope": target_scope,
            "matched_target_entities": matched_target_entities,
            "coverage_imbalance": coverage_imbalance,
            "mismatch_guard": mismatch_guard,
            "entity_matches": entity_matches,
            "relevant_evidence_ids": relevant_ids,
            "relevant_evidence": relevant_evidence,
            "relevant_urls": self._filter_source_urls([evidence.get("url") for evidence in relevant_evidence]),
            "media_entity_summaries": media_summaries,
            "media_entities": media_entities,
            "media_entity_count": len(media_entities),
            "facts_lookup": facts_lookup,
            "strongest_score_label": score_high_low[0],
            "weakest_score_label": score_high_low[1],
        }
        return context

    def _coerce_answer_context(self, value: Dict[str, Any] | AnswerContext | None) -> AnswerContext:
        if isinstance(value, AnswerContext):
            return value
        return AnswerContext.from_dict(value or {})

    def _coerce_evidence_bundle(self, value: Dict[str, Any] | EvidenceBundle | None) -> EvidenceBundle:
        if isinstance(value, EvidenceBundle):
            return value
        return EvidenceBundle.from_dict(value or {})

    def _coerce_knowledge_graph(self, value: Dict[str, Any] | KnowledgeGraph | None) -> KnowledgeGraph:
        if isinstance(value, KnowledgeGraph):
            return value
        return KnowledgeGraph.from_dict(value or {})

    def _register_evidence(
        self,
        index: Dict[str, Dict[str, Any]],
        *,
        evidence_id: str,
        title: str,
        snippet: str,
        url: str,
        source_name: str,
        confidence: float,
        authority: float,
    ) -> None:
        normalized_id = str(evidence_id or "").strip()
        if not normalized_id:
            return
        existing = dict(index.get(normalized_id) or {})
        index[normalized_id] = {
            "id": normalized_id,
            "title": str(title or existing.get("title") or "").strip(),
            "snippet": str(snippet or existing.get("snippet") or "").strip(),
            "url": str(url or existing.get("url") or "").strip(),
            "source_name": str(source_name or existing.get("source_name") or "").strip(),
            "confidence": max(float(confidence or 0.0), float(existing.get("confidence") or 0.0)),
            "authority": max(float(authority or 0.0), float(existing.get("authority") or 0.0)),
        }

    def _is_valid_url(self, value: Any) -> bool:
        text = str(value or "").strip()
        return text.startswith("http://") or text.startswith("https://")

    def _filter_source_urls(self, values: List[Any]) -> List[str]:
        urls = [str(value or "").strip() for value in list(values or [])]
        return self._dedupe_list([url for url in urls if self._is_valid_url(url)])

    def _urls_from_evidence(self, evidence_ids: List[str] | None, evidence_index: Dict[str, Dict[str, Any]]) -> List[str]:
        urls: List[str] = []
        for evidence_id in list(evidence_ids or []):
            payload = dict(evidence_index.get(str(evidence_id or "").strip()) or {})
            url = str(payload.get("url") or "").strip()
            if self._is_valid_url(url):
                urls.append(url)
        return self._filter_source_urls(urls)

    def _collect_links(self, *items: Any) -> Tuple[List[str], List[str]]:
        evidence_ids: List[str] = []
        source_urls: List[str] = []
        for item in items:
            if item is None:
                continue
            if isinstance(item, list):
                sub_evidence_ids, sub_source_urls = self._collect_links(*item)
                evidence_ids.extend(sub_evidence_ids)
                source_urls.extend(sub_source_urls)
                continue
            evidence_ids.extend(list(getattr(item, "evidence_ids", []) or []))
            source_urls.extend(self._filter_source_urls(list(getattr(item, "source_urls", []) or [])))
            findings = list(getattr(item, "findings", []) or [])
            if findings:
                sub_evidence_ids, sub_source_urls = self._collect_links(findings)
                evidence_ids.extend(sub_evidence_ids)
                source_urls.extend(sub_source_urls)
        return self._dedupe_list(evidence_ids), self._filter_source_urls(source_urls)

    def _build_title(self, input_data: InsightInput, context: Dict[str, Any]) -> str:
        target_entities = list(context.get("target_entities") or [])
        if target_entities:
            return f"{' vs '.join(target_entities[:2]) if len(target_entities) > 1 else target_entities[0]} Insight Result"
        target_scope = str(context.get("target_scope") or "")
        if target_scope:
            return f"{target_scope} Insight Result"
        return "Insight Result"

    def _build_result_summary(
        self,
        executive_summary: InsightSection | None,
        key_findings: List[InsightFinding],
        data_gaps: List[InsightFinding],
    ) -> str:
        if executive_summary is not None and executive_summary.summary:
            return executive_summary.summary
        if key_findings:
            return key_findings[0].summary
        if data_gaps:
            return data_gaps[0].summary
        return "Insight Engine completed with limited structured output."

    def _build_metadata(
        self,
        input_data: InsightInput,
        evidence_index: Dict[str, Dict[str, Any]],
        key_findings: List[InsightFinding],
        score_explanations: List[InsightFinding],
        risks: List[InsightRisk],
        opportunities: List[InsightOpportunity],
        data_gaps: List[InsightFinding],
        recommendations: List[InsightRecommendation],
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        evidence_bound_items = 0
        total_items = 0
        for item in [*key_findings, *score_explanations, *risks, *opportunities, *data_gaps, *recommendations]:
            total_items += 1
            if list(getattr(item, "evidence_ids", []) or []) and list(getattr(item, "source_urls", []) or []):
                evidence_bound_items += 1
        evidence_bound_rate = round(evidence_bound_items / total_items, 2) if total_items else 0.0
        return {
            "executed": True,
            "intent": input_data.intent,
            "coverage": float(input_data.verification_result.get("coverage") or 0.0),
            "blocking_conflict": bool(input_data.verification_result.get("blocking_conflict")),
            "evidence_count": len(evidence_index),
            "query_mode": context.get("query_mode"),
            "target_entities": list(context.get("target_entities") or []),
            "target_scope": context.get("target_scope"),
            "matched_target_entities": list(context.get("matched_target_entities") or []),
            "coverage_imbalance": bool(context.get("coverage_imbalance")),
            "mismatch_guard": bool(context.get("mismatch_guard")),
            "key_findings_count": len(key_findings),
            "score_explanations_count": len(score_explanations),
            "risk_count": len(risks),
            "opportunity_count": len(opportunities),
            "data_gap_count": len(data_gaps),
            "recommended_next_questions_count": len(recommendations),
            "evidence_bound_rate": evidence_bound_rate,
        }

    def _overall_confidence(self, verification: Dict[str, Any], *collections: Any) -> float:
        base = self._base_confidence(verification)
        counts = 0
        for item in collections:
            if isinstance(item, list):
                counts += len(item)
            elif item is not None:
                counts += 1
        if counts >= 5:
            base = min(0.95, base + 0.05)
        return round(base, 2)

    def _base_confidence(self, verification: Dict[str, Any]) -> float:
        coverage = float((verification or {}).get("coverage") or 0.0)
        verification_score = float((verification or {}).get("verification_score") or 0.0)
        if verification_score > 1.0:
            verification_score = min(1.0, verification_score / 100.0)
        score = max(coverage, verification_score)
        if bool((verification or {}).get("blocking_conflict")):
            score = max(0.2, score - 0.15)
        return round(max(0.2, min(0.95, score or 0.45)), 2)

    def _infer_query_mode(self, question: str) -> str:
        normalized = self._normalize_text(question)
        raw_text = str(question or "").strip()
        if re.search(r"^\s*(对比|比较|compare)\s+", raw_text, re.IGNORECASE) or re.search(r"\bvs\b|\bversus\b", raw_text, re.IGNORECASE):
            return "comparison"
        if self._looks_like_source_query(raw_text):
            return "source_query"
        if "媒体" in raw_text or "media" in normalized:
            return "media_list"
        if self._looks_like_score_query(raw_text):
            return "score_query"
        if self._looks_like_organization_query(raw_text):
            return "organization"
        if any(marker in normalized for marker in ["nonexistent", "not found", "missing", "不存在", "缺失", "没有数据", "不存", "未命中"]):
            return "missing_entity"
        return "organization"

    def _extract_target_entities(self, question: str, query_mode: str) -> List[str]:
        cleaned = self._clean_question_target(question)
        if not cleaned:
            return []
        if query_mode == "comparison":
            raw = re.sub(r"^(对比|比较|compare)\s*", "", cleaned, flags=re.IGNORECASE)
            parts = re.split(r"\s+(?:vs|versus)\s+|和|与|及|跟", raw, maxsplit=1, flags=re.IGNORECASE)
            return [part.strip(" ?!.,，。") for part in parts if part.strip(" ?!.,，。")]
        if query_mode == "media_list":
            return []
        if query_mode == "source_query":
            entity = self._extract_first_group(
                question,
                [
                    r"^\s*(?P<entity>.+?)\s*的\s*(?:数据来源|证据来源|来源)\s*(?:是什么)?[？?]?\s*$",
                    r"^\s*关于\s*(?P<entity>.+?)\s*的?信息来自哪里[？?]?\s*$",
                    r"^\s*(?P<entity>.+?)\s*的信息来自哪里[？?]?\s*$",
                    r"^\s*这条情报的来源是什么[？?]?\s*$",
                ],
            )
            if entity and entity != "这条情报":
                return [entity]
            if entity == "这条情报":
                return []
        if query_mode == "score_query":
            entity = self._extract_first_group(
                question,
                [
                    r"^\s*查询\s*(?P<entity>.+?)\s*的\s*(?:评分|分数)\s*[？?]?\s*$",
                    r"^\s*(?:为什么|为何)\s*(?P<entity>.+?)\s*的\s*(?:people|digital|intel|composite)\s*score.*$",
                    r"^\s*(?P<entity>.+?)\s*的\s*(?:people|digital|intel|composite)\s*score\s*(?:是多少|是什么|有多高|有多低)?.*$",
                    r"^\s*解释\s*(?P<entity>.+?)\s*的\s*(?:评分|分数).*$",
                    r"^\s*(?P<entity>.+?)\s*的\s*分数为什么.*$",
                    r"^\s*(?P<entity>.+?)\s*的\s*(?:评分|分数)\s*[？?]?\s*$",
                ],
            )
            return [entity] if entity else ([cleaned.strip()] if cleaned.strip() else [])
        if query_mode == "organization":
            entity = self._extract_first_group(
                question,
                [
                    r"^\s*分析\s*(?P<entity>.+?)\s*[？?]?\s*$",
                    r"^\s*评估\s*(?P<entity>.+?)\s*[？?]?\s*$",
                    r"^\s*生成\s*(?P<entity>.+?)\s*的?\s*(?:简要)?情报摘要\s*[？?]?\s*$",
                    r"^\s*(?P<entity>.+?)\s*有哪些优势和风险[？?]?\s*$",
                    r"^\s*(?P<entity>.+?)\s*的\s*(?:机构画像|情报摘要)\s*[？?]?\s*$",
                ],
            )
            return [entity] if entity else ([cleaned.strip()] if cleaned.strip() else [])
        return [cleaned.strip()] if cleaned.strip() else []

    def _infer_target_scope(self, question: str, query_mode: str, target_entities: List[str]) -> str:
        if query_mode == "media_list":
            return self._clean_question_target(question)
        if query_mode == "comparison" and len(target_entities) >= 2:
            return f"{target_entities[0]} vs {target_entities[1]}"
        if target_entities:
            return target_entities[0]
        return self._clean_question_target(question)

    def _clean_question_target(self, question: str) -> str:
        text = str(question or "").strip()
        text = re.sub(r"^(查询|分析|对比|比较|请分析|请查询|生成|评估|解释|为什么|为何)\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s+", " ", text).strip(" ?!.,，。")
        return text

    def _looks_like_source_query(self, question: str) -> bool:
        text = str(question or "").strip()
        return bool(
            re.search(r"(数据来源|证据来源|来源是什么|信息来自哪里)", text, re.IGNORECASE)
            and not re.search(r"^(你的|系统的|你从哪里|系统从哪里)", text, re.IGNORECASE)
        )

    def _looks_like_score_query(self, question: str) -> bool:
        text = str(question or "").strip()
        return bool(
            re.search(r"(评分|分数|score|rating)", text, re.IGNORECASE)
            or re.search(r"(为什么|为何).+(Digital|People|Intel|Composite)\s*Score", text, re.IGNORECASE)
        )

    def _looks_like_organization_query(self, question: str) -> bool:
        text = str(question or "").strip()
        return bool(
            re.search(r"^(分析|评估|生成).+", text, re.IGNORECASE)
            or re.search(r"(优势和风险|机构画像|情报摘要)", text, re.IGNORECASE)
        )

    def _extract_first_group(self, question: str, patterns: List[str]) -> str:
        text = str(question or "").strip()
        for pattern in list(patterns or []):
            match = re.search(pattern, text, re.IGNORECASE)
            if not match:
                continue
            entity = str(match.groupdict().get("entity") or "").strip(" ?!.,，。")
            entity = re.sub(r"\s+", " ", entity).strip()
            if entity:
                return entity
        return ""

    def _normalize_text(self, text: str) -> str:
        lowered = str(text or "").lower()
        lowered = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", " ", lowered)
        normalized = re.sub(r"\s+", " ", lowered).strip()
        return f" {normalized} "

    def _entity_tokens(self, entity: str) -> List[str]:
        raw_tokens = [token for token in self._normalize_text(entity).split() if token]
        return [token for token in raw_tokens if token not in STOPWORDS and len(token) > 1]

    def _match_relevant_evidence(
        self,
        target_entities: List[str],
        query_mode: str,
        evidence_index: Dict[str, Dict[str, Any]],
    ) -> Tuple[List[str], Dict[str, Dict[str, Any]]]:
        entity_matches: Dict[str, Dict[str, Any]] = {entity: {"evidence_ids": [], "source_urls": [], "confidence": 0.0} for entity in target_entities}
        relevant_ids: List[str] = []
        if query_mode == "media_list":
            relevant_ids = sorted(evidence_index.keys(), key=lambda item: float(evidence_index[item].get("confidence") or 0.0), reverse=True)
            return relevant_ids, entity_matches
        for evidence_id, payload in evidence_index.items():
            strong_text = " ".join(
                [
                    str(payload.get("title") or ""),
                    str(payload.get("source_name") or ""),
                    str(payload.get("url") or ""),
                ]
            )
            evidence_text = " ".join(
                [
                    strong_text,
                    str(payload.get("snippet") or ""),
                ]
            )
            normalized_strong = self._normalize_text(strong_text)
            normalized_evidence = self._normalize_text(evidence_text)
            matched_any = False
            for entity in target_entities:
                tokens = self._entity_tokens(entity)
                if not tokens:
                    continue
                normalized_entity = self._normalize_text(entity).strip()
                strong_match_count = sum(1 for token in tokens if f" {token} " in normalized_strong)
                matched_count = sum(1 for token in tokens if f" {token} " in normalized_evidence)
                full_strong_match = bool(normalized_entity and normalized_entity in normalized_strong)
                full_match = bool(normalized_entity and normalized_entity in normalized_evidence)
                is_strict_mode = query_mode in {"organization", "score_query", "source_query", "comparison", "missing_entity"}
                if full_strong_match or (is_strict_mode and strong_match_count >= max(1, len(tokens) - 1)) or (not is_strict_mode and (full_match or matched_count >= max(1, len(tokens) - 1))):
                    matched_any = True
                    entity_matches[entity]["evidence_ids"].append(evidence_id)
                    entity_matches[entity]["source_urls"].extend(self._filter_source_urls([payload.get("url")]))
                    entity_matches[entity]["confidence"] = max(
                        float(entity_matches[entity]["confidence"] or 0.0),
                        float(payload.get("confidence") or 0.0),
                    )
            if matched_any:
                relevant_ids.append(evidence_id)
        relevant_ids = self._dedupe_list(relevant_ids)
        for entity, payload in entity_matches.items():
            payload["evidence_ids"] = self._dedupe_list(payload.get("evidence_ids") or [])
            payload["source_urls"] = self._filter_source_urls(payload.get("source_urls") or [])
        return relevant_ids, entity_matches

    def _media_entity_summaries(self, relevant_evidence: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        grouped: Dict[str, Dict[str, Any]] = {}
        for evidence in relevant_evidence:
            name = self._display_entity_from_evidence(evidence)
            if not name:
                continue
            payload = grouped.setdefault(
                name,
                {"name": name, "evidence_ids": [], "source_urls": [], "confidence": 0.0},
            )
            payload["evidence_ids"].append(str(evidence.get("id") or ""))
            payload["source_urls"].extend(self._filter_source_urls([evidence.get("url")]))
            payload["confidence"] = max(float(payload.get("confidence") or 0.0), float(evidence.get("confidence") or 0.0))
        results: List[Dict[str, Any]] = []
        for name, payload in grouped.items():
            source_urls = self._filter_source_urls(payload["source_urls"])
            results.append(
                {
                    "name": name,
                    "evidence_ids": self._dedupe_list(payload["evidence_ids"]),
                    "source_urls": source_urls,
                    "source_count": len(source_urls),
                    "confidence": float(payload["confidence"] or 0.0),
                }
            )
        results.sort(key=lambda item: (item["source_count"], item["confidence"]), reverse=True)
        return results

    def _display_entity_from_evidence(self, evidence: Dict[str, Any]) -> str:
        source_name = str(evidence.get("source_name") or "").strip()
        title = str(evidence.get("title") or "").strip()
        if "/" in source_name:
            tail = source_name.split("/")[-1].strip()
            if tail and tail.lower() not in GENERIC_SOURCE_PREFIXES:
                return tail
        if source_name and source_name.lower() not in GENERIC_SOURCE_PREFIXES and not self._is_valid_url(source_name):
            return source_name
        if title:
            for part in re.split(r"[-:|]", title):
                candidate = part.strip()
                if candidate and len(candidate) >= 4:
                    return candidate
        url = str(evidence.get("url") or "").strip()
        if self._is_valid_url(url):
            domain = re.sub(r"^https?://(www\.)?", "", url).split("/")[0]
            return domain
        return ""

    def _facts_lookup(self, answer_context: AnswerContext) -> Dict[str, List[CoreFact]]:
        lookup: Dict[str, List[CoreFact]] = {}
        for fact in list(answer_context.facts or []):
            field_name = str(fact.field or "").strip().lower()
            if field_name:
                lookup.setdefault(field_name, []).append(fact)
        return lookup

    def _first_fact(self, answer_context: AnswerContext, field_name: str, relevant_evidence_ids: List[str]) -> CoreFact | None:
        candidates = list(self._facts_lookup(answer_context).get(field_name, []))
        if not candidates:
            return None
        if relevant_evidence_ids:
            for fact in candidates:
                if set(fact.evidence_ids or []).intersection(set(relevant_evidence_ids)):
                    return fact
        return candidates[0]

    def _primary_entity(self, context: Dict[str, Any]) -> str:
        entities = list(context.get("target_entities") or [])
        if entities:
            return entities[0]
        return str(context.get("target_scope") or "the requested entity")

    def _relevant_evidence(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        return list(context.get("relevant_evidence") or [])

    def _score_support_profile(
        self,
        input_data: InsightInput,
        evidence_index: Dict[str, Dict[str, Any]],
        context: Dict[str, Any],
    ) -> Dict[str, Dict[str, Any]]:
        answer_context = self._coerce_answer_context(input_data.answer_context)
        relevant_ids = list(context.get("relevant_evidence_ids") or [])
        relevant_evidence = self._relevant_evidence(context)

        leader_fact = self._first_fact(answer_context, "leader_name", relevant_ids)
        website_fact = self._first_fact(answer_context, "official_website", relevant_ids)
        member_fact = self._first_fact(answer_context, "member_count", relevant_ids)
        valid_urls = self._filter_source_urls([evidence.get("url") for evidence in relevant_evidence])
        digital_urls = [url for url in valid_urls if any(marker in url.lower() for marker in ["youtube", "facebook", "instagram", "x.com", "twitter", "tiktok", "website", "web", "victory", "cbnasia", "veritas", "febc"])]
        source_domains = {re.sub(r"^https?://(www\.)?", "", url).split("/")[0] for url in valid_urls}

        profile: Dict[str, Dict[str, Any]] = {
            "people_score": {"visible_support": [], "missing_support": [], "evidence_ids": []},
            "digital_score": {"visible_support": [], "missing_support": [], "evidence_ids": []},
            "intel_score": {"visible_support": [], "missing_support": [], "evidence_ids": []},
            "composite_score": {"visible_support": [], "missing_support": [], "evidence_ids": []},
        }
        if leader_fact is not None:
            profile["people_score"]["visible_support"].append(f"named leadership is visible ({leader_fact.value})")
            profile["people_score"]["evidence_ids"].extend(list(leader_fact.evidence_ids or []))
        else:
            profile["people_score"]["missing_support"].append("named leadership support is thin")
        if member_fact is not None:
            profile["people_score"]["visible_support"].append(f"reported scale is visible ({member_fact.value})")
            profile["people_score"]["evidence_ids"].extend(list(member_fact.evidence_ids or []))
        else:
            profile["people_score"]["missing_support"].append("member or audience scale is not clearly supported")

        if website_fact is not None:
            profile["digital_score"]["visible_support"].append(f"an official website is visible ({website_fact.value})")
            profile["digital_score"]["evidence_ids"].extend(list(website_fact.evidence_ids or []))
        else:
            profile["digital_score"]["missing_support"].append("an official website is not clearly supported")
        if digital_urls:
            profile["digital_score"]["visible_support"].append(f"{len(digital_urls)} digital or channel URL(s) are visible")
        else:
            profile["digital_score"]["missing_support"].append("social or channel coverage remains thin")

        if relevant_ids:
            profile["intel_score"]["visible_support"].append(f"{len(relevant_ids)} matched evidence item(s) are available")
            profile["intel_score"]["evidence_ids"].extend(relevant_ids[:4])
        if source_domains:
            profile["intel_score"]["visible_support"].append(f"source coverage spans {len(source_domains)} domain(s)")
        else:
            profile["intel_score"]["missing_support"].append("source diversity is still thin")
        if len(source_domains) < 2:
            profile["intel_score"]["missing_support"].append("more independent domains are needed for stronger validation")

        people_value = self._safe_number((input_data.score_fields or {}).get("people_score"))
        digital_value = self._safe_number((input_data.score_fields or {}).get("digital_score"))
        intel_value = self._safe_number((input_data.score_fields or {}).get("intel_score"))
        if people_value is not None and people_value < 50:
            profile["people_score"]["missing_support"].append("people-related support is weaker than a high-confidence organizational profile would need")
        if digital_value is not None and digital_value < 40:
            profile["digital_score"]["missing_support"].append("digital support remains materially thinner than the rest of the profile")
        if intel_value is not None and intel_value < 50:
            profile["intel_score"]["missing_support"].append("intelligence coverage remains thinner than a strong research profile would need")

        component_labels = []
        for field_name in ("people_score", "digital_score", "intel_score"):
            score_value = self._safe_number((input_data.score_fields or {}).get(field_name))
            if score_value is not None:
                component_labels.append(f"{SCORE_FIELD_TITLES[field_name]}={int(score_value)}")
        if component_labels:
            profile["composite_score"]["visible_support"].append(f"component scores currently visible: {', '.join(component_labels)}")
        profile["composite_score"]["missing_support"].append("composite should be read as an aggregate display, not as a standalone opportunity score")

        for payload in profile.values():
            payload["evidence_ids"] = self._dedupe_list(payload.get("evidence_ids") or [])
        return profile

    def _score_strength_labels(self, input_data: InsightInput, answer_context: AnswerContext) -> Tuple[str, str]:
        scores = []
        for field_name, label in SCORE_FIELD_TITLES.items():
            if field_name == "composite_score":
                continue
            value = self._safe_number((input_data.score_fields or {}).get(field_name))
            if value is not None:
                scores.append((label, value))
        if not scores:
            for fact in list(answer_context.facts or []):
                field_name = str(fact.field or "").strip().lower()
                if field_name == "composite_score" or field_name not in SCORE_FIELD_TITLES:
                    continue
                value = self._safe_number(fact.value)
                if value is not None:
                    scores.append((SCORE_FIELD_TITLES[field_name], value))
        if not scores:
            return "", ""
        strongest = max(scores, key=lambda item: item[1])[0]
        weakest = min(scores, key=lambda item: item[1])[0]
        return strongest, weakest

    def _safe_number(self, value: Any) -> float | None:
        text = str(value or "").strip()
        if not text:
            return None
        digits = []
        for char in text:
            if char.isdigit() or char == ".":
                digits.append(char)
            elif digits:
                break
        if not digits:
            return None
        try:
            return float("".join(digits))
        except ValueError:
            return None

    def _humanize_field(self, field_name: str) -> str:
        parts = [part for part in str(field_name or "").replace("-", "_").split("_") if part]
        if not parts:
            return "Unknown Field"
        return " ".join(part.capitalize() for part in parts)

    def _dedupe_list(self, items: List[Any]) -> List[str]:
        seen = set()
        ordered: List[str] = []
        for item in list(items or []):
            text = str(item or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            ordered.append(text)
        return ordered

    def _new_id(self, prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex[:12]}"
