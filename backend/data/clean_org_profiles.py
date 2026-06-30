"""
organization_profiles 数据清洗 — Step 1
清理 auto_extractor 灌入的噪声机构，建立白名单/黑名单机制
"""

import os
import sys

from sqlalchemy import text

script_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.dirname(script_dir)
os.chdir(backend_dir)
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from models.database import SessionLocal


DELETE_LIST = [
    "Pope Leo XIV",
    "Brigham Young University",
    "University of Oklahoma",
    "North American Jesuit colleges",
    "Northern Arabia Church",
    "Apostolic Vicariate of Northern Arabia",
]

SUSPECT_BUT_KEEP = [
    "SSPX (Society of Saint Pius X)",
    "Religious Liberty Commission",
    "Archdiocese of Palo",
]

PH_SEED = [
    "Victory Philippines",
    "Christ's Commission Fellowship (CCF)",
    "Jesus Is Lord Church (JIL)",
    "Philippine Council of Evangelical Churches (PCEC)",
    "CBN Asia",
]

INTL_KEEP = [
    "World Vision International",
    "YWAM (Youth With A Mission)",
    "Christianity Today",
    "Cru",
    "Biola University",
]


def clean_database():
    db = SessionLocal()

    print("=" * 60)
    print("organization_profiles 数据清洗")
    print("=" * 60)

    all_rows = db.execute(
        text(
            "SELECT id, name, country, source_name FROM organization_profiles "
            "ORDER BY country, name"
        )
    ).fetchall()

    print(f"\n清洗前: {len(all_rows)} 家机构")
    print("-" * 60)

    deleted = 0
    kept = 0
    tagged_suspect = 0

    for row in all_rows:
        org_id, name, country, source_name = row
        action = ""

        if name in DELETE_LIST:
            db.execute(
                text("DELETE FROM organization_ontology_tags WHERE organization_id = :id"),
                {"id": org_id},
            )
            db.execute(
                text("DELETE FROM organization_profiles WHERE id = :id"),
                {"id": org_id},
            )
            action = "❌ 删除（噪声）"
            deleted += 1
        else:
            kept += 1
            if name in SUSPECT_BUT_KEEP:
                db.execute(
                    text(
                        "UPDATE organization_profiles "
                        "SET source_name = 'auto_extracted_suspect' "
                        "WHERE id = :id"
                    ),
                    {"id": org_id},
                )
                action = "⚠️ 保留但标记为 suspect"
                tagged_suspect += 1
            elif name in PH_SEED:
                db.execute(
                    text(
                        "UPDATE organization_profiles "
                        "SET source_name = 'manual_seed' "
                        "WHERE id = :id"
                    ),
                    {"id": org_id},
                )
                action = "⭐ 保留（菲律宾种子）"
            elif name in INTL_KEEP:
                db.execute(
                    text(
                        "UPDATE organization_profiles "
                        "SET source_name = 'auto_extracted_verified' "
                        "WHERE id = :id"
                    ),
                    {"id": org_id},
                )
                action = "✅ 保留（国际认可）"
            else:
                action = "✅ 保留"

        print(f"  {name:40s} {action}")

    db.commit()

    print(f"\n{'=' * 60}")
    print(f"清洗结果: 删除 {deleted} 家 / 保留 {kept} 家 / 标记suspect {tagged_suspect} 家")
    print(f"{'=' * 60}")

    count = db.execute(text("SELECT COUNT(*) FROM organization_profiles")).scalar()
    print(f"\n清洗后总机构数: {count}")

    print("\n按来源分布:")
    for row in db.execute(
        text(
            "SELECT source_name, COUNT(*) FROM organization_profiles "
            "GROUP BY source_name ORDER BY COUNT(*) DESC"
        )
    ):
        print(f"  {(row[0] or 'NULL'):30s} {row[1]}")

    print("\n按国家分布:")
    for row in db.execute(
        text(
            "SELECT country, COUNT(*) FROM organization_profiles "
            "GROUP BY country ORDER BY COUNT(*) DESC"
        )
    ):
        print(f"  {(row[0] or 'NULL'):25s} {row[1]}")

    db.close()
    return {"deleted": deleted, "kept": kept, "remaining": count}


if __name__ == "__main__":
    result = clean_database()
    print(f"\n结果: {result}")
