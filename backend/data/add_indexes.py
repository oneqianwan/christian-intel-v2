"""
SQLite索引优化脚本 — 第一阶段 Day1
执行方式：cd backend && python data/add_indexes.py
"""

import os
import sys
from pathlib import Path

from sqlalchemy import create_engine, text


# 兼容不同启动路径
script_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.dirname(script_dir)
os.chdir(backend_dir)
sys.path.insert(0, backend_dir)

from config import settings


DATABASE_URL = settings.DATABASE_URL
db_path = DATABASE_URL.replace("+aiosqlite", "").replace("sqlite:///", "")
db_path = str(Path(db_path).resolve())

print(f"[Index] 数据库路径: {db_path}")
print(f"[Index] 数据库存在: {os.path.exists(db_path)}")

engine = create_engine(f"sqlite:///{Path(db_path).as_posix()}", echo=False)

INDEXES = [
    {
        "name": "idx_intel_scope_country",
        "table": "intelligence_items",
        "cols": "scope, country",
        "reason": "全球/国家筛选是最高频查询",
    },
    {
        "name": "idx_intel_ingested",
        "table": "intelligence_items",
        "cols": "ingested_at DESC",
        "reason": "时间排序/最新情报查询",
    },
    {
        "name": "idx_org_name_country",
        "table": "organization_profiles",
        "cols": "name, country",
        "reason": "机构名+国家联合查询",
    },
    {
        "name": "idx_entity_name",
        "table": "knowledge_entities",
        "cols": "name",
        "reason": "实体名匹配查询",
    },
]


def add_indexes():
    with engine.connect() as conn:
        result = conn.execute(text("SELECT name FROM sqlite_master WHERE type='index'"))
        existing = {row[0] for row in result}
        print(f"\n[Index] 现有索引: {len(existing)} 个")

        added = 0
        for idx in INDEXES:
            if idx["name"] in existing:
                print(f"  = {idx['name']} (已存在, 跳过)")
                continue

            sql = f"CREATE INDEX {idx['name']} ON {idx['table']}({idx['cols']})"
            try:
                conn.execute(text(sql))
                print(f"  + {idx['name']} ON {idx['table']}({idx['cols']})")
                print(f"    原因: {idx['reason']}")
                added += 1
            except Exception as exc:
                print(f"  ! {idx['name']} 失败: {exc}")

        conn.commit()

        result = conn.execute(text("SELECT name FROM sqlite_master WHERE type='index'"))
        all_indexes = [row[0] for row in result]

        print(f"\n{'=' * 50}")
        print(f"[Index] 本次新增: {added} 个")
        print(f"[Index] 总计索引: {len(all_indexes)} 个")
        print("\n验证查询计划:")

        explain = conn.execute(
            text(
                "EXPLAIN QUERY PLAN "
                "SELECT * FROM intelligence_items WHERE scope='global' AND country='菲律宾'"
            )
        )
        for row in explain:
            print(f"  {row}")

        print("\n✅ 索引优化完成")


if __name__ == "__main__":
    add_indexes()
