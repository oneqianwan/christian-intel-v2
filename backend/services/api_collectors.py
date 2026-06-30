"""
API采集器：NewsAPI / ScrapingBee / YouTube Data API
"""

import os
import re
import uuid
from datetime import datetime, timedelta

import httpx

from models.database import IntelligenceItem, RSSSource, SessionLocal, Source
from services.api_config_service import get_api_key


NEWSAPI_URL = "https://newsapi.org/v2/everything"
SCRAPINGBEE_URL = "https://app.scrapingbee.com/api/v1"
YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
_LAST_API_RUN_FILE = os.path.join(os.path.dirname(__file__), ".last_api_run")


def _should_run_api_collectors(cooldown_minutes: int = 30) -> bool:
    try:
        if not os.path.exists(_LAST_API_RUN_FILE):
            return True
        with open(_LAST_API_RUN_FILE, "r", encoding="utf-8") as handle:
            last_run = datetime.fromisoformat(handle.read().strip())
        return datetime.utcnow() - last_run >= timedelta(minutes=cooldown_minutes)
    except Exception:
        return True


def _mark_api_run() -> None:
    try:
        with open(_LAST_API_RUN_FILE, "w", encoding="utf-8") as handle:
            handle.write(datetime.utcnow().isoformat())
    except Exception:
        pass


def _get_or_create_api_source(
    db,
    *,
    url: str,
    name: str,
    source_type: str = "website",
    trust_level: str = "medium",
) -> Source:
    source = db.query(Source).filter(Source.url == url).first()
    if source:
        if source.scope != "global":
            source.scope = "global"
        if source.country != "全球":
            source.country = "全球"
        source.is_active = True
        db.commit()
        return source

    source = Source(
        id=str(uuid.uuid4()),
        name=name,
        url=url,
        type=source_type,
        country="全球",
        scope="global",
        trust_level=trust_level,
        is_active=True,
        created_at=datetime.utcnow(),
    )
    db.add(source)
    db.commit()
    return source


def _item_exists(db, source_url: str) -> bool:
    return db.query(IntelligenceItem).filter(IntelligenceItem.source_url == source_url).first() is not None


def _upsert_snapshot_item(
    db,
    *,
    source: Source,
    source_url: str,
    title: str,
    content: str,
    entity_name: str,
    entity_type: str,
    category: str,
    confidence: float,
) -> int:
    existing = db.query(IntelligenceItem).filter(IntelligenceItem.source_url == source_url).first()
    if existing:
        existing.title = title[:300]
        existing.content = content[:2000]
        existing.entity_name = entity_name
        existing.entity_type = entity_type
        existing.country = "全球"
        existing.category = category
        existing.source_name = source.name
        existing.ingested_at = datetime.utcnow()
        existing.confidence = confidence
        existing.scope = "global"
        db.commit()
        return 0

    db.add(
        IntelligenceItem(
            id=str(uuid.uuid4()),
            source_id=source.id,
            title=title[:300],
            content=content[:2000],
            entity_name=entity_name,
            entity_type=entity_type,
            country="全球",
            category=category,
            source_url=source_url,
            source_name=source.name,
            published_at=None,
            ingested_at=datetime.utcnow(),
            confidence=confidence,
            scope="global",
        )
    )
    db.commit()
    return 1


class NewsAPICollector:
    KEYWORDS = [
        "Christianity",
        "Christian church",
        "evangelical",
        "Vatican",
        "Pope Francis",
        "persecution Christians",
        "missionary",
        "religious freedom",
        "Lausanne",
        "World Evangelical Alliance",
    ]
    NEWSAPI_BACKUP_SOURCES = {
        "newsapi:lausanne": {
            "name": "洛桑运动 (Lausanne)",
            "keywords": ["Lausanne Movement", "Lausanne Congress"],
        },
        "newsapi:open_doors": {
            "name": "敞开的门 (Open Doors)",
            "keywords": ["Open Doors", "persecuted Christians"],
        },
        "newsapi:cbn": {
            "name": "CBN News",
            "keywords": ["CBN News", "Christian Broadcasting Network"],
        },
        "newsapi:world_vision": {
            "name": "世界宣明会 (World Vision)",
            "keywords": ["World Vision", "Christian humanitarian"],
        },
    }

    def __init__(self, db):
        self.db = db
        self.api_key = get_api_key(db, "newsapi")
        self.source = _get_or_create_api_source(
            db,
            url=NEWSAPI_URL,
            name="NewsAPI",
            source_type="news_page",
            trust_level="medium",
        )

    def _collect_keyword(self, keyword: str, *, label: str, limit_per_keyword: int) -> int:
        params = {
            "apiKey": self.api_key,
            "q": keyword,
            "language": "en",
            "sortBy": "publishedAt",
            "from": (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d"),
            "pageSize": limit_per_keyword,
        }
        resp = httpx.get(NEWSAPI_URL, params=params, timeout=20)
        data = resp.json()
        if data.get("status") != "ok":
            return 0

        added = 0
        for article in data.get("articles", []):
            url = article.get("url") or ""
            if not url or _item_exists(self.db, url):
                continue

            published_at = None
            date_text = article.get("publishedAt") or ""
            if date_text:
                try:
                    published_at = datetime.fromisoformat(date_text.replace("Z", "+00:00")).replace(tzinfo=None)
                except Exception:
                    published_at = None

            self.db.add(
                IntelligenceItem(
                    id=str(uuid.uuid4()),
                    source_id=self.source.id,
                    title=(article.get("title") or "")[:300],
                    content=((article.get("description") or "")[:2000]),
                    entity_name=label,
                    entity_type="news_topic",
                    country="全球",
                    category="api_news",
                    source_url=url,
                    source_name=f"NewsAPI / {(article.get('source') or {}).get('name', label)}",
                    published_at=published_at,
                    ingested_at=datetime.utcnow(),
                    confidence=0.76,
                    scope="global",
                )
            )
            added += 1

        self.db.commit()
        return added

    def collect_newsapi_backup(self, limit_per_keyword: int = 2) -> int:
        total = 0
        inactive_rss_sources = (
            self.db.query(RSSSource)
            .filter(RSSSource.is_active == False)
            .filter(RSSSource.category.ilike("newsapi:%"))
            .all()
        )

        for rss_source in inactive_rss_sources:
            config = self.NEWSAPI_BACKUP_SOURCES.get(rss_source.category or "", {})
            keywords = config.get("keywords") or []
            source_label = config.get("name") or rss_source.name

            source_total = 0
            for keyword in keywords:
                try:
                    source_total += self._collect_keyword(
                        keyword,
                        label=source_label,
                        limit_per_keyword=limit_per_keyword,
                    )
                except Exception as exc:
                    print(f"NewsAPI Backup {source_label} / {keyword}: {exc}")
            print(f"NewsAPI Backup {source_label}: +{source_total}")
            total += source_total

        return total

    def collect(self, limit_per_keyword: int = 3) -> int:
        if not self.api_key:
            return 0

        total = 0
        for keyword in self.KEYWORDS[:5]:
            try:
                total += self._collect_keyword(
                    keyword,
                    label=keyword,
                    limit_per_keyword=limit_per_keyword,
                )
            except Exception as exc:
                print(f"NewsAPI {keyword} error: {exc}")
        total += self.collect_newsapi_backup(limit_per_keyword=2)
        return total


class ScrapingBeeCollector:
    TARGETS = [
        {"name": "WEA", "url": "https://worldea.org"},
        {"name": "Lausanne", "url": "https://lausanne.org"},
        {"name": "Open Doors", "url": "https://www.opendoors.org"},
        {"name": "Barna Group", "url": "https://www.barna.com"},
        {"name": "VOM", "url": "https://www.persecution.com"},
    ]

    def __init__(self, db):
        self.db = db
        self.api_key = get_api_key(db, "scrapingbee")
        self.source = _get_or_create_api_source(
            db,
            url=SCRAPINGBEE_URL,
            name="ScrapingBee API",
            source_type="website",
            trust_level="high",
        )

    def collect(self) -> int:
        if not self.api_key:
            return 0

        total = 0
        for target in self.TARGETS:
            try:
                params = {
                    "api_key": self.api_key,
                    "url": target["url"],
                    "render_js": "true",
                    "premium_proxy": "true",
                }
                resp = httpx.get(SCRAPINGBEE_URL, params=params, timeout=40)
                if resp.status_code != 200:
                    continue

                text_content = re.sub(r"<[^>]+>", " ", resp.text)
                text_content = re.sub(r"\s+", " ", text_content).strip()[:2000]
                added = _upsert_snapshot_item(
                    self.db,
                    source=self.source,
                    source_url=target["url"],
                    title=f"{target['name']} 官网更新",
                    content=text_content,
                    entity_name=target["name"],
                    entity_type="organization",
                    category="api_scrape",
                    confidence=0.7,
                )
                total += added
                print(f"ScrapingBee {target['name']}: OK")
            except Exception as exc:
                print(f"ScrapingBee {target['name']}: {exc}")
        return total


class YouTubeCollector:
    CHANNELS = [
        {"name": "CBN Asia", "q": "CBN Asia"},
        {"name": "The 700 Club Asia", "q": "The 700 Club Asia"},
        {"name": "Hillsong Worship", "q": "Hillsong Worship"},
        {"name": "Elevation Worship", "q": "Elevation Worship"},
        {"name": "Bethel Music", "q": "Bethel Music"},
        {"name": "Focus on the Family", "q": "Focus on the Family"},
        {"name": "Billy Graham", "q": "Billy Graham"},
    ]

    def __init__(self, db):
        self.db = db
        self.api_key = get_api_key(db, "youtube") or get_api_key(db, "google_cse")
        self.source = _get_or_create_api_source(
            db,
            url=YOUTUBE_SEARCH_URL,
            name="YouTube Data API",
            source_type="website",
            trust_level="high",
        )

    def collect(self, max_results: int = 3) -> int:
        if not self.api_key:
            return 0

        total = 0
        published_after = (datetime.utcnow() - timedelta(days=7)).replace(microsecond=0).isoformat() + "Z"
        for channel in self.CHANNELS:
            try:
                search_params = {
                    "key": self.api_key,
                    "part": "snippet",
                    "q": channel["q"],
                    "type": "channel",
                    "maxResults": 1,
                }
                search_resp = httpx.get(YOUTUBE_SEARCH_URL, params=search_params, timeout=20)
                search_data = search_resp.json()
                if "error" in search_data or not search_data.get("items"):
                    continue

                channel_id = ((search_data["items"][0].get("id") or {}).get("channelId")) or ""
                if not channel_id:
                    continue

                video_params = {
                    "key": self.api_key,
                    "part": "snippet",
                    "channelId": channel_id,
                    "order": "date",
                    "maxResults": max_results,
                    "publishedAfter": published_after,
                    "type": "video",
                }
                video_resp = httpx.get(YOUTUBE_SEARCH_URL, params=video_params, timeout=20)
                video_data = video_resp.json()
                if "error" in video_data:
                    continue

                channel_added = 0
                for item in video_data.get("items", []):
                    video_id = ((item.get("id") or {}).get("videoId")) or ""
                    if not video_id:
                        continue
                    url = f"https://youtube.com/watch?v={video_id}"
                    if _item_exists(self.db, url):
                        continue

                    snippet = item.get("snippet") or {}
                    published_at = None
                    date_text = snippet.get("publishedAt") or ""
                    if date_text:
                        try:
                            published_at = datetime.fromisoformat(date_text.replace("Z", "+00:00")).replace(tzinfo=None)
                        except Exception:
                            published_at = None

                    self.db.add(
                        IntelligenceItem(
                            id=str(uuid.uuid4()),
                            source_id=self.source.id,
                            title=(snippet.get("title") or "")[:300],
                            content=((snippet.get("description") or "")[:2000]),
                            entity_name=channel["name"],
                            entity_type="youtube_channel",
                            country="全球",
                            category="youtube_video",
                            source_url=url,
                            source_name=f"YouTube / {channel['name']}",
                            published_at=published_at,
                            ingested_at=datetime.utcnow(),
                            confidence=0.74,
                            scope="global",
                        )
                    )
                    total += 1
                    channel_added += 1
                self.db.commit()
                print(f"YouTube {channel['name']}: +{channel_added}")
            except Exception as exc:
                print(f"YouTube {channel['name']}: {exc}")
        return total


def run_all_api_collectors(force: bool = False) -> int:
    if not force and not _should_run_api_collectors(cooldown_minutes=30):
        print("[API] 冷却中，跳过本轮 API 采集")
        return 0

    print(f"=== API采集 {datetime.utcnow().strftime('%H:%M')} ===")
    total = 0
    db = SessionLocal()
    try:
        try:
            collector = NewsAPICollector(db)
            count = collector.collect()
            print(f"NewsAPI: +{count}")
            total += count
        except Exception as exc:
            print(f"NewsAPI error: {exc}")

        try:
            collector = ScrapingBeeCollector(db)
            count = collector.collect()
            print(f"ScrapingBee: +{count}")
            total += count
        except Exception as exc:
            print(f"ScrapingBee error: {exc}")

        try:
            collector = YouTubeCollector(db)
            count = collector.collect()
            print(f"YouTube: +{count}")
            total += count
        except Exception as exc:
            print(f"YouTube error: {exc}")
    finally:
        db.close()

    _mark_api_run()
    print(f"=== 完成 +{total} ===")
    return total
