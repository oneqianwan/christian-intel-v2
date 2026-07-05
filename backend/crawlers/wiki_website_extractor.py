"""
从 Wikipedia 机构页面提取官网 URL — Phase 2 Day 4.5
比 LLM 猜域名更准确：优先从 Wikipedia infobox 提取 Official website。
"""

import html
import os
import re
import sys
from typing import Optional
from urllib.parse import unquote

import requests
from sqlalchemy import text

script_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.dirname(script_dir)
os.chdir(backend_dir)
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from models.database import SessionLocal


WIKI_API = "https://en.wikipedia.org/w/api.php"
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    )
}
BAD_DOMAINS = (
    "wikipedia.org",
    "wikimedia.org",
    "jstor.org",
    "books.google",
    "google.com/books",
    "doi.org",
    "projectmuse.org",
    "cambridge.org",
    "oxfordreference.com",
    "britannica.com",
    "toolforge.org",
    "worldhistory.org",
    "bwanet.org",
    "lutheranworld.org",
    "irfa.org.au",
    "keralaassembly.org",
    "facebook.com",
    "instagram.com",
    "twitter.com",
    "x.com",
    "youtube.com",
    "linkedin.com",
    "flickr.com",
    "archive.org",
)


def _clean_url(url: str) -> Optional[str]:
    if not url:
        return None

    value = html.unescape(url).strip()
    value = re.sub(r"<[^>]+>", "", value)
    value = value.replace("&amp;", "&").strip()

    if value.startswith("//"):
        value = f"https:{value}"
    elif value.startswith("/"):
        return None

    if not value.startswith(("http://", "https://")):
        return None

    value = value.rstrip(" .),;]}>\"'")
    lowered = value.lower()

    if any(domain in lowered for domain in BAD_DOMAINS):
        return None

    if "." not in value:
        return None

    return value


def _request_json(session: requests.Session, params: dict, timeout: int = 20) -> Optional[dict]:
    try:
        response = session.get(WIKI_API, params=params, timeout=timeout)
        response.raise_for_status()
        return response.json()
    except Exception:
        return None


def _resolve_page_title(session: requests.Session, page_title: str) -> Optional[str]:
    title = (page_title or "").strip()
    if not title:
        return None

    query_data = _request_json(
        session,
        {
            "action": "query",
            "titles": title,
            "format": "json",
            "redirects": 1,
        },
    )
    if query_data:
        normalized_map = {}
        for item in query_data.get("query", {}).get("normalized", []):
            normalized_map[item.get("from", "")] = item.get("to", "")
        redirects_map = {}
        for item in query_data.get("query", {}).get("redirects", []):
            redirects_map[item.get("from", "")] = item.get("to", "")

        pages = query_data.get("query", {}).get("pages", {})
        for page_id, page_data in pages.items():
            if page_id != "-1":
                return (
                    page_data.get("title")
                    or redirects_map.get(title)
                    or normalized_map.get(title)
                    or title
                )

    search_data = _request_json(
        session,
        {
            "action": "query",
            "list": "search",
            "srsearch": title,
            "srlimit": 5,
            "format": "json",
        },
    )
    if not search_data:
        return None

    for item in search_data.get("query", {}).get("search", []):
        candidate = (item.get("title") or "").strip()
        if candidate:
            return candidate

    return None


def _extract_website_from_html(html_text: str) -> Optional[str]:
    if not html_text:
        return None

    compact = re.sub(r"\s+", " ", html_text)

    row_patterns = [
        r"<tr[^>]*>.*?<th[^>]*>\s*(?:Official\s+website|Website)\s*</th>.*?<td[^>]*>(.*?)</td>.*?</tr>",
        r"<tr[^>]*>.*?<th[^>]*>.*?(?:Official\s+website|Website).*?</th>.*?<td[^>]*>(.*?)</td>.*?</tr>",
    ]
    for pattern in row_patterns:
        row_match = re.search(pattern, compact, re.IGNORECASE)
        if not row_match:
            continue
        cell_html = row_match.group(1)
        for href in re.findall(r'href="([^"]+)"', cell_html, re.IGNORECASE):
            cleaned = _clean_url(href)
            if cleaned:
                return cleaned

    # Fallback: try the first valid external link in the infobox.
    infobox_match = re.search(
        r'<table[^>]*class="[^"]*infobox[^"]*"[^>]*>(.*?)</table>',
        compact,
        re.IGNORECASE,
    )
    if infobox_match:
        infobox_html = infobox_match.group(1)
        for href in re.findall(r'href="([^"]+)"', infobox_html, re.IGNORECASE):
            cleaned = _clean_url(href)
            if cleaned:
                return cleaned

    return None


def _extract_website_from_extlinks(extlinks: list) -> Optional[str]:
    if not extlinks:
        return None

    preferred = []
    fallback = []

    for item in extlinks:
        url = _clean_url(item.get("*", ""))
        if not url:
            continue

        lowered = unquote(url).lower()
        if any(token in lowered for token in ("official", ".org", "church", "ministry", "mission")):
            preferred.append(url)
        else:
            fallback.append(url)

    if preferred:
        return preferred[0]
    if fallback:
        return fallback[0]
    return None


def fetch_page_website(page_title: str) -> Optional[str]:
    """
    通过 Wikipedia API 获取页面官网 URL。
    优先顺序：
    1. resolve 精确/搜索到真实页面标题
    2. parse 页面 HTML，从 infobox 的 Website/Official website 抽取
    3. query extlinks，挑选最像官网的外链
    """
    session = requests.Session()
    session.headers.update(REQUEST_HEADERS)

    resolved_title = _resolve_page_title(session, page_title)
    if not resolved_title:
        return None

    parse_data = _request_json(
        session,
        {
            "action": "parse",
            "page": resolved_title,
            "prop": "text",
            "format": "json",
            "redirects": 1,
        },
    )
    if parse_data and "parse" in parse_data:
        html_text = parse_data["parse"]["text"].get("*", "")
        url = _extract_website_from_html(html_text)
        if url:
            return url

    ext_data = _request_json(
        session,
        {
            "action": "query",
            "titles": resolved_title,
            "prop": "extlinks",
            "ellimit": 50,
            "format": "json",
            "redirects": 1,
        },
    )
    if not ext_data:
        return None

    pages = ext_data.get("query", {}).get("pages", {})
    for page_id, page_data in pages.items():
        if page_id == "-1":
            continue
        url = _extract_website_from_extlinks(page_data.get("extlinks", []))
        if url:
            return url

    return None


def normalize_org_name(name: str) -> str:
    """将机构名转为更适合 Wikipedia 搜索的页面标题。"""
    clean = re.sub(r"\([^)]*\)", "", (name or "")).strip()
    clean = re.sub(r"\s+", " ", clean)
    return clean


def batch_extract_websites(batch_size: int = 100, country_filter: str = None):
    """批量从 Wikipedia 提取官网 URL。"""
    db = SessionLocal()

    print("=" * 60)
    print(f"Wikipedia官网URL提取 (batch={batch_size})")
    print("=" * 60)

    if country_filter:
        sql = """
            SELECT id, name, country
            FROM organization_profiles
            WHERE source_name = 'wiki_extracted'
              AND (official_website IS NULL OR official_website = '')
              AND country = :country
            ORDER BY id
            LIMIT :limit
        """
        params = {"country": country_filter, "limit": batch_size}
    else:
        sql = """
            SELECT id, name, country
            FROM organization_profiles
            WHERE source_name = 'wiki_extracted'
              AND (official_website IS NULL OR official_website = '')
            ORDER BY
                CASE country
                    WHEN 'Philippines' THEN 1
                    WHEN 'United States' THEN 2
                    WHEN 'United Kingdom' THEN 3
                    WHEN 'India' THEN 4
                    WHEN 'Indonesia' THEN 5
                    ELSE 6
                END,
                id
            LIMIT :limit
        """
        params = {"limit": batch_size}

    rows = db.execute(text(sql), params).fetchall()
    print(f"\n待处理: {len(rows)} 家机构")

    found = 0
    not_found = 0

    for index, row in enumerate(rows, 1):
        org_id, name, country = row
        page_title = normalize_org_name(name)

        print(f"\n[{index}/{len(rows)}] {name[:50]}")
        print(f"      搜索Wikipedia: {page_title}")

        url = fetch_page_website(page_title)

        if not url:
            words = page_title.split()
            if len(words) > 3:
                short_title = " ".join(words[-3:])
                url = fetch_page_website(short_title)
                if url:
                    print(f"      使用短名回退: {short_title}")

        if url:
            db.execute(
                text("UPDATE organization_profiles SET official_website = :url WHERE id = :id"),
                {"url": url, "id": org_id},
            )
            print(f"      [OK] {url}")
            found += 1
        else:
            print("      [MISS] 未找到")
            not_found += 1

        if index % 10 == 0:
            db.commit()

    db.commit()

    print(f"\n{'=' * 60}")
    print(f"完成: 找到 {found} / 未找到 {not_found} / 总计 {len(rows)}")
    print(f"{'=' * 60}")

    db.close()
    return {"found": found, "not_found": not_found}


if __name__ == "__main__":
    # Development/Test entry. Not production collection path.
    print("测试：菲律宾机构官网URL提取")
    print("=" * 60)
    batch_extract_websites(batch_size=30, country_filter="Philippines")
