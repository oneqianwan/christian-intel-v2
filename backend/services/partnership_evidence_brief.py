from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.orm import Session

from models.database import OrganizationProfile
from services.contact_intelligence import build_organization_contact_payload
from services.partnership_action_planner import build_partnership_action_plan
from services.partnership_recommender import build_partnership_recommendations


_TRACKED_WARNING_CODES = {
    "missing_scores",
    "missing_contact",
    "contact_unverified",
    "contact_source_missing",
    "weak_relationship_signal",
    "insufficient_evidence",
    "manual_review_required",
    "no_safe_contact_channel",
    "target_not_in_recommendations",
    "no_recommendation_candidates_found",
}

_RISK_CATALOG = {
    "missing_scores": {
        "severity": "medium",
        "description": "One or more core score fields are missing, reducing confidence in partner fit assessment.",
        "mitigation": "Collect the missing score evidence before making a final outreach decision.",
    },
    "missing_contact": {
        "severity": "high",
        "description": "No safe public contact channel is available for the target organization.",
        "mitigation": "Verify official website and public contact pages before attempting any outreach.",
    },
    "contact_unverified": {
        "severity": "medium",
        "description": "The selected contact channel exists in the database but is not verified.",
        "mitigation": "Confirm the channel from an official public source before using it.",
    },
    "contact_source_missing": {
        "severity": "medium",
        "description": "The contact channel lacks a complete, traceable public source reference.",
        "mitigation": "Record a source URL and source name before using the channel operationally.",
    },
    "weak_relationship_signal": {
        "severity": "medium",
        "description": "Relationship evidence is weak or absent, so relational justification is limited.",
        "mitigation": "Review public partnership evidence and avoid relying on implied connections.",
    },
    "insufficient_evidence": {
        "severity": "high",
        "description": "The evidence base is too thin to support a high-confidence partnership decision.",
        "mitigation": "Gather more public evidence before proceeding.",
    },
    "manual_review_required": {
        "severity": "high",
        "description": "Risk conditions require internal review before any external action.",
        "mitigation": "Escalate to manual review and document the unresolved concerns.",
    },
    "no_safe_contact_channel": {
        "severity": "high",
        "description": "No public, safe contact channel is available for compliant outreach.",
        "mitigation": "Do not contact until a verified public channel is documented.",
    },
    "target_not_in_recommendations": {
        "severity": "medium",
        "description": "The specified target is not part of the rule-based recommendation candidates.",
        "mitigation": "Validate the strategic rationale manually before pursuing this target.",
    },
    "no_recommendation_candidates_found": {
        "severity": "high",
        "description": "No recommendation candidates were available for evidence brief generation.",
        "mitigation": "Expand candidate discovery and gather more organization evidence first.",
    },
}


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys([_normalize_text(value) for value in values if _normalize_text(value)]))


def _clamp_confidence(value: float) -> float:
    return max(0.0, min(1.0, round(value, 2)))


def _resolve_org(db: Session, *, org_id: Optional[str] = None) -> Optional[OrganizationProfile]:
    if not _normalize_text(org_id):
        return None
    return db.query(OrganizationProfile).filter(OrganizationProfile.id == _normalize_text(org_id)).first()


def _organization_payload(org: OrganizationProfile) -> dict:
    return {
        "id": org.id,
        "name": org.name,
        "source_url": _normalize_text(org.source_url) or None,
        "source_name": _normalize_text(org.source_name) or None,
        "updated_at": org.updated_at,
    }


def _empty_sections() -> dict:
    return {
        "score_evidence": {
            "people_score": None,
            "digital_score": None,
            "intel_score": None,
            "strengths": [],
            "weaknesses": [],
            "warnings": [],
        },
        "relationship_evidence": {
            "has_relationship_path": False,
            "relationship_count": 0,
            "strongest_relationship_type": None,
            "relationship_path_summary": [],
            "warnings": [],
        },
        "contact_evidence": {
            "has_website": False,
            "has_email": False,
            "has_phone": False,
            "has_social": False,
            "contact_count": 0,
            "verified_contact_count": 0,
            "missing_source_count": 0,
            "recommended_contact": None,
            "warnings": [],
        },
        "recommendation_evidence": {
            "recommendation_score": None,
            "priority": None,
            "confidence": 0.0,
            "reason_codes": [],
            "risks": [],
            "warnings": [],
        },
        "action_plan_evidence": {
            "plan_available": False,
            "blocked": False,
            "step_count": 0,
            "recommended_channel": None,
            "risk_level": None,
            "first_steps": [],
            "warnings": [],
        },
    }


def _empty_payload_for_org(org: OrganizationProfile, *, warnings: list[str]) -> dict:
    merged_warnings = _dedupe(warnings + ["no_recommendation_candidates_found"])
    missing_modules = ["partnership_recommender", "partnership_action_planner", "contact_intelligence", "relation_mapper"]
    return {
        "organization": _organization_payload(org),
        "target_org": None,
        "summary": {
            "brief_available": False,
            "decision": "research_more",
            "priority": "low",
            "confidence": 0.0,
            "risk_level": "high",
            "evidence_count": 0,
            "missing_evidence_count": len([item for item in merged_warnings if item in _TRACKED_WARNING_CODES]),
            "recommended_channel": "research_first",
        },
        "decision_rationale": {
            "headline": "当前数据库还没有足够的候选证据生成合作决策简报。",
            "reason_codes": [],
            "supporting_points": [],
            "limiting_factors": ["no_recommendation_candidates_found"],
        },
        "evidence_sections": _empty_sections(),
        "risk_register": _build_risk_register(merged_warnings),
        "recommended_next_actions": ["research_more"],
        "do_not_proceed_if": [
            "target organization identity is unclear",
            "no public contact channel exists",
            "evidence is insufficient",
        ],
        "audit": {
            "generated_by": "rule_based_evidence_brief",
            "no_llm": True,
            "source_modules": ["partnership_recommender", "partnership_action_planner"],
            "missing_modules": missing_modules,
        },
        "warnings": merged_warnings,
    }


def _reason_point(code: str) -> Optional[str]:
    mapping = {
        "strong_intelligence_score": "目标机构在已有评分中表现较强。",
        "high_digital_presence": "目标机构的数字化存在感较强。",
        "relationship_path_available": "数据库中存在可追溯的关系路径摘要。",
        "contact_available": "数据库中存在公开联系渠道。",
        "same_country": "目标机构与当前机构位于同一国家。",
        "same_city": "目标机构与当前机构位于同一城市。",
        "same_denomination": "目标机构与当前机构宗派一致。",
    }
    return mapping.get(code)


def _warning_limitation(code: str) -> Optional[str]:
    mapping = {
        "missing_scores": "评分证据不完整。",
        "missing_contact": "缺少可安全使用的公开联系方式。",
        "contact_unverified": "联系方式尚未验证。",
        "contact_source_missing": "联系方式来源缺失或不完整。",
        "weak_relationship_signal": "关系信号较弱或缺失。",
        "insufficient_evidence": "总体证据不足。",
        "manual_review_required": "当前风险需要人工复核。",
        "no_safe_contact_channel": "没有安全公开联系渠道。",
        "target_not_in_recommendations": "目标机构不在规则推荐候选中。",
        "no_recommendation_candidates_found": "当前没有推荐候选。",
    }
    return mapping.get(code)


def _score_evidence(score_snapshot: dict) -> dict:
    values = {
        "people_score": score_snapshot.get("people_score"),
        "digital_score": score_snapshot.get("digital_score"),
        "intel_score": score_snapshot.get("intel_score"),
    }
    strengths: list[str] = []
    weaknesses: list[str] = []
    warnings: list[str] = []

    for label, value in values.items():
        if value is None:
            warnings.append("missing_scores")
            weaknesses.append(f"{label} is missing.")
        elif value >= 70:
            strengths.append(f"{label} is strong ({value}).")
        elif value <= 40:
            weaknesses.append(f"{label} is weak ({value}).")

    return {
        **values,
        "strengths": _dedupe(strengths),
        "weaknesses": _dedupe(weaknesses),
        "warnings": _dedupe(warnings),
    }


def _relationship_evidence(relationship_snapshot: dict) -> dict:
    warnings: list[str] = []
    if not bool(relationship_snapshot.get("has_relationship_path")):
        warnings.append("weak_relationship_signal")
    return {
        "has_relationship_path": bool(relationship_snapshot.get("has_relationship_path")),
        "relationship_count": int(relationship_snapshot.get("relationship_count") or 0),
        "strongest_relationship_type": relationship_snapshot.get("strongest_relationship_type"),
        "relationship_path_summary": relationship_snapshot.get("relationship_path_summary") or [],
        "warnings": _dedupe(warnings),
    }


def _first_recommended_contact(action_plan_payload: dict, contact_payload: dict) -> Optional[dict]:
    for step in action_plan_payload.get("action_plan") or []:
        uses_contact = step.get("uses_contact") or {}
        if _normalize_text(uses_contact.get("type")) and _normalize_text(uses_contact.get("type")) != "none":
            return {
                "type": uses_contact.get("type") or "none",
                "value": uses_contact.get("value"),
                "source_url": uses_contact.get("source_url"),
                "is_verified": bool(uses_contact.get("is_verified")),
            }

    for contact in contact_payload.get("contacts") or []:
        contact_type = _normalize_text(contact.get("type"))
        if not contact_type:
            continue
        return {
            "type": contact_type,
            "value": contact.get("value"),
            "source_url": contact.get("source_url"),
            "is_verified": bool(contact.get("is_verified")),
        }
    return None


def _contact_evidence(contact_payload: dict, action_plan_payload: dict) -> dict:
    summary = contact_payload.get("summary") or {}
    recommended_contact = _first_recommended_contact(action_plan_payload, contact_payload)
    warnings: list[str] = []
    if int(summary.get("contact_count", 0) or 0) == 0:
        warnings.extend(["missing_contact", "no_safe_contact_channel"])
    if int(summary.get("missing_source_count", 0) or 0) > 0:
        warnings.append("contact_source_missing")
    if recommended_contact and not bool(recommended_contact.get("is_verified")):
        warnings.append("contact_unverified")

    return {
        "has_website": bool(summary.get("website_count", 0)),
        "has_email": bool(summary.get("email_count", 0)),
        "has_phone": bool(summary.get("phone_count", 0)),
        "has_social": bool(summary.get("social_count", 0)),
        "contact_count": int(summary.get("contact_count", 0) or 0),
        "verified_contact_count": int(summary.get("verified_count", 0) or 0),
        "missing_source_count": int(summary.get("missing_source_count", 0) or 0),
        "recommended_contact": recommended_contact,
        "warnings": _dedupe(warnings),
    }


def _recommendation_evidence(recommendation_snapshot: dict) -> dict:
    return {
        "recommendation_score": recommendation_snapshot.get("recommendation_score"),
        "priority": recommendation_snapshot.get("priority"),
        "confidence": float(recommendation_snapshot.get("confidence") or 0.0),
        "reason_codes": recommendation_snapshot.get("reason_codes") or [],
        "risks": recommendation_snapshot.get("risks") or [],
        "warnings": recommendation_snapshot.get("warnings") or [],
    }


def _action_plan_evidence(action_plan_payload: dict) -> dict:
    summary = action_plan_payload.get("summary") or {}
    return {
        "plan_available": bool(summary.get("plan_available")),
        "blocked": bool(summary.get("blocked")),
        "step_count": int(summary.get("step_count") or 0),
        "recommended_channel": summary.get("recommended_channel"),
        "risk_level": summary.get("risk_level"),
        "first_steps": [step.get("title") or step.get("action_type") or "step" for step in (action_plan_payload.get("action_plan") or [])[:3]],
        "warnings": action_plan_payload.get("warnings") or [],
    }


def _combined_warnings(*warning_groups: list[str]) -> list[str]:
    merged: list[str] = []
    for group in warning_groups:
        merged.extend(group or [])
    return _dedupe(merged)


def _risk_level(warnings: list[str]) -> str:
    score = 0
    for code in warnings:
        severity = (_RISK_CATALOG.get(code) or {}).get("severity")
        if severity == "high":
            score += 3
        elif severity == "medium":
            score += 2
        elif severity == "low":
            score += 1

    if score >= 6:
        return "high"
    if score >= 2:
        return "medium"
    return "low"


def _confidence(*, brief_available: bool, score_evidence: dict, relationship_evidence: dict, contact_evidence: dict, recommendation_evidence: dict, action_plan_evidence: dict, warnings: list[str]) -> float:
    if not brief_available:
        return 0.0

    confidence = 0.15
    present_scores = sum(1 for value in [score_evidence.get("people_score"), score_evidence.get("digital_score"), score_evidence.get("intel_score")] if value is not None)
    confidence += present_scores * 0.08
    confidence += 0.12 if relationship_evidence.get("has_relationship_path") else 0.0
    confidence += 0.12 if int(contact_evidence.get("contact_count") or 0) > 0 else 0.0
    confidence += 0.08 if int(contact_evidence.get("verified_contact_count") or 0) > 0 else 0.0
    confidence += 0.12 if (recommendation_evidence.get("recommendation_score") or 0) >= 70 else 0.0
    confidence += 0.08 if bool(action_plan_evidence.get("plan_available")) and not bool(action_plan_evidence.get("blocked")) else 0.0
    confidence += 0.05 if _normalize_text(action_plan_evidence.get("recommended_channel")) not in {"", "manual_review", "research_first"} else 0.0

    for code in warnings:
        if code in {"missing_scores", "missing_contact", "insufficient_evidence", "no_safe_contact_channel"}:
            confidence -= 0.12
        elif code in {"contact_unverified", "contact_source_missing", "weak_relationship_signal", "manual_review_required", "target_not_in_recommendations"}:
            confidence -= 0.08

    return _clamp_confidence(confidence)


def _decision(*, risk_level: str, warnings: list[str], recommendation_evidence: dict, contact_evidence: dict, action_plan_evidence: dict) -> str:
    has_safe_contact = int(contact_evidence.get("contact_count") or 0) > 0
    recommendation_score = int(recommendation_evidence.get("recommendation_score") or 0)

    if "no_safe_contact_channel" in warnings:
        return "do_not_contact"
    if risk_level == "high":
        return "manual_review"
    if "contact_unverified" in warnings or "contact_source_missing" in warnings or "weak_relationship_signal" in warnings or "target_not_in_recommendations" in warnings:
        return "manual_review"
    if "missing_scores" in warnings or "missing_contact" in warnings or "insufficient_evidence" in warnings:
        return "research_more"
    if recommendation_score >= 75 and has_safe_contact and not bool(action_plan_evidence.get("blocked")):
        return "proceed"
    return "research_more"


def _priority(*, decision: str, recommendation_evidence: dict, confidence: float) -> str:
    recommendation_priority = _normalize_text(recommendation_evidence.get("priority")) or "low"
    if decision == "proceed":
        return "high" if recommendation_priority == "high" else "medium"
    if decision == "manual_review":
        return "medium" if confidence >= 0.45 else "low"
    if decision == "do_not_contact":
        return "low"
    return "medium" if confidence >= 0.4 else "low"


def _evidence_count(score_evidence: dict, relationship_evidence: dict, contact_evidence: dict, recommendation_evidence: dict, action_plan_evidence: dict) -> int:
    count = 0
    count += sum(1 for value in [score_evidence.get("people_score"), score_evidence.get("digital_score"), score_evidence.get("intel_score")] if value is not None)
    count += 1 if relationship_evidence.get("has_relationship_path") else 0
    count += 1 if int(contact_evidence.get("contact_count") or 0) > 0 else 0
    count += 1 if recommendation_evidence.get("recommendation_score") is not None else 0
    count += len(action_plan_evidence.get("first_steps") or [])
    return count


def _missing_evidence_count(warnings: list[str]) -> int:
    return len([warning for warning in warnings if warning in _TRACKED_WARNING_CODES])


def _decision_rationale(*, decision: str, score_evidence: dict, relationship_evidence: dict, contact_evidence: dict, recommendation_evidence: dict, action_plan_evidence: dict, warnings: list[str]) -> dict:
    reason_codes = _dedupe((recommendation_evidence.get("reason_codes") or []) + (["action_plan_available"] if action_plan_evidence.get("plan_available") else []))
    supporting_points = _dedupe(
        [point for code in reason_codes for point in [_reason_point(code)] if point]
        + list(score_evidence.get("strengths") or [])
        + (["存在公开联系渠道。"] if int(contact_evidence.get("contact_count") or 0) > 0 else [])
        + (["行动计划已生成且可供执行参考。"] if action_plan_evidence.get("first_steps") else [])
    )
    limiting_factors = _dedupe([text for code in warnings for text in [_warning_limitation(code)] if text] + list(score_evidence.get("weaknesses") or []))

    headline_map = {
        "proceed": "当前证据支持谨慎推进合作。",
        "research_more": "当前证据不足，建议先补充研究后再决策。",
        "manual_review": "当前风险需要人工复核后再决定是否推进。",
        "do_not_contact": "当前没有安全公开渠道，不建议直接联系。",
    }

    return {
        "headline": headline_map.get(decision, "当前证据需要进一步评估。"),
        "reason_codes": reason_codes,
        "supporting_points": supporting_points,
        "limiting_factors": limiting_factors,
    }


def _build_risk_register(warnings: list[str]) -> list[dict]:
    items: list[dict] = []
    for code in _dedupe([warning for warning in warnings if warning in _RISK_CATALOG]):
        meta = _RISK_CATALOG[code]
        items.append(
            {
                "risk_code": code,
                "severity": meta["severity"],
                "description": meta["description"],
                "mitigation": meta["mitigation"],
            }
        )
    return items


def _recommended_next_actions(action_plan_payload: dict, decision: str) -> list[str]:
    first_steps = [step.get("title") or step.get("action_type") or "step" for step in (action_plan_payload.get("action_plan") or [])[:3]]
    if first_steps:
        return first_steps
    if decision == "manual_review":
        return ["manual_review"]
    if decision == "do_not_contact":
        return ["do_not_contact"]
    return ["research_more"]


def _do_not_proceed_if(action_plan_payload: dict) -> list[str]:
    rules: list[str] = []
    for step in action_plan_payload.get("action_plan") or []:
        rules.extend(step.get("do_not_proceed_if") or [])
    rules.extend(
        [
            "contact source cannot be verified",
            "target organization identity is unclear",
            "no public contact channel exists",
            "evidence is insufficient",
        ]
    )
    return _dedupe(rules)


def _audit_payload(*, brief_available: bool, score_evidence: dict, relationship_evidence: dict, contact_evidence: dict, recommendation_evidence: dict, action_plan_evidence: dict) -> dict:
    source_modules = ["partnership_recommender", "partnership_action_planner", "contact_intelligence", "relation_mapper"]
    missing_modules: list[str] = []
    if not brief_available:
        missing_modules.extend(["partnership_recommender", "partnership_action_planner", "contact_intelligence", "relation_mapper"])
    else:
        if any(value is None for value in [score_evidence.get("people_score"), score_evidence.get("digital_score"), score_evidence.get("intel_score")]):
            missing_modules.append("score_snapshot")
        if not relationship_evidence.get("has_relationship_path"):
            missing_modules.append("relation_mapper")
        if int(contact_evidence.get("contact_count") or 0) == 0:
            missing_modules.append("contact_intelligence")
        if recommendation_evidence.get("recommendation_score") is None:
            missing_modules.append("partnership_recommender")
        if not action_plan_evidence.get("plan_available"):
            missing_modules.append("partnership_action_planner")
    return {
        "generated_by": "rule_based_evidence_brief",
        "no_llm": True,
        "source_modules": _dedupe(source_modules),
        "missing_modules": _dedupe(missing_modules),
    }


def build_partnership_evidence_brief(
    *,
    db: Session,
    org_id: str,
    target_org_id: Optional[str] = None,
    recommendation_limit: int = 10,
) -> dict:
    source_org = _resolve_org(db, org_id=org_id)
    if not source_org:
        raise LookupError("organization_not_found")

    recommendations_payload = build_partnership_recommendations(db=db, org_id=org_id, limit=recommendation_limit)
    if recommendations_payload.get("found") is False:
        raise LookupError("organization_not_found")

    action_plan_payload = build_partnership_action_plan(
        db=db,
        org_id=org_id,
        target_org_id=target_org_id,
        recommendation_limit=recommendation_limit,
    )

    target_org = action_plan_payload.get("target_org")
    if not target_org:
        return _empty_payload_for_org(source_org, warnings=_dedupe((recommendations_payload.get("warnings") or []) + (action_plan_payload.get("warnings") or [])))

    target_contact_payload = build_organization_contact_payload(db=db, org_id=target_org["id"], include_unverified=True)
    recommendation_snapshot = ((action_plan_payload.get("evidence") or {}).get("recommendation_snapshot") or {})
    score_snapshot = ((action_plan_payload.get("evidence") or {}).get("score_snapshot") or {})
    relationship_snapshot = ((action_plan_payload.get("evidence") or {}).get("relationship_snapshot") or {})

    score_evidence = _score_evidence(score_snapshot)
    relationship_evidence = _relationship_evidence(relationship_snapshot)
    contact_evidence = _contact_evidence(target_contact_payload, action_plan_payload)
    recommendation_evidence = _recommendation_evidence(recommendation_snapshot)
    action_plan_evidence = _action_plan_evidence(action_plan_payload)

    warnings = _combined_warnings(
        score_evidence["warnings"],
        relationship_evidence["warnings"],
        contact_evidence["warnings"],
        recommendation_evidence["warnings"],
        recommendation_evidence["risks"],
        action_plan_evidence["warnings"],
        recommendations_payload.get("warnings") or [],
    )

    brief_available = True
    risk_level = _risk_level(warnings)
    confidence = _confidence(
        brief_available=brief_available,
        score_evidence=score_evidence,
        relationship_evidence=relationship_evidence,
        contact_evidence=contact_evidence,
        recommendation_evidence=recommendation_evidence,
        action_plan_evidence=action_plan_evidence,
        warnings=warnings,
    )
    decision = _decision(
        risk_level=risk_level,
        warnings=warnings,
        recommendation_evidence=recommendation_evidence,
        contact_evidence=contact_evidence,
        action_plan_evidence=action_plan_evidence,
    )
    priority = _priority(decision=decision, recommendation_evidence=recommendation_evidence, confidence=confidence)
    evidence_count = _evidence_count(score_evidence, relationship_evidence, contact_evidence, recommendation_evidence, action_plan_evidence)
    missing_evidence_count = _missing_evidence_count(warnings)
    decision_rationale = _decision_rationale(
        decision=decision,
        score_evidence=score_evidence,
        relationship_evidence=relationship_evidence,
        contact_evidence=contact_evidence,
        recommendation_evidence=recommendation_evidence,
        action_plan_evidence=action_plan_evidence,
        warnings=warnings,
    )

    return {
        "organization": _organization_payload(source_org),
        "target_org": {
            "id": target_org["id"],
            "name": target_org["name"],
            "source_url": target_org.get("source_url"),
            "source_name": target_org.get("source_name"),
        },
        "summary": {
            "brief_available": brief_available,
            "decision": decision,
            "priority": priority,
            "confidence": confidence,
            "risk_level": risk_level,
            "evidence_count": evidence_count,
            "missing_evidence_count": missing_evidence_count,
            "recommended_channel": action_plan_evidence.get("recommended_channel"),
        },
        "decision_rationale": decision_rationale,
        "evidence_sections": {
            "score_evidence": score_evidence,
            "relationship_evidence": relationship_evidence,
            "contact_evidence": contact_evidence,
            "recommendation_evidence": recommendation_evidence,
            "action_plan_evidence": action_plan_evidence,
        },
        "risk_register": _build_risk_register(warnings),
        "recommended_next_actions": _recommended_next_actions(action_plan_payload, decision),
        "do_not_proceed_if": _do_not_proceed_if(action_plan_payload),
        "audit": _audit_payload(
            brief_available=brief_available,
            score_evidence=score_evidence,
            relationship_evidence=relationship_evidence,
            contact_evidence=contact_evidence,
            recommendation_evidence=recommendation_evidence,
            action_plan_evidence=action_plan_evidence,
        ),
        "warnings": warnings,
    }
