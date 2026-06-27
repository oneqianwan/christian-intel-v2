import asyncio
import os
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from sqlalchemy.orm import Session
from telegram import Bot

from models.database import Source, IntelligenceItem
from services.ingestion_guard import is_duplicate, assess_item_quality, should_save

load_dotenv(override=True)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")


def get_telegram_bot() -> Optional[Bot]:
    if not TELEGRAM_BOT_TOKEN:
        return None
    return Bot(token=TELEGRAM_BOT_TOKEN)


PH_CHRISTIAN_TELEGRAM_CHANNELS = [
    {"username": "victoryph", "name": "Victory Philippines Telegram", "country": "菲律宾"},
    {"username": "ccfofficial", "name": "CCF Official Telegram", "country": "菲律宾"},
    {"username": "pcecphilippines", "name": "PCEC Philippines", "country": "菲律宾"},
]


async def fetch_channel_posts(channel_username: str, limit: int = 10) -> List[Dict[str, Any]]:
    bot = get_telegram_bot()
    if not bot:
        return []

    try:
        chat = await bot.get_chat(f"@{channel_username}")
        title = getattr(chat, "title", "") or ""
        description = getattr(chat, "description", "") or ""
        return [
            {
                "channel_id": getattr(chat, "id", None),
                "title": title,
                "username": getattr(chat, "username", channel_username),
                "description": description,
                "type": "channel_info",
            }
        ]
    except Exception as e:
        print(f"Telegram API错误: {e}")
        return []


def _extract_username_from_source(source: Source) -> Optional[str]:
    source_data = getattr(source, "data", None)
    if source_data and isinstance(source_data, dict) and source_data.get("username"):
        return str(source_data.get("username"))

    url = (source.url or "").strip()
    if url and "t.me/" in url:
        return url.split("t.me/")[-1].split("/")[0].strip("@")

    return None


def collect_telegram_channel(source: Source, db: Session) -> Dict[str, Any]:
    username = _extract_username_from_source(source)
    if not username:
        return {"status": "failed", "error": "缺少频道username", "new_items": 0}

    posts: List[Dict[str, Any]] = []
    try:
        try:
            posts = asyncio.run(fetch_channel_posts(username))
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            posts = loop.run_until_complete(fetch_channel_posts(username))
            loop.close()
    except Exception:
        posts = []

    new_count = 0
    for post in posts:
        source_url = f"https://t.me/{username}"
        item_data = {
            "title": (post.get("title") or username)[:300],
            "content": (post.get("description") or "")[:2000],
            "source_url": source_url,
            "source_name": source.name,
            "source_type": source.type,
            "category": "telegram_channel",
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
            title=item_data["title"],
            content=item_data["content"],
            source_url=item_data["source_url"],
            source_name=source.name,
            country=source.country,
            category="telegram_channel",
            ingested_at=item_data["ingested_at"],
            confidence=assessment["confidence"]["score"] / 100.0,
        )
        db.add(item)
        new_count += 1

    db.commit()

    return {
        "status": "success",
        "source": source.name,
        "posts_found": len(posts),
        "new_items": new_count,
    }
