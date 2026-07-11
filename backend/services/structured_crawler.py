import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from urllib.parse import urljoin, urlparse

import httpx

from crawlers.website_deep_crawler import assess_ai_maturity_v2, assess_digital_score_v2
from services.contact_intelligence import build_contact_candidates_from_crawl_result, extract_contact_candidates_from_text

logger = logging.getLogger(__name__)

NON_HTML_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".svg",
    ".bmp",
    ".ico",
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".zip",
    ".mp3",
    ".wav",
    ".m4a",
    ".mp4",
    ".avi",
    ".mov",
}

EMAIL_BLACKLIST = [
    "user@domain.com",
    "admin@example.com",
    "info@example.com",
    "contact@domain.com",
    "support@domain.com",
    "hello@example.com",
    "email@domain.com",
    "noreply@",
    "no-reply@",
    "webmaster@",
    "postmaster@",
    "hostmaster@",
    "test@",
    "demo@",
    "sample@",
]


PRIORITY_PAGES = [
    # About
    "/about",
    "/about-us",
    "/who-we-are",
    "/our-story",
    "/aboutus",
    "/whoweare",
    "/aboutourministry",
    "/about-our-ministry",
    "/learn-more-about-us",
    "/whoarewe",
    "/overview",
    # Mission / vision / beliefs
    "/mission",
    "/our-mission",
    "/vision",
    "/purpose",
    "/ourvision",
    "/missionandvision",
    "/mission-and-vision",
    "/whatwebelieve",
    "/what-we-believe",
    "/statement-of-faith",
    "/faith",
    "/doctrine",
    "/beliefs",
    # Leadership
    "/leadership",
    "/team",
    "/our-team",
    "/leaders",
    "/staff",
    "/board",
    "/ourleadership",
    "/our-staff",
    "/team-members",
    "/meettheteam",
    "/meet-the-team",
    "/people",
    "/ourpeople",
    "/directors",
    "/executive-team",
    "/senior-leadership",
    "/governing-board",
    # Programs / ministries
    "/programs",
    "/ministries",
    "/what-we-do",
    "/our-work",
    "/ourministries",
    "/our-programs",
    "/ministry",
    "/initiatives",
    "/projects",
    "/services",
    "/whatwedo",
    "/impact",
    "/our-impact",
    "/outreach",
    "/community",
    "/activities",
    "/campaigns",
    # Donate
    "/donate",
    "/giving",
    "/support",
    "/contribute",
    "/give",
    "/donatenow",
    "/make-a-donation",
    "/partner-with-us",
    "/ways-to-give",
    "/financial-support",
    "/join-us",
    # Contact
    "/contact",
    "/contact-us",
    "/contactus",
    "/getintouch",
    "/get-in-touch",
    "/reach-us",
    "/locations",
    "/offices",
    "/find-us",
    "/annual-report",
    "/reports",
    "/financials",
    "/partner",
    "/partners",
    "/collaborate",
    "/jobs",
    "/careers",
    "/opportunities",
    "/events",
    "/resources",
    "/library",
    "/blog",
    "/news",
    "/press",
    "/privacy",
    "/privacy-policy",
]


PAGE_FIELD_MAP = {
    "about": ["has_about", "description", "about_text"],
    "mission": ["has_mission", "mission_statement"],
    "vision": ["has_vision", "vision_statement"],
    "leadership": ["has_leadership_page", "leader_name", "leader_title"],
    "programs": ["has_programs"],
    "donate": ["has_donate"],
    "contact": ["has_contact", "contact_email"],
    "annual_report": ["has_annual_report"],
    "partner_page": ["has_partner_page"],
    "jobs": ["has_jobs"],
    "events": ["has_events"],
    "resources": ["has_resources"],
    "blog": ["has_blog"],
    "press": ["has_press"],
    "privacy": ["has_privacy"],
}


@dataclass
class CrawlResult:
    page_type: str
    url: str
    html: str
    status_code: int
    text_content: str = ""
    extracted_info: Dict = field(default_factory=dict)


@dataclass
class DeepCrawlReport:
    org_id: str
    org_name: str
    base_url: str
    pages_crawled: List[CrawlResult]
    has_errors: bool
    error_log: List[str]

    def to_db_updates(self) -> Dict:
        updates: Dict = {}

        for page in self.pages_crawled:
            for field_name in PAGE_FIELD_MAP.get(page.page_type, []):
                if field_name.startswith("has_"):
                    updates[field_name] = True

        about_page = self._find_page("about")
        if about_page and about_page.text_content:
            clean_about = self._clean_summary_text(about_page.text_content)
            updates["description"] = clean_about[:2000]
            updates["about_text"] = about_page.text_content[:5000]
            updates["has_about"] = True

        mission_page = self._find_page("mission")
        if mission_page and mission_page.text_content:
            updates["mission_statement"] = self._clean_summary_text(mission_page.text_content)[:2000]
            updates["has_mission"] = True

        vision_page = self._find_page("vision")
        if vision_page and vision_page.text_content:
            updates["vision_statement"] = self._clean_summary_text(vision_page.text_content)[:2000]
            updates["has_vision"] = True

        contact_page = self._find_page("contact")
        if contact_page:
            contact_candidates = build_contact_candidates_from_crawl_result(
                {
                    "emails": re.findall(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", contact_page.html or contact_page.text_content or ""),
                    "phones": re.findall(r"(\+?\d[\d\s\-\(\)]{7,}\d)", contact_page.html or contact_page.text_content or ""),
                    "source_url": contact_page.url,
                    "source_name": "structured_crawler",
                    "source_context": "contact_page",
                },
                organization_url=self.base_url,
                extraction_method="regex",
            )
            contact_candidates.extend(
                extract_contact_candidates_from_text(
                    contact_page.html or contact_page.text_content or "",
                    source_url=contact_page.url,
                    source_name="structured_crawler",
                    organization_url=self.base_url,
                    source_context="contact_page",
                )
            )
            for candidate in contact_candidates:
                candidate_type = candidate.get("type")
                platform = candidate.get("platform")
                if candidate_type == "email" and "contact_email" not in updates:
                    updates["contact_email"] = candidate["normalized_value"]
                elif candidate_type == "phone" and "phone_public" not in updates:
                    updates["phone_public"] = candidate["normalized_value"]
                elif candidate_type == "social_profile" and platform == "facebook" and "facebook_url" not in updates:
                    updates["facebook_url"] = candidate["normalized_value"]
                elif candidate_type == "social_profile" and platform == "youtube" and "youtube_url" not in updates:
                    updates["youtube_url"] = candidate["normalized_value"]
                elif candidate_type == "social_profile" and platform == "telegram" and "telegram_username" not in updates:
                    updates["telegram_username"] = candidate["value"]
            updates["has_contact"] = True

        all_text = "\n\n".join(page.text_content for page in self.pages_crawled if page.text_content)
        digital_flags = self._extract_digital_flags(all_text)
        updates.update(digital_flags)
        updates["ai_maturity_score"] = assess_ai_maturity_v2(bool(digital_flags.get("has_ai_initiative")), all_text)
        digital_extracted = {
            "has_ai_content": bool(digital_flags.get("has_ai_initiative")),
            "has_online_giving": bool(digital_flags.get("has_online_giving")),
            "has_mobile_app": bool(digital_flags.get("has_mobile_app")),
        }
        updates["digital_score"] = assess_digital_score_v2(digital_extracted, all_text)

        ai_snippet = self._extract_keyword_snippet(all_text, ["artificial intelligence", "ai", "machine learning", "chatbot"])
        if ai_snippet:
            updates["ai_strategy"] = ai_snippet[:2000]

        return updates

    def _find_page(self, page_type: str) -> Optional[CrawlResult]:
        for page in self.pages_crawled:
            if page.page_type == page_type:
                return page
        return None

    @staticmethod
    def _extract_email(html: str) -> Optional[str]:
        matches = re.findall(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", html or "")
        for match in matches:
            match_lower = match.lower()
            if any(blacklisted in match_lower for blacklisted in EMAIL_BLACKLIST):
                continue
            if "domain.com" in match_lower or "example." in match_lower:
                continue
            if len(match) > 50:
                continue
            return match
        return None

    @staticmethod
    def _extract_digital_flags(text: str) -> Dict[str, bool]:
        lowered = (text or "").lower()
        has_ai = any(
            token in lowered
            for token in [
                "artificial intelligence",
                " ai ",
                "machine learning",
                "chatbot",
                "openai",
                "chatgpt",
                "ai strategy",
                "ai-powered",
            ]
        )
        has_giving = any(
            token in lowered
            for token in ["online giving", "give online", "donate online", "donation", "online donation"]
        )
        has_app = any(token in lowered for token in ["app store", "google play", "mobile app", "download our app"])
        return {
            "has_ai_initiative": has_ai,
            "has_online_giving": has_giving,
            "has_mobile_app": has_app,
        }

    @staticmethod
    def _extract_keyword_snippet(text: str, keywords: List[str]) -> Optional[str]:
        if not text:
            return None
        chunks = [chunk.strip() for chunk in re.split(r"\n{2,}", text) if chunk.strip()]
        for chunk in chunks:
            lowered = chunk.lower()
            if any(keyword in lowered for keyword in keywords):
                return chunk
        return None

    @staticmethod
    def _clean_summary_text(text: str) -> str:
        lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
        filtered: List[str] = []
        skip_tokens = {
            "search",
            "close",
            "menu",
            "arrow_back",
            "arrow_forward_ios",
            "select a region",
        }
        for line in lines:
            lowered = line.lower()
            if lowered in skip_tokens:
                continue
            if len(line) <= 2:
                continue
            if len(line) < 60:
                continue
            if sum(char.isalpha() for char in line) < 30:
                continue
            filtered.append(line)
            if len(" ".join(filtered)) >= 2200:
                break
        if not filtered:
            filtered = [line for line in lines if len(line) >= 30][:8]
        return "\n".join(filtered).strip()


class StructuredCrawler:
    """标准化官网深采器。"""

    def __init__(self):
        self.client = httpx.AsyncClient(
            timeout=15.0,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            },
        )

    async def close(self):
        await self.client.aclose()

    async def crawl_organization(
        self,
        org_id: str,
        org_name: str,
        base_url: str,
        max_total_time: int = 30,
    ) -> DeepCrawlReport:
        start_time = time.time()
        normalized_base = self._normalize_base_url(base_url)
        report = DeepCrawlReport(
            org_id=org_id,
            org_name=org_name,
            base_url=normalized_base,
            pages_crawled=[],
            has_errors=False,
            error_log=[],
        )

        try:
            home_resp = await self.client.get(normalized_base, timeout=8)
            if home_resp.status_code != 200:
                report.has_errors = True
                report.error_log.append(f"Homepage HTTP {home_resp.status_code}")
                if home_resp.status_code in {403, 429}:
                    report.error_log.append("BLOCKED")
                return report

            if not self._is_html_response(str(home_resp.url), home_resp.headers.get("content-type")):
                report.has_errors = True
                report.error_log.append(
                    f"Non-HTML homepage: {(home_resp.headers.get('content-type') or '').lower()}"
                )
                return report

            home_html = home_resp.text or ""
            nav_links = self._extract_nav_links(home_html, normalized_base)
            is_redirect_trap = await self._detect_homepage_redirect_trap(normalized_base, home_html)
            if is_redirect_trap:
                sections = self._extract_sections_from_homepage(home_html)
                for section_type, section_html in sections.items():
                    section_text = self._html_to_text(section_html)
                    if len(section_text) < 80:
                        continue
                    report.pages_crawled.append(
                        CrawlResult(
                            page_type=section_type,
                            url=normalized_base,
                            html=section_html,
                            status_code=200,
                            text_content=section_text,
                            extracted_info={},
                        )
                    )

                if not report.pages_crawled:
                    home_text = self._html_to_text(home_html)
                    if home_text:
                        report.pages_crawled.append(
                            CrawlResult(
                                page_type="about",
                                url=normalized_base,
                                html=home_html,
                                status_code=200,
                                text_content=home_text,
                                extracted_info={},
                            )
                        )

                if not report.pages_crawled:
                    report.has_errors = True
                    report.error_log.append("Homepage redirect trap detected but no usable sections found")
                return report
        except httpx.TimeoutException:
            report.has_errors = True
            report.error_log.append("Homepage timeout (8s)")
            return report
        except Exception as exc:
            report.has_errors = True
            report.error_log.append(f"Homepage error: {str(exc)[:300]}")
            return report

        crawled_types = set()
        visited_urls = set()

        for page_path in PRIORITY_PAGES:
            if time.time() - start_time > max_total_time:
                report.error_log.append(
                    f"Total time limit ({max_total_time}s) reached, stopped at {len(report.pages_crawled)} pages"
                )
                break

            page_type = self._path_to_page_type(page_path)
            if page_type in crawled_types:
                continue

            page_url = nav_links.get(self._normalize_path(page_path), urljoin(normalized_base + "/", page_path.lstrip("/")))
            if page_url in visited_urls:
                continue
            visited_urls.add(page_url)

            try:
                resp = await self.client.get(page_url, timeout=6)
                if resp.status_code != 200:
                    continue
                if not self._is_allowed_link(str(resp.url), urlparse(normalized_base).netloc.lower()):
                    continue
                if not self._is_html_response(str(resp.url), resp.headers.get("content-type")):
                    logger.warning("  [SKIP] 非 HTML 页面: %s @ %s", page_type, str(resp.url))
                    continue
                is_valid = await self._validate_page_semantics(page_type, resp.text, org_name, str(resp.url))
                if not is_valid:
                    logger.warning("  [SKIP] 页面语义不匹配: %s @ %s", page_type, page_url)
                    continue
                text = self._html_to_text(resp.text)
                if len(text) < 80:
                    continue

                result = CrawlResult(
                    page_type=page_type,
                    url=str(resp.url),
                    html=resp.text,
                    status_code=resp.status_code,
                    text_content=text,
                    extracted_info={},
                )
                report.pages_crawled.append(result)
                crawled_types.add(page_type)
                logger.info("  [OK] %s: %s @ %s", org_name, page_type, str(resp.url))
            except httpx.TimeoutException:
                report.error_log.append(f"{page_type}: timeout (6s)")
                continue
            except httpx.TooManyRedirects:
                report.error_log.append(f"{page_type}: too many redirects")
                continue
            except Exception as exc:
                report.error_log.append(f"{page_type}: {str(exc)[:300]}")
                continue

        if not report.pages_crawled:
            report.has_errors = True
            report.error_log.append("No pages successfully crawled")
            return report

        if report.error_log:
            report.has_errors = True
        return report

    async def _validate_page_semantics(
        self,
        page_type: str,
        html: str,
        expected_org_name: str,
        final_url: str = "",
    ) -> bool:
        """校验页面标题是否与预期语义匹配，避免 302 到无关子页面。"""
        title_match = re.search(r"<title[^>]*>(.*?)</title>", html or "", re.IGNORECASE | re.DOTALL)
        title = re.sub(r"\s+", " ", title_match.group(1)).lower().strip() if title_match else ""
        h1_match = re.search(r"<h1[^>]*>(.*?)</h1>", html or "", re.IGNORECASE | re.DOTALL)
        h1 = re.sub(r"<[^>]+>", " ", h1_match.group(1)).lower().strip() if h1_match else ""

        org_name_lower = (expected_org_name or "").lower()
        org_words = re.findall(r"[a-zA-Z][a-zA-Z']+", org_name_lower)
        key_org_words = [word for word in org_words if len(word) > 3][:3]
        has_org_reference = any(word in title or word in h1 for word in key_org_words)

        page_keywords = {
            "about": ["about", "who we are", "our story", "overview"],
            "mission": ["mission", "vision", "purpose", "calling"],
            "vision": ["vision", "purpose", "future"],
            "leadership": ["leadership", "team", "leaders", "directors", "staff", "board"],
            "programs": ["programs", "ministries", "services", "initiatives", "projects"],
            "donate": ["donate", "give", "support", "contribute", "giving"],
            "contact": ["contact", "reach us", "get in touch", "locations"],
            "jobs": ["careers", "jobs", "opportunities", "join us", "work with us"],
            "events": ["events", "calendar", "upcoming", "gatherings"],
            "blog": ["blog", "news", "stories", "updates", "articles"],
            "press": ["press", "media", "newsroom", "media kit"],
            "privacy": ["privacy", "policy", "terms"],
        }
        type_keywords = page_keywords.get(page_type, [])
        has_type_reference = any(keyword in title or keyword in h1 for keyword in type_keywords)

        path = (urlparse(final_url).path or "").lower()
        path_segments = [segment for segment in path.split("/") if segment]
        final_slug = path_segments[-1] if path_segments else ""
        path_text = " ".join(path_segments)
        has_path_reference = any(keyword.replace(" ", "-") in path or keyword in path_text for keyword in type_keywords)

        generic_reject_tokens = [
            "podcast",
            "audio_message",
            "audio-message",
            "sermon",
            "episode",
            "worksheet",
            "download",
            "wp-content",
            "uploads",
            "attachment",
            "category",
            "tag",
            "author",
        ]
        if any(token in path for token in generic_reject_tokens):
            return False
        if re.search(r"/\d{4}/\d{2}/", path):
            return False
        if re.search(r"-\d{4}$", final_slug) and not has_org_reference:
            return False

        page_type_reject_tokens = {
            "about": ["article", "judas", "message"],
            "leadership": ["podcast", "audio", "video", "sermon"],
            "donate": ["thanks", "thanksgiving", "god-thanks"],
            "contact": ["form-", "leadership"],
        }
        if any(token in path for token in page_type_reject_tokens.get(page_type, [])):
            return False

        if not title_match and not h1_match and not final_url:
            return True
        return has_org_reference or has_type_reference or has_path_reference

    def _is_html_response(self, final_url: str, content_type: Optional[str]) -> bool:
        parsed_path = (urlparse(final_url).path or "").lower()
        if any(parsed_path.endswith(ext) for ext in NON_HTML_EXTENSIONS):
            return False
        lowered_content_type = (content_type or "").lower()
        if lowered_content_type and "text/html" not in lowered_content_type and "application/xhtml+xml" not in lowered_content_type:
            return False
        return True

    async def _detect_homepage_redirect_trap(self, base: str, home_html: str) -> bool:
        """检测站点是否把大多数路径重定向回首页。"""
        try:
            test_resp = await self.client.get(f"{base}/this-page-definitely-does-not-exist-12345", timeout=5)
            if test_resp.status_code != 200:
                return False
            if not self._is_html_response(str(test_resp.url), test_resp.headers.get("content-type")):
                return False
            test_text = self._html_to_text(test_resp.text)[:500]
            home_text = self._html_to_text(home_html)[:500]
            similarity = self._text_similarity(test_text, home_text)
            if similarity > 0.8:
                logger.warning("Homepage redirect trap detected for %s", base)
                return True
        except Exception:
            return False
        return False

    def _text_similarity(self, text1: str, text2: str) -> float:
        """简单词集相似度，用于判断未知路径是否回到首页。"""
        if not text1 or not text2:
            return 0.0
        words1 = set(re.findall(r"[a-zA-Z]{3,}", text1.lower()))
        words2 = set(re.findall(r"[a-zA-Z]{3,}", text2.lower()))
        if not words1 or not words2:
            return 0.0
        intersection = words1 & words2
        return len(intersection) / max(len(words1), len(words2))

    def _extract_sections_from_homepage(self, html: str) -> Dict[str, str]:
        """从单页首页按 section id/class 提取常见模块。"""
        sections: Dict[str, str] = {}
        section_patterns = {
            "about": r"<(section|div)[^>]*(?:id|class)=[\"'][^\"']*(?:about|whoweare|ourstory)[^\"']*[\"'][^>]*>.*?</\1>",
            "mission": r"<(section|div)[^>]*(?:id|class)=[\"'][^\"']*(?:mission|vision|purpose|beliefs)[^\"']*[\"'][^>]*>.*?</\1>",
            "leadership": r"<(section|div)[^>]*(?:id|class)=[\"'][^\"']*(?:leadership|team|leaders|staff)[^\"']*[\"'][^>]*>.*?</\1>",
            "programs": r"<(section|div)[^>]*(?:id|class)=[\"'][^\"']*(?:programs|ministries|services|whatwedo)[^\"']*[\"'][^>]*>.*?</\1>",
            "contact": r"<(section|div)[^>]*(?:id|class)=[\"'][^\"']*(?:contact|getintouch|locations)[^\"']*[\"'][^>]*>.*?</\1>",
            "donate": r"<(section|div)[^>]*(?:id|class)=[\"'][^\"']*(?:donate|giving|support|give)[^\"']*[\"'][^>]*>.*?</\1>",
        }
        for section_type, pattern in section_patterns.items():
            match = re.search(pattern, html or "", re.IGNORECASE | re.DOTALL)
            if match:
                sections[section_type] = match.group(0)
        return sections

    def _normalize_base_url(self, base_url: str) -> str:
        candidate = (base_url or "").strip().strip("`").strip()
        if not candidate.startswith(("http://", "https://")):
            candidate = f"https://{candidate}"
        return candidate.rstrip("/")

    def _extract_nav_links(self, html: str, base: str) -> Dict[str, str]:
        links: Dict[str, str] = {}
        base_host = (urlparse(base).netloc or "").lower()
        hrefs = re.findall(r'href=["\']([^"\']+)["\']', html or "", re.IGNORECASE)
        for href in hrefs[:1200]:
            lowered = href.lower()
            if not lowered or lowered.startswith(("#", "mailto:", "tel:", "javascript:")):
                continue
            if not any(
                token in lowered
                for token in [
                    "about",
                    "mission",
                    "vision",
                    "leadership",
                    "team",
                    "program",
                    "ministr",
                    "donat",
                    "giving",
                    "contact",
                    "annual",
                    "report",
                    "financial",
                    "partner",
                    "jobs",
                    "career",
                    "events",
                    "resources",
                    "library",
                    "blog",
                    "news",
                    "press",
                    "privacy",
                ]
            ):
                continue
            abs_url = urljoin(base + "/", href)
            if not self._is_allowed_link(abs_url, base_host):
                continue
            path_key = self._normalize_path(href)
            links[path_key] = abs_url
        return links

    def _is_allowed_link(self, abs_url: str, base_host: str) -> bool:
        parsed = urlparse(abs_url)
        host = (parsed.netloc or "").lower()
        if not host:
            return False
        blocked_hosts = ["google.com", "facebook.com", "instagram.com", "youtube.com", "linkedin.com", "x.com", "twitter.com"]
        if any(host == blocked or host.endswith("." + blocked) for blocked in blocked_hosts):
            return False
        if host == base_host or host.endswith("." + base_host) or base_host.endswith("." + host):
            return True
        return False

    def _path_to_page_type(self, path: str) -> str:
        path_lower = self._normalize_path(path).strip("/")
        mappings = {
            "about": "about",
            "about-us": "about",
            "who-we-are": "about",
            "our-story": "about",
            "aboutus": "about",
            "whoweare": "about",
            "aboutourministry": "about",
            "about-our-ministry": "about",
            "learn-more-about-us": "about",
            "whoarewe": "about",
            "overview": "about",
            "mission": "mission",
            "our-mission": "mission",
            "purpose": "mission",
            "missionandvision": "mission",
            "mission-and-vision": "mission",
            "whatwebelieve": "mission",
            "what-we-believe": "mission",
            "statement-of-faith": "mission",
            "faith": "mission",
            "doctrine": "mission",
            "beliefs": "mission",
            "vision": "vision",
            "our-vision": "vision",
            "ourvision": "vision",
            "leadership": "leadership",
            "team": "leadership",
            "our-team": "leadership",
            "leaders": "leadership",
            "staff": "leadership",
            "board": "leadership",
            "ourleadership": "leadership",
            "our-staff": "leadership",
            "team-members": "leadership",
            "meettheteam": "leadership",
            "meet-the-team": "leadership",
            "people": "leadership",
            "ourpeople": "leadership",
            "directors": "leadership",
            "executive-team": "leadership",
            "senior-leadership": "leadership",
            "governing-board": "leadership",
            "programs": "programs",
            "ministries": "programs",
            "what-we-do": "programs",
            "our-work": "programs",
            "ourministries": "programs",
            "our-programs": "programs",
            "ministry": "programs",
            "initiatives": "programs",
            "projects": "programs",
            "services": "programs",
            "whatwedo": "programs",
            "impact": "programs",
            "our-impact": "programs",
            "outreach": "programs",
            "community": "programs",
            "activities": "programs",
            "campaigns": "programs",
            "donate": "donate",
            "giving": "donate",
            "support": "donate",
            "contribute": "donate",
            "give": "donate",
            "donatenow": "donate",
            "make-a-donation": "donate",
            "partner-with-us": "donate",
            "ways-to-give": "donate",
            "financial-support": "donate",
            "join-us": "donate",
            "contact": "contact",
            "contact-us": "contact",
            "contactus": "contact",
            "getintouch": "contact",
            "get-in-touch": "contact",
            "reach-us": "contact",
            "locations": "contact",
            "offices": "contact",
            "find-us": "contact",
            "annual-report": "annual_report",
            "reports": "annual_report",
            "financials": "annual_report",
            "partner": "partner_page",
            "partners": "partner_page",
            "collaborate": "partner_page",
            "jobs": "jobs",
            "careers": "jobs",
            "opportunities": "jobs",
            "events": "events",
            "resources": "resources",
            "library": "resources",
            "blog": "blog",
            "news": "blog",
            "press": "press",
            "privacy": "privacy",
            "privacy-policy": "privacy",
        }
        return mappings.get(path_lower, "other")

    def _normalize_path(self, path: str) -> str:
        normalized = (path or "").lower().strip()
        if normalized.startswith("http"):
            normalized = urlparse(normalized).path
        normalized = normalized.rstrip("/")
        if not normalized.startswith("/"):
            normalized = "/" + normalized
        return normalized

    def _html_to_text(self, html: str) -> str:
        cleaned = re.sub(r"<(script|style|nav|footer|header)[^>]*>.*?</\1>", " ", html or "", flags=re.DOTALL | re.IGNORECASE)
        cleaned = re.sub(r"</(p|div|section|article|h[1-6]|li|br)>", "\n", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"<[^>]+>", " ", cleaned)
        cleaned = re.sub(r"\n\s*\n", "\n\n", cleaned)
        cleaned = re.sub(r"[ \t]+", " ", cleaned)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned.strip()


def crawl_organization_sync(
    org_id: str,
    org_name: str,
    base_url: str,
    max_total_time: int = 30,
) -> DeepCrawlReport:
    crawler = StructuredCrawler()
    try:
        return asyncio.run(crawler.crawl_organization(org_id, org_name, base_url, max_total_time=max_total_time))
    except Exception as exc:
        logger.error("Sync crawl failed for %s: %s", org_name, exc)
        return DeepCrawlReport(
            org_id=org_id,
            org_name=org_name,
            base_url=base_url,
            pages_crawled=[],
            has_errors=True,
            error_log=[str(exc)],
        )
    finally:
        try:
            asyncio.run(crawler.close())
        except Exception:
            pass
