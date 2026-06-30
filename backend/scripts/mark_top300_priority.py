#!/usr/bin/env python3
"""
标记机构优先级 Tier
T1 = Top 300（最重要，100%覆盖目标）
T2 = 第301-800家（50%覆盖目标）
T3 = 剩余（后续补充）
"""

import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models.database import OrganizationProfile, SessionLocal

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

T1_COUNTRIES = {
    "United States",
    "United Kingdom",
    "Philippines",
    "South Korea",
    "Australia",
    "Canada",
    "India",
    "Singapore",
    "Germany",
    "France",
    "Brazil",
    "Nigeria",
}


def _score_org(org: OrganizationProfile) -> int:
    score = 0
    if (org.official_website or "").strip():
        score += 5
    if (org.leader_name or "").strip():
        score += 3
    if (org.description or "").strip() or (org.about_text or "").strip():
        score += 2
    if org.ai_maturity_score is not None:
        score += 2 + max(org.ai_maturity_score, 0)
    if org.digital_score is not None:
        score += 1 + max(org.digital_score, 0)
    if org.last_website_crawl is not None:
        score += 2
    if org.country in T1_COUNTRIES:
        score += 4
    if (org.source_name or "").strip().lower() in {"manual_seed", "auto_extracted_verified", "wiki_extracted"}:
        score += 2
    if (org.url_tier or "").strip().upper() == "A":
        score += 3
    elif (org.url_tier or "").strip().upper() == "B":
        score += 2
    elif (org.url_tier or "").strip().upper() == "C":
        score += 1
    return score


def auto_mark_priority():
    """自动标记优先级。"""
    db = SessionLocal()
    try:
        total = db.query(OrganizationProfile).count()
        logger.info(f"总机构数: {total}")

        db.query(OrganizationProfile).update({"priority_tier": "T3"}, synchronize_session=False)
        db.commit()
        logger.info("全部标记为 T3")

        orgs = db.query(OrganizationProfile).all()
        ranked = sorted(
            orgs,
            key=lambda org: (
                _score_org(org),
                1 if org.country in T1_COUNTRIES else 0,
                org.updated_at.isoformat() if org.updated_at else "",
                org.id or "",
            ),
            reverse=True,
        )

        t1_candidates = ranked[:300]
        t1_ids = {org.id for org in t1_candidates}
        for org in t1_candidates:
            org.priority_tier = "T1"
        db.commit()
        logger.info(f"T1 标记: {len(t1_candidates)} 家")

        t2_candidates = [org for org in ranked if org.id not in t1_ids][:500]
        for org in t2_candidates:
            org.priority_tier = "T2"
        db.commit()
        logger.info(f"T2 标记: {len(t2_candidates)} 家")

        t1_count = db.query(OrganizationProfile).filter(OrganizationProfile.priority_tier == "T1").count()
        t2_count = db.query(OrganizationProfile).filter(OrganizationProfile.priority_tier == "T2").count()
        t3_count = db.query(OrganizationProfile).filter(OrganizationProfile.priority_tier == "T3").count()

        logger.info("=" * 40)
        logger.info("优先级分布")
        logger.info("=" * 40)
        logger.info(f"T1 (Top 300): {t1_count}")
        logger.info(f"T2 (Next 500): {t2_count}")
        logger.info(f"T3 (Remaining): {t3_count}")
    except Exception as exc:
        logger.error(f"标记失败: {exc}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    auto_mark_priority()
