from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from services.evidence_graph import EvidenceGraph
from services.evidence_models import EvidenceBundle, Fact
from services.runtime_metrics import get_runtime_metrics


@dataclass(frozen=True)
class EvidenceVerificationResult:
    verification_pass: bool
    evidence_ready: bool
    citation_ready: bool
    confidence: float
    missing_facts: List[str] = field(default_factory=list)
    unsupported_facts: List[str] = field(default_factory=list)
    conflicting_facts: List[Dict[str, Any]] = field(default_factory=list)
    duplicate_sources: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verification_pass": bool(self.verification_pass),
            "evidence_ready": bool(self.evidence_ready),
            "citation_ready": bool(self.citation_ready),
            "confidence": float(self.confidence),
            "missing_facts": list(self.missing_facts or []),
            "unsupported_facts": list(self.unsupported_facts or []),
            "conflicting_facts": [dict(item or {}) for item in (self.conflicting_facts or []) if isinstance(item, dict)],
            "duplicate_sources": list(self.duplicate_sources or []),
            "metadata": dict(self.metadata or {}),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EvidenceVerificationResult":
        payload = data or {}
        return cls(
            verification_pass=bool(payload.get("verification_pass")),
            evidence_ready=bool(payload.get("evidence_ready")),
            citation_ready=bool(payload.get("citation_ready")),
            confidence=float(payload.get("confidence") or 0.0),
            missing_facts=[str(item) for item in (payload.get("missing_facts") or []) if str(item or "").strip()],
            unsupported_facts=[str(item) for item in (payload.get("unsupported_facts") or []) if str(item or "").strip()],
            conflicting_facts=[dict(item or {}) for item in (payload.get("conflicting_facts") or []) if isinstance(item, dict)],
            duplicate_sources=[str(item) for item in (payload.get("duplicate_sources") or []) if str(item or "").strip()],
            metadata=dict(payload.get("metadata") or {}),
        )


class EvidenceVerifier:
    def __init__(self, trace_center: Any = None, runtime_metrics: Any = None):
        self.trace_center = trace_center
        self.runtime_metrics = runtime_metrics or get_runtime_metrics()

    def verify_bundle(
        self,
        bundle: EvidenceBundle | Dict[str, Any],
        *,
        required_fields: List[str] | None = None,
        minimum_sources: int = 1,
    ) -> EvidenceVerificationResult:
        evidence_bundle = bundle if isinstance(bundle, EvidenceBundle) else EvidenceBundle.from_dict(bundle or {})
        required_fields = [str(item) for item in (required_fields or []) if str(item or "").strip()]
        self._trace(
            "Evidence Verification Started",
            metadata={
                "fact_count": len(evidence_bundle.facts or []),
                "evidence_count": len(evidence_bundle.evidences or []),
            },
        )

        support = self.verify_fact_support(evidence_bundle)
        citation = self.verify_citation(evidence_bundle)
        conflict = self.verify_conflict(evidence_bundle)
        diversity = self.verify_source_diversity(evidence_bundle, minimum_sources=minimum_sources)

        fact_fields = {str(fact.predicate or "").strip().lower() for fact in (evidence_bundle.facts or [])}
        missing_facts: List[str] = []
        for field in required_fields:
            normalized = str(field or "").strip().lower()
            if not normalized:
                continue
            if normalized in {"source", "title", "url"}:
                if normalized == "source" and citation["source_ready"]:
                    continue
                if normalized == "title" and citation["title_ready"]:
                    continue
                if normalized == "url":
                    continue
            elif normalized in fact_fields:
                continue
            else:
                missing_facts.append(str(field))

        confidence = self.compute_verification_score(
            evidence_bundle,
            supported_fact_count=int(support["supported_fact_count"]),
            unsupported_fact_count=int(support["unsupported_fact_count"]),
            citation_ready_rate=float(citation["citation_ready_rate"]),
            conflict_count=int(conflict["conflict_count"]),
            source_diversity_score=float(diversity["source_diversity_score"]),
        )

        verification_pass = (
            bool(support["evidence_ready"])
            and bool(citation["citation_ready"])
            and not bool(conflict["conflict_detected"])
            and not bool(missing_facts)
        )

        result = EvidenceVerificationResult(
            verification_pass=verification_pass,
            evidence_ready=bool(support["evidence_ready"]),
            citation_ready=bool(citation["citation_ready"]),
            confidence=float(confidence),
            missing_facts=self._dedupe_list(missing_facts),
            unsupported_facts=list(support["unsupported_facts"] or []),
            conflicting_facts=list(conflict["conflicting_facts"] or []),
            duplicate_sources=list(diversity["duplicate_sources"] or []),
            metadata={
                "supported_fact_count": int(support["supported_fact_count"]),
                "unsupported_fact_count": int(support["unsupported_fact_count"]),
                "citation_ready_rate": float(citation["citation_ready_rate"]),
                "citation_missing": list(citation["citation_missing"] or []),
                "source_diversity_score": float(diversity["source_diversity_score"]),
                "source_count": int(diversity["source_count"]),
                "minimum_sources": int(minimum_sources or 1),
                "missing_sources": list(diversity["missing_sources"] or []),
                "conflict_detected": bool(conflict["conflict_detected"]),
                "conflict_count": int(conflict["conflict_count"]),
            },
        )
        self._record_metrics(result)
        self._trace(
            "Evidence Verification Finished",
            metadata={
                "verification_pass": bool(result.verification_pass),
                "confidence": float(result.confidence),
                "unsupported_fact_count": len(result.unsupported_facts or []),
                "conflict_count": len(result.conflicting_facts or []),
            },
        )
        return result

    def verify_fact_support(self, bundle: EvidenceBundle | Dict[str, Any]) -> Dict[str, Any]:
        evidence_bundle = bundle if isinstance(bundle, EvidenceBundle) else EvidenceBundle.from_dict(bundle or {})
        evidence_ids = {str(item.evidence_id) for item in (evidence_bundle.evidences or [])}
        unsupported_facts: List[str] = []
        supported_count = 0
        for fact in evidence_bundle.facts or []:
            fact_label = self._fact_label(fact)
            supported = bool([evidence_id for evidence_id in (fact.evidence_ids or []) if evidence_id in evidence_ids])
            if supported:
                supported_count += 1
                self._trace("Fact Supported", metadata={"fact": fact_label, "fact_id": fact.fact_id})
            else:
                unsupported_facts.append(fact_label)
                self._trace("Fact Unsupported", metadata={"fact": fact_label, "fact_id": fact.fact_id})
        unsupported_count = len(unsupported_facts)
        return {
            "evidence_ready": bool((supported_count > 0) and unsupported_count == 0),
            "supported_fact_count": supported_count,
            "unsupported_fact_count": unsupported_count,
            "unsupported_facts": unsupported_facts,
        }

    def verify_citation(self, bundle: EvidenceBundle | Dict[str, Any]) -> Dict[str, Any]:
        evidence_bundle = bundle if isinstance(bundle, EvidenceBundle) else EvidenceBundle.from_dict(bundle or {})
        ready_count = 0
        citation_missing: List[str] = []
        source_ready = True
        title_ready = True
        for evidence in evidence_bundle.evidences or []:
            source_name = str((evidence.metadata or {}).get("source_name") or evidence.source_id or "").strip()
            title = str(evidence.title or "").strip()
            url = str(evidence.url or "").strip()
            missing: List[str] = []
            if not source_name:
                source_ready = False
                missing.append("source")
            if not title:
                title_ready = False
                missing.append("title")
            if missing:
                citation_missing.append(f"{evidence.evidence_id}:{','.join(missing)}")
                self._trace("Citation Missing", metadata={"evidence_id": evidence.evidence_id, "missing": list(missing)})
            else:
                ready_count += 1
            if not url:
                citation_missing.append(f"{evidence.evidence_id}:url_optional_missing")
        total = len(evidence_bundle.evidences or [])
        ready_rate = round((ready_count / total), 3) if total else 0.0
        return {
            "citation_ready": bool(total > 0 and source_ready and title_ready),
            "citation_ready_rate": ready_rate,
            "citation_missing": self._dedupe_list(citation_missing),
            "source_ready": source_ready,
            "title_ready": title_ready,
        }

    def verify_conflict(self, bundle: EvidenceBundle | Dict[str, Any]) -> Dict[str, Any]:
        evidence_bundle = bundle if isinstance(bundle, EvidenceBundle) else EvidenceBundle.from_dict(bundle or {})
        graph = self._graph_from_bundle(evidence_bundle)
        conflict_edges = [edge for edge in (graph.edges or []) if str(edge.relation or "").strip().lower() == "contradicts"]
        conflicting_facts = [dict(item or {}) for item in (evidence_bundle.conflicts or []) if isinstance(item, dict)]
        if conflict_edges and not conflicting_facts:
            conflicting_facts = [{"relation": "contradicts", "edge_count": len(conflict_edges)}]
        if conflicting_facts:
            self._trace("Conflict Verified", metadata={"conflict_count": len(conflicting_facts)})
        return {
            "conflict_detected": bool(conflict_edges or conflicting_facts),
            "conflict_count": len(conflict_edges or conflicting_facts),
            "conflicting_facts": conflicting_facts,
        }

    def verify_source_diversity(self, bundle: EvidenceBundle | Dict[str, Any], *, minimum_sources: int = 1) -> Dict[str, Any]:
        evidence_bundle = bundle if isinstance(bundle, EvidenceBundle) else EvidenceBundle.from_dict(bundle or {})
        evidence_lookup = {str(item.evidence_id): item for item in (evidence_bundle.evidences or [])}
        source_counts: Dict[str, int] = {}
        for fact in evidence_bundle.facts or []:
            fact_sources = set()
            for evidence_id in (fact.evidence_ids or []):
                evidence = evidence_lookup.get(str(evidence_id))
                if evidence is None:
                    continue
                source_name = str((evidence.metadata or {}).get("source_name") or evidence.source_id or "").strip()
                if source_name:
                    fact_sources.add(source_name)
            for source_name in fact_sources:
                source_counts[source_name] = source_counts.get(source_name, 0) + 1
        unique_sources = len(source_counts)
        source_diversity_score = 0.0
        if evidence_bundle.facts:
            source_diversity_score = round(min(1.0, unique_sources / max(1, len(evidence_bundle.facts))), 3)
        elif unique_sources > 0:
            source_diversity_score = 1.0
        duplicate_sources = sorted([name for name, count in source_counts.items() if count > 1])
        missing_sources: List[str] = []
        if unique_sources < max(1, int(minimum_sources or 1)):
            missing_sources.append(f"need_{int(minimum_sources or 1)}_sources_have_{unique_sources}")
        return {
            "source_diversity_score": source_diversity_score,
            "source_count": unique_sources,
            "duplicate_sources": duplicate_sources,
            "missing_sources": missing_sources,
        }

    def compute_verification_score(
        self,
        bundle: EvidenceBundle | Dict[str, Any],
        *,
        supported_fact_count: int,
        unsupported_fact_count: int,
        citation_ready_rate: float,
        conflict_count: int,
        source_diversity_score: float,
    ) -> float:
        evidence_bundle = bundle if isinstance(bundle, EvidenceBundle) else EvidenceBundle.from_dict(bundle or {})
        fact_total = len(evidence_bundle.facts or [])
        evidence_total = len(evidence_bundle.evidences or [])
        support_ratio = supported_fact_count / fact_total if fact_total else 0.0
        evidence_ratio = min(1.0, evidence_total / max(1, fact_total or 1))
        penalty = 0.0
        if unsupported_fact_count > 0:
            penalty += min(0.35, unsupported_fact_count * 0.15)
        if conflict_count > 0:
            penalty += min(0.5, conflict_count * 0.25)
        score = (
            evidence_ratio * 20.0
            + support_ratio * 35.0
            + float(citation_ready_rate or 0.0) * 20.0
            + float(source_diversity_score or 0.0) * 25.0
            - penalty * 100.0
        )
        return round(max(0.0, min(score, 100.0)), 2)

    def export_result(self, result: EvidenceVerificationResult | Dict[str, Any]) -> Dict[str, Any]:
        if isinstance(result, EvidenceVerificationResult):
            return result.to_dict()
        return EvidenceVerificationResult.from_dict(result or {}).to_dict()

    def _graph_from_bundle(self, bundle: EvidenceBundle) -> EvidenceGraph:
        graph_payload = dict((bundle.metadata or {}).get("evidence_graph") or {})
        return EvidenceGraph.from_dict(graph_payload) if graph_payload else EvidenceGraph()

    def _fact_label(self, fact: Fact) -> str:
        return f"{str(fact.subject or '').strip()}::{str(fact.predicate or '').strip()}::{str(fact.object or '').strip()}"

    def _record_metrics(self, result: EvidenceVerificationResult) -> None:
        self.runtime_metrics.set("verification_score", float(result.confidence or 0.0))
        self.runtime_metrics.set(
            "supported_fact_count",
            float(result.metadata.get("supported_fact_count") or 0.0),
        )
        self.runtime_metrics.set(
            "unsupported_fact_count",
            float(result.metadata.get("unsupported_fact_count") or 0.0),
        )
        self.runtime_metrics.set(
            "citation_ready_rate",
            float(result.metadata.get("citation_ready_rate") or 0.0),
        )
        self.runtime_metrics.set(
            "conflict_detected",
            1.0 if bool(result.metadata.get("conflict_detected")) else 0.0,
        )
        self.runtime_metrics.set(
            "source_diversity_score",
            float(result.metadata.get("source_diversity_score") or 0.0),
        )

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
        self.trace_center.record_event("EVIDENCE", name, metadata=metadata or {})
