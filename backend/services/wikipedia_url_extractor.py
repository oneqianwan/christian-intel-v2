import asyncio
import logging
import re
from typing import Dict, List, Optional
from urllib.parse import unquote, urlparse

import httpx


logger = logging.getLogger(__name__)


DEFAULT_USER_AGENT = "CIO-Bot/1.0 (christian-intel-v2; wikipedia infobox url extractor)"


def _is_http_url(value: str) -> bool:
    return isinstance(value, str) and (value.startswith("http://") or value.startswith("https://"))


def _extract_title_from_wiki_url(wiki_url: str) -> Optional[str]:
    try:
        parsed = urlparse(wiki_url)
        if "/wiki/" not in (parsed.path or ""):
            return None
        title = unquote(parsed.path.split("/wiki/", 1)[1]).replace("_", " ").strip()
        return title or None
    except Exception:
        return None


def _wikipedia_api_from_url(wiki_url: str) -> str:
    try:
        parsed = urlparse(wiki_url)
        if parsed.netloc and parsed.netloc.endswith("wikipedia.org"):
            return f"https://{parsed.netloc}/w/api.php"
    except Exception:
        pass
    return "https://en.wikipedia.org/w/api.php"


class WikipediaURLExtractor:
    def __init__(self):
        self.client = httpx.Client(
            timeout=15.0,
            headers={"User-Agent": DEFAULT_USER_AGENT},
            follow_redirects=True,
        )

    def close(self) -> None:
        self.client.close()

    def extract_from_page(self, org_name: str, wikipedia_url: Optional[str] = None) -> Optional[str]:
        if wikipedia_url:
            return self._extract_from_url(wikipedia_url)

        search_url = self._search_wikipedia(org_name)
        if search_url:
            return self._extract_from_url(search_url)
        return None

    def _search_wikipedia(self, org_name: str) -> Optional[str]:
        try:
            resp = self.client.get(
                "https://en.wikipedia.org/w/api.php",
                params={
                    "action": "opensearch",
                    "search": org_name,
                    "limit": 3,
                    "namespace": 0,
                    "format": "json",
                },
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
            if isinstance(data, list) and len(data) > 3 and data[3]:
                return data[3][0]
        except Exception as e:
            logger.error("Wikipedia搜索失败 %s: %s", org_name, str(e)[:200])
        return None

    def _extract_from_url(self, wiki_url: str) -> Optional[str]:
        title = _extract_title_from_wiki_url(wiki_url)
        api_url = _wikipedia_api_from_url(wiki_url)
        if not title:
            return None

        try:
            resp = self.client.get(
                api_url,
                params={
                    "action": "parse",
                    "page": title,
                    "format": "json",
                    "prop": "text",
                    "redirects": 1,
                },
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
            html = (((data.get("parse") or {}).get("text") or {}).get("*")) or ""
            if not html:
                return None

            candidates: List[str] = []

            infobox_website_patterns = [
                r"<th[^>]*>\s*Website\s*</th>\s*<td[^>]*>.*?href=\"([^\"]+)\"",
                r"Official website.*?href=\"([^\"]+)\"",
            ]
            for pattern in infobox_website_patterns:
                for match in re.findall(pattern, html, re.IGNORECASE | re.DOTALL):
                    candidates.append(match)

            for url in candidates:
                url = url.strip()
                if url.startswith("//"):
                    url = "https:" + url
                if _is_http_url(url) and "wikipedia.org" not in url and "wikidata.org" not in url:
                    return url

            ext_section = re.search(r"id=\"External_links\".*?</h2>(.*?)(<h2|$)", html, re.IGNORECASE | re.DOTALL)
            if ext_section:
                block = ext_section.group(1)
                for url in re.findall(r"href=\"(https?://[^\"]+)\"", block, re.IGNORECASE):
                    if "wikipedia.org" in url or "wikidata.org" in url:
                        continue
                    return url
        except Exception as e:
            logger.error("提取Wikipedia URL失败 %s: %s", wiki_url, str(e)[:200])

        return None


def find_urls_from_wikipedia(org_names: List[str]) -> Dict[str, str]:
    async def _runner() -> Dict[str, str]:
        names = [n for n in (org_names or []) if n and n.strip()]
        if not names:
            return {}

        semaphore = asyncio.Semaphore(10)
        results: Dict[str, str] = {}

        async with httpx.AsyncClient(
            timeout=15.0,
            headers={"User-Agent": DEFAULT_USER_AGENT},
            follow_redirects=True,
        ) as client:

            async def _search(name: str) -> Optional[str]:
                try:
                    resp = await client.get(
                        "https://en.wikipedia.org/w/api.php",
                        params={
                            "action": "opensearch",
                            "search": name,
                            "limit": 3,
                            "namespace": 0,
                            "format": "json",
                        },
                    )
                    if resp.status_code != 200:
                        return None
                    data = resp.json()
                    if isinstance(data, list) and len(data) > 3 and data[3]:
                        return data[3][0]
                except Exception:
                    return None
                return None

            async def _parse(wiki_url: str) -> Optional[str]:
                title = _extract_title_from_wiki_url(wiki_url)
                api_url = _wikipedia_api_from_url(wiki_url)
                if not title:
                    return None
                try:
                    resp = await client.get(
                        api_url,
                        params={
                            "action": "parse",
                            "page": title,
                            "format": "json",
                            "prop": "text",
                            "redirects": 1,
                        },
                    )
                    if resp.status_code != 200:
                        return None
                    data = resp.json()
                    html = (((data.get("parse") or {}).get("text") or {}).get("*")) or ""
                    if not html:
                        return None

                    candidates: List[str] = []
                    infobox_website_patterns = [
                        r"<th[^>]*>\s*Website\s*</th>\s*<td[^>]*>.*?href=\"([^\"]+)\"",
                        r"Official website.*?href=\"([^\"]+)\"",
                    ]
                    for pattern in infobox_website_patterns:
                        candidates.extend(re.findall(pattern, html, re.IGNORECASE | re.DOTALL))

                    for url in candidates:
                        url = url.strip()
                        if url.startswith("//"):
                            url = "https:" + url
                        if _is_http_url(url) and "wikipedia.org" not in url and "wikidata.org" not in url:
                            return url

                    ext_section = re.search(
                        r"id=\"External_links\".*?</h2>(.*?)(<h2|$)",
                        html,
                        re.IGNORECASE | re.DOTALL,
                    )
                    if ext_section:
                        block = ext_section.group(1)
                        for url in re.findall(r"href=\"(https?://[^\"]+)\"", block, re.IGNORECASE):
                            if "wikipedia.org" in url or "wikidata.org" in url:
                                continue
                            return url
                except Exception:
                    return None
                return None

            async def _worker(name: str) -> None:
                async with semaphore:
                    wiki_url = await _search(name)
                    if not wiki_url:
                        return
                    url = await _parse(wiki_url)
                    if url:
                        results[name] = url

            await asyncio.gather(*[_worker(n) for n in names])

        return results

    try:
        return asyncio.run(_runner())
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(_runner())
        finally:
            loop.close()
