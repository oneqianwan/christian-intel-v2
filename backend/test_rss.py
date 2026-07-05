import os
import sys
sys.path.insert(0, os.path.dirname(__file__))

from models.database import get_db, Source, IntelligenceItem
from services.rss_scanner import fetch_rss

# Development/Test entry. Not production collection path.
db = next(get_db())

# 获取Christianity Today RSS源
source = db.query(Source).filter(Source.type == "rss").first()
if not source:
    print("数据库中没有RSS源，请先运行来源种子发现")
    sys.exit(1)

print(f"找到RSS源: {source.name} - {source.url}")
result = fetch_rss(source, db)
print(f"\n扫描结果: {result}")

# 验证入库
items = db.query(IntelligenceItem).filter(IntelligenceItem.source_id == source.id).all()
print(f"\n入库情报条目数: {len(items)}")
for item in items[:5]:
    print(f"  - [{item.published_at}] {item.title[:60]}")
    print(f"    URL: {item.source_url[:80]}")
