import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
sys.stdout.reconfigure(encoding="utf-8")

import time

from models.database import get_db, init_db
from services.arda_collector import fetch_arda_country, store_arda_data

init_db()
db = next(get_db())


def batch_collect(start: int, end: int):
    results = {"success": 0, "failed": 0, "skipped": 0}

    for code_num in range(start, end + 1):
        code = f"{code_num}c"

        arda_data = fetch_arda_country(code)

        if arda_data.get("status") == "success" and arda_data.get("country_name"):
            result = store_arda_data(db, code, arda_data)
            if result["status"] in ["created", "updated"]:
                results["success"] += 1
                print(f"✅ [{code}] {arda_data['country_name']}")
            else:
                results["skipped"] += 1
        else:
            results["failed"] += 1

        time.sleep(3)

    return results


print("\n=== ARDA批量采集：第3批 (101-150) ===")
r3 = batch_collect(101, 150)
print(f"成功: {r3['success']} | 失败: {r3['failed']} | 跳过: {r3['skipped']}")

print("\n=== ARDA批量采集：第4批 (151-200) ===")
r4 = batch_collect(151, 200)
print(f"成功: {r4['success']} | 失败: {r4['failed']} | 跳过: {r4['skipped']}")

print("\n=== ARDA批量采集：第5批 (201-251) ===")
r5 = batch_collect(201, 251)
print(f"成功: {r5['success']} | 失败: {r5['failed']} | 跳过: {r5['skipped']}")

from models.database import KnowledgeEntity

total = db.query(KnowledgeEntity).filter(KnowledgeEntity.entity_type == "country_profile").count()
print("\n=== ARDA采集完成 ===")
print(f"国家概况实体总数: {total}")

db.close()
