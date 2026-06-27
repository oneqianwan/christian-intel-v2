import uuid
import httpx
from datetime import datetime
from typing import Dict, Any
from sqlalchemy.orm import Session
from bs4 import BeautifulSoup
from models.database import Source, Page, IntelligenceItem
from services.ingestion_guard import is_duplicate, assess_item_quality, should_save


def scrape_page(source: Source, db: Session) -> Dict[str, Any]:
    """抓取单个官网页面的更新"""
    print(f"开始抓取页面: {source.name} ({source.url})")

    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        resp = httpx.get(source.url, headers=headers, timeout=15, follow_redirects=True, verify=False)
        resp.raise_for_status()
    except Exception as e:
        return {"status": "failed", "error": f"抓取失败: {str(e)}", "new_items": 0}

    soup = BeautifulSoup(resp.text, 'lxml')

    # 提取页面标题和关键文本
    title = soup.title.string if soup.title else source.name
    # 提取正文（去除脚本和样式）
    for script in soup(["script", "style", "nav", "footer"]):
        script.decompose()
    text = soup.get_text(separator='\n', strip=True)
    # 限制长度
    text = text[:5000]

    # 检查是否已有相同URL的记录
    existing = db.query(Page).filter(Page.url == source.url).order_by(Page.extracted_at.desc()).first()

    # 如果内容没有变化，跳过
    if existing and existing.content == text[:1000]:
        return {"status": "no_change", "source": source.name, "new_items": 0}

    # 写入Page记录
    page = Page(
        id=str(uuid.uuid4()),
        source_id=source.id,
        url=source.url,
        title=title[:300],
        content=text[:3000],
        status="parsed",
        extracted_at=datetime.utcnow()
    )
    db.add(page)
    db.flush()

    # 提取关键信息写入情报条目
    # 从页面标题和首段提取
    first_para = text[:500] if text else ""

    item_data = {
        "title": title[:300],
        "content": first_para,
        "source_url": source.url,
        "source_name": source.name,
        "source_type": source.type,
        "category": "official_page",
        "published_at": None,
        "ingested_at": datetime.utcnow(),
    }
    if is_duplicate(db, item_data["source_url"], item_data["title"]):
        db.commit()
        return {"status": "no_change", "source": source.name, "new_items": 0}

    assessment = assess_item_quality(item_data)
    if not should_save(item_data, assessment):
        db.commit()
        return {"status": "filtered", "source": source.name, "new_items": 0}

    item = IntelligenceItem(
        id=str(uuid.uuid4()),
        source_id=source.id,
        page_id=page.id,
        title=item_data["title"],
        content=item_data["content"],
        entity_name=source.name,
        entity_type="organization",
        country=source.country,
        category="official_page",
        source_url=item_data["source_url"],
        source_name=source.name,
        ingested_at=item_data["ingested_at"],
        confidence=assessment["confidence"]["score"] / 100.0,
    )
    db.add(item)
    db.commit()

    return {
        "status": "success",
        "source": source.name,
        "title": title[:100],
        "new_items": 1
    }
