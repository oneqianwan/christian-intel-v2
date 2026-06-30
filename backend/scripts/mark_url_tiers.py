#!/usr/bin/env python3
"""
URL 可信度分级标记
A级 = 官方确认(99%): manual_seed / auto_extracted_verified / 高度域名匹配
B级 = 可信(90%): wiki_extracted / wikipedia / 常见官方组织域名
C级 = 猜测(70%): 域名猜测 / LLM推断 / 其他弱来源
NULL = 待补充: 无官网 URL
"""

import logging
import os
import re
import sys
from urllib.parse import urlparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import or_

from models.database import OrganizationProfile, SessionLocal

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def _normalize_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


def _extract_domain_core(url: str) -> str:
    raw = (url or "").strip().strip("`").strip()
    if not raw:
        return ""
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    host = (parsed.netloc or parsed.path).lower().replace("www.", "")
    core = host.split("/")[0].split(":")[0].split(".")[0]
    return _normalize_text(core)


def _acronym_match(org_name: str, domain_core: str) -> bool:
    words = re.findall(r"[A-Za-z]+", org_name or "")
    if len(words) < 2:
        return False
    acronym = "".join(word[0] for word in words if word and word[0].isalpha()).lower()
    return len(acronym) >= 2 and acronym == domain_core.lower()


def _is_strong_domain_match(org_name: str, url: str) -> bool:
    org_name_clean = _normalize_text(org_name)
    domain_core = _extract_domain_core(url)
    if not org_name_clean or not domain_core:
        return False

    if org_name_clean in domain_core or domain_core in org_name_clean:
        return True
    return _acronym_match(org_name, domain_core)


def mark_url_tiers():
    db = SessionLocal()
    try:
        orgs_with_url = (
            db.query(OrganizationProfile)
            .filter(OrganizationProfile.official_website.isnot(None), OrganizationProfile.official_website != "")
            .all()
        )

        for org in orgs_with_url:
            url = (org.official_website or "").lower()
            source = (org.source_name or "").lower().strip()
            current_tier = (org.url_tier or "").upper().strip()

            if current_tier == "A":
                continue

            is_a_tier = False
            if source in {"manual_seed", "auto_extracted_verified", "manual_verified"}:
                is_a_tier = True
            elif _is_strong_domain_match(org.name or "", url):
                is_a_tier = True

            if is_a_tier:
                org.url_tier = "A"
                continue

            if source in {"wiki_extracted", "wikipedia", "wikidata"}:
                org.url_tier = "B"
                continue

            if any(tld in url for tld in [".org", ".edu", ".foundation", ".church"]):
                org.url_tier = "B"
                continue

            org.url_tier = "C"

        db.commit()

        db.query(OrganizationProfile).filter(
            or_(OrganizationProfile.official_website.is_(None), OrganizationProfile.official_website == "")
        ).update({"url_tier": None}, synchronize_session=False)
        db.commit()

        a_total = db.query(OrganizationProfile).filter(OrganizationProfile.url_tier == "A").count()
        b_total = db.query(OrganizationProfile).filter(OrganizationProfile.url_tier == "B").count()
        c_total = db.query(OrganizationProfile).filter(OrganizationProfile.url_tier == "C").count()
        null_total = db.query(OrganizationProfile).filter(OrganizationProfile.url_tier.is_(None)).count()

        logger.info("=" * 40)
        logger.info("URL分层结果")
        logger.info("=" * 40)
        logger.info(f"A级 (官方确认): {a_total}")
        logger.info(f"B级 (可信): {b_total}")
        logger.info(f"C级 (猜测): {c_total}")
        logger.info(f"NULL (待补充): {null_total}")
        logger.info(f"总计: {a_total + b_total + c_total + null_total}")
    except Exception as exc:
        logger.error(f"标记失败: {exc}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    mark_url_tiers()
