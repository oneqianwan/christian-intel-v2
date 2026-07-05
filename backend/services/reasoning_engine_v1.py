import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Tuple


from services.core_models import QuestionType, Requirement
from services.feature_flags import feature_flag_enabled
from services.knowledge_layer import KnowledgeGraph


@dataclass
class EvidenceEvaluation:
    sufficient: bool
    coverage: float
    missing_fields: List[str]
    missing_sources: List[str]
    field_coverage: Dict[str, bool]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sufficient": bool(self.sufficient),
            "coverage": float(self.coverage),
            "missing_fields": list(self.missing_fields),
            "missing_sources": list(self.missing_sources),
            "field_coverage": dict(self.field_coverage),
        }


@dataclass
class Conflict:
    field: str
    severity: str
    type: str
    values: List[str]
    sources: List[str]
    evidence: List[Dict[str, Any]]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "field": str(self.field),
            "severity": str(self.severity),
            "type": str(self.type),
            "values": list(self.values),
            "sources": list(self.sources),
            "evidence": list(self.evidence),
        }


@dataclass
class ReasoningResult:
    question_type: QuestionType
    country: str
    requirement: Requirement
    tool_plan: List[str]
    evaluation: EvidenceEvaluation | None = None
    conflicts: List[Conflict] | None = None
    ranked_evidence: List[Dict[str, Any]] | None = None
    merged_facts: List[Dict[str, Any]] | None = None
    outline: List[str] | None = None
    verification: Dict[str, Any] | None = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "question_type": self.question_type.value,
            "country": self.country,
            "requirement": self.requirement.to_dict() if self.requirement else {},
            "tool_plan": list(self.tool_plan or []),
            "evaluation": self.evaluation.to_dict() if self.evaluation else None,
            "conflicts": [c.to_dict() for c in (self.conflicts or [])] if self.conflicts is not None else None,
            "ranked_evidence": list(self.ranked_evidence or []) if self.ranked_evidence is not None else None,
            "merged_facts": list(self.merged_facts or []) if self.merged_facts is not None else None,
            "outline": list(self.outline or []) if self.outline is not None else None,
            "verification": dict(self.verification or {}) if self.verification is not None else None,
        }


class ReasoningEngineV1:
    def __init__(self):
        self._source_trust = {
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
            "rss": 0.60,
            "newsapi": 0.55,
            "unknown": 0.30,
        }

    def classify_question(self, user_message: str) -> QuestionType:
        raw = (user_message or "").strip()
        lowered = raw.lower()

        if any(token in lowered for token in ["关系图", "图谱", "graph", "network"]):
            return QuestionType.GRAPH
        if any(token in lowered for token in ["联系方式", "联系信息", "联系人", "邮箱", "电话", "contact"]):
            return QuestionType.CONTACT
        if any(token in lowered for token in ["时间线", "timeline"]):
            return QuestionType.TIMELINE
        if any(token in lowered for token in ["对比", "比较", "vs", "versus", "compare"]):
            return QuestionType.COMPARISON
        if any(token in lowered for token in ["largest", "top", "排名", "最大", "最多", "highest", "biggest"]):
            return QuestionType.RANKING
        if any(token in lowered for token in ["invested in", "who invested", "投资", "融资", "funding", "investor"]):
            return QuestionType.INVESTMENT
        if any(token in lowered for token in ["关系", "合作", "partner", "partnership", "collaboration", "relationship"]):
            return QuestionType.RELATIONSHIP
        if any(token in lowered for token in ["最近", "最新", "news", "headline", "intelligence", "动态"]):
            return QuestionType.NEWS
        if any(token in lowered for token in ["国家", "概况", "占比", "宗派构成", "country", "overview", "landscape"]):
            return QuestionType.COUNTRY
        if any(token in lowered for token in ["profile", "介绍", "是什么机构", "是什么组织", "背景", "情况", "画像"]):
            return QuestionType.PROFILE
        return QuestionType.UNKNOWN

    def infer_information_requirements(
        self,
        question_type: QuestionType,
        entities: List[Dict[str, Any]] | None,
        country: str,
    ) -> Requirement:
        qt = question_type
        base_fields = ["source", "updated_at"]
        org_fields = ["name", "country", "website", "leader", "member_count"]
        news_fields = ["title", "published_at", "source", "url"]

        if qt == QuestionType.CONTACT:
            requirement = Requirement(
                required_fields=["name", "country", "website", "leader", "source"] + base_fields,
                required_sources=[],
                minimum_sources=1,
                minimum_confidence=0.0,
                coverage_threshold=0.0,
                allow_partial=True,
            )
            return requirement
        if qt == QuestionType.TIMELINE:
            requirement = Requirement(
                required_fields=news_fields + ["snippet", "ranking"],
                required_sources=[],
                minimum_sources=1,
                minimum_confidence=0.0,
                coverage_threshold=0.0,
                allow_partial=True,
            )
            return requirement
        if qt == QuestionType.NEWS:
            requirement = Requirement(
                required_fields=news_fields + ["snippet", "country", "ranking"],
                required_sources=[],
                minimum_sources=1,
                minimum_confidence=0.0,
                coverage_threshold=0.0,
                allow_partial=True,
            )
            return requirement
        if qt == QuestionType.COMPARISON:
            requirement = Requirement(
                required_fields=["name", "country", "source", "updated_at"],
                required_sources=[],
                minimum_sources=1,
                minimum_confidence=0.0,
                coverage_threshold=0.0,
                allow_partial=True,
            )
            return requirement
        if qt == QuestionType.RANKING:
            requirement = Requirement(
                required_fields=["name", "country", "member_count", "source", "updated_at", "ranking"],
                required_sources=[],
                minimum_sources=2,
                minimum_confidence=0.0,
                coverage_threshold=0.0,
                allow_partial=True,
            )
            return requirement
        if qt in {QuestionType.INVESTMENT, QuestionType.RELATIONSHIP}:
            meta = ["graph"] if qt == QuestionType.RELATIONSHIP else []
            requirement = Requirement(
                required_fields=["name", "country", "source", "url", "updated_at"] + meta,
                required_sources=[],
                minimum_sources=1,
                minimum_confidence=0.0,
                coverage_threshold=0.0,
                allow_partial=True,
            )
            return requirement
        if qt == QuestionType.GRAPH:
            requirement = Requirement(
                required_fields=["name", "country", "source", "updated_at", "graph"],
                required_sources=[],
                minimum_sources=1,
                minimum_confidence=0.0,
                coverage_threshold=0.0,
                allow_partial=True,
            )
            return requirement
        if qt == QuestionType.COUNTRY:
            requirement = Requirement(
                required_fields=["country", "source", "updated_at"],
                required_sources=[],
                minimum_sources=1,
                minimum_confidence=0.0,
                coverage_threshold=0.0,
                allow_partial=True,
            )
            return requirement
        if qt == QuestionType.PROFILE:
            requirement = Requirement(
                required_fields=org_fields + base_fields,
                required_sources=[],
                minimum_sources=1,
                minimum_confidence=0.0,
                coverage_threshold=0.0,
                allow_partial=True,
            )
            return requirement
        requirement = Requirement(
            required_fields=["source"],
            required_sources=[],
            minimum_sources=1,
            minimum_confidence=0.0,
            coverage_threshold=0.0,
            allow_partial=True,
        )
        return requirement

    def plan_tools(self, requirement: Requirement, entities: List[Dict[str, Any]] | None) -> List[str]:
        fields = set((requirement.required_fields or []) if requirement else [])

        plan: List[str] = []
        if "country" in fields and "name" not in fields:
            plan.append("query_arda_country")
            plan.append("query_database")
            return plan

        if "member_count" in fields or "leader" in fields or "website" in fields:
            plan.append("query_organization_profile")
            if "snippet" in fields or "title" in fields:
                plan.append("query_intelligence")
            return self._dedupe_plan(plan)

        if "title" in fields or "published_at" in fields:
            plan.append("query_intelligence")
            if "ranking" in fields:
                plan.append("query_database")
            return self._dedupe_plan(plan)

        if "graph" in fields:
            plan.append("query_graph")
        plan.append("query_database")
        return self._dedupe_plan(plan)

    def evaluate_evidence(self, knowledge_input: Any, requirement: Requirement) -> Dict[str, Any]:
        graph = self._ensure_knowledge_graph(knowledge_input)
        if graph is not None:
            return self._evaluate_knowledge_graph(graph, requirement)
        tool_results = list(knowledge_input or [])
        required_fields = list(requirement.required_fields or []) if requirement else []
        meta_fields = {"ranking", "graph"}
        effective_fields = [f for f in required_fields if str(f).strip().lower() not in meta_fields]
        min_sources = int(requirement.minimum_sources or 1) if requirement else 1

        coverage_hits = 0
        missing_fields: List[str] = []
        field_coverage: Dict[str, bool] = {}

        evidence = self._extract_evidence(tool_results)
        sources = {self._normalize_source_name(item.get("source_name") or "") for item in evidence if item.get("source_name")}
        sources = {s for s in sources if s}

        for field in effective_fields:
            has = self._has_field(tool_results, evidence, field)
            field_coverage[str(field)] = bool(has)
            if has:
                coverage_hits += 1
            else:
                missing_fields.append(field)

        coverage = (coverage_hits / len(effective_fields)) if effective_fields else 0.0
        missing_sources: List[str] = []
        if len(sources) < min_sources:
            missing_sources = [f"need_{min_sources}_sources_have_{len(sources)}"]

        sufficient = (not missing_fields) and (len(sources) >= min_sources)
        evaluation = EvidenceEvaluation(
            sufficient=bool(sufficient),
            coverage=float(round(coverage, 2)),
            missing_fields=missing_fields,
            missing_sources=missing_sources,
            field_coverage=field_coverage,
        )
        return evaluation.to_dict()

    def detect_conflicts(self, knowledge_input: Any) -> List[Dict[str, Any]]:
        graph = self._ensure_knowledge_graph(knowledge_input)
        if graph is not None:
            return self._detect_conflicts_from_graph(graph)
        tool_results = list(knowledge_input or [])
        fields = ["leader_name", "member_count", "member_estimate", "official_website", "country", "denomination"]
        conflicts: List[Conflict] = []
        evidence = self._extract_evidence(tool_results)
        all_sources = sorted({(item.get("source_name") or "").strip() for item in evidence if (item.get("source_name") or "").strip()})
        for field in fields:
            values = self._collect_values(tool_results, field)
            unique = sorted({v for v in values if v})
            if len(unique) >= 2:
                conflicts.append(
                    Conflict(
                        field=field,
                        severity="medium",
                        type="field_conflict",
                        values=unique,
                        sources=all_sources,
                        evidence=[],
                    )
                )
        return [c.to_dict() for c in conflicts]

    def rank_evidence(self, knowledge_input: Any) -> List[Dict[str, Any]]:
        graph = self._ensure_knowledge_graph(knowledge_input)
        if graph is not None:
            evidence = self._evidence_from_graph(graph)
            return sorted(evidence, key=lambda item: (self._best_timestamp(item), self._coerce_float(item.get("confidence")), self._source_trust_score(item.get("source_name") or "")), reverse=True)
        tool_results = list(knowledge_input or [])
        evidence = self._extract_evidence(tool_results)
        deduped = self._dedupe_evidence(evidence)

        def score(item: Dict[str, Any]) -> Tuple[float, float, float]:
            ts = self._best_timestamp(item)
            conf = self._coerce_float(item.get("confidence"))
            trust = self._source_trust_score(item.get("source_name") or "")
            return (ts, conf, trust)

        return sorted(deduped, key=score, reverse=True)

    def merge_duplicate_facts(self, knowledge_input: Any) -> List[Dict[str, Any]]:
        graph = self._ensure_knowledge_graph(knowledge_input)
        if graph is not None:
            merged: List[Dict[str, Any]] = []
            for node in graph.nodes or []:
                merged.append(
                    {
                        "key": f"{node.type}:{node.name}",
                        "representative": node.to_dict(),
                        "evidence": list(node.evidence_ids or []),
                    }
                )
            for relation in graph.relations or []:
                merged.append(
                    {
                        "key": f"{relation.source_node}:{relation.relation}:{relation.target_node}",
                        "representative": relation.to_dict(),
                        "evidence": list(relation.evidence_ids or []),
                    }
                )
            return merged
        evidence = list(knowledge_input or [])
        groups: Dict[str, List[Dict[str, Any]]] = {}
        for item in evidence or []:
            key = (item.get("url") or "").strip()
            if not key:
                key = "|".join(
                    [
                        (item.get("title") or "").strip(),
                        (item.get("source_name") or "").strip(),
                        (item.get("published_at") or "").strip(),
                    ]
                ).strip("|")
            if not key:
                continue
            groups.setdefault(key, []).append(item)

        merged: List[Dict[str, Any]] = []
        for key, items in groups.items():
            representative = items[0]
            merged.append({"key": key, "representative": representative, "evidence": items})
        return merged

    def build_answer_outline(self, question_type: QuestionType, requirement: Requirement, knowledge_input: Any) -> List[str]:
        qt = question_type
        if qt == QuestionType.RANKING:
            return ["Introduction", "Ranking", "Evidence", "Conclusion"]
        if qt == QuestionType.COMPARISON:
            return ["Overview", "Comparison", "Differences", "Evidence", "Summary"]
        if qt in {QuestionType.TIMELINE, QuestionType.NEWS}:
            return ["Overview", "Chronology", "Current Status", "Sources"]
        if qt == QuestionType.PROFILE:
            return ["Overview", "Key Facts", "Recent Signals", "Evidence"]
        if qt == QuestionType.CONTACT:
            return ["Contact Summary", "Evidence"]
        if qt in {QuestionType.INVESTMENT, QuestionType.RELATIONSHIP}:
            return ["Overview", "Relationships", "Evidence", "Summary"]
        if qt == QuestionType.GRAPH:
            return ["Graph Overview", "Key Links", "Evidence"]
        if qt == QuestionType.COUNTRY:
            return ["Country Baseline", "Evidence"]
        return ["Answer", "Evidence"]

    def verification(self, evaluation: Dict[str, Any], conflicts: List[Dict[str, Any]], evidence: List[Dict[str, Any]]) -> Dict[str, Any]:
        evidence_enough = bool(evaluation.get("sufficient"))
        citation_ready = bool(evidence)
        has_conflict = bool(conflicts)
        answer_ready = evidence_enough and citation_ready
        return {
            "evidence_enough": evidence_enough,
            "citation_ready": citation_ready,
            "has_conflict": has_conflict,
            "answer_ready": answer_ready,
        }

    def build_reasoning_result_pre(
        self,
        user_message: str,
        entities: List[Dict[str, Any]] | None,
        country: str,
        memory_context: Any = None,
    ) -> ReasoningResult:
        memory_entities = list(getattr(memory_context, "current_entities", []) or [])
        memory_country = str(getattr(memory_context, "current_country", "") or "")
        memory_requirement = getattr(memory_context, "current_requirement", None)
        entities = list(entities or memory_entities or [])
        country = str(country or memory_country or "")
        question_type = self.classify_question(user_message)
        if question_type == QuestionType.UNKNOWN and isinstance(memory_requirement, Requirement):
            requirement = memory_requirement
        else:
            requirement = self.infer_information_requirements(question_type, entities, country)
        capability_planner_enabled = feature_flag_enabled("CAPABILITY_PLANNER_ENABLED")
        tool_plan = [] if capability_planner_enabled else self.plan_tools(requirement, entities)
        return ReasoningResult(
            question_type=question_type,
            country=str(country or ""),
            requirement=requirement,
            tool_plan=tool_plan,
        )

    def build_reasoning_result_post(self, pre: ReasoningResult, knowledge_input: Any) -> ReasoningResult:
        evaluation_dict = self.evaluate_evidence(knowledge_input, pre.requirement)
        evaluation = EvidenceEvaluation(
            sufficient=bool(evaluation_dict.get("sufficient")),
            coverage=float(evaluation_dict.get("coverage") or 0.0),
            missing_fields=list(evaluation_dict.get("missing_fields") or []),
            missing_sources=list(evaluation_dict.get("missing_sources") or []),
            field_coverage=dict(evaluation_dict.get("field_coverage") or {}),
        )
        conflicts = []
        for item in self.detect_conflicts(knowledge_input) or []:
            if isinstance(item, dict):
                conflicts.append(
                    Conflict(
                        field=str(item.get("field") or ""),
                        severity=str(item.get("severity") or "medium"),
                        type=str(item.get("type") or "field_conflict"),
                        values=list(item.get("values") or []),
                        sources=list(item.get("sources") or []),
                        evidence=list(item.get("evidence") or []),
                    )
                )
        ranked = self.rank_evidence(knowledge_input)
        merged = self.merge_duplicate_facts(knowledge_input)
        outline = self.build_answer_outline(pre.question_type, pre.requirement, knowledge_input)
        verification = self.verification(evaluation.to_dict(), [c.to_dict() for c in conflicts], ranked)
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

    def _ensure_knowledge_graph(self, value: Any) -> KnowledgeGraph | None:
        if isinstance(value, KnowledgeGraph):
            return value
        if isinstance(value, dict) and ("nodes" in value or "relations" in value):
            return KnowledgeGraph.from_dict(value)
        return None

    def _evaluate_knowledge_graph(self, graph: KnowledgeGraph, requirement: Requirement) -> Dict[str, Any]:
        required_fields = list(requirement.required_fields or []) if requirement else []
        effective_fields = [field for field in required_fields if str(field).strip().lower() not in {"ranking", "graph"}]
        evidence = self._evidence_from_graph(graph)
        sources = {self._normalize_source_name(item.get("source_name") or "") for item in evidence if item.get("source_name")}
        sources = {item for item in sources if item}
        field_coverage: Dict[str, bool] = {}
        missing_fields: List[str] = []
        covered_count = 0
        for field in effective_fields:
            covered = self._field_covered_in_graph(graph, str(field))
            field_coverage[str(field)] = bool(covered)
            if covered:
                covered_count += 1
            else:
                missing_fields.append(str(field))
        coverage = (covered_count / len(effective_fields)) if effective_fields else 0.0
        minimum_sources = int(requirement.minimum_sources or 1) if requirement else 1
        missing_sources = []
        if len(sources) < minimum_sources:
            missing_sources.append(f"need_{minimum_sources}_sources_have_{len(sources)}")
        evaluation = EvidenceEvaluation(
            sufficient=(not missing_fields) and len(sources) >= minimum_sources,
            coverage=float(round(coverage, 2)),
            missing_fields=missing_fields,
            missing_sources=missing_sources,
            field_coverage=field_coverage,
        )
        return evaluation.to_dict()

    def _detect_conflicts_from_graph(self, graph: KnowledgeGraph) -> List[Dict[str, Any]]:
        conflicts: List[Conflict] = []
        for node in graph.nodes or []:
            node_conflicts = dict((node.properties or {}).get("_conflicts") or {})
            for field, values in node_conflicts.items():
                normalized_values = [str(item) for item in (values or []) if str(item or "").strip()]
                unique_values = sorted({item for item in normalized_values if item})
                if len(unique_values) < 2:
                    continue
                conflicts.append(
                    Conflict(
                        field=str(field),
                        severity="medium",
                        type="field_conflict",
                        values=unique_values,
                        sources=list(node.sources or []),
                        evidence=[{"id": evidence_id} for evidence_id in (node.evidence_ids or [])],
                    )
                )
        return [item.to_dict() for item in conflicts]

    def _evidence_from_graph(self, graph: KnowledgeGraph) -> List[Dict[str, Any]]:
        evidence_index = dict((graph.metadata or {}).get("evidence_index") or {})
        evidence: List[Dict[str, Any]] = []
        for item in evidence_index.values():
            if isinstance(item, dict):
                evidence.append(dict(item))
        return evidence

    def _field_covered_in_graph(self, graph: KnowledgeGraph, field: str) -> bool:
        normalized = str(field or "").strip().lower()
        if not normalized:
            return False
        evidence = self._evidence_from_graph(graph)
        if normalized == "source":
            return any(str(item.get("source_name") or "").strip() for item in evidence)
        if normalized in {"title", "url", "snippet", "confidence", "published_at", "updated_at", "type"}:
            return any(str(item.get(normalized) or "").strip() for item in evidence)
        if normalized in {"graph", "relationship"}:
            return bool(graph.relations)
        for node in graph.nodes or []:
            node_type = str(node.type or "").strip().lower()
            if normalized == "name" and node_type == "organization" and str(node.name or "").strip():
                return True
            if normalized == "country" and ((node_type == "country" and str(node.name or "").strip()) or str((node.properties or {}).get("country") or "").strip()):
                return True
            if normalized in {"leader", "leader_name"}:
                if str((node.properties or {}).get("leader_name") or (node.properties or {}).get("leader") or "").strip():
                    return True
                if any(str(relation.relation or "").upper() == "LED_BY" and relation.source_node == node.id for relation in (graph.relations or [])):
                    return True
            if normalized in {"website", "official_website"} and str((node.properties or {}).get("official_website") or (node.properties or {}).get("website") or "").strip():
                return True
            if normalized in {"member_count", "member_estimate"} and str((node.properties or {}).get("member_count") or (node.properties or {}).get("member_estimate") or "").strip():
                return True
            if normalized == "denomination" and str((node.properties or {}).get("denomination") or "").strip():
                return True
        return False

    def _dedupe_plan(self, plan: List[str]) -> List[str]:
        seen = set()
        ordered: List[str] = []
        for name in plan:
            if not name or name in seen:
                continue
            seen.add(name)
            ordered.append(name)
        return ordered

    def _extract_evidence(self, tool_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        evidence: List[Dict[str, Any]] = []
        for result in tool_results or []:
            if not isinstance(result, dict):
                continue
            items = result.get("evidence")
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict):
                        evidence.append(item)
        return evidence

    def _dedupe_evidence(self, evidence: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        seen = set()
        out: List[Dict[str, Any]] = []
        for item in evidence or []:
            url = (item.get("url") or "").strip()
            key = url or "|".join(
                [
                    (item.get("title") or "").strip(),
                    (item.get("source_name") or "").strip(),
                    (item.get("published_at") or "").strip(),
                ]
            )
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(item)
        return out

    def _best_timestamp(self, item: Dict[str, Any]) -> float:
        published = self._parse_time(item.get("published_at"))
        updated = self._parse_time(item.get("updated_at"))
        ts = max(published, updated)
        return ts

    def _parse_time(self, value: Any) -> float:
        if not value:
            return 0.0
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value).strip()
        if not text:
            return 0.0
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
            return dt.timestamp()
        except Exception:
            return 0.0

    def _coerce_float(self, value: Any) -> float:
        try:
            return float(value or 0.0)
        except Exception:
            return 0.0

    def _normalize_source_name(self, value: str) -> str:
        lowered = (value or "").strip().lower()
        if not lowered:
            return ""
        return lowered

    def _source_trust_score(self, source_name: str) -> float:
        lowered = (source_name or "").strip().lower()
        if not lowered:
            return self._source_trust.get("unknown", 0.30)
        for key, score in self._source_trust.items():
            if key != "unknown" and key in lowered:
                return score
        return self._source_trust.get("unknown", 0.30)

    def _has_field(self, tool_results: List[Dict[str, Any]], evidence: List[Dict[str, Any]], field: str) -> bool:
        fld = (field or "").strip().lower()
        if not fld:
            return False
        if fld in {"title", "url", "snippet", "source", "source_name", "confidence", "published_at", "updated_at", "type"}:
            for item in evidence:
                if fld == "source" and item.get("source_name"):
                    return True
                if fld in item and str(item.get(fld) or "").strip():
                    return True
            return False
        if fld in {"name", "leader", "leader_name", "website", "official_website", "member_count", "member_estimate", "country", "denomination"}:
            values = self._collect_values(tool_results, fld)
            return any(v for v in values)
        return False

    def _collect_values(self, tool_results: List[Dict[str, Any]], field: str) -> List[str]:
        key = (field or "").strip()
        values: List[str] = []
        for result in tool_results or []:
            if not isinstance(result, dict):
                continue
            values.extend(self._collect_from_payload(result, key))
        cleaned = []
        seen = set()
        for v in values:
            norm = (v or "").strip()
            if not norm:
                continue
            if norm in seen:
                continue
            seen.add(norm)
            cleaned.append(norm)
        return cleaned

    def _collect_from_payload(self, payload: Any, key: str) -> List[str]:
        results: List[str] = []
        if isinstance(payload, dict):
            if key in payload and payload.get(key) not in (None, ""):
                results.append(str(payload.get(key)))
            aliases = {
                "leader": ["leader_name"],
                "website": ["official_website", "website", "source_url"],
                "member_count": ["member_count", "member_estimate"],
            }
            for alias in aliases.get(key, []):
                if alias in payload and payload.get(alias) not in (None, ""):
                    results.append(str(payload.get(alias)))
            for value in payload.values():
                if isinstance(value, (dict, list)):
                    results.extend(self._collect_from_payload(value, key))
        elif isinstance(payload, list):
            for item in payload[:30]:
                results.extend(self._collect_from_payload(item, key))
        return results
