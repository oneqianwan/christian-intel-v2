from __future__ import annotations

from datetime import datetime
from difflib import SequenceMatcher
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from models.database import IntelligenceItem
from services.scoring import confidence_assessment, freshness_assessment


def _normalize_text(value: str) -> str:
    return " ".join((value or "").strip().lower().split())


def _map_source_type(raw_type: str, source_name: str) -> str:
    normalized_type = (raw_type or "").strip().lower()
    normalized_name = (source_name or "").strip().lower()

    if any(token in normalized_name for token in ["official", "官网", "official site"]):
        return "official"
    if normalized_type in {"website"}:
        return "official"
    if normalized_type in {"data_archive", "database"}:
        return "database"
    if normalized_type in {"telegram_channel", "social"}:
        return "social"
    return "media"


def is_duplicate(db: Session, url: str, title: str) -> bool:
    """按 URL、标题精确匹配和高相似度标题做去重。"""
    normalized_title = _normalize_text(title)

    if url:
        existing = db.query(IntelligenceItem).filter(IntelligenceItem.source_url == url).first()
        if existing:
            return True

    if normalized_title:
        exact_title = db.query(IntelligenceItem).filter(IntelligenceItem.title == title).first()
        if exact_title:
            return True

        recent_candidates = (
            db.query(IntelligenceItem)
            .filter(IntelligenceItem.title.isnot(None))
            .order_by(IntelligenceItem.ingested_at.desc())
            .limit(200)
            .all()
        )
        for candidate in recent_candidates:
            candidate_title = _normalize_text(candidate.title or "")
            if not candidate_title:
                continue
            if SequenceMatcher(None, normalized_title, candidate_title).ratio() >= 0.94:
                return True

    return False


def assess_item_quality(item_data: Dict[str, Any]) -> Dict[str, Any]:
    source_name = item_data.get("source_name", "未知")
    source_type = _map_source_type(item_data.get("source_type", ""), source_name)
    data_timestamp = item_data.get("published_at") or item_data.get("ingested_at") or datetime.utcnow()

    conf = confidence_assessment(
        sources=[{"name": source_name, "type": source_type, "url": item_data.get("source_url", "")}],
        data_timestamp=data_timestamp,
        cross_validation_count=0,
        contradictions=0,
    )
    fresh = freshness_assessment(data_timestamp)
    return {"confidence": conf, "freshness": fresh}


def should_save(item_data: Dict[str, Any], assessment: Optional[Dict[str, Any]] = None) -> bool:
    """低质量、黑名单和明显异常内容直接过滤。"""
    assessment = assessment or assess_item_quality(item_data)
    conf = assessment["confidence"]

    title = (item_data.get("title") or "").strip()
    content = (item_data.get("content") or "").strip()
    source_name = item_data.get("source_name", "")

    if not title or len(title) < 8:
        return False

    blocked_titles = {"home", "redirecting...", "page not found", "404", "untitled"}
    lowered_title = title.lower()
    if lowered_title in blocked_titles or "page not found" in lowered_title or "404" in lowered_title:
        return False

    blacklist = {"spam_site", "known_fake"}
    if source_name in blacklist:
        return False

    if conf["score"] < 15:
        return False

    # 空内容仅允许新闻列表摘要类场景继续保存。
    category = (item_data.get("category") or "").lower()
    if not content and category not in {"news_article", "youtube_video", "telegram_channel"}:
        return False

    return True
