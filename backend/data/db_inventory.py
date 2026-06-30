"""
CIO 数据库全景盘点 — 2026-06-28
运行方式：cd backend && python data/db_inventory.py
"""

import os
import sys
from pathlib import Path

from sqlalchemy import create_engine, text

script_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.dirname(script_dir)
os.chdir(backend_dir)
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from config import settings


DATABASE_URL = settings.DATABASE_URL
db_path = DATABASE_URL.replace("+aiosqlite", "").replace("sqlite:///", "")
db_path = str(Path(db_path).resolve())
engine = create_engine(f"sqlite:///{Path(db_path).as_posix()}", echo=False)


def count_table(conn, table):
    try:
        result = conn.execute(text(f"SELECT COUNT(*) FROM {table}"))
        return result.scalar()
    except Exception:
        return None


def print_rows(conn, query: str, formatter):
    try:
        result = conn.execute(text(query))
        for row in result:
            print(formatter(row))
    except Exception as exc:
        print(f"  查询失败: {exc}")


with engine.connect() as conn:
    print("=" * 60)
    print("CIO 数据库全景盘点")
    print("=" * 60)
    print(f"数据库路径: {db_path}")

    print("\n📊 核心表行数:")
    tables = [
        "intelligence_items",
        "organization_profiles",
        "sources",
        "rss_sources",
        "conversations",
        "messages",
        "bookmarks",
        "missions",
        "knowledge_entities",
        "pages",
        "organization_types",
        "theological_positions",
        "scale_levels",
        "ai_maturity_levels",
        "collaboration_preferences",
        "organization_ontology_tags",
        "investors",
        "funding_rounds",
        "investments",
        "tasks",
        "user_profiles",
        "user_feedbacks",
    ]

    for table in tables:
        count = count_table(conn, table)
        status = f"{count:,}" if count is not None else "表不存在"
        print(f"  {table:40s} {status}")

    print("\n🌍 intelligence_items 按 scope 分布:")
    print_rows(
        conn,
        "SELECT scope, COUNT(*) FROM intelligence_items GROUP BY scope ORDER BY COUNT(*) DESC",
        lambda row: f"  {(row[0] or 'NULL'):15s} {row[1]:,}",
    )

    print("\n🏳️ intelligence_items 按 country 分布（前20）:")
    print_rows(
        conn,
        "SELECT country, COUNT(*) FROM intelligence_items WHERE country IS NOT NULL GROUP BY country ORDER BY COUNT(*) DESC LIMIT 20",
        lambda row: f"  {(row[0] or 'NULL'):25s} {row[1]:,}",
    )

    print("\n📡 intelligence_items 按 source_name 分布（前15）:")
    print_rows(
        conn,
        "SELECT source_name, COUNT(*) FROM intelligence_items GROUP BY source_name ORDER BY COUNT(*) DESC LIMIT 15",
        lambda row: f"  {(row[0] or 'NULL'):30s} {row[1]:,}",
    )

    print("\n🏢 organization_profiles 按 country 分布:")
    print_rows(
        conn,
        "SELECT country, COUNT(*) FROM organization_profiles GROUP BY country ORDER BY COUNT(*) DESC",
        lambda row: f"  {(row[0] or 'NULL'):25s} {row[1]:,}",
    )

    print("\n📋 organization_profiles 完整列表:")
    print_rows(
        conn,
        "SELECT name, country, official_website, source_name FROM organization_profiles ORDER BY country, name",
        lambda row: f"  {str(row[0] or ''):35s} {str(row[1] or ''):15s} {str(row[2] or '无官网'):30s} [{str(row[3] or '')}]",
    )

    print("\n🏷️ Ontology标签覆盖:")
    try:
        tagged_org_count = conn.execute(
            text("SELECT COUNT(DISTINCT organization_id) FROM organization_ontology_tags")
        ).scalar()
        print(f"  已打标签的机构数: {tagged_org_count}")
        print_rows(
            conn,
            "SELECT tag_type, COUNT(*) FROM organization_ontology_tags GROUP BY tag_type ORDER BY COUNT(*) DESC",
            lambda row: f"  {str(row[0]):25s} {row[1]:,} 条",
        )
    except Exception as exc:
        print(f"  查询失败: {exc}")

    print("\n💰 投资机构:")
    investor_count = count_table(conn, "investors")
    print(f"  总数: {investor_count}")
    print_rows(
        conn,
        "SELECT country, COUNT(*) FROM investors GROUP BY country ORDER BY COUNT(*) DESC LIMIT 10",
        lambda row: f"  {(row[0] or 'NULL'):25s} {row[1]:,}",
    )

    print("\n📈 融资轮次:")
    funding_count = count_table(conn, "funding_rounds")
    print(f"  总数: {funding_count}")

    print("\n📚 ARDA数据检查:")
    try:
        arda_count = conn.execute(
            text("SELECT COUNT(*) FROM intelligence_items WHERE source_name = 'ARDA'")
        ).scalar()
        print(f"  source_name='ARDA' 的记录: {arda_count}")
        global_count = conn.execute(
            text("SELECT COUNT(*) FROM intelligence_items WHERE scope = 'global'")
        ).scalar()
        print(f"  scope='global' 的记录: {global_count}")
        country_profile_count = conn.execute(
            text("SELECT COUNT(*) FROM intelligence_items WHERE entity_type = 'country_profile'")
        ).scalar()
        print(f"  entity_type='country_profile': {country_profile_count}")
    except Exception as exc:
        print(f"  查询失败: {exc}")

    print("\n🕐 数据新鲜度:")
    try:
        latest = conn.execute(text("SELECT MAX(ingested_at) FROM intelligence_items")).scalar()
        print(f"  最新情报入库时间: {latest}")
    except Exception as exc:
        print(f"  查询失败: {exc}")

    print("\n" + "=" * 60)
    print("盘点完成")
    print("=" * 60)
