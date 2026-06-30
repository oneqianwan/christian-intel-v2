import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin

import httpx


logger = logging.getLogger(__name__)


LEADERSHIP_TITLES = [
    "CEO",
    "Chief Executive Officer",
    "President",
    "Founder",
    "Co-Founder",
    "Director",
    "Executive Director",
    "Managing Director",
    "General Secretary",
    "Pastor",
    "Senior Pastor",
    "Lead Pastor",
    "Bishop",
    "Archbishop",
    "Elder",
    "Deacon",
    "Chaplain",
    "Minister",
    "Reverend",
    "Rev",
    "Chairman",
    "Vice Chairman",
    "Chair",
    "Vice Chair",
    "Head",
    "Leader",
    "Coordinator",
    "Superintendent",
    "CTO",
    "Chief Technology Officer",
    "IT Director",
    "Digital Director",
    "AI Director",
    "Technology Director",
    "Communications Director",
    "Principal",
    "Dean",
    "Provost",
    "Rector",
]


LEADERSHIP_PAGE_PATTERNS = [
    "/leadership",
    "/team",
    "/about/leadership",
    "/about/team",
    "/staff",
    "/people",
    "/board",
    "/trustees",
    "/governance",
    "/about-us/leadership",
    "/about-us/team",
    "/who-we-are",
    "/executive",
    "/senior-leadership",
    "/management",
]


@dataclass
class PersonInfo:
    name: str
    title: str
    source_url: str
    confidence: int = 70


class PeopleExtractor:
    def __init__(self):
        self.client = httpx.AsyncClient(
            timeout=15.0,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            },
        )

    async def close(self) -> None:
        await self.client.aclose()

    def _should_skip_url(self, website_url: Optional[str]) -> bool:
        low = (website_url or "").strip().lower()
        return not low or any(bad in low for bad in ["google.com/search", "wikipedia.org", "wikidata.org"])

    def _normalize_website_url(self, website_url: str) -> str:
        website_url = (website_url or "").strip()
        if not website_url.startswith("http"):
            website_url = "https://" + website_url
        return website_url.rstrip("/") + "/"

    async def extract_from_website(self, org_name: str, website_url: str) -> Optional[PersonInfo]:
        if self._should_skip_url(website_url):
            return None

        base_url = self._normalize_website_url(website_url)
        leadership_page = await self._find_leadership_page(base_url)
        if not leadership_page:
            leadership_page = base_url

        try:
            resp = await self.client.get(leadership_page)
            html = resp.text or ""
            if resp.status_code != 200 or len(html) < 1500:
                html = await self._fetch_with_playwright(leadership_page) or html
                if not html:
                    return None
            person = self._extract_person_from_html(html, leadership_page)
            if not person:
                return None
            return self._validate_and_clean(person, org_name)
        except Exception as e:
            logger.warning("提取People失败 %s: %s", org_name, str(e)[:200])
            return None

    async def _quick_find_leadership_page(self, base_url: str) -> Optional[str]:
        for pattern in LEADERSHIP_PAGE_PATTERNS[:5]:
            test_url = urljoin(base_url, pattern.lstrip("/"))
            try:
                resp = await self.client.head(test_url, timeout=5.0)
                if resp.status_code == 200:
                    return test_url
                if resp.status_code in (403, 405):
                    resp2 = await self.client.get(test_url, timeout=5.0)
                    if resp2.status_code == 200:
                        return str(resp2.url)
            except Exception:
                continue
        return None

    async def _find_leadership_page(self, base_url: str) -> Optional[str]:
        quick = await self._quick_find_leadership_page(base_url)
        if quick:
            return quick

        try:
            resp = await self.client.get(base_url, timeout=10.0)
            if resp.status_code != 200:
                return None
            html = resp.text or ""
            hrefs = re.findall(r'href=\"([^\"]+)\"', html, re.IGNORECASE)
            keywords_priority = [
                "leadership",
                "team",
                "staff",
                "board",
                "trustee",
                "governance",
                "executive",
                "management",
                "who-we-are",
                "about",
            ]
            scored_links: List[Tuple[int, str]] = []
            for href in hrefs[:500]:
                href_l = (href or "").lower()
                if not href_l or href_l.startswith("#") or href_l.startswith("mailto:") or href_l.startswith("tel:"):
                    continue
                for idx, keyword in enumerate(keywords_priority):
                    if keyword in href_l:
                        scored_links.append((idx, href))
                        break

            seen = set()
            ordered: List[str] = []
            for _, href in sorted(scored_links, key=lambda item: item[0]):
                if href in seen:
                    continue
                seen.add(href)
                ordered.append(href)

            for href in ordered[:15]:
                full_url = href if href.startswith("http") else urljoin(base_url, href)
                try:
                    resp2 = await self.client.get(full_url, timeout=8.0)
                    if resp2.status_code == 200:
                        return str(resp2.url)
                except Exception:
                    continue
        except Exception:
            return None

        return None

    async def _fetch_with_playwright(self, url: str) -> Optional[str]:
        try:
            from crawlers.dynamic_crawler import DynamicCrawler
        except Exception:
            return None

        crawler = DynamicCrawler(headless=True)
        try:
            result = await crawler.fetch_page(url, extract_text=False, timeout=15000, max_retries=1)
            return ((result or {}).get("html") or "")[:50000] or None
        except Exception:
            return None
        finally:
            try:
                await crawler.stop()
            except Exception:
                pass

    def _extract_person_from_html(self, html: str, source_url: str) -> Optional[PersonInfo]:
        blocks = self._find_person_blocks(html)
        for block in blocks[:5]:
            name = self._extract_name_from_block(block)
            title = self._extract_title_from_block(block)
            if name and title and self._is_valid_title(title):
                return PersonInfo(
                    name=self._normalize_person_name(name.strip()),
                    title=title.strip(),
                    source_url=source_url,
                    confidence=80,
                )

        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text).strip()[:20000]

        seed_titles = ["CEO", "President", "Founder", "Pastor", "Director", "Chairman", "Bishop"]
        for title in seed_titles:
            pattern = rf"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){{1,3}})[,\s-]+(?:{re.escape(title)})\b"
            m = re.search(pattern, text)
            if m and self._is_likely_person_name(m.group(1)):
                return PersonInfo(self._normalize_person_name(m.group(1)), title, source_url, 60)

        for title in seed_titles:
            pattern = rf"(?:{re.escape(title)})[:\s-]+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){{1,3}})\b"
            m = re.search(pattern, text)
            if m and self._is_likely_person_name(m.group(1)):
                return PersonInfo(self._normalize_person_name(m.group(1)), title, source_url, 55)

        combos = [
            "President and CEO",
            "Chief Executive Officer",
            "Executive Director",
            "Managing Director",
            "General Secretary",
            "Senior Pastor",
            "Lead Pastor",
        ]
        for combo in combos:
            pattern = rf"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){{1,3}})\s+{re.escape(combo)}\b"
            m = re.search(pattern, text)
            if m and self._is_likely_person_name(m.group(1)):
                return PersonInfo(self._normalize_person_name(m.group(1)), combo, source_url, 58)

        for combo in combos + ["president", "ceo", "executive director", "bishop", "archbishop"]:
            pattern = rf"announced\s+(?:today\s+)?that\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){{1,3}})\s+will\s+serve\s+as\s+(?:its\s+)?(?:new\s+)?{re.escape(combo)}"
            m = re.search(pattern, text, re.IGNORECASE)
            if m and self._is_likely_person_name(m.group(1)):
                return PersonInfo(self._normalize_person_name(m.group(1)), combo.title(), source_url, 55)

        return None

    def _normalize_person_name(self, name: str) -> str:
        words = [w for w in (name or "").split() if w]
        bad_prefixes = {"diversity", "global", "leadership", "ministry", "operations", "oneness", "director", "co-director"}
        while len(words) >= 3 and words[0].lower() in bad_prefixes:
            words = words[1:]
        if len(words) > 4:
            words = words[:4]
        return " ".join(words)

    def _find_person_blocks(self, html: str) -> List[str]:
        blocks: List[str] = []
        patterns = [
            r"<div[^>]*class=\"[^\"]*(?:team|member|person|leader|staff|director)[^\"]*\"[^>]*>.*?</div>",
            r"<div[^>]*class=\"[^\"]*(?:bio|profile|card)[^\"]*\"[^>]*>.*?</div>",
            r"<article[^>]*class=\"[^\"]*(?:team|member|person)[^\"]*\"[^>]*>.*?</article>",
            r"<li[^>]*class=\"[^\"]*(?:team|member|person)[^\"]*\"[^>]*>.*?</li>",
        ]
        for pattern in patterns:
            blocks.extend(re.findall(pattern, html, re.IGNORECASE | re.DOTALL))
        if not blocks:
            blocks = re.findall(r"<h[234][^>]*>.*?</h[234]>", html, re.IGNORECASE | re.DOTALL)
        return blocks

    def _extract_name_from_block(self, block: str) -> Optional[str]:
        for pattern in [r"<h[234][^>]*>(.*?)</h[234]>", r"<strong>(.*?)</strong>"]:
            m = re.search(pattern, block, re.IGNORECASE | re.DOTALL)
            if not m:
                continue
            name = self._clean_text(m.group(1))
            if self._is_likely_person_name(name):
                return name
        return None

    def _extract_title_from_block(self, block: str) -> Optional[str]:
        title_patterns = [
            r"<p[^>]*class=\"[^\"]*(?:title|role|position)[^\"]*\"[^>]*>(.*?)</p>",
            r"<span[^>]*class=\"[^\"]*(?:title|role|position)[^\"]*\"[^>]*>(.*?)</span>",
            r"<p[^>]*>(.*?)</p>",
            r"<span[^>]*>(.*?)</span>",
        ]
        for pattern in title_patterns:
            for match in re.findall(pattern, block, re.IGNORECASE | re.DOTALL):
                title = self._clean_text(match)
                if self._is_valid_title(title):
                    return title
        return None

    def _is_valid_title(self, text: str) -> bool:
        text_lower = (text or "").lower()
        return any(title.lower() in text_lower for title in LEADERSHIP_TITLES)

    def _is_likely_person_name(self, text: str) -> bool:
        if not text:
            return False
        text = text.strip()
        if len(text) < 3 or len(text) > 50:
            return False
        text_lower = text.lower()
        banned_prefixes = [
            "about",
            "contact",
            "team",
            "leadership",
            "staff",
            "meet",
            "our",
            "board",
            "directors",
            "follow",
            "share",
            "menu",
            "home",
            "back",
        ]
        if any(text_lower.startswith(prefix) for prefix in banned_prefixes):
            return False
        if re.fullmatch(r"\d+", text_lower):
            return False
        words = text.split()
        if len(words) < 1 or len(words) > 4:
            return False
        if text.islower():
            return False
        if any(c in text for c in ["@", "#", "$", "%", "*", "[", "]", "{", "}", "|", "\\", "<", ">", '"']):
            return False
        return bool([w for w in words if w and w[0].isupper() and len(w) > 1])

    def _clean_text(self, text: str) -> str:
        text = re.sub(r"<[^>]+>", "", text or "")
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def _validate_and_clean(self, person: PersonInfo, org_name: str) -> Optional[PersonInfo]:
        if not person.name or len(person.name) < 3 or len(person.name) > 40:
            return None
        org_words = set((org_name or "").lower().split())
        name_words = set((person.name or "").lower().split())
        if len(org_words & name_words) >= 2 and len(name_words) <= 3:
            logger.info("名字与机构名重叠过多，跳过: %s / %s", person.name, org_name)
            return None
        return person


class PeopleExtractorBatch(PeopleExtractor):
    """批量提取，复用浏览器实例"""

    def __init__(self, max_concurrent_tabs: int = 3):
        super().__init__()
        self.browser = None
        self.context = None
        self.pw = None
        self.max_concurrent_tabs = max(1, min(int(max_concurrent_tabs), 5))

    async def start_browser(self) -> None:
        if self.browser and self.context:
            return
        from playwright.async_api import async_playwright

        self.pw = await async_playwright().start()
        self.browser = await self.pw.chromium.launch(headless=True)
        self.context = await self.browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )

    async def close_browser(self) -> None:
        if self.context:
            await self.context.close()
            self.context = None
        if self.browser:
            await self.browser.close()
            self.browser = None
        if self.pw:
            await self.pw.stop()
            self.pw = None

    async def _render_with_batch_browser(self, url: str) -> Optional[str]:
        if not self.context:
            return None
        page = await self.context.new_page()
        try:
            await page.goto(url, timeout=15000, wait_until="domcontentloaded")
            await page.wait_for_timeout(1200)
            html = await page.content()
            return html or None
        except Exception:
            return None
        finally:
            await page.close()

    async def extract_batch(self, orgs: List[Tuple[str, str]]) -> List[Dict]:
        await self.start_browser()
        semaphore = asyncio.Semaphore(self.max_concurrent_tabs)
        results: List[Dict] = []

        async def _worker(org_name: str, website_url: str) -> None:
            if self._should_skip_url(website_url):
                return

            base_url = self._normalize_website_url(website_url)
            leadership_page = await self._quick_find_leadership_page(base_url)
            if not leadership_page:
                leadership_page = await self._find_leadership_page(base_url)
            if not leadership_page:
                return

            async with semaphore:
                try:
                    html = await self._render_with_batch_browser(leadership_page)
                    if not html:
                        resp = await self.client.get(leadership_page, timeout=10.0)
                        if resp.status_code != 200:
                            return
                        html = resp.text or ""
                    person = self._extract_person_from_html(html, leadership_page)
                    if not person:
                        logger.info("✗ %s: 未提取到People", org_name)
                        return
                    person = self._validate_and_clean(person, org_name)
                    if not person:
                        return
                    results.append(
                        {
                            "org_name": org_name,
                            "name": person.name,
                            "title": person.title,
                            "source_url": person.source_url,
                            "confidence": person.confidence,
                        }
                    )
                    logger.info("✓ %s: %s - %s", org_name, person.name, person.title)
                except Exception as e:
                    logger.warning("处理 %s 失败: %s", org_name, str(e)[:200])

        try:
            await asyncio.gather(*[_worker(org_name, website_url) for org_name, website_url in orgs])
        finally:
            await self.close_browser()

        return results


def extract_people_sync(org_name: str, website_url: str) -> Optional[Dict]:
    async def _runner() -> Optional[Dict]:
        extractor = PeopleExtractor()
        try:
            result = await extractor.extract_from_website(org_name, website_url)
            if not result:
                return None
            return {
                "name": result.name,
                "title": result.title,
                "source_url": result.source_url,
                "confidence": result.confidence,
            }
        finally:
            await extractor.close()

    try:
        return asyncio.run(_runner())
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(_runner())
        finally:
            loop.close()
