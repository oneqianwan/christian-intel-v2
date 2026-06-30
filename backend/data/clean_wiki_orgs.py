"""
Wikipedia机构噪声清洗脚本 — Phase 2 Day 2
删除泛称/概念性条目，保留具体机构
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


DELETE_PATTERNS = [
    r"^Cathedrals?$",
    r"^Church$",
    r"^Mission$",
    r"^Baptist$",
    r"^Catholic$",
    r"^Protestant$",
    r"^Evangelical$",
    r"^Pentecostal$",
    r"^Orthodox$",
    r"^Anglican$",
    r"^Methodist$",
    r"^Presbyterian$",
    r"^Lutheran$",
    r"^Christianity$",
    r"^Christiandenominations$",
    r"^Church-State",
    r"^Christian\s+denominations$",
    r"^Religion\s+in\s+",
    r"^Christianity\s+in\s+",
    r"^History\s+of\s+",
    r"^List\s+of\s+",
    r"^Outline\s+of\s+",
    r"^Portal:",
    r"^Template:",
    r"^Category:",
    r"^File:",
]


def is_noise(name: str) -> tuple[bool, str]:
    if not name or not isinstance(name, str):
        return True, "空值"

    candidate = name.strip()
    if len(candidate) < 3:
        return True, "名称太短"

    for pattern in DELETE_PATTERNS:
        if re.match(pattern, candidate, re.IGNORECASE):
            return True, f"匹配噪声模式: {pattern}"

    if re.match(r"^in\s+", candidate, re.IGNORECASE):
        return True, "以'in XXX'开头，无具体名称"

    org_indicators = [
        "church",
        "ministry",
        "mission",
        "fellowship",
        "association",
        "council",
        "convention",
        "conference",
        "assembly",
        "union",
        "society",
        "organization",
        "institute",
        "network",
        "alliance",
        "foundation",
        "diocese",
        "archdiocese",
        "college",
        "seminary",
        "university",
        "federation",
        "coalition",
        "center",
        "centre",
        "bible",
        "gospel",
        "salvation",
        "apostolic",
        "pentecostal",
        "evangelical",
        "charismatic",
        "reformed",
        "baptist",
        "methodist",
        "presbyterian",
        "lutheran",
        "anglican",
        "catholic",
        "orthodox",
        "congregation",
        "tabernacle",
        "chapel",
        "cathedral",
        "denomination",
    ]

    lowered = candidate.lower()
    has_indicator = any(ind in lowered for ind in org_indicators)

    if not has_indicator and len(candidate) < 15:
        return True, "无机构指示词且名称短"

    return False, ""


def clean_wiki_orgs():
    db = SessionLocal()
    try:
        print("=" * 60)
        print("Wikipedia机构噪声清洗")
        print("=" * 60)

        rows = db.execute(
            text(
                """
                SELECT id, name, country
                FROM organization_profiles
                WHERE source_name = 'wiki_extracted'
                ORDER BY id
                """
            )
        ).fetchall()

        print(f"\n待清洗: {len(rows)} 条wiki_extracted")

        deleted = 0
        kept = 0

        for org_id, name, country in rows:
            noise, reason = is_noise(name)
            if noise:
                db.execute(
                    text("DELETE FROM organization_ontology_tags WHERE organization_id = :id"),
                    {"id": org_id},
                )
                db.execute(
                    text("DELETE FROM organization_profiles WHERE id = :id"),
                    {"id": org_id},
                )
                display_name = (name or "")[:60]
                display_country = country or "UNKNOWN"
                print(f"  [DEL] {display_country:15s} | {display_name} | {reason}")
                deleted += 1
            else:
                kept += 1

        db.commit()

        print(f"\n{'=' * 60}")
        print(f"清洗结果: 删除 {deleted} / 保留 {kept} / 总计 {len(rows)}")
        print(f"{'=' * 60}")

        total = db.execute(text("SELECT COUNT(*) FROM organization_profiles")).scalar()
        print(f"\n清洗后总机构数: {total}")

        return {"deleted": deleted, "kept": kept, "remaining": total}
    finally:
        db.close()


if __name__ == "__main__":
    result = clean_wiki_orgs()
    print(f"\n结果: {result}")
