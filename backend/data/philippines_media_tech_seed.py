"""
菲律宾 Christian media / tech intelligence seed

目标：
- 为 Phase 51 提供可检索的菲律宾基督教媒体/科技机构基础情报
- 来源限定在 Website / News / RSS / YouTube
"""

import os
import sys
import uuid
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models.database import IntelligenceItem, Source, SessionLocal, init_db


SEED_ITEMS = [
    {
        "title": "CBN Asia 官方主页显示其在菲律宾通过媒体、祷告与跨文化宣教开展事工",
        "content": (
            "CBN Asia 是菲律宾的 Christian media 机构，官网展示 The 700 Club Asia、Superbook、"
            "digital media、prayer counseling 与 cross-cultural missions，适合作为 Philippines Christian media seed。"
        ),
        "entity_name": "CBN Asia",
        "country": "菲律宾",
        "category": "website_profile",
        "source_name": "Website crawler / CBN Asia",
        "source_url": "https://www.cbnasia.org/home/",
        "source_type": "website",
    },
    {
        "title": "FEBC Philippines 作为 Christian radio 网络在菲律宾运营多站点广播",
        "content": (
            "FEBC Philippines 被官方介绍为 Gospel Media Ministry，在菲律宾运营多座 AM/FM 电台并覆盖多种本地语言，"
            "可归入 Philippines Christian radio / church media 机构。"
        ),
        "entity_name": "FEBC Philippines",
        "country": "菲律宾",
        "category": "website_profile",
        "source_name": "Website crawler / FEBC Philippines",
        "source_url": "https://anniversary.febc.ph/about-febc/",
        "source_type": "website",
    },
    {
        "title": "Veritas PH 是菲律宾教会新闻与数字媒体平台",
        "content": (
            "Veritas PH 首页与介绍页将其描述为菲律宾 online church media 与 Radio Veritas 数字平台，"
            "持续发布 Philippines Christian news，并带有社交媒体与直播入口。"
        ),
        "entity_name": "Veritas PH",
        "country": "菲律宾",
        "category": "news",
        "source_name": "News / Veritas PH",
        "source_url": "https://www.veritasph.net/",
        "source_type": "website",
    },
    {
        "title": "CBN Asia 媒体栏目可通过 RSS/Feed 追踪菲律宾基督教媒体动态",
        "content": (
            "CBN Asia 的 media 分类页持续发布菲律宾 Christian media 更新，包括节目、文章与 ministry content，"
            "适合作为 Philippines Christian news / RSS seed。"
        ),
        "entity_name": "CBN Asia",
        "country": "菲律宾",
        "category": "rss_media",
        "source_name": "RSS / CBN Asia",
        "source_url": "https://www.cbnasia.org/blog/category/media/",
        "source_type": "rss",
    },
    {
        "title": "Philippine Bible Society 推出 BibliApp Pilipinas 作为菲律宾 Bible app",
        "content": (
            "BibliApp Pilipinas 由 Philippine Bible Society 推出，主打 Philippine languages Bible reading、audio、notes、"
            "reading tracker 与 prayer request，可视为 Philippines Christian app / Bible app Philippines。"
        ),
        "entity_name": "Philippine Bible Society",
        "country": "菲律宾",
        "category": "faithtech_bible",
        "source_name": "Website crawler / Philippine Bible Society",
        "source_url": "https://bible.org.ph/bibliapp-pilipinas/",
        "source_type": "website",
    },
    {
        "title": "CBN Asia YouTube 频道持续输出菲律宾 Christian media 视频内容",
        "content": (
            "CBN Asia 官方 YouTube 频道说明其通过 media、prayer counseling、humanitarian aid 与 missions 触达菲律宾与亚洲，"
            "可作为 Philippines church media / YouTube seed。"
        ),
        "entity_name": "CBN Asia",
        "country": "菲律宾",
        "category": "youtube_video",
        "source_name": "YouTube / CBN Asia",
        "source_url": "https://www.youtube.com/@CBNAsia",
        "source_type": "website",
    },
    {
        "title": "FEBC PH YouTube 频道补充菲律宾 Christian radio 的视频与节目分发",
        "content": (
            "FEBC PH 官方 YouTube 频道发布 The FEBC Report 与电台相关内容，是 Philippines Christian radio 与 online church platform 的补充分发入口。"
        ),
        "entity_name": "FEBC Philippines",
        "country": "菲律宾",
        "category": "youtube_video",
        "source_name": "YouTube / FEBC PH",
        "source_url": "https://www.youtube.com/@febcphilippines",
        "source_type": "website",
    },
    {
        "title": "Veritas PH YouTube 频道承接菲律宾基督教新闻与直播节目",
        "content": (
            "Veritas PH 官方 YouTube 频道承接菲律宾 Christian news、homily 与 daily live stream，"
            "是 Philippines Christian news Philippines / YouTube seed。"
        ),
        "entity_name": "Veritas PH",
        "country": "菲律宾",
        "category": "youtube_video",
        "source_name": "YouTube / Veritas PH",
        "source_url": "https://www.youtube.com/@veritasphdotnet",
        "source_type": "website",
    },
]


def _ensure_source(db, *, name: str, url: str, source_type: str) -> Source:
    source = db.query(Source).filter(Source.url == url).first()
    if source:
        source.name = name
        source.type = source_type
        source.country = "菲律宾"
        source.scope = "country"
        source.is_active = True
        return source

    source = Source(
        id=str(uuid.uuid4()),
        name=name,
        url=url,
        type=source_type,
        country="菲律宾",
        scope="country",
        trust_level="medium",
        is_active=True,
        created_at=datetime.utcnow(),
    )
    db.add(source)
    db.flush()
    return source


def seed_philippines_media_tech() -> None:
    init_db()
    db = SessionLocal()
    created = 0
    updated = 0

    try:
        for item in SEED_ITEMS:
            source = _ensure_source(
                db,
                name=item["source_name"],
                url=item["source_url"],
                source_type=item.get("source_type") or "website",
            )
            existing = db.query(IntelligenceItem).filter(IntelligenceItem.source_url == item["source_url"]).first()
            if existing:
                existing.title = item["title"]
                existing.content = item["content"]
                existing.entity_name = item["entity_name"]
                existing.entity_type = "organization"
                existing.country = item["country"]
                existing.category = item["category"]
                existing.source_name = item["source_name"]
                existing.source_id = source.id
                existing.scope = "country"
                existing.confidence = 0.82
                existing.ingested_at = datetime.utcnow()
                updated += 1
                continue

            db.add(
                IntelligenceItem(
                    id=str(uuid.uuid4()),
                    page_id=None,
                    source_id=source.id,
                    title=item["title"],
                    content=item["content"],
                    entity_name=item["entity_name"],
                    entity_type="organization",
                    country=item["country"],
                    category=item["category"],
                    source_url=item["source_url"],
                    source_name=item["source_name"],
                    published_at=datetime.utcnow(),
                    ingested_at=datetime.utcnow(),
                    confidence=0.82,
                    scope="country",
                )
            )
            created += 1

        db.commit()
        print(f"✅ 菲律宾 media/tech intelligence seed 完成，新增 {created} 条，更新 {updated} 条")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed_philippines_media_tech()
