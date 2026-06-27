import json
import re
from typing import Any, Dict
from urllib.parse import urlparse, quote_plus

import httpx


def detect_platform(url: str) -> str:
    domain = urlparse(url).netloc.lower()
    if "tiktok.com" in domain:
        return "tiktok"
    if "youtube.com" in domain or "youtu.be" in domain:
        return "youtube"
    if "facebook.com" in domain or "fb.watch" in domain:
        return "facebook"
    if "instagram.com" in domain:
        return "instagram"
    if "twitter.com" in domain or "x.com" in domain:
        return "twitter"
    if "t.me" in domain:
        return "telegram"
    return "unknown"


def extract_og_tags(html: str) -> Dict[str, str]:
    og_data: Dict[str, str] = {}
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html or "", "lxml")
        for tag in soup.find_all("meta"):
            prop = (tag.get("property") or "").strip()
            name = (tag.get("name") or "").strip()
            content = (tag.get("content") or "").strip()
            if not content:
                continue
            key = ""
            if prop.lower().startswith("og:"):
                key = prop[3:]
            elif name.lower().startswith("og:"):
                key = name[3:]
            if key:
                og_data[key] = content
        return og_data
    except Exception:
        pass

    pattern_property = re.compile(
        r'<meta[^>]*property=["\']og:([^"\'\s]+)["\'][^>]*content=["\']([^"\']*)["\']',
        re.IGNORECASE,
    )
    for key, value in pattern_property.findall(html or ""):
        og_data[key] = value

    pattern_name = re.compile(
        r'<meta[^>]*name=["\']og:([^"\'\s]+)["\'][^>]*content=["\']([^"\']*)["\']',
        re.IGNORECASE,
    )
    for key, value in pattern_name.findall(html or ""):
        og_data[key] = value

    return og_data


def _extract_script_text_by_id(html: str, element_id: str) -> str:
    if not html:
        return ""
    marker = f'id="{element_id}"'
    idx = html.find(marker)
    if idx < 0:
        marker = f"id='{element_id}'"
        idx = html.find(marker)
        if idx < 0:
            return ""
    start_tag_idx = html.rfind("<script", 0, idx)
    if start_tag_idx < 0:
        return ""
    start_close = html.find(">", idx)
    if start_close < 0:
        return ""
    end_tag_idx = html.find("</script>", start_close)
    if end_tag_idx < 0:
        return ""
    return html[start_close + 1 : end_tag_idx].strip()


def analyze_url(url: str) -> Dict[str, Any]:
    platform = detect_platform(url)

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        resp = httpx.get(url, headers=headers, timeout=20, follow_redirects=True, verify=False)
        html = resp.text or ""

        og = extract_og_tags(html)
        if not og.get("title") or not og.get("description"):
            try:
                from bs4 import BeautifulSoup

                soup = BeautifulSoup(html, "lxml")
                if not og.get("title") and soup.title and soup.title.string:
                    og["title"] = soup.title.string.strip()
                if not og.get("description"):
                    meta_desc = soup.find("meta", attrs={"name": "description"})
                    if meta_desc and meta_desc.get("content"):
                        og["description"] = meta_desc.get("content", "").strip()
            except Exception:
                pass

        result: Dict[str, Any] = {
            "platform": platform,
            "url": url,
            "final_url": str(resp.url),
            "http_status": resp.status_code,
            "title": og.get("title", ""),
            "description": og.get("description", ""),
            "image": og.get("image", ""),
            "site_name": og.get("site_name", platform),
            "type": og.get("type", "website"),
            "author": og.get("author", ""),
            "publish_date": og.get("updated_time") or og.get("published_time", ""),
            "status": "success",
            "html_length": len(html),
        }

        if platform == "tiktok":
            script_text = ""
            m = re.search(r'<script[^>]*id=["\']SIGI_STATE["\'][^>]*>(.*?)</script>', html, re.DOTALL)
            if m:
                script_text = (m.group(1) or "").strip()
            if not script_text:
                script_text = _extract_script_text_by_id(html, "SIGI_STATE")
            if script_text:
                try:
                    sigi = json.loads(script_text)
                    item_module = sigi.get("ItemModule", {}) if isinstance(sigi, dict) else {}
                    if isinstance(item_module, dict):
                        for _, data in item_module.items():
                            if not isinstance(data, dict):
                                continue
                            result["author"] = data.get("author", result.get("author", ""))
                            result["nickname"] = data.get("nickname", "")
                            result["title"] = data.get("desc", result.get("title", ""))
                            stats = data.get("stats", {}) if isinstance(data.get("stats"), dict) else {}
                            result["stats"] = {
                                "likes": stats.get("diggCount", 0),
                                "comments": stats.get("commentCount", 0),
                                "shares": stats.get("shareCount", 0),
                                "plays": stats.get("playCount", 0),
                            }
                            result["create_time"] = data.get("createTime", "")
                            music = data.get("music", {}) if isinstance(data.get("music"), dict) else {}
                            result["music"] = music.get("title", "")
                            break
                except Exception:
                    pass

            if not result.get("author") or result.get("title") in ["", "TikTok - Make Your Day"]:
                try:
                    oembed_url = f"https://www.tiktok.com/oembed?url={quote_plus(str(resp.url))}"
                    o = httpx.get(
                        oembed_url,
                        headers=headers,
                        timeout=15,
                        follow_redirects=True,
                        verify=False,
                    )
                    if o.status_code == 200:
                        data = o.json()
                        if isinstance(data, dict):
                            if not result.get("title"):
                                result["title"] = data.get("title", "") or result.get("title", "")
                            if not result.get("author"):
                                result["author"] = data.get("author_name", "") or result.get("author", "")
                            if not result.get("image"):
                                result["image"] = data.get("thumbnail_url", "") or result.get("image", "")
                            result["oembed"] = {"provider": "tiktok", "ok": True}
                except Exception:
                    pass

            if not result.get("stats"):
                try:
                    m_stats = re.search(
                        r'"diggCount"\s*:\s*(\d+).*?"commentCount"\s*:\s*(\d+).*?"shareCount"\s*:\s*(\d+).*?"playCount"\s*:\s*(\d+)',
                        html,
                        re.DOTALL,
                    )
                    if m_stats:
                        result["stats"] = {
                            "likes": int(m_stats.group(1)),
                            "comments": int(m_stats.group(2)),
                            "shares": int(m_stats.group(3)),
                            "plays": int(m_stats.group(4)),
                        }
                        result["stats_extracted"] = "regex"
                except Exception:
                    pass

        elif platform == "youtube":
            m = re.search(r"var\s+ytInitialData\s*=\s*({.*?})\s*;\s*</script>", html, re.DOTALL)
            if not m:
                m = re.search(r"ytInitialData\s*=\s*({.*?})\s*;\s*</script>", html, re.DOTALL)
            if m:
                try:
                    _ = json.loads(m.group(1))
                    result["extracted"] = "youtube_data_found"
                except Exception:
                    pass
            if not result.get("title"):
                try:
                    oembed_url = f"https://www.youtube.com/oembed?url={quote_plus(str(resp.url))}&format=json"
                    o = httpx.get(
                        oembed_url,
                        headers=headers,
                        timeout=15,
                        follow_redirects=True,
                        verify=False,
                    )
                    if o.status_code == 200:
                        data = o.json()
                        if isinstance(data, dict):
                            result["title"] = data.get("title", "") or result.get("title", "")
                            result["author"] = data.get("author_name", "") or result.get("author", "")
                            result["image"] = data.get("thumbnail_url", "") or result.get("image", "")
                            result["oembed"] = {"provider": "youtube", "ok": True}
                except Exception:
                    pass

        return result

    except Exception as e:
        return {
            "platform": platform,
            "url": url,
            "status": "error",
            "error": str(e)[:200],
        }
