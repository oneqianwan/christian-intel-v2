from __future__ import annotations

from datetime import datetime
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import or_
from sqlalchemy.orm import Session

from models.database import IntelligenceItem, KnowledgeEntity, OrganizationProfile, RelationEdge
from models.watch_alert import WatchTarget


def _normalize_string(value):
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    trimmed = value.strip()
    return trimmed or None


def _normalize_url(value):
    normalized = _normalize_string(value)
    if not normalized:
        return None
    parsed = urlsplit(normalized)
    if parsed.scheme not in {"http", "https"}:
        return None
    path = parsed.path or ""
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, parsed.query, ""))


def _normalize_number(value):
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else value
    if isinstance(value, str):
        trimmed = value.strip()
        if not trimmed:
            return None
        try:
            parsed = float(trimmed)
        except ValueError:
            return None
        return int(parsed) if parsed.is_integer() else parsed
    return None


def _sorted_unique(values):
    normalized = [value for value in values if value]
    return sorted(set(normalized))


def _intelligence_query(db: Session, watch_target: WatchTarget, org: OrganizationProfile | None, entity: KnowledgeEntity | None):
    names = set()
    if org:
        for candidate in [org.name, org.official_name, org.short_name, org.english_name]:
            normalized = _normalize_string(candidate)
            if normalized:
                names.add(normalized.lower())
    if entity:
        normalized_name = _normalize_string(entity.name)
        if normalized_name:
            names.add(normalized_name.lower())

    conditions = []
    if names:
        conditions.extend(IntelligenceItem.entity_name.ilike(name) for name in names)

    query = db.query(IntelligenceItem)
    if conditions:
        query = query.filter(or_(*conditions))
    else:
        query = query.filter(IntelligenceItem.id == "__watch_no_match__")

    return query.order_by(IntelligenceItem.published_at.desc().nullslast(), IntelligenceItem.ingested_at.desc())


def _build_relation_keys(relations):
    keys = []
    for relation in relations:
        source_type = _normalize_string(relation.source_type) or "organization"
        target_type = _normalize_string(relation.target_type) or "organization"
        source_id = _normalize_string(relation.source_id)
        target_id = _normalize_string(relation.target_id)
        relation_type = _normalize_string(relation.relation_type)
        source_item = _normalize_string(relation.source_item)
        key = f"{source_type}:{source_id}|{relation_type}|{target_type}:{target_id}"
        if source_item:
            key = f"{key}|{source_item}"
        keys.append(key)
    return _sorted_unique(keys)


def _classify_news_urls(items):
    urls = []
    for item in items:
        url = _normalize_url(item.source_url)
        if not url:
            continue
        category = (_normalize_string(item.category) or "").lower()
        if "news" in category or "article" in category:
            urls.append(url)
    return _sorted_unique(urls)


def _classify_video_urls(items):
    urls = []
    for item in items:
        url = _normalize_url(item.source_url)
        if not url:
            continue
        category = (_normalize_string(item.category) or "").lower()
        if "video" in category or "youtube" in category or "youtu.be" in url or "youtube.com" in url:
            urls.append(url)
    return _sorted_unique(urls)


def _is_news_item(item) -> bool:
    category = (_normalize_string(item.category) or "").lower()
    url = _normalize_url(item.source_url) or ""
    return "news" in category or "article" in category or "/news" in url


def _is_video_item(item) -> bool:
    category = (_normalize_string(item.category) or "").lower()
    url = _normalize_url(item.source_url) or ""
    return "video" in category or "youtube" in category or "youtu.be" in url or "youtube.com" in url


def _load_entity_context(db: Session, watch_target: WatchTarget):
    org = None
    entity = None
    if watch_target.entity_type == "organization":
        org = db.query(OrganizationProfile).filter(OrganizationProfile.id == watch_target.entity_id).first()
        entity = (
            db.query(KnowledgeEntity)
            .filter(KnowledgeEntity.id == watch_target.entity_id, KnowledgeEntity.entity_type == "organization")
            .first()
        )
        if not org and not entity:
            return None, None
    else:
        entity = db.query(KnowledgeEntity).filter(KnowledgeEntity.id == watch_target.entity_id).first()
        if not entity:
            return None, None
    return org, entity


def build_watch_snapshot(db: Session, watch_target: WatchTarget) -> dict:
    org, entity = _load_entity_context(db, watch_target)
    if not org and not entity:
        raise LookupError("WATCH_TARGET_ENTITY_NOT_FOUND")

    items = _intelligence_query(db, watch_target, org, entity).all()
    relations = (
        db.query(RelationEdge)
        .filter(or_(RelationEdge.source_id == watch_target.entity_id, RelationEdge.target_id == watch_target.entity_id))
        .order_by(RelationEdge.created_at.desc())
        .all()
    )

    name = None
    leader_name = None
    official_website = None
    email = None
    phone = None
    people_score = None
    digital_score = None
    intel_score = None

    if org:
        name = _normalize_string(org.name) or _normalize_string(org.official_name) or _normalize_string(org.english_name)
        leader_name = _normalize_string(org.leader_name)
        official_website = _normalize_url(org.official_website)
        email = _normalize_string(org.contact_email)
        phone = _normalize_string(org.phone_public)
        people_score = _normalize_number(org.people_score)
        digital_score = _normalize_number(org.digital_score)
        intel_score = _normalize_number(org.intel_score)
    elif entity:
        name = _normalize_string(entity.name)
        official_website = _normalize_url(entity.source_url)

    composite_score = sum(value for value in [people_score, digital_score, intel_score] if value is not None)
    if people_score is None and digital_score is None and intel_score is None:
        composite_score = None

    intelligence_ids = _sorted_unique(
        _normalize_string(item.id)
        for item in items
        if not _is_news_item(item) and not _is_video_item(item)
    )
    news_urls = _classify_news_urls(items)
    video_urls = _classify_video_urls(items)
    relation_keys = _build_relation_keys(relations)

    fields = {
        "name": name,
        "leader_name": leader_name,
        "official_website": official_website,
        "email": email,
        "phone": phone,
        "people_score": people_score,
        "digital_score": digital_score,
        "intel_score": intel_score,
        "composite_score": composite_score,
    }

    return {
        "snapshot_version": 1,
        "entity_id": watch_target.entity_id,
        "entity_type": watch_target.entity_type,
        "captured_at": datetime.utcnow().isoformat(),
        "fields": fields,
        "intelligence_ids": intelligence_ids,
        "news_urls": news_urls,
        "video_urls": video_urls,
        "relation_keys": relation_keys,
    }
