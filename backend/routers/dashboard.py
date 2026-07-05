import json
import os
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from models.database import (
    FieldChangeHistory,
    FundingRound,
    Investment,
    Investor,
    KnowledgeEntity,
    LeaderCandidate,
    OrganizationProfile,
    get_db,
)
from services.history_recorder import record_change
from services.quality_scorer import ProfileQualityScorer, get_t1_quality_summary

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


class ManualUpdateRequest(BaseModel):
    org_id: str = Field(..., description="OrganizationProfile.id，当前为字符串主键")
    field: str
    value: Any
    source: str = "manual"
    confidence: float = 0.95


class ApproveCandidateRequest(BaseModel):
    candidate_id: str
    action: str
    notes: str = ""


class QuickPeopleEntry(BaseModel):
    org_name: str
    leader_name: str
    leader_title: str
    source: str = "manual"
    notes: str = ""


class InlineEntryRequest(BaseModel):
    org_id: str
    field: str
    value: str
    source: str = "manual_inline"
    notes: str = ""


class BulkEntryItem(BaseModel):
    org_name: str
    value: str
    notes: str = ""


class BulkInlineEntryRequest(BaseModel):
    field: str
    entries: list[BulkEntryItem]
    source: str = "manual_bulk"


def _count_non_empty(db: Session, column) -> int:
    return db.query(OrganizationProfile).filter(column.isnot(None), column != "").count()


def _is_non_empty(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def _get_missing_fields(org: OrganizationProfile) -> list[str]:
    missing = []
    if not _is_non_empty(org.official_website):
        missing.append("website")
    if not _is_non_empty(org.leader_name):
        missing.append("people")
    if not _is_non_empty(org.description):
        missing.append("about")
    if not _is_non_empty(org.mission_statement):
        missing.append("mission")
    if org.ai_maturity_score is None:
        missing.append("ai_score")
    return missing


def _clean_manual_value(field_name: str, value: Any) -> Any:
    if value is None:
        return None

    if field_name in {"official_website", "leader_bio_url", "facebook_url", "youtube_url", "twitter_url", "wikipedia_url", "google_maps_url", "apple_maps_url"}:
        cleaned = str(value).strip().strip("`").strip()
        if not cleaned:
            return ""
        parsed = urlparse(cleaned if "://" in cleaned else f"https://{cleaned}")
        if not parsed.netloc and parsed.path:
            cleaned = f"https://{parsed.path}"
        return cleaned

    if field_name == "founded_year":
        if value in ("", None):
            return None
        return int(value)

    return str(value).strip() if isinstance(value, str) else value


def _load_source_trail(raw_value: str | None) -> list[dict[str, Any]]:
    if not raw_value:
        return []
    try:
        parsed = json.loads(raw_value)
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []


def _parse_people_value(value: str) -> tuple[str, str]:
    parts = [part.strip() for part in value.split("|", 1)]
    leader_name = parts[0] if parts else ""
    leader_title = parts[1] if len(parts) > 1 else "Leader"
    if not leader_name:
        raise ValueError("Leader name is required")
    return leader_name, leader_title


def _load_relation_graph() -> dict[str, Any]:
    graph_path = os.path.join(os.path.dirname(__file__), "..", "data", "relation_graph.json")
    if not os.path.exists(graph_path):
        return {}
    try:
        with open(graph_path, "r", encoding="utf-8") as file_obj:
            payload = json.load(file_obj)
            return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _resolve_round_target(db: Session, funding_round: FundingRound) -> dict[str, Any]:
    entity = db.query(KnowledgeEntity).filter(KnowledgeEntity.id == funding_round.entity_id).first()
    if not entity:
        return {
            "target_id": f"entity:{funding_round.entity_id}",
            "target_name": funding_round.entity_id,
            "target_country": None,
            "target_source": "unknown",
        }

    candidates = [entity.name] if entity.name else []
    if entity.name and "/" in entity.name:
        candidates.extend(part.strip() for part in entity.name.split("/") if part.strip())

    for candidate in candidates:
        query = db.query(OrganizationProfile).filter(
            or_(
                OrganizationProfile.name == candidate,
                OrganizationProfile.english_name == candidate,
                OrganizationProfile.official_name == candidate,
                OrganizationProfile.short_name == candidate,
            )
        )
        if entity.country:
            org = query.filter(OrganizationProfile.country == entity.country).first()
            if org:
                return {
                    "target_id": org.id,
                    "target_name": org.name,
                    "target_country": org.country,
                    "target_source": "organization_profile",
                }
        org = query.first()
        if org:
            return {
                "target_id": org.id,
                "target_name": org.name,
                "target_country": org.country,
                "target_source": "organization_profile",
            }

    return {
        "target_id": f"entity:{entity.id}",
        "target_name": entity.name or funding_round.entity_id,
        "target_country": entity.country,
        "target_source": "knowledge_entity",
    }


def _resolve_inline_config(normalized_field: str) -> dict[str, Any] | None:
    field_config = {
        "people": {
            "columns": ["leader_name", "leader_title"],
            "parser": _parse_people_value,
        },
        "website": {
            "columns": ["official_website"],
            "parser": lambda value: (_clean_manual_value("official_website", value),),
        },
        "contact": {
            "columns": ["contact_email"],
            "parser": lambda value: (str(value).strip(),),
        },
        "about": {
            "columns": ["description"],
            "parser": lambda value: (str(value).strip(),),
        },
        "mission": {
            "columns": ["mission_statement"],
            "parser": lambda value: (str(value).strip(),),
        },
        "vision": {
            "columns": ["vision_statement"],
            "parser": lambda value: (str(value).strip(),),
        },
        "ai_score": {
            "columns": ["ai_maturity_score"],
            "parser": lambda value: (int(str(value).strip()) if str(value).strip().isdigit() else None,),
        },
        "digital_score": {
            "columns": ["digital_score"],
            "parser": lambda value: (int(str(value).strip()) if str(value).strip().isdigit() else None,),
        },
        "social": {
            "columns": ["facebook_url"],
            "parser": lambda value: (_clean_manual_value("facebook_url", value),),
        },
    }
    return field_config.get(normalized_field)


def _apply_inline_update(
    db: Session,
    org: OrganizationProfile,
    normalized_field: str,
    raw_value: str,
    source: str,
    notes: str,
    candidate_method: str,
    reviewed_by: str,
) -> float:
    config = _resolve_inline_config(normalized_field)
    if not config:
        raise ValueError(f"Field '{normalized_field}' not supported for inline entry")

    old_values = {column: getattr(org, column, None) for column in config["columns"]}
    old_has_leadership_page = org.has_leadership_page
    parsed_values = config["parser"](raw_value)
    for index, column in enumerate(config["columns"]):
        if index < len(parsed_values) and parsed_values[index] is not None and hasattr(org, column):
            setattr(org, column, parsed_values[index])

    org.source_name = source
    org.confidence = max(float(org.confidence or 0.0), 0.95)
    if normalized_field == "website" and _is_non_empty(org.official_website):
        org.url_tier = "A"
    if normalized_field == "people":
        leader_name, leader_title = _parse_people_value(raw_value)
        org.has_leadership_page = True
        org.leader_bio_url = org.official_website

        duplicate_candidate = (
            db.query(LeaderCandidate)
            .filter(
                LeaderCandidate.organization_id == org.id,
                LeaderCandidate.candidate_name == leader_name,
                LeaderCandidate.candidate_title == leader_title,
                LeaderCandidate.status == "approved",
            )
            .first()
        )
        if not duplicate_candidate:
            candidate = LeaderCandidate(
                organization_id=org.id,
                candidate_name=leader_name,
                candidate_title=leader_title,
                source_url=org.official_website,
                extraction_method=candidate_method,
                confidence=0.95,
                status="approved",
                reviewed_by=reviewed_by,
                reviewed_at=datetime.utcnow(),
                validation_notes=notes or "Gap Workbench entry",
                approved_leader_id=org.id,
            )
            db.add(candidate)

    sources = _load_source_trail(org.data_sources_json)
    sources.append(
        {
            "field": normalized_field,
            "source": source,
            "updated_at": datetime.utcnow().isoformat(),
            "value_preview": raw_value[:50],
            "notes": notes or candidate_method,
        }
    )
    org.data_sources_json = json.dumps(sources[-20:], ensure_ascii=False)

    if hasattr(org, "notes") and notes:
        existing_notes = str(org.notes or "").strip()
        appended_note = f"[{datetime.utcnow().strftime('%Y-%m-%d')}] {notes}"
        org.notes = f"{existing_notes}\n{appended_note}".strip()

    db.commit()
    db.refresh(org)

    for column in config["columns"]:
        record_change(
            org_id=org.id,
            field_name=column,
            old_value=old_values.get(column),
            new_value=getattr(org, column, None),
            source=source,
            changed_by="user",
        )
    if normalized_field == "people":
        record_change(
            org_id=org.id,
            field_name="has_leadership_page",
            old_value=old_has_leadership_page,
            new_value=org.has_leadership_page,
            source=source,
            changed_by="user",
        )

    scorer = ProfileQualityScorer()
    return scorer.score_organization(org).overall_score


@router.get("/coverage")
def get_coverage_overview(db: Session = Depends(get_db)):
    """Coverage Dashboard 核心 API：返回关键字段覆盖率统计。"""
    total = db.query(OrganizationProfile).count()
    if total == 0:
        return {"total_organizations": 0, "generated_at": datetime.utcnow().isoformat(), "metrics": {}}

    metrics = {
        "website": {
            "label": "Website URL",
            "current": _count_non_empty(db, OrganizationProfile.official_website),
            "target": int(total * 0.6),
            "tier": "P0",
        },
        "people": {
            "label": "People (Leader)",
            "current": _count_non_empty(db, OrganizationProfile.leader_name),
            "target": int(total * 0.4),
            "tier": "P0",
        },
        "deep_crawl": {
            "label": "Deep Profile",
            "current": db.query(OrganizationProfile).filter(OrganizationProfile.last_website_crawl.isnot(None)).count(),
            "target": int(total * 0.5),
            "tier": "P0",
        },
        "about": {
            "label": "About",
            "current": _count_non_empty(db, OrganizationProfile.description),
            "target": int(total * 0.8),
            "tier": "P1",
        },
        "mission": {
            "label": "Mission",
            "current": _count_non_empty(db, OrganizationProfile.mission_statement),
            "target": int(total * 0.8),
            "tier": "P1",
        },
        "contact_email": {
            "label": "Email",
            "current": _count_non_empty(db, OrganizationProfile.contact_email),
            "target": int(total * 0.2),
            "tier": "P1",
        },
        "facebook": {
            "label": "Facebook",
            "current": _count_non_empty(db, OrganizationProfile.facebook_url),
            "target": int(total * 0.7),
            "tier": "P1",
        },
        "leadership_page": {
            "label": "Leadership Page",
            "current": db.query(OrganizationProfile).filter(OrganizationProfile.has_leadership_page.is_(True)).count(),
            "target": int(total * 0.4),
            "tier": "P1",
        },
        "programs": {
            "label": "Programs",
            "current": db.query(OrganizationProfile).filter(OrganizationProfile.has_programs.is_(True)).count(),
            "target": int(total * 0.5),
            "tier": "P1",
        },
        "donate": {
            "label": "Donate Page",
            "current": db.query(OrganizationProfile).filter(OrganizationProfile.has_donate.is_(True)).count(),
            "target": int(total * 0.4),
            "tier": "P2",
        },
        "annual_report": {
            "label": "Annual Report",
            "current": db.query(OrganizationProfile).filter(OrganizationProfile.has_annual_report.is_(True)).count(),
            "target": int(total * 0.15),
            "tier": "P2",
        },
        "ai_score": {
            "label": "AI Score",
            "current": db.query(OrganizationProfile).filter(OrganizationProfile.ai_maturity_score.isnot(None)).count(),
            "target": int(total * 0.6),
            "tier": "P1",
        },
        "digital_score": {
            "label": "Digital Score",
            "current": db.query(OrganizationProfile).filter(OrganizationProfile.digital_score.isnot(None)).count(),
            "target": int(total * 0.4),
            "tier": "P1",
        },
        "url_tier": {
            "label": "URL Tier (A/B/C)",
            "current": _count_non_empty(db, OrganizationProfile.url_tier),
            "target": total,
            "tier": "P0",
        },
        "priority_tier": {
            "label": "Priority Tier (T1/T2/T3)",
            "current": _count_non_empty(db, OrganizationProfile.priority_tier),
            "target": total,
            "tier": "P0",
        },
    }

    for metric in metrics.values():
        metric["percentage"] = round(metric["current"] / total * 100, 1) if total else 0.0
        metric["target_percentage"] = round(metric["target"] / total * 100, 1) if total else 0.0
        metric["gap"] = max(metric["target"] - metric["current"], 0)

    return {
        "total_organizations": total,
        "generated_at": datetime.utcnow().isoformat(),
        "metrics": metrics,
    }


@router.get("/coverage/tier1")
def get_tier1_coverage(db: Session = Depends(get_db)):
    """T1 专项覆盖率面板，只统计 Top 300 机构。"""
    total_t1 = 300
    t1_query = db.query(OrganizationProfile).filter(OrganizationProfile.priority_tier == "T1")

    metrics = {
        "website": {
            "label": "Website URL",
            "current": t1_query.filter(
                OrganizationProfile.official_website.isnot(None),
                OrganizationProfile.official_website != "",
            ).count(),
            "target": 300,
            "tier": "T1",
        },
        "people": {
            "label": "People",
            "current": t1_query.filter(
                OrganizationProfile.leader_name.isnot(None),
                OrganizationProfile.leader_name != "",
            ).count(),
            "target": 300,
            "tier": "T1",
        },
        "deep_crawl": {
            "label": "Deep Profile",
            "current": t1_query.filter(OrganizationProfile.last_deep_crawl.isnot(None)).count(),
            "target": 300,
            "tier": "T1",
        },
        "about": {
            "label": "About",
            "current": t1_query.filter(
                OrganizationProfile.description.isnot(None),
                OrganizationProfile.description != "",
            ).count(),
            "target": 240,
            "tier": "T1",
        },
        "mission": {
            "label": "Mission",
            "current": t1_query.filter(
                OrganizationProfile.mission_statement.isnot(None),
                OrganizationProfile.mission_statement != "",
            ).count(),
            "target": 240,
            "tier": "T1",
        },
        "email": {
            "label": "Contact Email",
            "current": t1_query.filter(
                OrganizationProfile.contact_email.isnot(None),
                OrganizationProfile.contact_email != "",
            ).count(),
            "target": 150,
            "tier": "T1",
        },
        "ai_score": {
            "label": "AI Score",
            "current": t1_query.filter(OrganizationProfile.ai_maturity_score.isnot(None)).count(),
            "target": 180,
            "tier": "T1",
        },
        "digital_score": {
            "label": "Digital Score",
            "current": t1_query.filter(OrganizationProfile.digital_score.isnot(None)).count(),
            "target": 180,
            "tier": "T1",
        },
    }

    for metric in metrics.values():
        metric["percentage"] = round(metric["current"] / total_t1 * 100, 1) if total_t1 else 0.0
        metric["target_percentage"] = round(metric["target"] / total_t1 * 100, 1) if total_t1 else 0.0
        metric["gap"] = max(metric["target"] - metric["current"], 0)

    return {
        "total_t1": total_t1,
        "generated_at": datetime.utcnow().isoformat(),
        "metrics": metrics,
    }


@router.get("/quality-scores")
def get_quality_scores(limit: int = 50):
    scorer = ProfileQualityScorer()
    results = scorer.score_all_t1()

    return {
        "summary": get_t1_quality_summary(),
        "organizations": [
            {
                "id": result.org_id,
                "name": result.org_name,
                "score": result.overall_score,
                "field_scores": result.field_scores,
                "missing_fields": result.missing_fields,
                "rank": result.priority_rank,
                "needs_attention": result.overall_score < 60,
            }
            for result in results[:limit]
        ],
    }


@router.get("/top-priority")
def get_top_priority_gaps(limit: int = 20, db: Session = Depends(get_db)):
    """返回最需要优先补数的 T1 机构。"""
    orgs = (
        db.query(OrganizationProfile)
        .filter(OrganizationProfile.priority_tier == "T1")
        .filter(
            or_(
                OrganizationProfile.official_website.is_(None),
                OrganizationProfile.official_website == "",
                OrganizationProfile.leader_name.is_(None),
                OrganizationProfile.leader_name == "",
                OrganizationProfile.description.is_(None),
                OrganizationProfile.description == "",
                OrganizationProfile.mission_statement.is_(None),
                OrganizationProfile.mission_statement == "",
            )
        )
        .order_by(OrganizationProfile.country.asc(), OrganizationProfile.name.asc())
        .limit(limit)
        .all()
    )

    return [
        {
            "id": org.id,
            "name": org.name,
            "country": org.country,
            "priority": org.priority_tier,
            "missing": {
                "website": not bool(org.official_website),
                "people": not bool(org.leader_name),
                "about": not bool(org.description),
                "mission": not bool(org.mission_statement),
            },
        }
        for org in orgs
    ]


@router.get("/tier-distribution")
def get_tier_distribution(db: Session = Depends(get_db)):
    """返回 T1/T2/T3 优先级分布。"""
    rows = (
        db.query(OrganizationProfile.priority_tier, func.count(OrganizationProfile.id))
        .group_by(OrganizationProfile.priority_tier)
        .all()
    )
    return {tier or "unassigned": count for tier, count in rows}


@router.get("/tier1-gaps")
def get_tier1_gaps(field: str | None = None, limit: int = 100, db: Session = Depends(get_db)):
    """返回 T1 机构的数据缺口清单，可按字段过滤。"""
    query = db.query(OrganizationProfile).filter(OrganizationProfile.priority_tier == "T1")
    normalized_field = (field or "").strip().lower() or None

    if normalized_field == "website":
        query = query.filter(or_(OrganizationProfile.official_website.is_(None), OrganizationProfile.official_website == ""))
    elif normalized_field in {"people", "leader"}:
        query = query.filter(or_(OrganizationProfile.leader_name.is_(None), OrganizationProfile.leader_name == ""))
    elif normalized_field == "about":
        query = query.filter(or_(OrganizationProfile.description.is_(None), OrganizationProfile.description == ""))
    elif normalized_field == "mission":
        query = query.filter(or_(OrganizationProfile.mission_statement.is_(None), OrganizationProfile.mission_statement == ""))
    elif normalized_field == "contact":
        query = query.filter(
            or_(
                OrganizationProfile.contact_email.is_(None),
                OrganizationProfile.contact_email == "",
            )
        ).filter(or_(OrganizationProfile.phone_public.is_(None), OrganizationProfile.phone_public == ""))
    elif normalized_field == "vision":
        query = query.filter(or_(OrganizationProfile.vision_statement.is_(None), OrganizationProfile.vision_statement == ""))
    elif normalized_field == "programs":
        query = query.filter(or_(OrganizationProfile.has_programs.is_(None), OrganizationProfile.has_programs == False))
    elif normalized_field == "leadership_page":
        query = query.filter(or_(OrganizationProfile.has_leadership_page.is_(None), OrganizationProfile.has_leadership_page == False))
    elif normalized_field == "annual_report":
        query = query.filter(or_(OrganizationProfile.has_annual_report.is_(None), OrganizationProfile.has_annual_report == False))
    elif normalized_field == "ai_score":
        query = query.filter(OrganizationProfile.ai_maturity_score.is_(None))
    elif normalized_field == "digital_score":
        query = query.filter(OrganizationProfile.digital_score.is_(None))
    elif normalized_field == "social":
        query = query.filter(
            or_(
                OrganizationProfile.facebook_url.is_(None),
                OrganizationProfile.facebook_url == "",
            )
        ).filter(
            or_(
                OrganizationProfile.youtube_url.is_(None),
                OrganizationProfile.youtube_url == "",
            )
        ).filter(
            or_(
                OrganizationProfile.social_accounts_json.is_(None),
                OrganizationProfile.social_accounts_json == "",
            )
        )
    elif normalized_field == "funding":
        query = query.filter(
            or_(
                OrganizationProfile.annual_revenue.is_(None),
                OrganizationProfile.annual_revenue == "",
            )
        ).filter(or_(OrganizationProfile.budget_scale.is_(None), OrganizationProfile.budget_scale == ""))
    elif normalized_field:
        raise HTTPException(
            status_code=400,
            detail="field 仅支持 website/people/about/mission/contact/vision/programs/leadership_page/annual_report/ai_score/digital_score/social/funding/leader",
        )
    else:
        query = query.filter(
            or_(
                OrganizationProfile.official_website.is_(None),
                OrganizationProfile.official_website == "",
                OrganizationProfile.leader_name.is_(None),
                OrganizationProfile.leader_name == "",
                OrganizationProfile.description.is_(None),
                OrganizationProfile.description == "",
                OrganizationProfile.mission_statement.is_(None),
                OrganizationProfile.mission_statement == "",
                OrganizationProfile.ai_maturity_score.is_(None),
            )
        )

    total_gaps = query.count()
    orgs = query.order_by(OrganizationProfile.country.asc(), OrganizationProfile.name.asc()).limit(limit).all()
    total_t1 = db.query(OrganizationProfile).filter(OrganizationProfile.priority_tier == "T1").count()

    return {
        "total_t1": total_t1,
        "gaps_count": total_gaps,
        "returned_count": len(orgs),
        "field_filter": normalized_field,
        "organizations": [
            {
                "id": org.id,
                "name": org.name,
                "english_name": org.english_name,
                "country": org.country,
                "url_tier": org.url_tier,
                "official_website": org.official_website,
                "leader_name": org.leader_name,
                "has_about": _is_non_empty(org.description),
                "has_mission": _is_non_empty(org.mission_statement),
                "ai_maturity_score": org.ai_maturity_score,
                "missing_fields": _get_missing_fields(org),
            }
            for org in orgs
        ],
    }


@router.post("/manual-update")
def manual_update_field(request: ManualUpdateRequest, db: Session = Depends(get_db)):
    """人工字段更新 API，支持手机/前端直接录入。"""
    org = db.query(OrganizationProfile).filter(OrganizationProfile.id == request.org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    field_mapping = {
        "official_website": "official_website",
        "leader_name": "leader_name",
        "leader_title": "leader_title",
        "leader_bio_url": "leader_bio_url",
        "contact_email": "contact_email",
        "contact_phone": "phone_public",
        "phone_public": "phone_public",
        "facebook_url": "facebook_url",
        "youtube_url": "youtube_url",
        "twitter_url": "twitter_url",
        "description": "description",
        "mission_statement": "mission_statement",
        "vision_statement": "vision_statement",
        "founded_year": "founded_year",
        "organization_type": "organization_type",
        "denomination": "denomination",
        "english_name": "english_name",
        "short_name": "short_name",
        "wikipedia_url": "wikipedia_url",
        "wikidata_id": "wikidata_id",
    }
    internal_field = field_mapping.get(request.field)
    if not internal_field:
        raise HTTPException(
            status_code=400,
            detail=f"Field '{request.field}' not allowed. Allowed: {sorted(field_mapping.keys())}",
        )

    old_value = getattr(org, internal_field, None)
    cleaned_value = _clean_manual_value(internal_field, request.value)
    setattr(org, internal_field, cleaned_value)
    org.source_name = request.source
    org.confidence = max(0.0, min(float(request.confidence), 1.0))

    sources = []
    if org.data_sources_json:
        try:
            sources = json.loads(org.data_sources_json)
            if not isinstance(sources, list):
                sources = []
        except Exception:
            sources = []

    sources.append(
        {
            "field": internal_field,
            "source": request.source,
            "confidence": org.confidence,
            "updated_at": datetime.utcnow().isoformat(),
        }
    )
    org.data_sources_json = json.dumps(sources[-20:], ensure_ascii=False)

    if internal_field == "official_website" and _is_non_empty(cleaned_value):
        org.url_tier = "A"

    db.commit()
    db.refresh(org)
    record_change(
        org_id=org.id,
        field_name=internal_field,
        old_value=old_value,
        new_value=getattr(org, internal_field),
        source=request.source,
        changed_by="user",
    )

    return {
        "success": True,
        "org_id": org.id,
        "org_name": org.name,
        "field_updated": internal_field,
        "new_value": getattr(org, internal_field),
        "url_tier": org.url_tier,
        "source_trail_count": len(sources[-20:]),
    }


@router.post("/inline-entry")
def inline_entry(request: InlineEntryRequest, db: Session = Depends(get_db)):
    """Dashboard 内联补录 API，用于 Gap Workbench 直接补字段。"""
    org = db.query(OrganizationProfile).filter(OrganizationProfile.id == request.org_id).first()
    if not org:
        return {"error": "Organization not found", "org_id": request.org_id}

    normalized_field = (request.field or "").strip().lower()
    raw_value = str(request.value or "").strip()
    if not raw_value:
        return {"error": "value is required"}

    try:
        new_score = _apply_inline_update(
            db=db,
            org=org,
            normalized_field=normalized_field,
            raw_value=raw_value,
            source=request.source,
            notes=request.notes or "gap-workbench",
            candidate_method="manual_inline",
            reviewed_by="dashboard_inline",
        )
    except Exception as exc:
        return {"error": f"Failed to parse value: {exc}"}

    return {
        "success": True,
        "org_id": request.org_id,
        "org_name": org.name,
        "field_updated": normalized_field,
        "new_score": new_score.overall_score,
        "message": f"Updated {normalized_field} for {org.name}. New score: {new_score.overall_score}",
    }


@router.post("/inline-entry/bulk")
def bulk_inline_entry(request: BulkInlineEntryRequest, db: Session = Depends(get_db)):
    """Dashboard 批量补录 API，支持一次粘贴多条 `机构名|值`。"""
    results = []
    success_count = 0
    fail_count = 0
    normalized_field = (request.field or "").strip().lower()

    if not _resolve_inline_config(normalized_field):
        return {
            "total": len(request.entries),
            "success": 0,
            "failed": len(request.entries),
            "results": [
                {
                    "org_name": item.org_name,
                    "status": "error",
                    "message": f"Field '{request.field}' not supported for bulk inline entry",
                }
                for item in request.entries
            ],
        }

    for item in request.entries:
        search_term = (item.org_name or "").strip()
        raw_value = str(item.value or "").strip()
        if not search_term or not raw_value:
            results.append(
                {
                    "org_name": item.org_name,
                    "status": "error",
                    "message": "org_name and value are required",
                }
            )
            fail_count += 1
            continue

        org = (
            db.query(OrganizationProfile)
            .filter(
                or_(
                    OrganizationProfile.name.ilike(f"%{search_term}%"),
                    OrganizationProfile.english_name.ilike(f"%{search_term}%"),
                    OrganizationProfile.short_name.ilike(f"%{search_term}%"),
                )
            )
            .order_by(
                (OrganizationProfile.priority_tier == "T1").desc(),
                (OrganizationProfile.name == search_term).desc(),
                OrganizationProfile.id.asc(),
            )
            .first()
        )

        if not org:
            results.append(
                {
                    "org_name": item.org_name,
                    "status": "not_found",
                    "message": f"Organization '{item.org_name}' not found",
                }
            )
            fail_count += 1
            continue

        try:
            new_score = _apply_inline_update(
                db=db,
                org=org,
                normalized_field=normalized_field,
                raw_value=raw_value,
                source=request.source,
                notes=item.notes or "gap-workbench-bulk",
                candidate_method="manual_bulk",
                reviewed_by="dashboard_bulk",
            )
            results.append(
                {
                    "org_name": org.name,
                    "status": "success",
                    "new_score": new_score,
                    "message": f"Updated. New score: {new_score}",
                }
            )
            success_count += 1
        except Exception as exc:
            db.rollback()
            results.append(
                {
                    "org_name": item.org_name,
                    "status": "error",
                    "message": str(exc)[:100],
                }
            )
            fail_count += 1

    return {
        "total": len(request.entries),
        "success": success_count,
        "failed": fail_count,
        "results": results,
    }


@router.get("/recommend-next")
def recommend_next_org(field: str = "people", db: Session = Depends(get_db)):
    """按 Tier 目标与字段优先级返回最该优先修复的机构 Top 5。"""
    normalized_field = (field or "").strip().lower()
    scorer = ProfileQualityScorer()
    orgs = (
        db.query(OrganizationProfile)
        .filter(OrganizationProfile.priority_tier.in_(["T1", "T2", "T3"]))
        .all()
    )

    field_map = {
        "people": lambda org: not _is_non_empty(org.leader_name),
        "website": lambda org: not _is_non_empty(org.official_website),
        "contact": lambda org: not (_is_non_empty(org.contact_email) or _is_non_empty(org.phone_public)),
        "about": lambda org: not _is_non_empty(org.description),
        "mission": lambda org: not _is_non_empty(org.mission_statement),
        "vision": lambda org: not _is_non_empty(org.vision_statement),
        "programs": lambda org: not bool(org.has_programs),
        "ai_score": lambda org: org.ai_maturity_score is None,
        "digital_score": lambda org: org.digital_score is None,
        "social": lambda org: not (
            _is_non_empty(org.facebook_url)
            or _is_non_empty(org.youtube_url)
            or _is_non_empty(org.social_accounts_json)
        ),
        "funding": lambda org: not (_is_non_empty(org.annual_revenue) or _is_non_empty(org.budget_scale)),
    }
    check_func = field_map.get(normalized_field)
    if not check_func:
        raise HTTPException(status_code=400, detail="unsupported field for recommend-next")

    tier_weights = {
        "T1": 10,
        "T2": 5,
        "T3": 2,
    }
    field_priority = {
        "people": 15,
        "mission": 10,
        "about": 8,
        "ai_score": 8,
        "website": 5,
        "contact": 5,
        "digital_score": 5,
        "programs": 4,
        "vision": 3,
        "social": 3,
        "funding": 2,
    }

    scored_orgs = []
    for org in orgs:
        if not check_func(org):
            continue

        score_result = scorer.score_organization(org)
        tier_weight = tier_weights.get(score_result.tier, 1)
        field_weight = field_priority.get(normalized_field, 5)
        priority_score = (100 - score_result.overall_score) * tier_weight * field_weight

        scored_orgs.append(
            {
                "id": org.id,
                "name": org.name,
                "country": org.country,
                "website": org.official_website,
                "tier": score_result.tier,
                "current_score": score_result.overall_score,
                "priority_score": round(priority_score, 1),
                "missing_fields": score_result.missing_fields[:5],
            }
        )

    scored_orgs.sort(
        key=lambda item: (
            -item["priority_score"],
            item["current_score"],
            (item["name"] or "").lower(),
        )
    )

    return {
        "field": normalized_field,
        "total_missing": len(scored_orgs),
        "recommendations": scored_orgs[:5],
    }


@router.get("/people-candidates")
def get_people_candidates(
    status: str = "pending",
    limit: int = 50,
    db: Session = Depends(get_db),
):
    """返回 People 候选清单，供人工确认。"""
    candidates = (
        db.query(LeaderCandidate, OrganizationProfile)
        .join(OrganizationProfile, LeaderCandidate.organization_id == OrganizationProfile.id)
        .filter(LeaderCandidate.status == status)
        .order_by(LeaderCandidate.confidence.desc(), LeaderCandidate.created_at.desc())
        .limit(limit)
        .all()
    )

    return {
        "total_pending": db.query(LeaderCandidate).filter(LeaderCandidate.status == "pending").count(),
        "total_approved": db.query(LeaderCandidate).filter(LeaderCandidate.status == "approved").count(),
        "total_rejected": db.query(LeaderCandidate).filter(LeaderCandidate.status == "rejected").count(),
        "candidates": [
            {
                "candidate_id": lc.id,
                "org_id": op.id,
                "org_name": op.name,
                "org_country": op.country,
                "official_website": op.official_website,
                "candidate_name": lc.candidate_name,
                "candidate_title": lc.candidate_title,
                "confidence": lc.confidence,
                "extraction_method": lc.extraction_method,
                "source_url": lc.source_url,
                "status": lc.status,
                "validation_notes": lc.validation_notes,
            }
            for lc, op in candidates
        ],
    }


@router.post("/people-candidates/review")
def review_candidate(request: ApproveCandidateRequest, db: Session = Depends(get_db)):
    """人工审核 People 候选。"""
    candidate = db.query(LeaderCandidate).filter(LeaderCandidate.id == request.candidate_id).first()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    normalized_action = (request.action or "").strip().lower()
    if normalized_action in {"approve", "approved"}:
        target_status = "approved"
    elif normalized_action in {"reject", "rejected"}:
        target_status = "rejected"
    else:
        raise HTTPException(status_code=400, detail="action 仅支持 approve/approved/reject/rejected")

    candidate.status = target_status
    candidate.validation_notes = request.notes
    candidate.reviewed_at = datetime.utcnow()
    candidate.reviewed_by = "manual"

    approved_org_name = None
    old_leader_name = None
    old_leader_title = None
    old_has_leadership_page = None
    if target_status == "approved":
        org = db.query(OrganizationProfile).filter(OrganizationProfile.id == candidate.organization_id).first()
        if org:
            old_leader_name = org.leader_name
            old_leader_title = org.leader_title
            old_has_leadership_page = org.has_leadership_page
            org.leader_name = candidate.candidate_name
            org.leader_title = candidate.candidate_title
            org.leader_bio_url = candidate.source_url
            org.has_leadership_page = True

            sources = _load_source_trail(org.data_sources_json)
            sources.append(
                {
                    "field": "leader_name",
                    "source": "candidate_approved",
                    "confidence": candidate.confidence,
                    "updated_at": datetime.utcnow().isoformat(),
                }
            )
            org.data_sources_json = json.dumps(sources[-20:], ensure_ascii=False)
            candidate.approved_leader_id = org.id
            approved_org_name = org.name

    db.commit()
    if target_status == "approved" and approved_org_name:
        record_change(
            org_id=candidate.organization_id,
            field_name="leader_name",
            old_value=old_leader_name,
            new_value=candidate.candidate_name,
            source="candidate_review",
            changed_by="user",
        )
        record_change(
            org_id=candidate.organization_id,
            field_name="leader_title",
            old_value=old_leader_title,
            new_value=candidate.candidate_title,
            source="candidate_review",
            changed_by="user",
        )
        record_change(
            org_id=candidate.organization_id,
            field_name="has_leadership_page",
            old_value=old_has_leadership_page,
            new_value=True,
            source="candidate_review",
            changed_by="user",
        )

    return {
        "success": True,
        "candidate_id": request.candidate_id,
        "action": target_status,
        "org_name": approved_org_name,
    }


@router.post("/quick-people-entry")
def quick_people_entry(request: QuickPeopleEntry, db: Session = Depends(get_db)):
    """快速手动录入 People 信息，支持模糊匹配机构名。"""
    search_term = (request.org_name or "").strip()
    if not search_term:
        raise HTTPException(status_code=400, detail="org_name is required")

    org = (
        db.query(OrganizationProfile)
        .filter(
            or_(
                OrganizationProfile.name.ilike(f"%{search_term}%"),
                OrganizationProfile.english_name.ilike(f"%{search_term}%"),
                OrganizationProfile.short_name.ilike(f"%{search_term}%"),
            )
        )
        .order_by(
            (OrganizationProfile.priority_tier == "T1").desc(),
            (OrganizationProfile.name == search_term).desc(),
            OrganizationProfile.id.asc(),
        )
        .first()
    )

    if not org:
        return {
            "error": f"Organization '{request.org_name}' not found",
            "suggestion": "Try exact name or check /api/search",
        }

    leader_name = str(request.leader_name or "").strip()
    leader_title = str(request.leader_title or "").strip()
    if not leader_name or not leader_title:
        raise HTTPException(status_code=400, detail="leader_name and leader_title are required")

    old_leader_name = org.leader_name
    old_leader_title = org.leader_title
    old_has_leadership_page = org.has_leadership_page
    org.leader_name = leader_name
    org.leader_title = leader_title
    org.leader_bio_url = org.official_website
    org.has_leadership_page = True
    org.source_name = request.source
    org.confidence = max(float(org.confidence or 0.0), 0.95)

    sources = _load_source_trail(org.data_sources_json)
    sources.append(
        {
            "field": "leader_name",
            "source": request.source,
            "confidence": 0.95,
            "updated_at": datetime.utcnow().isoformat(),
            "notes": request.notes or "Quick entry by user",
        }
    )
    org.data_sources_json = json.dumps(sources[-20:], ensure_ascii=False)

    duplicate_candidate = (
        db.query(LeaderCandidate)
        .filter(
            LeaderCandidate.organization_id == org.id,
            LeaderCandidate.candidate_name == leader_name,
            LeaderCandidate.candidate_title == leader_title,
            LeaderCandidate.status == "approved",
        )
        .first()
    )
    if not duplicate_candidate:
        candidate = LeaderCandidate(
            organization_id=org.id,
            candidate_name=leader_name,
            candidate_title=leader_title,
            source_url=org.official_website,
            extraction_method="manual",
            confidence=0.95,
            status="approved",
            reviewed_by="manual_quick_entry",
            reviewed_at=datetime.utcnow(),
            validation_notes=request.notes or "Quick entry by user",
            approved_leader_id=org.id,
        )
        db.add(candidate)

    db.commit()
    record_change(
        org_id=org.id,
        field_name="leader_name",
        old_value=old_leader_name,
        new_value=leader_name,
        source=request.source,
        changed_by="user",
    )
    record_change(
        org_id=org.id,
        field_name="leader_title",
        old_value=old_leader_title,
        new_value=leader_title,
        source=request.source,
        changed_by="user",
    )
    record_change(
        org_id=org.id,
        field_name="has_leadership_page",
        old_value=old_has_leadership_page,
        new_value=True,
        source=request.source,
        changed_by="user",
    )

    people_coverage_now = _count_non_empty(db, OrganizationProfile.leader_name)

    return {
        "success": True,
        "org_id": org.id,
        "org_name": org.name,
        "leader_name": leader_name,
        "leader_title": leader_title,
        "people_coverage_now": people_coverage_now,
    }


@router.get("/overview")
def get_overview(db: Session = Depends(get_db)):
    """全局概览统计，供产品首页展示。"""

    total_orgs = db.query(OrganizationProfile).count()
    t1_total = db.query(OrganizationProfile).filter(OrganizationProfile.priority_tier == "T1").count()
    t2_total = db.query(OrganizationProfile).filter(OrganizationProfile.priority_tier == "T2").count()
    country_count = (
        db.query(OrganizationProfile.country)
        .filter(OrganizationProfile.country.isnot(None), OrganizationProfile.country != "")
        .distinct()
        .count()
    )

    def coverage(field: str, is_bool: bool = False) -> float:
        query = db.query(OrganizationProfile).filter(OrganizationProfile.priority_tier == "T1")
        column = getattr(OrganizationProfile, field)
        if is_bool:
            has = query.filter(column.is_(True)).count()
        else:
            has = query.filter(column.isnot(None), column != "").count()
        return round(has / t1_total * 100, 1) if t1_total > 0 else 0.0

    return {
        "total_organizations": total_orgs,
        "tier_counts": {"T1": t1_total, "T2": t2_total},
        "countries_covered": country_count,
        "coverage": {
            "website": coverage("official_website"),
            "people": coverage("leader_name"),
            "about": coverage("description"),
            "mission": coverage("mission_statement"),
            "programs": coverage("has_programs", is_bool=True),
            "contact": coverage("contact_email"),
            "deep_profile": coverage("deep_crawl_status"),
            "ai_score": coverage("ai_maturity_score"),
        },
        "gap_priority": [
            {"field": "contact", "coverage": coverage("contact_email"), "target": 60},
            {"field": "mission", "coverage": coverage("mission_statement"), "target": 70},
            {"field": "about", "coverage": coverage("description"), "target": 80},
            {"field": "programs", "coverage": coverage("has_programs", is_bool=True), "target": 50},
            {"field": "people", "coverage": coverage("leader_name"), "target": 30},
        ],
    }


@router.get("/country-stats")
def get_country_stats(country: str | None = None, db: Session = Depends(get_db)):
    """国家维度统计。"""

    query = db.query(OrganizationProfile)
    if country:
        query = query.filter(OrganizationProfile.country == country)

    total = query.count()
    if total == 0:
        return {"country": country, "total": 0}

    has_website = query.filter(
        OrganizationProfile.official_website.isnot(None),
        OrganizationProfile.official_website != "",
    ).count()
    has_people = query.filter(
        OrganizationProfile.leader_name.isnot(None),
        OrganizationProfile.leader_name != "",
    ).count()
    has_ai = query.filter(OrganizationProfile.ai_maturity_score.isnot(None)).count()
    orgs = query.order_by(OrganizationProfile.priority_tier.asc(), OrganizationProfile.name.asc()).limit(10).all()

    return {
        "country": country or "Global",
        "total_organizations": total,
        "with_website": has_website,
        "with_people": has_people,
        "with_ai_assessment": has_ai,
        "top_organizations": [
            {"name": o.name, "type": o.organization_type, "people": o.leader_name}
            for o in orgs
        ],
    }


@router.get("/relations/network-overview")
def get_network_overview(db: Session = Depends(get_db)):
    """关系网络全局概览。"""
    investor_count = db.query(Investor).count()
    funding_count = db.query(FundingRound).count()
    investment_count = db.query(Investment).count()
    funded_entities = db.query(func.count(func.distinct(FundingRound.entity_id))).scalar() or 0

    active_investors = (
        db.query(
            Investment.investor_id,
            func.count().label("count"),
        )
        .group_by(Investment.investor_id)
        .order_by(func.count().desc())
        .limit(5)
        .all()
    )

    top_investors = []
    for investor_id, count in active_investors:
        investor = db.query(Investor).filter(Investor.id == investor_id).first()
        top_investors.append(
            {
                "id": investor_id,
                "name": investor.name if investor else str(investor_id),
                "investments": count,
            }
        )

    return {
        "network_stats": {
            "investor_nodes": investor_count,
            "funding_rounds": funding_count,
            "investment_edges": investment_count,
            "orgs_with_funding": funded_entities,
        },
        "top_investors": top_investors,
        "density": round(investment_count / max(investor_count, 1), 2),
    }


@router.get("/relations/investor/{investor_id}")
def get_investor_network(investor_id: int, db: Session = Depends(get_db)):
    """获取投资方的投资组合。"""
    investor = db.query(Investor).filter(Investor.id == investor_id).first()
    if not investor:
        raise HTTPException(status_code=404, detail="Investor not found")

    investments = (
        db.query(Investment)
        .filter(Investment.investor_id == investor_id)
        .order_by(Investment.id.desc())
        .all()
    )

    portfolio = []
    for investment in investments:
        funding = db.query(FundingRound).filter(FundingRound.id == investment.funding_round_id).first()
        if not funding:
            continue
        target = _resolve_round_target(db, funding)
        portfolio.append(
            {
                "org_name": target["target_name"],
                "org_id": target["target_id"],
                "country": target["target_country"],
                "round": funding.round_type,
                "amount": investment.amount,
                "lead_investor": bool(investment.lead_investor),
                "announced_date": funding.announced_date.isoformat() if funding.announced_date else None,
                "source_type": target["target_source"],
            }
        )

    return {
        "investor_name": investor.name,
        "investor_id": investor_id,
        "portfolio_size": len(portfolio),
        "portfolio": portfolio,
    }


@router.get("/relations/{org_id}")
def get_org_relations(org_id: str, db: Session = Depends(get_db)):
    """获取机构的投资关系图谱。"""
    org = db.query(OrganizationProfile).filter(OrganizationProfile.id == org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    graph_data = _load_relation_graph()
    result = {
        "organization_id": org_id,
        "organization_name": org.name,
        "investors": [],
        "co_investors": [],
        "funding_history": [],
    }

    matching_rounds = []
    funding_rounds = db.query(FundingRound).order_by(FundingRound.announced_date.desc().nullslast(), FundingRound.id.desc()).all()
    for funding_round in funding_rounds:
        target = _resolve_round_target(db, funding_round)
        if target["target_id"] == org_id:
            matching_rounds.append((funding_round, target))

    for funding_round, target in matching_rounds:
        investments = db.query(Investment).filter(Investment.funding_round_id == funding_round.id).all()
        round_investors = []
        for investment in investments:
            investor = db.query(Investor).filter(Investor.id == investment.investor_id).first()
            if investor:
                round_investors.append(
                    {
                        "name": investor.name,
                        "id": investor.id,
                        "country": investor.country,
                        "amount": investment.amount,
                        "lead_investor": bool(investment.lead_investor),
                    }
                )

        result["funding_history"].append(
            {
                "round_id": funding_round.id,
                "round_name": funding_round.round_type,
                "amount": funding_round.amount,
                "date": funding_round.announced_date.isoformat() if funding_round.announced_date else None,
                "investors": round_investors,
                "source_type": target["target_source"],
            }
        )
        result["investors"].extend(round_investors)

    seen = set()
    unique_investors = []
    for investor in result["investors"]:
        if investor["id"] in seen:
            continue
        seen.add(investor["id"])
        unique_investors.append(investor)
    result["investors"] = unique_investors

    if graph_data:
        current_investor_ids = {str(investor["id"]) for investor in result["investors"]}
        co_investors = []
        for pair in graph_data.get("co_investors", []):
            investor_a = str(pair.get("investor_a"))
            investor_b = str(pair.get("investor_b"))
            if investor_a in current_investor_ids or investor_b in current_investor_ids:
                co_investors.append(pair)
        result["co_investors"] = co_investors

    return result


@router.get("/history/summary")
def get_history_summary(db: Session = Depends(get_db)):
    """全局变更统计，展示 History Layer 当前价值。"""
    total_changes = db.query(FieldChangeHistory).count()

    field_dist = (
        db.query(
            FieldChangeHistory.field_name,
            func.count().label("cnt"),
        )
        .group_by(FieldChangeHistory.field_name)
        .order_by(func.count().desc())
        .all()
    )

    thirty_days_ago = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    thirty_days_ago = thirty_days_ago.replace(day=max(1, thirty_days_ago.day))
    from datetime import timedelta

    recent = (
        db.query(FieldChangeHistory)
        .filter(FieldChangeHistory.created_at >= (datetime.utcnow() - timedelta(days=30)))
        .count()
    )

    return {
        "total_changes_recorded": total_changes,
        "changes_last_30_days": recent,
        "field_distribution": [{"field": field_name, "changes": count} for field_name, count in field_dist],
        "history_layer_status": "active" if total_changes > 0 else "ready",
    }


@router.get("/history/{org_id}")
def get_org_history(org_id: str, limit: int = 20, db: Session = Depends(get_db)):
    """获取机构字段变更历史。"""
    history = (
        db.query(FieldChangeHistory)
        .filter(FieldChangeHistory.organization_id == org_id)
        .order_by(FieldChangeHistory.created_at.desc())
        .limit(limit)
        .all()
    )

    return {
        "organization_id": org_id,
        "total_changes": len(history),
        "changes": [
            {
                "field": item.field_name,
                "old": item.old_value,
                "new": item.new_value,
                "source": item.change_source,
                "by": item.changed_by,
                "at": item.created_at.isoformat() if item.created_at else None,
            }
            for item in history
        ],
    }


@router.get("/scores")
def get_organization_scores(org_id: str = None, db: Session = Depends(get_db)):
    """
    返回机构的三个评分：People / Digital / Intel
    如果 org_id 为空，返回全局评分统计。
    """
    if org_id:
        org = db.query(OrganizationProfile).filter(OrganizationProfile.id == org_id).first()
        if not org:
            raise HTTPException(status_code=404, detail="Organization not found")

        people_total = org.people_score or 0
        digital_total = org.digital_score or 0
        intel_total = org.intel_score or 0
        composite_total = people_total + digital_total + intel_total

        return {
            "organization": {
                "id": org.id,
                "name": org.name,
                "country": org.country,
            },
            "people_score": {
                "total": people_total,
                "grade": org.people_score_grade or "F",
                "dimensions": _safe_json_parse(org.people_score_dimensions),
            },
            "digital_score": {
                "total": digital_total,
                "grade": org.digital_score_grade or "F",
                "dimensions": _safe_json_parse(org.digital_score_dimensions),
            },
            "intel_score": {
                "total": intel_total,
                "grade": org.intel_score_grade or "F",
                "dimensions": _safe_json_parse(org.intel_score_dimensions),
            },
            "composite": {
                "total": composite_total,
                "grade": _composite_grade([people_total, digital_total, intel_total]),
            },
        }

    total_orgs = db.query(func.count(OrganizationProfile.id)).scalar()

    people_dist = (
        db.query(OrganizationProfile.people_score_grade, func.count(OrganizationProfile.id))
        .group_by(OrganizationProfile.people_score_grade)
        .all()
    )
    digital_dist = (
        db.query(OrganizationProfile.digital_score_grade, func.count(OrganizationProfile.id))
        .group_by(OrganizationProfile.digital_score_grade)
        .all()
    )
    intel_dist = (
        db.query(OrganizationProfile.intel_score_grade, func.count(OrganizationProfile.id))
        .group_by(OrganizationProfile.intel_score_grade)
        .all()
    )

    avg_people = db.query(func.avg(OrganizationProfile.people_score)).scalar() or 0
    avg_digital = db.query(func.avg(OrganizationProfile.digital_score)).scalar() or 0
    avg_intel = db.query(func.avg(OrganizationProfile.intel_score)).scalar() or 0

    return {
        "total_organizations": total_orgs,
        "scoring_coverage": {
            "people": db.query(func.count(OrganizationProfile.id)).filter(OrganizationProfile.people_score > 0).scalar(),
            "digital": db.query(func.count(OrganizationProfile.id)).filter(OrganizationProfile.digital_score > 0).scalar(),
            "intel": db.query(func.count(OrganizationProfile.id)).filter(OrganizationProfile.intel_score > 0).scalar(),
        },
        "average_scores": {
            "people": round(avg_people, 1),
            "digital": round(avg_digital, 1),
            "intel": round(avg_intel, 1),
            "composite": round(avg_people + avg_digital + avg_intel, 1),
        },
        "grade_distribution": {
            "people": {grade: count for grade, count in sorted(people_dist)},
            "digital": {grade: count for grade, count in sorted(digital_dist)},
            "intel": {grade: count for grade, count in sorted(intel_dist)},
        },
    }


@router.get("/scores/top")
def get_top_scored_organizations(
    limit: int = 20,
    country: str = None,
    min_grade: str = None,
    db: Session = Depends(get_db),
):
    """
    评分排行榜：按三评分综合分排序
    支持按国家筛选、最低等级筛选。
    """
    composite_total = (
        func.coalesce(OrganizationProfile.people_score, 0)
        + func.coalesce(OrganizationProfile.digital_score, 0)
        + func.coalesce(OrganizationProfile.intel_score, 0)
    )
    composite_average = composite_total / 3.0

    query = db.query(OrganizationProfile).filter(OrganizationProfile.people_score.isnot(None))

    if country:
        query = query.filter(OrganizationProfile.country == country)

    if min_grade:
        thresholds = {"A": 60, "B": 45, "C": 30, "D": 15, "F": 0}
        query = query.filter(composite_average >= thresholds.get(min_grade.upper(), 0))

    results = query.order_by(composite_total.desc(), OrganizationProfile.name.asc()).limit(limit).all()

    return {
        "total": len(results),
        "organizations": [
            {
                "id": org.id,
                "name": org.name,
                "country": org.country,
                "type": org.organization_type,
                "scores": {
                    "people": {"total": org.people_score or 0, "grade": org.people_score_grade or "F"},
                    "digital": {"total": org.digital_score or 0, "grade": org.digital_score_grade or "F"},
                    "intel": {"total": org.intel_score or 0, "grade": org.intel_score_grade or "F"},
                },
                "composite": {
                    "total": (org.people_score or 0) + (org.digital_score or 0) + (org.intel_score or 0),
                    "grade": _composite_grade([
                        org.people_score or 0,
                        org.digital_score or 0,
                        org.intel_score or 0,
                    ]),
                },
                "website": org.official_website,
            }
            for org in results
        ],
    }


def _safe_json_parse(raw_value: str | None) -> dict:
    """安全解析 JSON 字符串，同时兼容历史 str(dict) 格式。"""
    if not raw_value:
        return {}
    try:
        parsed = json.loads(raw_value)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        try:
            import ast

            parsed = ast.literal_eval(raw_value)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}


def _composite_grade(scores: list[int]) -> str:
    """三评分综合等级。"""
    average_score = sum(scores) / max(len(scores), 1)
    if average_score >= 60:
        return "A"
    if average_score >= 45:
        return "B"
    if average_score >= 30:
        return "C"
    if average_score >= 15:
        return "D"
    return "F"
