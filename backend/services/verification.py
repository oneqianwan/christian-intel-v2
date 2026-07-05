from __future__ import annotations

from typing import Any, Dict, List

from services.core_models import AnswerContext, Requirement
from services.evidence_models import EvidenceBundle
from services.evidence_verifier import EvidenceVerifier
from services.runtime_metrics import get_runtime_metrics


def build_verification_result(
    evidence_bundle: EvidenceBundle | Dict[str, Any],
    answer_context: AnswerContext,
    requirement: Requirement,
    *,
    trace_center: Any = None,
    runtime_metrics: Any = None,
) -> Dict[str, Any]:
    bundle = evidence_bundle if isinstance(evidence_bundle, EvidenceBundle) else EvidenceBundle.from_dict(evidence_bundle or {})
    metrics = runtime_metrics or get_runtime_metrics()
    verifier = EvidenceVerifier(trace_center=trace_center, runtime_metrics=metrics)
    verification = verifier.verify_bundle(
        bundle,
        required_fields=list(requirement.required_fields or []),
        minimum_sources=int(getattr(requirement, "minimum_sources", 1) or 1),
    )
    verification_payload = verification.to_dict()
    missing_fields = _dedupe_list(
        [*list(verification.missing_facts or []), *list(getattr(answer_context, "missing", []) or [])]
    )
    missing_sources = _dedupe_list(list((verification.metadata or {}).get("missing_sources") or []))
    coverage_threshold = float(getattr(requirement, "coverage_threshold", 0.0) or 0.0)
    coverage = _coverage_ratio(requirement, missing_fields, verification)
    blocking_conflict = bool(verification.conflicting_facts)
    result = {
        "evidence_enough": bool(verification.evidence_ready),
        "citation_ready": bool(verification.citation_ready),
        "has_conflict": blocking_conflict,
        "answer_ready": bool(verification.verification_pass),
        "missing_fields": missing_fields,
        "missing_sources": missing_sources,
        "coverage": coverage,
        "coverage_threshold": coverage_threshold,
        "blocking_conflict": blocking_conflict,
        "verification_score": float(verification.confidence or 0.0),
        "evidence_verification": verification_payload,
    }
    return result


def _coverage_ratio(requirement: Requirement, missing_fields: List[str], verification: Any) -> float:
    required_fields = [str(item) for item in (requirement.required_fields or []) if str(item or "").strip()]
    if required_fields:
        covered = max(0, len(required_fields) - len(missing_fields or []))
        return round(covered / len(required_fields), 2)
    confidence = float(getattr(verification, "confidence", 0.0) or 0.0)
    return round(min(1.0, confidence / 100.0), 2)


def _dedupe_list(items: List[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for item in items or []:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out
