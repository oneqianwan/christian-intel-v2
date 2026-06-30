"""
官网URL清洗脚本 — Phase 1 Day 2
清洗 organization_profiles 中的无效官网 URL
"""

import os
import re
import sys

from sqlalchemy import text

script_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.dirname(script_dir)
os.chdir(backend_dir)
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from models.database import SessionLocal


INVALID_PATTERNS = [
    r"^/us-religion/",
    r"^/world-religion/",
    r"^/history/",
    r"^/search",
    r"^/wiki/",
    r"^$",
]

SUSPICIOUS_DOMAINS = [
    "thearda.com",
    "pewresearch.org",
    "wikipedia.org",
]


def is_invalid_url(url: str) -> tuple[bool, str]:
    """判断 URL 是否无效，返回 (是否无效, 原因)。"""
    if not url or not isinstance(url, str):
        return True, "空值"

    candidate = url.strip()
    if not candidate.startswith(("http://", "https://")):
        return True, "非http(s)协议"

    lowered = candidate.lower()
    for pattern in INVALID_PATTERNS:
        if re.search(pattern, lowered):
            return True, f"匹配无效模式: {pattern}"

    for domain in SUSPICIOUS_DOMAINS:
        if domain in lowered:
            return True, f"可疑域名: {domain}"

    return False, ""


def clean_urls():
    db = SessionLocal()
    try:
        print("=" * 60)
        print("官网URL清洗")
        print("=" * 60)

        rows = db.execute(
            text(
                """
                SELECT id, name, official_website, source_name, country
                FROM organization_profiles
                WHERE official_website IS NOT NULL
                  AND official_website != ''
                ORDER BY id
                """
            )
        ).fetchall()
        print(f"\n待检查: {len(rows)} 条URL")

        deleted = 0
        kept = 0
        for org_id, name, url, source, country in rows:
            invalid, reason = is_invalid_url(url)
            if invalid:
                db.execute(
                    text("UPDATE organization_profiles SET official_website = NULL WHERE id = :id"),
                    {"id": org_id},
                )
                print(f"  [DEL] 清空 [{source}] {name}: {str(url)[:60]}")
                print(f"        原因: {reason}")
                deleted += 1
            else:
                kept += 1

        db.commit()

        print(f"\n{'=' * 60}")
        print(f"清洗结果: 清空 {deleted} 条 / 保留 {kept} 条")
        print(f"{'=' * 60}")

        valid_count = db.execute(
            text("SELECT COUNT(*) FROM organization_profiles WHERE official_website IS NOT NULL AND official_website != ''")
        ).scalar()
        print(f"\n清洗后有效官网URL: {valid_count} 条")

        print("\n按来源分布:")
        rows = db.execute(
            text(
                """
                SELECT source_name, COUNT(*)
                FROM organization_profiles
                WHERE official_website IS NOT NULL
                  AND official_website != ''
                GROUP BY source_name
                ORDER BY COUNT(*) DESC
                """
            )
        ).fetchall()
        for source_name, count in rows:
            print(f"  {str(source_name or 'NULL'):30s} {count}")

        return {"deleted": deleted, "kept": kept, "valid": valid_count}
    finally:
        db.close()


if __name__ == "__main__":
    result = clean_urls()
    print(f"\n结果: {result}")
