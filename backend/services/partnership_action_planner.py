from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.orm import Session

from models.database import OrganizationProfile
from services.contact_intelligence import build_organization_contact_payload
from services.partnership_recommender import build_partnership_recommendations
from services.relation_mapper import RelationMapper


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


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


def _target_payload(org: OrganizationProfile) -> dict:
    return {
        "id": org.id,
        "name": org.name,
        "source_url": _normalize_text(org.source_url) or None,
        "source_name": _normalize_text(org.source_name) or None,
    }


def _score_snapshot(org: OrganizationProfile) -> dict:
    return {
        "people_score": org.people_score,
        "digital_score": org.digital_score,
        "intel_score": org.intel_score,
    }


def _relationship_snapshot(mapper: RelationMapper, source_org_id: str, target_org_id: str) -> dict:
    relations = mapper.get_relations_for_org(source_org_id)
    matched: list[dict] = []
    for relation in relations:
        other_org = relation.get("other_org") or {}
        if _normalize_text(other_org.get("id")) == target_org_id:
            matched.append(relation)

    if not matched:
        return {
            "has_relationship_path": False,
            "relationship_count": 0,
            "strongest_relationship_type": None,
            "relationship_path_summary": [],
        }

    strongest = max(matched, key=lambda item: float(item.get("confidence") or 0.0))
    summary_lines: list[str] = []
    for relation in matched[:3]:
        relation_type = _normalize_text(relation.get("relation_type")) or "unknown"
        evidence = relation.get("evidence") or {}
        source_name = _normalize_text(evidence.get("source")) or "database"
        summary_lines.append(f"{relation_type} via {source_name}")

    return {
        "has_relationship_path": True,
        "relationship_count": len(matched),
        "strongest_relationship_type": _normalize_text(strongest.get("relation_type")) or None,
        "relationship_path_summary": summary_lines,
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


def _empty_recommendation_snapshot(*, target_org: Optional[OrganizationProfile] = None, warnings: Optional[list[str]] = None) -> dict:
    return {
        "target_org_id": getattr(target_org, "id", None),
        "target_org_name": getattr(target_org, "name", None),
        "recommendation_score": 0,
        "priority": "low",
        "confidence": 0.0,
        "reason_codes": [],
        "risks": [],
        "warnings": list(dict.fromkeys(warnings or [])),
        "recommended_next_action": "research_more",
    }


def _empty_payload_for_org(org: OrganizationProfile, *, block_reasons: list[str], warnings: Optional[list[str]] = None) -> dict:
    empty_score_snapshot = _score_snapshot(org)
    return {
        "organization": _organization_payload(org),
        "target_org": None,
        "summary": {
            "plan_available": False,
            "step_count": 0,
            "blocked": True,
            "block_reasons": list(dict.fromkeys(block_reasons)),
            "recommended_channel": "research_first",
            "risk_level": "high",
            "confidence": 0.0,
        },
        "action_plan": [],
        "evidence": {
            "score_snapshot": empty_score_snapshot,
            "relationship_snapshot": {
                "has_relationship_path": False,
                "relationship_count": 0,
                "strongest_relationship_type": None,
                "relationship_path_summary": [],
            },
            "contact_snapshot": {
                "has_website": False,
                "has_email": False,
                "has_phone": False,
                "has_social": False,
                "contact_count": 0,
                "verified_contact_count": 0,
                "missing_source_count": 0,
            },
            "recommendation_snapshot": _empty_recommendation_snapshot(warnings=block_reasons),
        },
        "warnings": list(dict.fromkeys((warnings or []) + block_reasons)),
    }


def _select_contact(contact_payload: dict) -> dict:
    contacts = contact_payload.get("contacts") or []
    by_type: dict[str, list[dict]] = {}
    for contact in contacts:
        by_type.setdefault(str(contact.get("type") or ""), []).append(contact)

    for preferred_type in ["email", "website", "phone", "social_profile"]:
        options = by_type.get(preferred_type) or []
        if options:
            return options[0]

    return {
        "type": "none",
        "value": None,
        "source_url": None,
        "is_verified": False,
        "warnings": [],
    }


def _recommended_channel(contact_snapshot: dict, *, high_risk: bool) -> str:
    if contact_snapshot["has_email"] and not high_risk:
        return "email"
    if contact_snapshot["has_website"] and not high_risk:
        return "website"
    if contact_snapshot["has_phone"] and not high_risk:
        return "phone"
    if contact_snapshot["has_social"] and not high_risk:
        return "social"
    if contact_snapshot["contact_count"] == 0:
        return "research_first"
    return "manual_review"


def _base_warning_set(*, recommendation_snapshot: dict, contact_snapshot: dict, relationship_snapshot: dict, score_snapshot: dict, target_in_recommendations: bool) -> list[str]:
    warnings: list[str] = []
    warnings.extend(recommendation_snapshot.get("warnings") or [])
    warnings.extend(recommendation_snapshot.get("risks") or [])

    if any(value is None for value in score_snapshot.values()):
        warnings.append("missing_scores")
    if contact_snapshot["contact_count"] == 0:
        warnings.append("missing_contact")
        warnings.append("no_safe_contact_channel")
    if contact_snapshot["missing_source_count"] > 0:
        warnings.append("contact_source_missing")
    if not relationship_snapshot["has_relationship_path"]:
        warnings.append("weak_relationship_signal")
    if not target_in_recommendations:
        warnings.append("target_not_in_recommendations")
    if not recommendation_snapshot.get("reason_codes") and not relationship_snapshot["has_relationship_path"] and contact_snapshot["contact_count"] == 0:
        warnings.append("insufficient_evidence")

    return list(dict.fromkeys(warnings))


def _risk_level(*, warnings: list[str], contact_snapshot: dict) -> str:
    if "insufficient_evidence" in warnings or "manual_review_required" in warnings:
        return "high"
    if "missing_scores" in warnings and "weak_relationship_signal" in warnings:
        return "high"
    if contact_snapshot["contact_count"] == 0:
        return "medium"
    if "contact_source_missing" in warnings or "weak_relationship_signal" in warnings:
        return "medium"
    return "low"


def _plan_confidence(*, recommendation_snapshot: dict, warnings: list[str], relationship_snapshot: dict, contact_snapshot: dict) -> float:
    confidence = float(recommendation_snapshot.get("confidence") or 0.45)
    confidence -= 0.18 if "missing_scores" in warnings else 0.0
    confidence -= 0.12 if "contact_source_missing" in warnings else 0.0
    confidence -= 0.12 if "insufficient_evidence" in warnings else 0.0
    confidence -= 0.08 if "weak_relationship_signal" in warnings else 0.0
    confidence -= 0.08 if contact_snapshot["contact_count"] == 0 else 0.0
    confidence -= 0.05 if "target_not_in_recommendations" in warnings else 0.0
    confidence += 0.05 if relationship_snapshot["has_relationship_path"] else 0.0
    confidence += 0.04 if contact_snapshot["has_email"] else 0.0
    return _clamp_confidence(confidence)


def _uses_contact(contact: Optional[dict]) -> dict:
    if not contact or str(contact.get("type") or "") == "none":
        return {
            "type": "none",
            "value": None,
            "source_url": None,
            "is_verified": False,
        }
    return {
        "type": contact.get("type") or "none",
        "value": contact.get("value"),
        "source_url": contact.get("source_url"),
        "is_verified": bool(contact.get("is_verified")),
    }


def _build_steps(
    *,
    recommended_channel: str,
    selected_contact: dict,
    warnings: list[str],
    relationship_snapshot: dict,
    high_risk: bool,
) -> list[dict]:
    steps: list[dict] = []

    def add_step(
        *,
        action_type: str,
        title: str,
        description: str,
        channel: str,
        depends_on: list[int],
        required_evidence: list[str],
        uses_contact: Optional[dict] = None,
        risk_flags: Optional[list[str]] = None,
        success_criteria: Optional[list[str]] = None,
        do_not_proceed_if: Optional[list[str]] = None,
        priority: str = "medium",
    ) -> None:
        steps.append(
            {
                "step_number": len(steps) + 1,
                "action_type": action_type,
                "title": title,
                "description": description,
                "channel": channel,
                "depends_on": depends_on,
                "required_evidence": required_evidence,
                "uses_contact": _uses_contact(uses_contact),
                "risk_flags": list(dict.fromkeys(risk_flags or [])),
                "success_criteria": success_criteria or [],
                "do_not_proceed_if": do_not_proceed_if or [],
                "priority": priority,
            }
        )

    common_stop_rules = [
        "发现联系方式来源缺失且无法人工确认",
        "发现证据与数据库记录不一致",
        "需要使用非公开或误导性渠道才能推进",
    ]

    selected_contact_flags: list[str] = []
    if selected_contact.get("type") not in {None, "none"}:
        if "field_level_source_missing" in (selected_contact.get("warnings") or []) or not selected_contact.get("source_url"):
            selected_contact_flags.append("contact_source_missing")
        if not bool(selected_contact.get("is_verified")):
            selected_contact_flags.append("contact_unverified")

    if "missing_scores" in warnings or "insufficient_evidence" in warnings or "target_not_in_recommendations" in warnings:
        add_step(
            action_type="research",
            title="补充目标机构公开情报",
            description="核对目标机构公开来源、评分缺口和合作背景，确认是否具备继续推进的基础证据。",
            channel="internal_review",
            depends_on=[],
            required_evidence=["score_snapshot", "recommendation_snapshot", "target public source"],
            risk_flags=[warning for warning in warnings if warning in {"missing_scores", "insufficient_evidence", "target_not_in_recommendations"}],
            success_criteria=["评分和来源缺口已记录", "目标机构公开资料可追溯"],
            do_not_proceed_if=["仍需依赖推测补全核心事实", "目标机构不存在公开可验证资料"],
            priority="high",
        )

    if recommended_channel == "research_first":
        add_step(
            action_type="verify_contact",
            title="先补充并验证安全联系渠道",
            description="当前数据库没有可安全使用的公开联系方式，应先在公开官网或官方社媒中核实联系入口。",
            channel="internal_review",
            depends_on=[step["step_number"] for step in steps] if steps else [],
            required_evidence=["contact_snapshot", "official website"],
            risk_flags=["missing_contact", "no_safe_contact_channel"],
            success_criteria=["找到公开且可追溯的联系渠道", "记录来源页面"],
            do_not_proceed_if=["只能依赖非公开联系信息", "需要绕过公开渠道才能联系"],
            priority="high",
        )
        if relationship_snapshot["has_relationship_path"]:
            add_step(
                action_type="review_relationship",
                title="复核关系路径证据",
                description="在补充联系渠道前，同步确认现有关系路径是否适合作为后续内部判断依据。",
                channel="internal_review",
                depends_on=[step["step_number"] for step in steps] if steps else [],
                required_evidence=["relationship_snapshot"],
                risk_flags=["weak_relationship_signal"] if "weak_relationship_signal" in warnings else [],
                success_criteria=["已确认关系路径只用于内部判断", "没有把未验证关系当作确定事实"],
                do_not_proceed_if=["关系证据无法公开追溯", "关系路径与数据库记录不一致"],
                priority="medium",
            )
        return steps

    if relationship_snapshot["has_relationship_path"]:
        add_step(
            action_type="review_relationship",
            title="复核关系路径证据",
            description="查看现有关系路径及证据来源，确认是否适合在外联前引用公开合作背景。",
            channel="internal_review",
            depends_on=[step["step_number"] for step in steps] if steps else [],
            required_evidence=["relationship_snapshot"],
            risk_flags=["weak_relationship_signal"] if "weak_relationship_signal" in warnings else [],
            success_criteria=["已确认可引用的公开关系证据", "不依赖未验证关系做外联表述"],
            do_not_proceed_if=["关系路径与证据不一致", "关系证据无法公开引用"],
            priority="high",
        )

    if selected_contact_flags or recommended_channel in {"website", "phone", "social"}:
        add_step(
            action_type="verify_contact",
            title="验证联系渠道可用性",
            description="在使用联系渠道前，先确认该渠道仍为官方公开入口，并记录来源页面。",
            channel="internal_review" if high_risk else recommended_channel,
            depends_on=[step["step_number"] for step in steps] if steps else [],
            required_evidence=["contact_snapshot", "contact source"],
            uses_contact=selected_contact,
            risk_flags=selected_contact_flags,
            success_criteria=["联系渠道来源可追溯", "渠道属于目标机构公开入口"],
            do_not_proceed_if=list(dict.fromkeys(common_stop_rules + ["联系渠道明显过期或无法验证"])),
            priority="high",
        )

    add_step(
        action_type="prepare_outreach",
        title="准备透明合作外联提纲",
        description="基于公开证据整理简短、透明、非误导性的合作沟通提纲，仅引用已验证的关系、评分和公开联系信息。",
        channel="internal_review",
        depends_on=[step["step_number"] for step in steps] if steps else [],
        required_evidence=["recommendation_snapshot", "score_snapshot", "relationship_snapshot"],
        risk_flags=[warning for warning in warnings if warning in {"missing_scores", "weak_relationship_signal", "contact_source_missing"}],
        success_criteria=["外联提纲只包含已验证公开事实", "没有夸大关系或伪造共同背景"],
        do_not_proceed_if=["需要使用虚假身份或误导性话术", "需要引用未验证事实"],
        priority="medium" if high_risk else "high",
    )

    if high_risk:
        add_step(
            action_type="monitor",
            title="人工复核后再决定是否联系",
            description="当前风险较高，先提交内部人工复核，待确认评分、证据和联系方式后再决定是否外联。",
            channel="internal_review",
            depends_on=[step["step_number"] for step in steps] if steps else [],
            required_evidence=["manual review"],
            risk_flags=["manual_review_required"],
            success_criteria=["人工复核通过", "确认继续推进不会依赖不安全渠道"],
            do_not_proceed_if=["人工复核未通过", "仍存在关键证据或渠道缺口"],
            priority="high",
        )
        return steps

    add_step(
        action_type="contact",
        title="通过公开渠道发起合作联系",
        description="仅通过数据库中已有的公开机构渠道发起透明联系，不伪装身份、不绕过公开入口、不使用未验证个人信息。",
        channel=recommended_channel,
        depends_on=[step["step_number"] for step in steps] if steps else [],
        required_evidence=["verified public channel", "recommendation_snapshot"],
        uses_contact=selected_contact,
        risk_flags=selected_contact_flags,
        success_criteria=["联系记录指向公开渠道", "沟通内容只引用已验证事实"],
        do_not_proceed_if=list(dict.fromkeys(common_stop_rules + ["需要联系个人隐私渠道", "需要伪装第三方身份"])),
        priority="high",
    )

    return steps


def build_partnership_action_plan(
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

    recommendations = recommendations_payload.get("recommendations") or []
    recommendation_lookup = {item["target_org"]["id"]: item for item in recommendations if (item.get("target_org") or {}).get("id")}
    target_in_recommendations = True

    if _normalize_text(target_org_id):
        target_org = _resolve_org(db, org_id=target_org_id)
        if not target_org:
            raise LookupError("target_org_not_found")
        recommendation_snapshot = recommendation_lookup.get(target_org.id)
        if recommendation_snapshot is None:
            target_in_recommendations = False
            recommendation_snapshot = _empty_recommendation_snapshot(target_org=target_org, warnings=["target_not_in_recommendations"])
    else:
        if not recommendations:
            return _empty_payload_for_org(
                source_org,
                block_reasons=["no_recommendation_candidates_found"],
                warnings=recommendations_payload.get("warnings") or [],
            )
        recommendation_snapshot = recommendations[0]
        target_org = _resolve_org(db, org_id=recommendation_snapshot["target_org"]["id"])
        if not target_org:
            raise LookupError("target_org_not_found")

    mapper = RelationMapper(db)
    score_snapshot = _score_snapshot(target_org)
    relationship_snapshot = _relationship_snapshot(mapper, source_org.id, target_org.id)
    contact_payload = build_organization_contact_payload(db=db, org_id=target_org.id, include_unverified=True)
    contact_snapshot = _contact_snapshot(contact_payload)
    selected_contact = _select_contact(contact_payload)

    warnings = _base_warning_set(
        recommendation_snapshot=recommendation_snapshot,
        contact_snapshot=contact_snapshot,
        relationship_snapshot=relationship_snapshot,
        score_snapshot=score_snapshot,
        target_in_recommendations=target_in_recommendations,
    )
    high_risk = _risk_level(warnings=warnings, contact_snapshot=contact_snapshot) == "high"
    recommended_channel = _recommended_channel(contact_snapshot, high_risk=high_risk)
    if high_risk and recommended_channel not in {"research_first", "manual_review"}:
        warnings.append("manual_review_required")
        warnings = list(dict.fromkeys(warnings))
        recommended_channel = "manual_review"

    confidence = _plan_confidence(
        recommendation_snapshot=recommendation_snapshot,
        warnings=warnings,
        relationship_snapshot=relationship_snapshot,
        contact_snapshot=contact_snapshot,
    )
    risk_level = _risk_level(warnings=warnings, contact_snapshot=contact_snapshot)
    steps = _build_steps(
        recommended_channel=recommended_channel,
        selected_contact=selected_contact,
        warnings=warnings,
        relationship_snapshot=relationship_snapshot,
        high_risk=risk_level == "high",
    )

    payload = {
        "organization": _organization_payload(source_org),
        "target_org": _target_payload(target_org),
        "summary": {
            "plan_available": bool(steps),
            "step_count": len(steps),
            "blocked": False,
            "block_reasons": [],
            "recommended_channel": recommended_channel,
            "risk_level": risk_level,
            "confidence": confidence,
        },
        "action_plan": steps,
        "evidence": {
            "score_snapshot": score_snapshot,
            "relationship_snapshot": relationship_snapshot,
            "contact_snapshot": contact_snapshot,
            "recommendation_snapshot": {
                "target_org_id": recommendation_snapshot.get("target_org", {}).get("id")
                if isinstance(recommendation_snapshot.get("target_org"), dict)
                else recommendation_snapshot.get("target_org_id"),
                "target_org_name": recommendation_snapshot.get("target_org", {}).get("name")
                if isinstance(recommendation_snapshot.get("target_org"), dict)
                else recommendation_snapshot.get("target_org_name"),
                "recommendation_score": int(recommendation_snapshot.get("recommendation_score") or 0),
                "priority": recommendation_snapshot.get("priority") or "low",
                "confidence": float(recommendation_snapshot.get("confidence") or 0.0),
                "reason_codes": recommendation_snapshot.get("reason_codes") or [],
                "risks": recommendation_snapshot.get("risks") or [],
                "warnings": recommendation_snapshot.get("warnings") or [],
                "recommended_next_action": recommendation_snapshot.get("recommended_next_action") or "research_more",
            },
        },
        "warnings": warnings,
    }
    return payload
