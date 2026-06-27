import os
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from dotenv import load_dotenv
from googleapiclient.discovery import build
from sqlalchemy.orm import Session

from models.database import Source, IntelligenceItem
from services.ingestion_guard import is_duplicate, assess_item_quality, should_save

load_dotenv(override=True)

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")


def get_youtube_client():
    if not YOUTUBE_API_KEY:
        return None
    return build("youtube", "v3", developerKey=YOUTUBE_API_KEY, cache_discovery=False)


PH_CHRISTIAN_CHANNELS = [
    {"channel_id": "UCnxKW4DWLxzUcwd3cGI934g", "name": "Victory Philippines", "country": "菲律宾"},
    {"channel_id": "UCF1Wrrlls2ioQyn5WG-_nIQ", "name": "Christ’s Commission Fellowship", "country": "菲律宾"},
    {"channel_id": "UCVppYdcDfve_kDEnNXXKhaQ", "name": "Jesus Is Lord Church Worldwide", "country": "菲律宾"},
    {"channel_id": "UCdNOvV39P0nKauDRmzBFBTQ", "name": "CBN Asia", "country": "菲律宾"},
]


def _resolve_channel_id_by_search(query: str) -> Optional[str]:
    youtube = get_youtube_client()
    if not youtube or not query:
        return None
    try:
        resp = youtube.search().list(part="snippet", q=query, type="channel", maxResults=1).execute()
        items = resp.get("items") or []
        if not items:
            return None
        return ((items[0].get("id") or {}).get("channelId")) or None
    except Exception:
        return None


def _is_valid_channel_id(channel_id: str) -> bool:
    youtube = get_youtube_client()
    if not youtube or not channel_id:
        return False
    try:
        resp = youtube.channels().list(part="id", id=channel_id).execute()
        return bool(resp.get("items"))
    except Exception:
        return False



def fetch_channel_videos(channel_id: str, max_results: int = 10) -> List[Dict[str, Any]]:
    youtube = get_youtube_client()
    if not youtube:
        return []

    if not _is_valid_channel_id(channel_id):
        return []

    try:
        channel_resp = youtube.channels().list(part="contentDetails", id=channel_id).execute()
        if not channel_resp.get("items"):
            return []
        uploads_playlist_id = channel_resp["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
        playlist_resp = youtube.playlistItems().list(
            part="snippet",
            playlistId=uploads_playlist_id,
            maxResults=max_results,
        ).execute()

        videos: List[Dict[str, Any]] = []
        for item in playlist_resp.get("items", []):
            snippet = item.get("snippet") or {}
            resource = snippet.get("resourceId") or {}
            video_id = resource.get("videoId")
            if not video_id:
                continue
            videos.append(
                {
                    "video_id": video_id,
                    "title": (snippet.get("title") or "")[:300],
                    "description": (snippet.get("description") or "")[:2000],
                    "published_at": snippet.get("publishedAt") or "",
                    "thumbnail": ((snippet.get("thumbnails") or {}).get("high") or {}).get("url") or "",
                    "channel_title": snippet.get("channelTitle") or "",
                }
            )

        video_ids = [v["video_id"] for v in videos if v.get("video_id")]
        if video_ids:
            stats_resp = youtube.videos().list(part="statistics", id=",".join(video_ids)).execute()
            stats_map = {s.get("id"): (s.get("statistics") or {}) for s in stats_resp.get("items", [])}
            for v in videos:
                stats = stats_map.get(v["video_id"], {}) if isinstance(stats_map.get(v["video_id"]), dict) else {}
                v["view_count"] = stats.get("viewCount", 0)
                v["like_count"] = stats.get("likeCount", 0)
                v["comment_count"] = stats.get("commentCount", 0)

        return videos
    except Exception as e:
        print(f"YouTube API错误: {e}")
        return []


def _extract_channel_id_from_source(source: Source) -> Optional[str]:
    url = (source.url or "").strip()
    if not url:
        return None

    if "channel/" in url:
        return url.split("channel/")[-1].split("/")[0]

    parsed = urlparse(url)
    if parsed.path.startswith("/channel/"):
        return parsed.path.split("/channel/")[-1].split("/")[0]

    return None


def collect_youtube_channel(source: Source, db: Session) -> Dict[str, Any]:
    channel_id = _extract_channel_id_from_source(source)
    if not channel_id:
        resolved = _resolve_channel_id_by_search(source.name)
        if not resolved:
            return {"status": "failed", "error": "缺少channel_id", "new_items": 0}
        channel_id = resolved

    if not _is_valid_channel_id(channel_id):
        resolved = _resolve_channel_id_by_search(source.name)
        if resolved and resolved != channel_id:
            channel_id = resolved
            source.url = f"https://youtube.com/channel/{channel_id}"
            db.commit()

    videos = fetch_channel_videos(channel_id, max_results=10)

    new_count = 0
    for video in videos:
        video_id = video.get("video_id")
        if not video_id:
            continue
        source_url = f"https://youtube.com/watch?v={video_id}"

        published_at = None
        if video.get("published_at"):
            try:
                published_at = datetime.fromisoformat(str(video["published_at"]).replace("Z", "+00:00"))
            except Exception:
                published_at = None

        content_parts = [video.get("description") or ""]
        view_count = video.get("view_count")
        like_count = video.get("like_count")
        comment_count = video.get("comment_count")
        if view_count or like_count or comment_count:
            content_parts.append(f"\n\nviews={view_count or 0} likes={like_count or 0} comments={comment_count or 0}")

        item_data = {
            "title": (video.get("title") or "")[:300],
            "content": "".join(content_parts)[:2000],
            "source_url": source_url,
            "source_name": source.name,
            "source_type": source.type,
            "category": "youtube_video",
            "published_at": published_at,
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
            category="youtube_video",
            published_at=published_at,
            ingested_at=item_data["ingested_at"],
            confidence=assessment["confidence"]["score"] / 100.0,
        )
        db.add(item)
        new_count += 1

    db.commit()

    return {
        "status": "success",
        "source": source.name,
        "videos_found": len(videos),
        "new_items": new_count,
    }
