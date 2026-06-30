"""
RSS采集服务 - 修复版
"""

import sys
import uuid
from datetime import datetime
from email.utils import parsedate_to_datetime
from html import unescape
import re
from urllib.parse import urljoin

sys.path.insert(0, r"C:\Users\baiwan\christian-intel-v2\backend")

import feedparser
import httpx

from models.database import Base, IntelligenceItem, RSSSource, SessionLocal, Source, engine


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/xml, text/xml, application/atom+xml, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.google.com/",
}

RSS_URL_OVERRIDES = {
    "https://www.opendoors.org/feed": "https://www.opendoors.org/feed/",
    "https://www.opendoors.org/en-US/feed": "https://www.opendoors.org/feed/",
    "https://religionnews.com/feed": "https://religionnews.com/feed/",
    "https://www.thegospelcoalition.org/feed": "https://www.thegospelcoalition.org/feed/",
    "https://www.christianitytoday.com/rss": "https://www.christianitytoday.com/rss/",
    "https://www.barna.com/feed": "https://www.barna.com/feed/",
    "https://worldea.org/feed": "https://worldea.org/feed/",
    "https://www1.cbn.com/rss": "https://www1.cbn.com/rss/",
}


def _strip_html(text: str) -> str:
    clean = re.sub(r"<[^>]+>", " ", text or "")
    clean = re.sub(r"\s+", " ", unescape(clean)).strip()
    return clean


def _parse_entry_date(entry) -> datetime | None:
    if entry.get("published_parsed"):
        try:
            return datetime(*entry.published_parsed[:6])
        except Exception:
            pass

    for key in ("published", "updated", "created"):
        raw = entry.get(key)
        if not raw:
            continue
        try:
            parsed = parsedate_to_datetime(raw)
            if parsed.tzinfo is not None:
                return parsed.astimezone().replace(tzinfo=None)
            return parsed
        except Exception:
            continue
    return None


def _ensure_source(db, rss_source: RSSSource, active_url: str) -> Source:
    source = db.query(Source).filter(Source.url == active_url).first()
    source_type = "rss_global" if (rss_source.scope or "global") == "global" else "rss"

    if source:
        source.name = rss_source.name
        source.type = source_type
        source.country = rss_source.country or "全球"
        source.scope = rss_source.scope or "global"
        source.is_active = True
        return source

    legacy_source = db.query(Source).filter(Source.url == rss_source.rss_url).first()
    if legacy_source:
        legacy_source.url = active_url
        legacy_source.name = rss_source.name
        legacy_source.type = source_type
        legacy_source.country = rss_source.country or "全球"
        legacy_source.scope = rss_source.scope or "global"
        legacy_source.is_active = True
        return legacy_source

    source = Source(
        id=str(uuid.uuid4()),
        name=rss_source.name,
        url=active_url,
        type=source_type,
        country=rss_source.country or "全球",
        scope=rss_source.scope or "global",
        trust_level="medium",
        is_active=True,
        created_at=datetime.utcnow(),
    )
    db.add(source)
    db.flush()
    return source


def parse_feed_safely(content: str, url: str):
    feed = feedparser.parse(content)

    if feed.entries:
        return feed, None

    rss_links = re.findall(
        r'<link[^>]+type=["\']application/rss\+xml["\'][^>]+href=["\']([^"\']+)["\']',
        content,
        flags=re.IGNORECASE,
    )
    if rss_links:
        print(f"    在HTML中发现RSS链接: {rss_links[0]}")
        return None, rss_links[0]

    atom_links = re.findall(
        r'<link[^>]+type=["\']application/atom\+xml["\'][^>]+href=["\']([^"\']+)["\']',
        content,
        flags=re.IGNORECASE,
    )
    if atom_links:
        print(f"    在HTML中发现Atom链接: {atom_links[0]}")
        return None, atom_links[0]

    if "<html" in content.lower()[:500]:
        print("    返回的是HTML页面，不是RSS feed")
        return None, None

    snippet = content[:200].replace("\n", " ")
    print(f"    feedparser未解析到条目，原始内容前200字符: {snippet}")
    return None, None


def _request_feed(url: str):
    resp = httpx.get(
        url,
        headers=HEADERS,
        timeout=20,
        follow_redirects=True,
        verify=False,
    )
    content_type = resp.headers.get("content-type", "unknown")
    print(f"  HTTP状态: {resp.status_code}, Content-Type: {content_type}, 大小: {len(resp.text)} bytes")
    return resp


def _candidate_urls(feed_url: str) -> list[str]:
    candidates = [RSS_URL_OVERRIDES.get(feed_url, feed_url)]
    if not candidates[0].endswith("/"):
        candidates.append(f"{candidates[0]}/")
    if candidates[0].startswith("https://"):
        candidates.append(candidates[0].replace("https://", "http://"))
    if "://www." in candidates[0]:
        candidates.append(candidates[0].replace("://www.", "://"))

    unique_candidates = []
    seen = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        unique_candidates.append(candidate)
    return unique_candidates


def collect_rss(limit_per_source: int = 30):
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    total_inserted = 0
    failed_sources = []

    try:
        sources = (
            db.query(RSSSource)
            .filter(RSSSource.is_active == True)
            .order_by(RSSSource.id.asc())
            .all()
        )

        if not sources:
            print("[WARN] 未找到已激活的 RSS 源，请先运行 python data/rss_global_seed.py")
            return 0, []

        print(f"开始采集 RSS，活跃源数量: {len(sources)}")

        for rss_source in sources:
            original_url = rss_source.rss_url
            candidate_urls = _candidate_urls(original_url)
            feed_url = candidate_urls[0]
            print(f"\n采集: {rss_source.name} ({feed_url})")

            try:
                feed = None
                last_error = None
                used_url = feed_url

                for idx, candidate_url in enumerate(candidate_urls):
                    if idx > 0:
                        print(f"  尝试备选URL: {candidate_url}")
                    try:
                        resp = _request_feed(candidate_url)
                    except Exception as exc:
                        print(f"  请求异常: {exc}")
                        last_error = str(exc)
                        continue

                    used_url = str(resp.url)
                    if resp.status_code != 200:
                        last_error = f"HTTP {resp.status_code}"
                        continue

                    feed, discovered_url = parse_feed_safely(resp.text, used_url)

                    if discovered_url and not feed:
                        if not discovered_url.startswith("http"):
                            discovered_url = urljoin(used_url, discovered_url)
                        print(f"  尝试从发现的RSS链接重新抓取: {discovered_url}")
                        try:
                            resp = _request_feed(discovered_url)
                            used_url = str(resp.url)
                            if resp.status_code == 200:
                                feed, _ = parse_feed_safely(resp.text, used_url)
                        except Exception as exc:
                            print(f"  抓取发现的链接失败: {exc}")

                    if feed and feed.entries:
                        break

                if not feed or not feed.entries:
                    print("  [WARN] 未解析到条目")
                    failed_sources.append(
                        {"name": rss_source.name, "url": used_url, "error": last_error or "no entries parsed"}
                    )
                    continue

                print(f"  解析到 {len(feed.entries)} 个条目")
                mapped_source = _ensure_source(db, rss_source, used_url)

                inserted = 0
                for entry in feed.entries[: max(limit_per_source, 1)]:
                    title = (entry.get("title") or "").strip()[:300]
                    link = (entry.get("link") or "").strip()[:500]
                    summary = _strip_html(entry.get("summary") or entry.get("description") or "")[:2000]
                    published_at = _parse_entry_date(entry)

                    if not title or not link:
                        continue

                    existing = db.query(IntelligenceItem).filter(IntelligenceItem.source_url == link).first()
                    if existing:
                        continue

                    db.add(
                        IntelligenceItem(
                            id=str(uuid.uuid4()),
                            source_id=mapped_source.id,
                            title=title,
                            content=summary,
                            entity_name=title[:200],
                            entity_type="rss_news",
                            country="全球",
                            category=rss_source.category or "rss_news",
                            source_url=link,
                            source_name=rss_source.name,
                            published_at=published_at,
                            ingested_at=datetime.utcnow(),
                            confidence=0.78,
                            scope="global",
                        )
                    )
                    inserted += 1

                rss_source.last_fetched_at = datetime.utcnow()
                if used_url != rss_source.rss_url:
                    print(f"  更新RSS源URL: {rss_source.rss_url} -> {used_url}")
                    rss_source.rss_url = used_url
                mapped_source.last_scan_at = rss_source.last_fetched_at
                mapped_source.success_rate = 1.0 if inserted > 0 else 0.8
                db.commit()

                total_inserted += inserted
                print(f"  [OK] 新增: {inserted} 条")
            except Exception as exc:
                db.rollback()
                print(f"  [ERR] 异常: {exc}")
                failed_sources.append({"name": rss_source.name, "url": feed_url, "error": str(exc)})

        print(f"\n{'=' * 50}")
        print(f"RSS采集完成: 新增 {total_inserted} 条")
        print(f"失败源: {len(failed_sources)} 个")
        for failed in failed_sources:
            print(f"  - {failed['name']}: {failed['error']} ({failed['url']})")

        return total_inserted, failed_sources
    finally:
        db.close()


if __name__ == "__main__":
    collect_rss()
