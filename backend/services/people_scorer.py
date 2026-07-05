"""
People Score 计算服务 V2
核心策略：最大化利用已有 deep crawl 数据，最小化 HTTP 探测
"""

import json
import re
from typing import Dict, Optional
from urllib.parse import urljoin, urlparse

import requests

from models.database import OrganizationProfile

REQUEST_TIMEOUT = 3


class PeopleScorerV2:
    BOARD_PATHS = ["/board", "/directors", "/about/board", "/governance", "/trustees", "/advisory-board"]
    PEOPLE_PATHS = ["/people", "/leadership", "/team", "/about/team", "/our-team", "/executive-team"]

    PEOPLE_PAGE_KEYWORDS = [
        "leadership",
        "team",
        "people",
        "staff",
        "board",
        "directors",
        "governance",
        "executive",
        "senior",
        "our-team",
    ]

    def __init__(self, timeout: int = REQUEST_TIMEOUT):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.max_redirects = 2
        self.session.headers.update({"User-Agent": "Mozilla/5.0 (compatible; ChristianIntelBot/1.0)"})

    def score_from_record(self, org: OrganizationProfile) -> Dict:
        """
        V2 评分主入口：
        1. 从已有字段提取 Leadership + Team 信号
        2. 从 pages_crawled 提取 Board + Depth 信号
        3. 仅当 pages_crawled 为空或无有效 people 页面时才发 1-2 个轻探测
        """
        result = {
            "total_score": 0,
            "grade": "F",
            "dimensions": {
                "leadership": 0,
                "team": 0,
                "board": 0,
                "depth": 0,
            },
            "pages_found": [],
            "data_source": "record",
            "error": None,
        }

        result["dimensions"]["leadership"] = self._score_leadership(org)
        result["dimensions"]["team"] = self._score_team(org)

        board_score, depth_score, pages, source = self._score_board_and_depth(org)
        result["dimensions"]["board"] = board_score
        result["dimensions"]["depth"] = depth_score
        result["pages_found"] = pages
        result["data_source"] = source

        result["total_score"] = sum(result["dimensions"].values())
        result["grade"] = self._score_to_grade(result["total_score"])
        return result

    def _score_leadership(self, org: OrganizationProfile) -> int:
        score = 0
        if org.leader_name and len(org.leader_name.strip()) > 1:
            score += 15
        if org.leader_title and len(org.leader_title.strip()) > 1:
            score += 10
        if org.leader_bio_url and len(org.leader_bio_url.strip()) > 5:
            score += 5
        return min(score, 30)

    def _score_team(self, org: OrganizationProfile) -> int:
        score = 0
        if org.employee_count and org.employee_count > 0:
            score += 10
            if org.employee_count >= 10:
                score += 5
            if org.employee_count >= 50:
                score += 5
        if org.has_leadership_page:
            score += 5
        if org.church_count and org.church_count > 1:
            score += 5
        return min(score, 25)

    def _score_board_and_depth(self, org: OrganizationProfile) -> tuple[int, int, list[str], str]:
        pages_crawled_raw = org.pages_crawled or ""
        if not pages_crawled_raw:
            if org.official_website:
                return self._probe_single(org.official_website)
            return 0, 0, [], "record"

        pages = self._extract_pages(org, pages_crawled_raw)
        people_pages = []
        for page in pages:
            normalized_page = page.strip()
            lower_page = normalized_page.lower()
            if any(keyword in lower_page for keyword in self.PEOPLE_PAGE_KEYWORDS):
                people_pages.append(normalized_page)

        if not people_pages:
            if org.official_website:
                return self._probe_single(org.official_website)
            return 0, 0, [], "record"

        board_score = 0
        depth_score = 0
        fetched_pages: list[str] = []
        for url in people_pages[:2]:
            html = self._fetch(url)
            if html:
                fetched_pages.append(url)
                board_score = max(board_score, self._analyze_board(html))
                depth_score = max(depth_score, self._analyze_depth(html))

        if fetched_pages:
            return board_score, depth_score, fetched_pages, "pages_crawled"

        if org.official_website:
            return self._probe_single(org.official_website)
        return 0, 0, [], "record"

    def _extract_pages(self, org: OrganizationProfile, pages_crawled_raw: str) -> list[str]:
        try:
            pages = json.loads(pages_crawled_raw)
        except (json.JSONDecodeError, TypeError):
            pages = [item.strip() for item in str(pages_crawled_raw).split(",") if item.strip()]

        if isinstance(pages, str):
            pages = [item.strip() for item in pages.split(",") if item.strip()]
        if not isinstance(pages, list):
            pages = [pages]

        extracted_pages: list[str] = []
        base = self._normalize_url(org.official_website or "")
        for item in pages:
            candidate = None
            if isinstance(item, dict):
                candidate = item.get("url") or item.get("page_url") or item.get("path")
            else:
                candidate = str(item).strip()

            if not candidate:
                continue

            candidate = candidate.strip()
            if candidate.startswith("/"):
                if base:
                    candidate = urljoin(base, candidate)
                else:
                    continue
            elif not candidate.startswith(("http://", "https://")):
                if base:
                    candidate = urljoin(base + "/", candidate.lstrip("/"))
                else:
                    continue

            extracted_pages.append(candidate)

        seen = set()
        deduped = []
        for page in extracted_pages:
            if page in seen:
                continue
            seen.add(page)
            deduped.append(page)
        return deduped

    def _probe_single(self, website: str) -> tuple[int, int, list[str], str]:
        base = self._normalize_url(website)
        if not base:
            return 0, 0, [], "record"

        url = urljoin(base, "/leadership")
        html = self._fetch(url)
        if not html:
            url = urljoin(base, "/team")
            html = self._fetch(url)

        if html:
            return self._analyze_board(html), self._analyze_depth(html), [url], "probe"
        return 0, 0, [], "record"

    def _analyze_board(self, html: str) -> int:
        text = html.lower()
        score = 0

        board_kws = ["board", "director", "trustee", "governance", "council", "elders", "oversight"]
        if any(keyword in text for keyword in board_kws):
            score += 10

        names = re.findall(r"[A-Z][a-z]+ [A-Z][a-z]+", html)
        unique_names = len(set(names))
        if unique_names >= 3:
            score += 10
        if unique_names >= 6:
            score += 5

        return min(score, 25)

    def _analyze_depth(self, html: str) -> int:
        text = html.lower()
        score = 0

        img_count = html.count("<img")
        if img_count >= 3:
            score += 8
        elif img_count >= 1:
            score += 4

        bio_kws = [
            "biography",
            "bio",
            "about ",
            "background",
            "education",
            "experience",
            "previously",
            "served as",
            "ordained",
            "graduated",
            "degrees",
        ]
        bio_count = sum(1 for keyword in bio_kws if keyword in text)
        if bio_count >= 2:
            score += 6
        if bio_count >= 4:
            score += 6

        return min(score, 20)

    def _fetch(self, url: str) -> Optional[str]:
        try:
            resp = self.session.get(url, timeout=self.timeout)
            if resp.status_code == 200 and len(resp.text) > 300:
                return resp.text
        except Exception:
            pass
        return None

    def _normalize_url(self, url: str) -> Optional[str]:
        url = (url or "").strip()
        if not url:
            return None
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        parsed = urlparse(url)
        if not parsed.netloc:
            return None
        return f"{parsed.scheme}://{parsed.netloc}"

    def _score_to_grade(self, score: int) -> str:
        if score >= 80:
            return "A"
        if score >= 60:
            return "B"
        if score >= 40:
            return "C"
        if score >= 20:
            return "D"
        return "F"


PeopleScorer = PeopleScorerV2
