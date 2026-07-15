"""
单机构详情 API
提供完整的机构画像：评分、关系网络、情报时间线。
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, or_
from sqlalchemy.orm import Session

from dependencies.auth import require_authenticated_user
from models.schemas import (
    OrganizationContactPayload,
    OrganizationRelationsResponse,
    PartnershipActionPlanPayload,
    PartnershipEvidenceBriefPayload,
    PartnershipRecommendationPayload,
)
from models.database import IntelligenceItem, OrganizationProfile, get_db
from services.contact_intelligence import build_organization_contact_payload
from services.partnership_action_planner import build_partnership_action_plan
from services.partnership_evidence_brief import build_partnership_evidence_brief
from services.partnership_recommender import build_partnership_recommendations
from services.relation_mapper import RelationMapper, build_organization_graph

router = APIRouter(prefix="/api/dashboard/org", tags=["org-detail"], dependencies=[Depends(require_authenticated_user)])


@router.get("/{org_id}")
def get_org_detail(org_id: str, db: Session = Depends(get_db)):
    """机构基础信息 + 三维度评分。"""
    org = db.query(OrganizationProfile).filter(OrganizationProfile.id == org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    return {
        "id": org.id,
        "name": org.name,
        "english_name": org.english_name,
        "short_name": org.short_name,
        "country": org.country,
        "city": org.city,
        "type": org.organization_type,
        "denomination": org.denomination,
        "website": org.official_website,
        "founded_year": org.founded_year,
        "member_count": org.member_count,
        "employee_count": org.employee_count,
        "annual_revenue": org.annual_revenue,
        "description": org.description,
        "mission_statement": org.mission_statement,
        "leader": {
            "name": org.leader_name,
            "title": org.leader_title,
            "bio_url": org.leader_bio_url,
        },
        "scores": {
            "people": {
                "total": org.people_score or 0,
                "grade": org.people_score_grade or "F",
            },
            "digital": {
                "total": org.digital_score or 0,
                "grade": org.digital_score_grade or "F",
            },
            "intel": {
                "total": org.intel_score or 0,
                "grade": org.intel_score_grade or "F",
            },
            "composite": {
                "total": (org.people_score or 0) + (org.digital_score or 0) + (org.intel_score or 0),
            },
        },
        "flags": {
            "has_ai_initiative": org.has_ai_initiative,
            "has_online_giving": org.has_online_giving,
            "has_mobile_app": org.has_mobile_app,
            "has_leadership_page": org.has_leadership_page,
            "has_about": org.has_about,
            "has_mission": org.has_mission,
            "has_vision": org.has_vision,
            "has_donate": org.has_donate,
            "has_annual_report": org.has_annual_report,
            "has_podcast": org.has_podcast,
            "has_video": org.has_video,
            "has_blog": org.has_blog,
        },
        "social": {
            "facebook": org.facebook_url,
            "youtube": org.youtube_url,
            "twitter": org.twitter_url,
            "telegram": org.telegram_username,
        },
    }


@router.get("/{org_id}/relations", response_model=OrganizationRelationsResponse)
def get_org_relations(org_id: str, include_unverified: bool = False, limit: int = 50, db: Session = Depends(get_db)):
    """机构关系网络：投资、合作、关联（含映射）。"""
    org = db.query(OrganizationProfile).filter(OrganizationProfile.id == org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    mapper = RelationMapper(db)
    relations = mapper.get_relations_for_org(org_id)
    graph = build_organization_graph(
        db=db,
        org_id=org_id,
        depth=1,
        limit=limit,
        include_unverified=include_unverified,
    )
    return {
        "total": len(relations),
        "relations": relations,
        "graph": graph,
    }


@router.get("/{org_id}/contacts", response_model=OrganizationContactPayload)
def get_org_contacts(org_id: str, db: Session = Depends(get_db)):
    """机构可信联系方式合同。"""
    payload = build_organization_contact_payload(db=db, org_id=org_id, include_unverified=True)
    if payload.get("found") is False:
        raise HTTPException(status_code=404, detail="Organization not found")
    return payload


@router.get("/{org_id}/recommendations", response_model=PartnershipRecommendationPayload)
def get_org_recommendations(org_id: str, limit: int = 10, db: Session = Depends(get_db)):
    """机构合作对象推荐合同。"""
    payload = build_partnership_recommendations(db=db, org_id=org_id, limit=limit)
    if payload.get("found") is False:
        raise HTTPException(status_code=404, detail="Organization not found")
    return payload


@router.get("/{org_id}/action-plan", response_model=PartnershipActionPlanPayload)
def get_org_action_plan(org_id: str, target_org_id: Optional[str] = None, db: Session = Depends(get_db)):
    """机构合作行动计划合同。"""
    try:
        return build_partnership_action_plan(
            db=db,
            org_id=org_id,
            target_org_id=target_org_id,
        )
    except LookupError as exc:
        message = str(exc)
        if message == "organization_not_found":
            raise HTTPException(status_code=404, detail="Organization not found") from exc
        if message == "target_org_not_found":
            raise HTTPException(status_code=404, detail="Target organization not found") from exc
        raise


@router.get("/{org_id}/evidence-brief", response_model=PartnershipEvidenceBriefPayload)
def get_org_evidence_brief(org_id: str, target_org_id: Optional[str] = None, db: Session = Depends(get_db)):
    """机构合作证据简报合同。"""
    try:
        return build_partnership_evidence_brief(
            db=db,
            org_id=org_id,
            target_org_id=target_org_id,
        )
    except LookupError as exc:
        message = str(exc)
        if message == "organization_not_found":
            raise HTTPException(status_code=404, detail="Organization not found") from exc
        if message == "target_org_not_found":
            raise HTTPException(status_code=404, detail="Target organization not found") from exc
        raise


@router.get("/{org_id}/timeline")
def get_org_timeline(org_id: str, limit: int = 20, db: Session = Depends(get_db)):
    """机构情报时间线。"""
    org = db.query(OrganizationProfile).filter(OrganizationProfile.id == org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    org_names = []
    for value in [org.name, org.english_name, org.short_name]:
        if value and value.strip() and value.strip() not in org_names:
            org_names.append(value.strip())

    items = []
    if org_names:
        filters = [IntelligenceItem.entity_name.ilike(f"%{name}%") for name in org_names]
        items = (
            db.query(IntelligenceItem)
            .filter(or_(*filters))
            .order_by(desc(IntelligenceItem.ingested_at))
            .limit(limit)
            .all()
        )

    return {
        "total": len(items),
        "organization_name": org.name,
        "items": [
            {
                "id": item.id,
                "title": item.title,
                "content": item.content[:500] if item.content else None,
                "entity_name": item.entity_name,
                "entity_type": item.entity_type,
                "category": item.category,
                "country": item.country,
                "source_name": item.source_name,
                "source_url": item.source_url,
                "published_at": item.published_at.isoformat() if item.published_at else None,
                "ingested_at": item.ingested_at.isoformat() if item.ingested_at else None,
                "confidence": item.confidence,
            }
            for item in items
        ],
    }
