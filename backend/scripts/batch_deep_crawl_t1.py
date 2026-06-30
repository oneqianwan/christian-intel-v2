#!/usr/bin/env python3
"""
T1 机构标准化深采
只处理 T1 + A/B 级 URL 的机构
"""

import json
import logging
import os
import sys
from datetime import datetime, timedelta

from sqlalchemy import or_

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models.database import OrganizationProfile, SessionLocal
from services.history_recorder import record_change
from services.structured_crawler import crawl_organization_sync

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def _count_non_empty(db, field_name: str) -> int:
    column = getattr(OrganizationProfile, field_name)
    return (
        db.query(OrganizationProfile)
        .filter(
            OrganizationProfile.priority_tier == "T1",
            column.isnot(None),
            column != "",
        )
        .count()
    )


def _get_existing_fail_count(org: OrganizationProfile) -> int:
    try:
        parsed = json.loads(org.pages_crawled) if org.pages_crawled else None
    except Exception:
        parsed = None

    if isinstance(parsed, dict):
        failure_meta = parsed.get("crawl_failure") or parsed
        if isinstance(failure_meta, dict):
            try:
                return int(failure_meta.get("fail_count") or 0)
            except Exception:
                return 0
    return 0


def _record_failure(org: OrganizationProfile, errors: list[str]):
    failed_at = datetime.utcnow()
    fail_count = _get_existing_fail_count(org) + 1
    failure_payload = {
        "crawl_failure": {
            "failed_at": failed_at.isoformat(),
            "errors": [str(error)[:300] for error in (errors or ["unknown error"])][:5],
            "fail_count": fail_count,
        }
    }
    org.deep_crawl_status = "failed"
    org.last_deep_crawl = failed_at
    org.pages_crawled = json.dumps(failure_payload, ensure_ascii=False)
    if hasattr(org, "notes"):
        existing_notes = getattr(org, "notes") or ""
        error_info = json.dumps(failure_payload["crawl_failure"], ensure_ascii=False)
        setattr(
            org,
            "notes",
            f"{existing_notes}\n[CRAWL_FAIL {failed_at.strftime('%Y-%m-%d')}] {error_info[:200]}".strip(),
        )


def batch_deep_crawl_t1(batch_size: int = 20):
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        seven_days_ago = now - timedelta(days=7)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        orgs = (
            db.query(OrganizationProfile)
            .filter(
                OrganizationProfile.priority_tier == "T1",
                OrganizationProfile.official_website.isnot(None),
                OrganizationProfile.official_website != "",
                OrganizationProfile.url_tier.in_(["A", "B"]),
                or_(
                    OrganizationProfile.deep_crawl_status.is_(None),
                    OrganizationProfile.deep_crawl_status != "failed",
                    OrganizationProfile.last_deep_crawl.is_(None),
                    OrganizationProfile.last_deep_crawl < seven_days_ago,
                ),
            )
            .filter(
                (OrganizationProfile.last_deep_crawl == None)
                | (OrganizationProfile.deep_crawl_status == "failed")
                | (OrganizationProfile.deep_crawl_status == "partial")
                | (OrganizationProfile.last_deep_crawl < month_start)
            )
            .order_by(
                (OrganizationProfile.url_tier == "A").desc(),
                (OrganizationProfile.source_name == "manual_seed").desc(),
                OrganizationProfile.last_deep_crawl.asc().nullsfirst(),
                OrganizationProfile.id.asc(),
            )
            .limit(batch_size)
            .all()
        )

        logger.info(f"找到 {len(orgs)} 家待深采的 T1 机构")
        skipped_recent_failed = (
            db.query(OrganizationProfile)
            .filter(
                OrganizationProfile.priority_tier == "T1",
                OrganizationProfile.official_website.isnot(None),
                OrganizationProfile.official_website != "",
                OrganizationProfile.url_tier.in_(["A", "B"]),
                OrganizationProfile.deep_crawl_status == "failed",
                OrganizationProfile.last_deep_crawl.isnot(None),
                OrganizationProfile.last_deep_crawl >= seven_days_ago,
            )
            .count()
        )
        logger.info(f"最近7天失败并已跳过: {skipped_recent_failed}")

        total_t1 = db.query(OrganizationProfile).filter(OrganizationProfile.priority_tier == "T1").count()
        before_deep = (
            db.query(OrganizationProfile)
            .filter(
                OrganizationProfile.priority_tier == "T1",
                OrganizationProfile.last_deep_crawl.isnot(None),
            )
            .count()
        )
        before_about = _count_non_empty(db, "description")
        before_mission = _count_non_empty(db, "mission_statement")
        before_email = _count_non_empty(db, "contact_email")

        success = 0
        partial = 0
        failed = 0

        for org in orgs:
            logger.info(f"\n处理: {org.name} ({org.official_website})")
            try:
                report = crawl_organization_sync(
                    org.id,
                    org.name,
                    org.official_website or "",
                    max_total_time=30,
                )
                if report.has_errors and not report.pages_crawled:
                    logger.warning(f"  [ERR] 完全失败: {report.error_log}")
                    _record_failure(org, report.error_log)
                    db.commit()
                    failed += 1
                    continue

                updates = report.to_db_updates()
                tracked_old_values = {
                    field: getattr(org, field, None)
                    for field in [
                        "description",
                        "about_text",
                        "mission_statement",
                        "contact_email",
                        "leader_name",
                        "leader_title",
                        "has_programs",
                        "has_leadership_page",
                    ]
                    if hasattr(org, field)
                }
                for field, value in updates.items():
                    if hasattr(org, field):
                        setattr(org, field, value)

                org.pages_crawled = json.dumps(
                    [{"type": page.page_type, "url": page.url} for page in report.pages_crawled],
                    ensure_ascii=False,
                )
                org.last_deep_crawl = datetime.utcnow()
                org.last_website_crawl = datetime.utcnow()
                org.deep_crawl_status = "success" if not report.has_errors else "partial"

                for field_name, old_value in tracked_old_values.items():
                    if field_name in updates:
                        record_change(
                            org_id=org.id,
                            field_name=field_name,
                            old_value=old_value,
                            new_value=getattr(org, field_name, None),
                            source="deep_crawl",
                            changed_by="system",
                            db=db,
                        )

                db.commit()
                if report.has_errors:
                    partial += 1
                else:
                    success += 1
                logger.info(f"  [OK] 成功采集 {len(report.pages_crawled)} 个页面")
                if report.error_log:
                    logger.info(f"  [WARN] 部分错误: {report.error_log[:3]}")
            except Exception as exc:
                logger.error(f"  [ERR] 异常: {exc}")
                db.rollback()
                _record_failure(org, [str(exc)])
                db.commit()
                failed += 1

        after_deep = (
            db.query(OrganizationProfile)
            .filter(
                OrganizationProfile.priority_tier == "T1",
                OrganizationProfile.last_deep_crawl.isnot(None),
            )
            .count()
        )
        after_about = _count_non_empty(db, "description")
        after_mission = _count_non_empty(db, "mission_statement")
        after_email = _count_non_empty(db, "contact_email")

        logger.info("\n" + "=" * 50)
        logger.info("T1 深采报告")
        logger.info("=" * 50)
        logger.info(f"处理: {len(orgs)}")
        logger.info(f"成功: {success}")
        logger.info(f"部分成功: {partial}")
        logger.info(f"失败: {failed}")
        logger.info(f"最近7天失败跳过: {skipped_recent_failed}")
        logger.info(f"T1 深采覆盖: {after_deep}/{total_t1} ({(after_deep / total_t1 * 100) if total_t1 else 0:.1f}%)")
        logger.info(f"T1 About: {before_about} -> {after_about} (delta {after_about - before_about:+d})")
        logger.info(f"T1 Mission: {before_mission} -> {after_mission} (delta {after_mission - before_mission:+d})")
        logger.info(f"T1 Email: {before_email} -> {after_email} (delta {after_email - before_email:+d})")
    except Exception as exc:
        logger.error(f"批量深采失败: {exc}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="T1 机构标准化深采")
    parser.add_argument("--batch-size", type=int, default=20)
    args = parser.parse_args()
    batch_deep_crawl_t1(args.batch_size)
