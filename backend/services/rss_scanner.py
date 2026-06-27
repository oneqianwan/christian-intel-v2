import uuid
import feedparser
from datetime import datetime
from typing import Dict, Any
import httpx
from sqlalchemy.orm import Session
from models.database import Source, IntelligenceItem
from services.ingestion_guard import is_duplicate, assess_item_quality, should_save


def fetch_rss(source: Source, db: Session) -> Dict[str, Any]:
    """扫描单个RSS源，返回新条目数"""
    print(f"开始扫描RSS源: {source.name} ({source.url})")

    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        resp = httpx.get(source.url, headers=headers, timeout=15, follow_redirects=True, verify=False)
        resp.raise_for_status()
        parsed = feedparser.parse(resp.text)
    except Exception as e:
        return {"status": "failed", "error": f"解析失败: {str(e)}", "new_items": 0}

    is_global_scope = (getattr(source, "scope", "country") or "country") == "global"

    # 菲律宾关键词过滤（标题或摘要匹配）
    PH_KEYWORDS = [
        "philippines", "filipino", "philippine", "菲律宾",
        "manila", "davao", "cebu", "metro manila",
        "pcec", "victory church", "victory philippines", "ccf",
        "evangelical council philippines", "born again philippines",
        "christian conference philippines", "cbn asia",
        "jesus is lord", "church of god philippines",
        "united methodist philippines", "baptist philippines"
    ]
    ASIA_KEYWORDS = [
        "asia", "asian", "africa", "europe", "latin america",
        "middle east", "global", "international", "missionary",
        "evangelical", "christian", "church", "bible", "theology"
    ]

    new_count = 0
    skipped = 0
    max_entries_per_feed = 20 if is_global_scope else (250 if source.country == "尼日利亚" else 50)
    entries_to_process = parsed.entries[:max_entries_per_feed]
    skipped_old = max(len(parsed.entries) - len(entries_to_process), 0)

    for entry in entries_to_process:
        title = entry.get("title", "")
        summary = entry.get("summary", "")
        link = entry.get("link", "")
        published = entry.get("published", "")

        if is_duplicate(db, link, title):
            continue

        item_data = {
            "title": title[:300],
            "content": summary[:2000],
            "source_url": link,
            "source_name": source.name,
            "source_type": source.type,
            "category": "rss_news",
            "published_at": _parse_date(published),
            "ingested_at": datetime.utcnow(),
        }
        assessment = assess_item_quality(item_data)
        if not should_save(item_data, assessment):
            continue

        # 写入情报条目
        item = IntelligenceItem(
            id=str(uuid.uuid4()),
            source_id=source.id,
            title=item_data["title"],
            content=item_data["content"],
            source_url=item_data["source_url"],
            source_name=source.name,
            country="全球" if is_global_scope else ("菲律宾" if source.type == "rss_global" else source.country),
            category="rss_news",
            published_at=item_data["published_at"],
            ingested_at=item_data["ingested_at"],
            confidence=assessment["confidence"]["score"] / 100.0,
            scope="global" if is_global_scope else "country",
        )

        # 全局RSS源采用宽松过滤：优先菲律宾，其次全球基督教动态
        if source.type == "rss_global":
            text = (title + " " + summary).lower()
            if any(kw in text for kw in PH_KEYWORDS):
                item.country = "菲律宾"
                new_count += 1
            elif any(kw in text for kw in ASIA_KEYWORDS):
                item.country = "global"
                new_count += 1
            else:
                skipped += 1
                continue
        elif is_global_scope:
            item.country = "全球"
            new_count += 1
        else:
            new_count += 1

        db.add(item)

    db.commit()

    # 更新来源最后扫描时间
    source.last_scan_at = datetime.utcnow()
    source.success_rate = 1.0 if new_count > 0 else 0.5
    db.commit()

    return {
        "status": "success",
        "source": source.name,
        "scanned": len(parsed.entries),
        "processed": len(entries_to_process),
        "new_items": new_count,
        "skipped": skipped + skipped_old
    }


def _parse_date(date_str: str) -> datetime:
    """尝试解析RSS日期"""
    try:
        from email.utils import parsedate_to_datetime
        parsed = parsedate_to_datetime(date_str)
        if parsed.tzinfo is not None:
            return parsed.astimezone().replace(tzinfo=None)
        return parsed
    except:
        return datetime.utcnow()
