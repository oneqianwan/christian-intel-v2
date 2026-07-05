"""
全球 RSS 源注册 - 阶段7 Day1
"""

import sys

sys.path.insert(0, r"C:\Users\baiwan\christian-intel-v2\backend")

from models.database import Base, RSSSource, engine, SessionLocal


# RSS采集配置
RSS_DEFAULT_LIMIT = 30  # 每源默认采集条数，避免新库重灌时只恢复到快照级别


RSS_SOURCES = [
    {
        "name": "今日基督教 (Christianity Today)",
        "rss_url": "https://www.christianitytoday.com/rss",
        "country": "美国",
        "language": "en",
        "category": "news",
        "scope": "global",
    },
    {
        "name": "基督邮报 (Christian Post)",
        "rss_url": "https://www.christianpost.com/rss",
        "country": "美国",
        "language": "en",
        "category": "news",
        "scope": "global",
    },
    {
        "name": "宗教新闻通讯社 (RNS)",
        "rss_url": "https://religionnews.com/feed",
        "country": "美国",
        "language": "en",
        "category": "news",
        "scope": "global",
    },
    {
        "name": "Barna Group",
        "rss_url": "https://www.barna.com/feed",
        "country": "美国",
        "language": "en",
        "category": "research",
        "scope": "global",
    },
    {
        "name": "世界福音联盟 (WEA)",
        "rss_url": "https://worldea.org/feed",
        "country": "全球",
        "language": "en",
        "category": "organization",
        "scope": "global",
    },
    {
        "name": "洛桑运动 (Lausanne)",
        "rss_url": "https://lausanne.org/feed",
        "country": "全球",
        "language": "en",
        "category": "movement",
        "scope": "global",
    },
    {
        "name": "敞开的门 (Open Doors)",
        "rss_url": "https://www.opendoors.org/feed",
        "country": "全球",
        "language": "en",
        "category": "persecution",
        "scope": "global",
    },
    {
        "name": "CBN News",
        "rss_url": "https://www1.cbn.com/rss",
        "country": "美国",
        "language": "en",
        "category": "news",
        "scope": "global",
    },
    {
        "name": "福音联盟 (TGC)",
        "rss_url": "https://www.thegospelcoalition.org/feed",
        "country": "美国",
        "language": "en",
        "category": "theology",
        "scope": "global",
    },
    {
        "name": "世界宣明会 (World Vision)",
        "rss_url": "https://www.wvi.org/rss",
        "country": "全球",
        "language": "en",
        "category": "ngo",
        "scope": "global",
    },
    {
        "name": "Veritas PH",
        "rss_url": "https://www.veritasph.net/feed/",
        "country": "菲律宾",
        "language": "en",
        "category": "news",
        "scope": "country",
    },
    {
        "name": "CBN Asia",
        "rss_url": "https://www.cbnasia.org/feed/",
        "country": "菲律宾",
        "language": "en",
        "category": "media",
        "scope": "country",
    },
    {
        "name": "CBN Asia Blog Media",
        "rss_url": "https://www.cbnasia.org/blog/category/media/feed/",
        "country": "菲律宾",
        "language": "en",
        "category": "media",
        "scope": "country",
    },
]


def seed_rss_sources() -> None:
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    created = 0
    updated = 0

    try:
        for src in RSS_SOURCES:
            existing = session.query(RSSSource).filter_by(rss_url=src["rss_url"]).first()
            if existing:
                existing.name = src["name"]
                existing.country = src["country"]
                existing.language = src["language"]
                existing.category = src["category"]
                existing.scope = src["scope"]
                existing.is_active = True
                updated += 1
                continue

            session.add(RSSSource(**src))
            created += 1

        session.commit()
        count = session.query(RSSSource).count()
        print(f"✅ RSS源注册完成！新增: {created} 个，更新: {updated} 个，总计: {count} 个")
    except Exception as exc:
        session.rollback()
        print(f"❌ RSS源注册失败: {exc}")
        raise
    finally:
        session.close()


if __name__ == "__main__":
    seed_rss_sources()
