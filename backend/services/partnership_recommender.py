from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy.orm import Session

from models.database import OrganizationProfile
from services.contact_intelligence import build_organization_contact_payload
from services.relation_mapper import RelationMapper


_STALE_DATA_DAYS = 365
_RECOMMENDATION_LIMIT = 10


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _clamp_score(value: float) -> int:
    return max(0, min(100, int(round(value))))


def _clamp_confidence(value: float) -> float:
    return max(0.0, min(1.0, round(value, 2)))


def _resolve_org(db: Session, *, org_id: Optional[str] = None, organization_name: Optional[str] = None) -> Optional[OrganizationProfile]:
    if _normalize_text(org_id):
        org = db.query(OrganizationProfile).filter(OrganizationProfile.id == _normalize_text(org_id)).first()
        if org:
            return org
    if _normalize_text(organization_name):
        lowered = _normalize_text(organization_name).lower()
        for org in db.query(OrganizationProfile).all():
            for candidate in [org.name, org.english_name, org.short_name, org.official_name]:
                if _normalize_text(candidate).lower() == lowered:
                    return org
    return None


def _organization_payload(org: OrganizationProfile) -> dict:
    return {
        "id": org.id,
        "name": org.name,
        "source_url": _normalize_text(org.source_url) or None,
        "source_name": _normalize_text(org.source_name) or None,
        "updated_at": org.updated_at,
    }


def _empty_payload(*, warnings: list[str], found: bool, organization: Optional[dict]) -> dict:
    return {
        "organization": organization,
        "summary": {
            "candidate_count": 0,
            "recommended_count": 0,
            "high_priority_count": 0,
            "with_contact_count": 0,
            "with_relationship_path_count": 0,
            "warning_count": len(list(dict.fromkeys(warnings))),
        },
        "recommendations": [],
        "warnings": list(dict.fromkeys(warnings)),
        "found": found,
    }


def _score_snapshot(org: OrganizationProfile) -> dict:
    return {
        "people_score": org.people_score,
        "digital_score": org.digital_score,
        "intel_score": org.intel_score,
    }


def _contact_snapshot(contact_payload: dict) -> dict:
    summary = contact_payload.get("summary") or {}
    return {
        "has_website": bool(summary.get("website_count", 0)),
        "has_email": bool(summary.get("email_count", 0)),
        "has_phone": bool(summary.get("phone_count", 0)),
        "has_social": bool(summary.get("social_count", 0)),
        "contact_count": int(summary.get("contact_count", 0) or 0),
        "verified_contact_count": int(summary.get("verified_count", 0) or 0),
        "missing_source_count": int(summary.get("missing_source_count", 0) or 0),
    }


def _relationship_lookup(mapper: RelationMapper, org_id: str) -> dict[str, list[dict]]:
    relations = mapper.get_relations_for_org(org_id)
    lookup: dict[str, list[dict]] = {}
    for relation in relations:
        other_org = relation.get("other_org") or {}
        other_id = _normalize_text(other_org.get("id"))
        if not other_id:
            continue
        lookup.setdefault(other_id, []).append(relation)
    return lookup


def _relationship_snapshot(relations: list[dict]) -> dict:
    if not relations:
        return {
            "has_relationship_path": False,
            "relationship_count": 0,
            "strongest_relationship_type": None,
            "relationship_path_summary": [],
        }
    strongest = max(relations, key=lambda item: float(item.get("confidence") or 0.0))
    summary_lines = []
    for relation in relations[:3]:
        relation_type = _normalize_text(relation.get("relation_type")) or "unknown"
        evidence = relation.get("evidence") or {}
        source_name = _normalize_text(evidence.get("source")) or "database"
        summary_lines.append(f"{relation_type} via {source_name}")
    return {
        "has_relationship_path": True,
        "relationship_count": len(relations),
        "strongest_relationship_type": _normalize_text(strongest.get("relation_type")) or None,
        "relationship_path_summary": summary_lines,
    }


def _reason_codes(
    source_org: OrganizationProfile,
    candidate: OrganizationProfile,
    *,
    score_snapshot: dict,
    relationship_snapshot: dict,
    contact_snapshot: dict,
) -> list[str]:
    reasons: list[str] = []
    score_values = [value for value in score_snapshot.values() if isinstance(value, int)]
    average_score = sum(score_values) / len(score_values) if score_values else 0.0
    if average_score >= 70:
        reasons.append("strong_intelligence_score")
    if (score_snapshot.get("digital_score") or 0) >= 60:
        reasons.append("high_digital_presence")
    if relationship_snapshot["has_relationship_path"]:
        reasons.append("relationship_path_available")
    if contact_snapshot["contact_count"] > 0:
        reasons.append("contact_available")
    if _normalize_text(candidate.country) and _normalize_text(candidate.country) == _normalize_text(source_org.country):
        reasons.append("same_country")
    if _normalize_text(candidate.city) and _normalize_text(candidate.city) == _normalize_text(source_org.city):
        reasons.append("same_city")
    if _normalize_text(candidate.denomination) and _normalize_text(candidate.denomination) == _normalize_text(source_org.denomination):
        reasons.append("same_denomination")
    return list(dict.fromkeys(reasons))


def _risks_and_warnings(candidate: OrganizationProfile, *, score_snapshot: dict, contact_payload: dict, relationship_snapshot: dict) -> tuple[list[str], list[str]]:
    risks: list[str] = []
    warnings: list[str] = []

    if any(value is None for value in score_snapshot.values()):
        risks.append("missing_scores")
    score_values = [value for value in score_snapshot.values() if isinstance(value, int)]
    average_score = sum(score_values) / len(score_values) if score_values else 0.0
    if score_values and average_score < 40:
        risks.append("low_intelligence_score")
    if not score_values:
        risks.append("insufficient_evidence")

    contact_summary = contact_payload.get("summary") or {}
    if int(contact_summary.get("contact_count", 0) or 0) == 0:
        risks.append("missing_contact")
    if int(contact_summary.get("missing_source_count", 0) or 0) > 0:
        warnings.append("missing_contact_source")

    if not relationship_snapshot["has_relationship_path"]:
        warnings.append("weak_relationship_signal")

    if not _normalize_text(candidate.source_url) or not _normalize_text(candidate.source_name):
        warnings.append("insufficient_evidence")

    updated_at = getattr(candidate, "updated_at", None)
    if isinstance(updated_at, datetime) and updated_at < datetime.utcnow() - timedelta(days=_STALE_DATA_DAYS):
        warnings.append("stale_data")

    return list(dict.fromkeys(risks)), list(dict.fromkeys(warnings))


def _component_scores(candidate: OrganizationProfile, *, contact_snapshot: dict, relationship_snapshot: dict) -> dict[str, float]:
    score_values = [value for value in [candidate.people_score, candidate.digital_score, candidate.intel_score] if isinstance(value, int)]
    intelligence_fit_score = float(sum(score_values) / len(score_values)) if score_values else 0.0

    relationship_count = int(relationship_snapshot["relationship_count"])
    relation_type = _normalize_text(relationship_snapshot.get("strongest_relationship_type"))
    relationship_score = min(100.0, relationship_count * 25.0)
    if relation_type in {"partner", "affiliate", "collaboration"}:
        relationship_score = min(100.0, relationship_score + 15.0)
    if relationship_snapshot["has_relationship_path"]:
        relationship_score = min(100.0, relationship_score + 10.0)

    contact_readiness_score = 0.0
    if contact_snapshot["has_website"]:
        contact_readiness_score += 20.0
    if contact_snapshot["has_email"]:
        contact_readiness_score += 35.0
    if contact_snapshot["has_phone"]:
        contact_readiness_score += 20.0
    if contact_snapshot["has_social"]:
        contact_readiness_score += 15.0
    if contact_snapshot["contact_count"] > 0 and contact_snapshot["missing_source_count"] == 0:
        contact_readiness_score += 10.0

    evidence_score = 0.0
    if _normalize_text(candidate.source_url):
        evidence_score += 40.0
    if _normalize_text(candidate.source_name):
        evidence_score += 30.0
    if getattr(candidate, "updated_at", None):
        evidence_score += 30.0

    return {
        "intelligence_fit_score": min(100.0, intelligence_fit_score),
        "relationship_score": min(100.0, relationship_score),
        "contact_readiness_score": min(100.0, contact_readiness_score),
        "evidence_score": min(100.0, evidence_score),
    }


def _risk_penalty(risks: list[str], warnings: list[str]) -> float:
    penalty = 0.0
    penalty += 12.0 if "missing_scores" in risks else 0.0
    penalty += 14.0 if "missing_contact" in risks else 0.0
    penalty += 10.0 if "low_intelligence_score" in risks else 0.0
    penalty += 8.0 if "insufficient_evidence" in risks else 0.0
    penalty += 6.0 if "missing_contact_source" in warnings else 0.0
    penalty += 6.0 if "weak_relationship_signal" in warnings else 0.0
    penalty += 6.0 if "stale_data" in warnings else 0.0
    return penalty


def _priority(score: int) -> str:
    if score >= 75:
        return "high"
    if score >= 50:
        return "medium"
    return "low"


def _recommended_next_action(score: int, *, contact_snapshot: dict, risks: list[str], warnings: list[str]) -> str:
    if score < 35:
        return "skip"
    if score >= 60 and (contact_snapshot["has_email"] or contact_snapshot["has_phone"] or contact_snapshot["has_website"]):
        return "contact"
    if "missing_scores" in risks or "insufficient_evidence" in risks:
        return "research_more"
    if "missing_contact" in risks or "missing_contact_source" in warnings:
        return "review_manually"
    return "research_more"


def _explanation(reason_codes: list[str], *, risks: list[str], warnings: list[str]) -> str:
    if not reason_codes:
        return "谨慎推荐：当前数据库证据有限，建议先补充情报。"

    fragments: list[str] = []
    if "strong_intelligence_score" in reason_codes:
        fragments.append("该机构情报评分较高")
    if "relationship_path_available" in reason_codes:
        fragments.append("与当前机构存在关系路径")
    if "contact_available" in reason_codes:
        fragments.append("存在可用联系方式")
    if "same_country" in reason_codes:
        fragments.append("与当前机构位于同一国家")
    if "same_city" in reason_codes:
        fragments.append("与当前机构位于同一城市")
    if "same_denomination" in reason_codes:
        fragments.append("与当前机构宗派一致")
    if "high_digital_presence" in reason_codes:
        fragments.append("数字化存在感较强")

    prefix = "推荐原因：" if not risks and not warnings else "谨慎推荐："
    sentence = "，".join(fragments[:3]) if fragments else "当前数据库中存在部分正向信号"
    caution = []
    if "missing_scores" in risks:
        caution.append("评分数据不足")
    if "missing_contact" in risks:
        caution.append("联系方式缺失")
    if "missing_contact_source" in warnings:
        caution.append("联系方式来源不完整")
    if "weak_relationship_signal" in warnings:
        caution.append("关系信号较弱")
    if caution:
        return f"{prefix}{sentence}；但{'、'.join(caution)}，建议人工复核。"
    return f"{prefix}{sentence}。"


def _candidate_eligible(source_org: OrganizationProfile, candidate: OrganizationProfile, *, relationship_snapshot: dict, score_snapshot: dict, contact_snapshot: dict) -> bool:
    if source_org.id == candidate.id:
        return False
    shared_country = _normalize_text(source_org.country) and _normalize_text(source_org.country) == _normalize_text(candidate.country)
    shared_city = _normalize_text(source_org.city) and _normalize_text(source_org.city) == _normalize_text(candidate.city)
    shared_denomination = _normalize_text(source_org.denomination) and _normalize_text(source_org.denomination) == _normalize_text(candidate.denomination)
    high_score = any((value or 0) >= 60 for value in score_snapshot.values() if value is not None)
    has_contact = contact_snapshot["contact_count"] > 0
    has_relationship = relationship_snapshot["has_relationship_path"]
    return bool(shared_country or shared_city or shared_denomination or high_score or has_contact or has_relationship)


def build_partnership_recommendations(
    *,
    db: Session,
    org_id: Optional[str] = None,
    organization_name: Optional[str] = None,
    limit: int = _RECOMMENDATION_LIMIT,
) -> dict:
    source_org = _resolve_org(db, org_id=org_id, organization_name=organization_name)
    if not source_org:
        return _empty_payload(warnings=["not_found"], found=False, organization=None)

    mapper = RelationMapper(db)
    relation_lookup = _relationship_lookup(mapper, source_org.id)
    all_orgs = db.query(OrganizationProfile).all()
    recommendations: list[dict] = []

    for candidate in all_orgs:
        if candidate.id == source_org.id:
            continue

        score_snapshot = _score_snapshot(candidate)
        candidate_relations = relation_lookup.get(candidate.id, [])
        relationship_snapshot = _relationship_snapshot(candidate_relations)
        contact_payload = build_organization_contact_payload(db=db, org_id=candidate.id, include_unverified=True)
        contact_snapshot = _contact_snapshot(contact_payload)

        if not _candidate_eligible(
            source_org,
            candidate,
            relationship_snapshot=relationship_snapshot,
            score_snapshot=score_snapshot,
            contact_snapshot=contact_snapshot,
        ):
            continue

        reason_codes = _reason_codes(
            source_org,
            candidate,
            score_snapshot=score_snapshot,
            relationship_snapshot=relationship_snapshot,
            contact_snapshot=contact_snapshot,
        )
        risks, warnings = _risks_and_warnings(
            candidate,
            score_snapshot=score_snapshot,
            contact_payload=contact_payload,
            relationship_snapshot=relationship_snapshot,
        )
        component_scores = _component_scores(candidate, contact_snapshot=contact_snapshot, relationship_snapshot=relationship_snapshot)
        score = _clamp_score(
            component_scores["intelligence_fit_score"] * 0.40
            + component_scores["relationship_score"] * 0.25
            + component_scores["contact_readiness_score"] * 0.20
            + component_scores["evidence_score"] * 0.15
            - _risk_penalty(risks, warnings)
        )
        missing_score_count = sum(1 for value in score_snapshot.values() if value is None)
        base_confidence = 0.75
        base_confidence += 0.1 if relationship_snapshot["has_relationship_path"] else 0.0
        base_confidence += 0.05 if contact_snapshot["contact_count"] > 0 else 0.0
        base_confidence -= 0.1 * missing_score_count
        base_confidence -= 0.08 if "missing_contact" in risks else 0.0
        base_confidence -= 0.06 if "missing_contact_source" in warnings else 0.0
        base_confidence -= 0.06 if "insufficient_evidence" in warnings or "insufficient_evidence" in risks else 0.0
        confidence = _clamp_confidence(base_confidence)

        recommendations.append(
            {
                "target_org": {
                    "id": candidate.id,
                    "name": candidate.name,
                    "country": candidate.country,
                    "city": candidate.city,
                    "denomination": candidate.denomination,
                    "source_url": _normalize_text(candidate.source_url) or None,
                    "source_name": _normalize_text(candidate.source_name) or None,
                },
                "recommendation_score": score,
                "priority": _priority(score),
                "confidence": confidence,
                "reason_codes": reason_codes,
                "explanation": _explanation(reason_codes, risks=risks, warnings=warnings),
                "score_snapshot": score_snapshot,
                "relationship_snapshot": relationship_snapshot,
                "contact_snapshot": contact_snapshot,
                "risks": risks,
                "warnings": warnings,
                "recommended_next_action": _recommended_next_action(
                    score,
                    contact_snapshot=contact_snapshot,
                    risks=risks,
                    warnings=warnings,
                ),
            }
        )

    recommendations.sort(
        key=lambda item: (
            int(item["recommendation_score"]),
            float(item["confidence"]),
            int(item["contact_snapshot"]["contact_count"]),
            int(item["relationship_snapshot"]["relationship_count"]),
        ),
        reverse=True,
    )
    trimmed = recommendations[: max(1, min(int(limit or _RECOMMENDATION_LIMIT), 50))]
    payload_warnings: list[str] = []
    if not trimmed:
        payload_warnings.append("no_recommendation_candidates_found")

    summary = {
        "candidate_count": len(recommendations),
        "recommended_count": len(trimmed),
        "high_priority_count": sum(1 for item in trimmed if item["priority"] == "high"),
        "with_contact_count": sum(1 for item in trimmed if item["contact_snapshot"]["contact_count"] > 0),
        "with_relationship_path_count": sum(1 for item in trimmed if item["relationship_snapshot"]["has_relationship_path"]),
        "warning_count": len(payload_warnings) + sum(len(item["warnings"]) for item in trimmed),
    }
    return {
        "organization": _organization_payload(source_org),
        "summary": summary,
        "recommendations": trimmed,
        "warnings": payload_warnings,
        "found": True,
    }
