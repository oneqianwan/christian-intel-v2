"""
修复4个失败源：停用 RSS，标记为需 NewsAPI 补采
"""

import sys

sys.path.insert(0, r"C:\Users\baiwan\christian-intel-v2\backend")

from models.database import RSSSource, SessionLocal


FAILED_SOURCES_FIX = [
    {
        "name": "洛桑运动 (Lausanne)",
        "backup_code": "newsapi:lausanne",
        "rss_urls": ["https://lausanne.org/feed", "https://lausanne.org/feed/"],
        "newsapi_keywords": ["Lausanne Movement", "Lausanne Congress"],
        "reason": "RSS返回HTML页面，无可用feed",
    },
    {
        "name": "敞开的门 (Open Doors)",
        "backup_code": "newsapi:open_doors",
        "rss_urls": [
            "https://www.opendoors.org/feed/",
            "https://www.opendoors.org/feed",
            "https://www.opendoors.org/en-US/feed/",
            "https://www.opendoors.org/en-US/feed",
        ],
        "newsapi_keywords": ["Open Doors", "persecuted Christians", "Christian persecution"],
        "reason": "RSS路径404",
    },
    {
        "name": "CBN News",
        "backup_code": "newsapi:cbn",
        "rss_urls": ["https://www1.cbn.com/rss/", "https://www1.cbn.com/rss"],
        "newsapi_keywords": ["CBN News", "Christian Broadcasting Network"],
        "reason": "RSS重定向到HTML登录页",
    },
    {
        "name": "世界宣明会 (World Vision)",
        "backup_code": "newsapi:world_vision",
        "rss_urls": ["https://www.wvi.org/rss", "https://www.wvi.org/rss/"],
        "newsapi_keywords": ["World Vision", "Christian humanitarian"],
        "reason": "RSS重定向到搜索页",
    },
]


def fix_failed_sources() -> None:
    session = SessionLocal()

    try:
        for fix in FAILED_SOURCES_FIX:
            src = (
                session.query(RSSSource)
                .filter(RSSSource.name == fix["name"])
                .first()
            )

            if not src:
                src = (
                    session.query(RSSSource)
                    .filter(RSSSource.rss_url.in_(fix["rss_urls"]))
                    .first()
                )

            if src:
                src.is_active = False
                src.category = fix["backup_code"]
                print(f"✅ {fix['name']}: RSS已停用，改为NewsAPI补采")
                print(f"   关键词: {fix['newsapi_keywords']}")
                print(f"   原因: {fix['reason']}")
            else:
                print(f"⚠️ {fix['name']}: 数据库中未找到，跳过")

        session.commit()

        active = session.query(RSSSource).filter(RSSSource.is_active == True).count()
        inactive = session.query(RSSSource).filter(RSSSource.is_active == False).count()
        print(f"\nRSS源状态统计: 活跃{active}个, 停用{inactive}个")
    except Exception as exc:
        session.rollback()
        print(f"❌ 修复失败: {exc}")
        raise
    finally:
        session.close()


if __name__ == "__main__":
    print("=" * 50)
    print("修复4个失败RSS源")
    print("=" * 50)
    fix_failed_sources()
