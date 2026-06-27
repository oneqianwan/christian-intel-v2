import uuid
from datetime import datetime
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from models.database import Source, IntelligenceItem
from services.ingestion_guard import is_duplicate, assess_item_quality, should_save


def _normalize_url(source_url: str, candidate_url: str) -> str:
    candidate_url = (candidate_url or "").strip()
    if not candidate_url:
        return ""
    return urljoin(source_url.rstrip("/") + "/", candidate_url)


def _is_valid_article(title: str, url: str, source: Source) -> bool:
    if not title or len(title) <= 5:
        return False
    if "{" in title or "}" in title:
        return False
    if not url or url == source.url:
        return False
    if any(url.startswith(prefix) for prefix in ["javascript:", "#", "mailto:", "tel:"]):
        return False

    parsed = urlparse(url)
    source_host = urlparse(source.url).netloc.replace("www.", "")
    url_host = parsed.netloc.replace("www.", "")
    if source_host and url_host and source_host != url_host:
        return False

    lowered_url = url.lower()
    blocked_parts = ["/tag/", "/tags/", "/author/", "/category/", "/search", "/video/", "/cdn-cgi/"]
    if any(part in lowered_url for part in blocked_parts):
        return False

    lowered_title = title.lower()
    blocked_titles = ["read more", "advertisement", "subscribe", "sign in", "tag page"]
    if any(text in lowered_title for text in blocked_titles):
        return False

    return True


def _append_article(articles: list, seen_urls: set, source: Source, title: str, url: str) -> None:
    title = (title or "").strip()
    normalized_url = _normalize_url(source.url, url)
    if not _is_valid_article(title, normalized_url, source):
        return
    if normalized_url in seen_urls:
        return

    articles.append({"title": title[:200], "url": normalized_url[:500]})
    seen_urls.add(normalized_url)


def _find_heading_link(heading):
    link = heading.find("a", href=True)
    if link:
        return link

    parent_link = heading.find_parent("a", href=True)
    if parent_link:
        return parent_link

    parent = heading.parent
    if parent:
        link = parent.find("a", href=True)
        if link:
            return link

        grandparent = parent.parent
        if grandparent:
            link = grandparent.find("a", href=True)
            if link:
                return link

    return None


def scrape_news_page(source: Source, db: Session) -> dict:
    """只抓取新闻列表页的文章标题和链接，不抓整页正文"""
    print(f"开始抓取新闻页: {source.name} ({source.url})")

    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        resp = httpx.get(source.url, headers=headers, timeout=15, follow_redirects=True, verify=False)
        resp.raise_for_status()
    except Exception as e:
        return {"status": "failed", "error": str(e), "new_items": 0}

    soup = BeautifulSoup(resp.text, "lxml")

    # 提取文章列表（不同网站结构不同，这里用通用规则）
    articles = []
    seen_urls = set()

    # 策略1：找 article 标签
    for article in soup.find_all("article"):
        title_tag = article.find(["h1", "h2", "h3", "h4"])
        link_tag = article.find("a", href=True)
        if title_tag and link_tag:
            title = title_tag.get_text(strip=True)
            _append_article(articles, seen_urls, source, title, link_tag["href"])

    # 策略2：直接遍历标题，兼容“标题被外层 a 包裹”的结构
    for heading in soup.find_all(["h1", "h2", "h3", "h4"]):
        title = heading.get_text(" ", strip=True)
        link = _find_heading_link(heading)
        if link:
            _append_article(articles, seen_urls, source, title, link["href"])

    # 去重并入库
    new_count = 0
    for article in articles[:20]:  # 每页最多取20条
        if is_duplicate(db, article["url"], article["title"]):
            continue

        item_data = {
            "title": article["title"],
            "content": article["title"],
            "source_url": article["url"],
            "source_name": source.name,
            "source_type": source.type,
            "category": "news_article",
            "published_at": None,
            "ingested_at": datetime.utcnow(),
        }
        assessment = assess_item_quality(item_data)
        if not should_save(item_data, assessment):
            continue

        item = IntelligenceItem(
            id=str(uuid.uuid4()),
            source_id=source.id,
            title=item_data["title"],
            content="",  # 新闻页只存标题和链接，不抓正文
            source_url=item_data["source_url"],
            source_name=source.name,
            country=source.country,
            category="news_article",
            ingested_at=item_data["ingested_at"],
            confidence=assessment["confidence"]["score"] / 100.0,
        )
        db.add(item)
        new_count += 1

    # 更新来源扫描时间
    source.last_scan_at = datetime.utcnow()
    db.commit()

    return {
        "status": "success",
        "source": source.name,
        "articles_found": len(articles),
        "new_items": new_count,
    }
