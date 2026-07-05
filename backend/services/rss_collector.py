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

ACTIVE_FEEDS = {
    "今日基督教 (Christianity Today)": "https://www.christianitytoday.com/rss/",
    "基督邮报 (Christian Post)": "https://www.christianpost.com/rss",
    "宗教新闻通讯社 (RNS)": "https://religionnews.com/feed/",
    "Barna Group": "https://www.barna.com/feed/",
    "世界福音联盟 (WEA)": "https://worldea.org/feed/",
    "福音联盟 (TGC)": "http://www.thegospelcoalition.org/feed/",
    # ===== 扩源 Sprint 2025-07-01：新增 7 个源 =====
    "天主教通讯社 (CNA)": "https://www.catholicnewsagency.com/rss/news.xml",
    "CBN新闻 (CBN News)": "https://www1.cbn.com/rss/cbnnews.xml",
    "基督教头条 (Christian Headlines)": "https://www.christianheadlines.com/rss",
    "世界杂志 (World Magazine)": "https://wng.org/rss.xml",
    "Relevant杂志 (Relevant)": "https://relevantmagazine.com/feed/",
    "Premier基督教新闻 (Premier UK)": "https://www.premierchristiannews.com/rss.xml",
    "福音聚焦 (Evangelical Focus)": "https://evangelicalfocus.com/rss",
}

CHRISTIAN_KEYWORDS = [
    "christian", "church", "jesus", "gospel", "bible", "faith",
    "ministry", "pastor", "missionary", "denomination", "evangelical",
    "catholic", "orthodox", "protestant", "baptist", "methodist",
    "pentecostal", "presbyterian", "anglican", "lutheran",
    "worship", "prayer", "theology", "christ", "salvation",
    "christianity", "disciple", "congregation", "parish", "diocese",
    "archbishop", "bishop", "pope", "vatican", "sermon",
    "revival", "reformation", "saint", "apostle", "prophet",
]

CORE_CHRISTIAN_KEYWORDS = [
    "christian", "church", "jesus", "gospel", "bible", "faith",
    "god", "christ", "theology", "prayer", "worship", "ministry",
    "pastor", "scripture", "disciple", "evangelical", "reformed",
    "sermon", "salvation", "grace", "orthodox", "catholic",
    "protestant", "baptist", "presbyterian", "anglican",
]

NON_CHRISTIAN_SIGNALS = [
    "world cup", "fifa", "olympic", "nba", "nfl", "super bowl",
    "haircut", "pinkwashing", "lgbtq", "transgender", "abortion",
    "roe v wade", "election", "vote", "political", "democrat", "republican",
    "disney", "netflix", "hollywood", "celebrity",
    "climate change", "global warming", "el nino",
]

POLITICAL_SOCIAL_SIGNALS = [
    "election", "vote", "voting", "political", "democrat", "republican",
    "campaign", "ballot", "midterm", "primary",
    "lgbtq", "transgender", "trans", "gay", "lesbian", "pride",
    "same-sex", "homosexual",
    "abortion", "roe v wade", "pro-choice", "pro-life",
    "supreme court", "court ruling", "lawsuit", "legal battle",
    "settlement", "appeal",
    "israel-hamas", "gaza", "palestinian", "hamas",
    "war in", "military conflict", "ceasefire",
    "economy", "inflation", "recession", "stock market", "tariff",
    "climate change", "global warming", "paris agreement",
]

COUNTRY_KEYWORDS = {
    "united states": "United States",
    "usa": "United States",
    "america": "United States",
    "american": "United States",
    "nigeria": "Nigeria",
    "nigerian": "Nigeria",
    "brazil": "Brazil",
    "brazilian": "Brazil",
    "brasil": "Brazil",
    "philippines": "Philippines",
    "philippine": "Philippines",
    "filipino": "Philippines",
    "south korea": "South Korea",
    "korean": "South Korea",
    "korea": "South Korea",
    "india": "India",
    "indian": "India",
    "united kingdom": "United Kingdom",
    "uk": "United Kingdom",
    "british": "United Kingdom",
    "britain": "United Kingdom",
    "england": "United Kingdom",
    "australia": "Australia",
    "australian": "Australia",
    "canada": "Canada",
    "canadian": "Canada",
    "germany": "Germany",
    "german": "Germany",
    "deutschland": "Germany",
    "kenya": "Kenya",
    "kenyan": "Kenya",
    "south africa": "South Africa",
    "china": "China",
    "chinese": "China",
    "indonesia": "Indonesia",
    "indonesian": "Indonesia",
    "egypt": "Egypt",
    "egyptian": "Egypt",
    "mexico": "Mexico",
    "mexican": "Mexico",
    "israel": "Israel",
    "israeli": "Israel",
    "uganda": "Uganda",
    "ghana": "Ghana",
    "ethiopia": "Ethiopia",
    "tanzania": "Tanzania",
    "singapore": "Singapore",
    "japan": "Japan",
    "japanese": "Japan",
    "france": "France",
    "french": "France",
    "russia": "Russia",
    "russian": "Russia",
    "syria": "Syria",
    "syrian": "Syria",
    "iraq": "Iraq",
    "iraqi": "Iraq",
    "iran": "Iran",
    "iranian": "Iran",
    "pakistan": "Pakistan",
    "pakistani": "Pakistan",
}


def _strip_html(text: str) -> str:
    clean = re.sub(r"<[^>]+>", " ", text or "")
    clean = re.sub(r"\s+", " ", unescape(clean)).strip()
    return clean


def is_christian_relevant(title: str, content: str, source_name: str = "") -> bool:
    """
    三层过滤：
    L1: 必须有 Christian 关键词
    L2: 非 Christian 信号不能超过阈值
    L3 (RNS/TGC only): 标题级精细化过滤
    """
    text = f"{title or ''} {content or ''}".lower()
    title_lower = (title or "").lower()

    # ===== L1: 必须有 Christian 关键词 =====
    has_christian = any(kw in text for kw in CHRISTIAN_KEYWORDS)
    if not has_christian:
        return False

    # ===== L2: 全局非 Christian 信号检查 =====
    non_christian_score = sum(1 for sig in NON_CHRISTIAN_SIGNALS if sig in text)
    if non_christian_score >= 2:
        return False

    # ===== L3: RNS/TGC 精细化二次去噪 =====
    if source_name in ["宗教新闻通讯社 (RNS)", "福音联盟 (TGC)"]:
        has_core_in_title = any(kw in title_lower for kw in CORE_CHRISTIAN_KEYWORDS)
        has_political_in_title = any(sig in title_lower for sig in POLITICAL_SOCIAL_SIGNALS)

        # 标题有政治/社会硬信号但没有 Christian 核心词，直接丢弃。
        if has_political_in_title and not has_core_in_title:
            return False

        christian_count = sum(1 for kw in CHRISTIAN_KEYWORDS if kw in text)
        if christian_count < 2 and not has_core_in_title:
            return False

        strong_christian_signals = [
            "church", "jesus", "gospel", "bible", "pastor", "ministry",
            "worship", "prayer", "sermon", "missionary", "theology",
            "christianity", "christian school", "christian college",
            "evangelical", "catholic", "orthodox",
        ]
        has_strong_signal = any(signal in title_lower for signal in strong_christian_signals)

        if source_name == "福音联盟 (TGC)":
            culture_review_signals = [
                "book review", "movie", "film", "album", "music review",
                "tv show", "television", "netflix", "podcast review",
            ]
            is_culture_review = any(signal in title_lower for signal in culture_review_signals)
            if is_culture_review and not has_strong_signal:
                return False

    # ===== Step 4.1: Title Pattern 定向黑名单 =====
    if source_name == "宗教新闻通讯社 (RNS)":
        policy_law_patterns = [
            "court", "judge", "ruling", "lawsuit", "legal", "law ",
            "supreme court", "appeals court", "district court",
            "election", "vote", "ballot", "voting", "elect ",
            "senate", "house of", "congress", "legislation", "bill ",
            "policy", "executive order", "government",
        ]
        institutional_signals = [
            "church", "churches", "denomination", "diocese", "parish",
            "ministry", "ministries", "mission", "missions",
            "seminary", "theological", "christian school", "christian college",
            "catholic", "baptist", "methodist", "presbyterian", "anglican",
            "evangelical", "pentecostal", "orthodox",
            "pope", "vatican", "archbishop", "bishop", "cardinal",
            "pastor", "priest", "reverend", "clergy",
        ]
        is_policy_law = any(pattern in title_lower for pattern in policy_law_patterns)
        has_institution = any(signal in title_lower for signal in institutional_signals)
        if is_policy_law and not has_institution:
            return False

        war_patterns = [
            "war ", "conflict", "gaza", "hamas", "israeli", "palestinian",
            "ceasefire", "hostage", "airstrike", "military",
        ]
        response_signals = [
            "church", "churches", "christian", "evangelical", "catholic",
            "ministry", "ministries", "mission", "aid", "relief",
            "prayer", "pray", "pastor", "bishop",
        ]
        is_war = any(pattern in title_lower for pattern in war_patterns)
        has_response = any(signal in title_lower for signal in response_signals)
        if is_war and not has_response:
            return False

    if source_name == "福音联盟 (TGC)":
        culture_consumption_patterns = [
            "book review", "review: ", "review -", "review --",
            "movie", "film ", "tv series", "television", "netflix",
            "album", "music review", "podcast",
            "what ", "teaches us", "lessons from",
            "how to ", "why we ", "should christians",
            "christian guide to", "christian case for",
            "for christians", "christian perspective on",
            "reading ", "watching ", "listening ",
        ]
        academic_institutions = [
            "seminary", "theological", "divinity school",
            "biblical", "reformed theological", "southern baptist theological",
            "westminster", "covenant", " rts ", " tgc ", " 9marks ",
        ]
        is_culture_consumption = any(pattern in title_lower for pattern in culture_consumption_patterns)
        is_academic = any(pattern in title_lower for pattern in academic_institutions)
        if is_culture_consumption and not is_academic:
            return False

        devotional_patterns = [
            "daily ", "morning ", "evening ", "devotion",
            "meditation", "reflection", "prayer for",
            "my ", "your ", "our ", "when you",
            "walking with", "journey with", "finding ",
        ]
        has_institutional_scope = any(signal in title_lower for signal in [
            "church", "churches", "denomination", "movement",
            "reformation", "revival", "history of", "global ",
            "evangelicalism", "christianity ", "the church",
        ])
        is_devotional = any(pattern in title_lower for pattern in devotional_patterns)
        if is_devotional and not has_institutional_scope:
            return False

    if source_name == "基督邮报 (Christian Post)":
        cp_social_patterns = [
            " viral", "trending", "social media", "tweet", "twitter",
            "celebrity", "famous", "hollywood", "oscar", "grammy",
            "super bowl", "world cup", "olympic",
        ]
        cp_christian_signals = [
            "church", "pastor", "ministry", "bible", "gospel",
            "christian school", "christian college", "seminary",
            "missionary", "missions", "evangelical", "catholic",
            "baptist", "presbyterian", "pentecostal",
        ]
        is_social_news = any(pattern in title_lower for pattern in cp_social_patterns)
        has_cp_christian = any(signal in title_lower for signal in cp_christian_signals)
        if is_social_news and not has_cp_christian:
            return False

    if source_name == "Barna Group":
        barna_generic_patterns = [
            "americans ", "american adults", "young people",
            "young adults", "teenagers", "teens ", "generation ",
            "gen z", "millennial", "boomer", "parents",
            "most ", "least ", "likely to", "unlikely to",
        ]
        barna_christian_focus = [
            "christian", "church", "pastor", "believer", "faith",
            "evangelical", "catholic", "protestant", "bible",
            "practicing christian", "committed christian",
        ]
        is_generic_pop = any(pattern in title_lower for pattern in barna_generic_patterns)
        has_christian_focus = any(signal in title_lower for signal in barna_christian_focus)
        if is_generic_pop and not has_christian_focus:
            return False

    return True


def extract_country_from_text(title: str, content: str) -> str | None:
    """从标题和内容提取国家归因。"""
    text = f"{title or ''} {content or ''}".lower()
    for keyword, country in COUNTRY_KEYWORDS.items():
        if keyword in text:
            return country
    return None


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

                    if not is_christian_relevant(title, summary, rss_source.name):
                        continue

                    country = extract_country_from_text(title, summary)

                    db.add(
                        IntelligenceItem(
                            id=str(uuid.uuid4()),
                            source_id=mapped_source.id,
                            title=title,
                            content=summary,
                            entity_name=title[:200],
                            entity_type="rss_news",
                            country=country,
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
                    duplicate_source = (
                        db.query(RSSSource)
                        .filter(RSSSource.id != rss_source.id, RSSSource.rss_url == used_url)
                        .first()
                    )
                    if duplicate_source:
                        print(f"  跳过URL更新，避免与现有RSS源冲突: {used_url}")
                    else:
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
    # Development/Test entry. Not production collection path.
    collect_rss()
