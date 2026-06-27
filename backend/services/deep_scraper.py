import uuid
from datetime import datetime
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from models.database import Source, Page, IntelligenceItem
from services.ingestion_guard import is_duplicate, assess_item_quality, should_save

# 各机构官网的关键子页面路径
ORG_SUBPATHS = {
    "pcec.org.ph": ["/", "/about", "/statement-of-faith-2"],
    "ccf.org.ph": ["/", "/about", "/news", "/events", "/ministries"],
    "victory.org.ph": ["/", "/about", "/stories", "/events", "/locations"],
    "philbible.org.ph": ["/"],
    "lifetube.tv": ["/", "/news"],
}


def _normalize_domain(url: str) -> str:
    netloc = urlparse(url).netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc


def deep_scrape_organization(source: Source, db: Session) -> dict:
    """深度抓取机构官网：首页+关键子页面"""
    domain = _normalize_domain(source.url)
    subpaths = ORG_SUBPATHS.get(domain, ["/"])

    total_new = 0
    results = []

    for path in subpaths:
        url = source.url.rstrip("/") + path
        try:
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
            resp = httpx.get(url, headers=headers, timeout=15, follow_redirects=True, verify=False)
            if resp.status_code != 200:
                results.append({"url": url, "status": "skipped", "http_status": resp.status_code})
                continue

            soup = BeautifulSoup(resp.text, "lxml")
            title = soup.title.string if soup.title else url

            # 清理文本
            for script in soup(["script", "style", "nav", "footer"]):
                script.decompose()
            text = soup.get_text(separator="\n", strip=True)[:4000]

            # 检查是否已有相同记录
            existing = db.query(Page).filter(Page.url == url).order_by(Page.extracted_at.desc()).first()
            if existing and existing.content and existing.content[:500] == text[:500]:
                results.append({"url": url, "status": "no_change", "title": str(title)[:80] if title else ""})
                continue

            # 写入Page
            page = Page(
                id=str(uuid.uuid4()),
                source_id=source.id,
                url=url,
                title=str(title)[:300] if title else url,
                content=text[:3000],
                status="parsed",
                extracted_at=datetime.utcnow(),
            )
            db.add(page)
            db.flush()

            # 提取关键段落作为情报
            paragraphs = [p.strip() for p in text.split("\n") if 50 < len(p.strip()) < 500]
            for para in paragraphs[:3]:  # 每个页面取前3个有效段落
                item_data = {
                    "title": str(title)[:200] if title else source.name,
                    "content": para[:500],
                    "source_url": url,
                    "source_name": source.name,
                    "source_type": source.type,
                    "category": "deep_scrape",
                    "published_at": None,
                    "ingested_at": datetime.utcnow(),
                }
                if is_duplicate(db, item_data["source_url"], item_data["title"]):
                    continue

                assessment = assess_item_quality(item_data)
                if not should_save(item_data, assessment):
                    continue

                item = IntelligenceItem(
                    id=str(uuid.uuid4()),
                    source_id=source.id,
                    page_id=page.id,
                    title=item_data["title"],
                    content=item_data["content"],
                    entity_name=source.name,
                    entity_type="organization",
                    country=source.country,
                    category="deep_scrape",
                    source_url=item_data["source_url"],
                    source_name=source.name,
                    ingested_at=item_data["ingested_at"],
                    confidence=assessment["confidence"]["score"] / 100.0,
                )
                db.add(item)
                total_new += 1

            db.commit()
            results.append({"url": url, "status": "fetched", "title": str(title)[:80] if title else ""})

        except Exception as e:
            db.rollback()
            results.append({"url": url, "status": "failed", "error": str(e)[:100]})

    return {
        "status": "success",
        "source": source.name,
        "pages_scanned": len(subpaths),
        "new_items": total_new,
        "details": results,
    }
