import asyncio
import json
import logging
import re
from dataclasses import dataclass
from typing import Dict, List, Optional

import httpx

from services.llm_client import call_llm

logger = logging.getLogger(__name__)


PEOPLE_EXTRACTION_PROMPT = """You are a data extraction specialist. Extract leadership/team information from the following HTML content of an organization's leadership or team page.

HTML Content:
{html_content}

Organization Name: {org_name}

Instructions:
1. Extract the TOP 3 most senior leaders (CEO, President, Founder, Senior Pastor, Director, Chairman, Bishop, etc.)
2. For each person, extract:
   - Full name
   - Title/Position
   - Brief bio (if available, max 100 chars)
3. Return ONLY a JSON array in this exact format:
[
  {{
    "name": "Full Name",
    "title": "Job Title",
    "bio": "Brief description if available"
  }}
]

CRITICAL RULES - MUST FOLLOW:
- Only extract CURRENT leaders of THIS organization
- DO NOT extract: journalists, columnists, writers, contributors, editors, reporters, bloggers
- DO NOT extract: generic roles without specific names (e.g., "Contact Us", "Our Team")
- DO NOT extract: Admin, Webmaster, IT Support, Contact Person, Info Desk
- DO NOT extract: authors of articles on the page unless they are the organization's leaders
- DO NOT extract: board members or advisors unless explicitly listed on the leadership page
- Prioritize: CEO, President, Founder, Senior Pastor, Lead Pastor, Bishop, Archbishop, Executive Director, General Secretary, Superintendent, Overseer, Chairman
- If the page is not a leadership/team page, return []
- If no person names are found, return []
- Only extract REAL people with REAL titles
- Do NOT extract: menu items, navigation, footer text, copyright notices
"""


@dataclass
class PersonLLM:
    name: str
    title: str
    bio: str = ""
    confidence: int = 75


class PeopleExtractorLLM:
    """使用 LLM 从官网 Team/Leadership 页面提取 People 信息。"""

    def __init__(self, llm_call_func=None):
        self.llm_call_func = llm_call_func or self._default_llm_call
        self.client = httpx.Client(
            timeout=30.0,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
        )

    def close(self) -> None:
        self.client.close()

    def _default_llm_call(self, prompt: str) -> str:
        try:
            return call_llm(prompt, max_tokens=1200, temperature=0.1)
        except Exception as exc:
            logger.error("Failed to call LLM: %s", exc)
            return "[]"

    async def extract_from_html(self, org_name: str, html_content: str, source_url: str) -> List[PersonLLM]:
        truncated_html = (html_content or "")[:15000]
        text_content = self._clean_html(truncated_html)
        if len(text_content) < 300:
            return []

        prompt = PEOPLE_EXTRACTION_PROMPT.format(
            html_content=text_content[:8000],
            org_name=org_name,
        )

        try:
            response = await asyncio.to_thread(self.llm_call_func, prompt)
            people_data = self._parse_llm_response(response)

            people: List[PersonLLM] = []
            for item in people_data[:3]:
                name = str(item.get("name", "")).strip()
                title = str(item.get("title", "")).strip()
                bio = str(item.get("bio", "")).strip()[:100]
                if self._validate_person(name, title, org_name):
                    people.append(PersonLLM(name=name, title=title, bio=bio, confidence=75))
            return people
        except Exception as exc:
            logger.error("LLM extraction failed for %s: %s", org_name, exc)
            return []

    def extract_from_url(self, org_name: str, source_url: str) -> List[Dict]:
        try:
            response = self.client.get(source_url)
            if response.status_code != 200 or not response.text:
                return []
            people = asyncio.run(self.extract_from_html(org_name, response.text, source_url))
            return [
                {
                    "name": p.name,
                    "title": p.title,
                    "bio": p.bio,
                    "confidence": p.confidence,
                    "source_url": source_url,
                }
                for p in people
            ]
        except RuntimeError:
            loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(loop)
                response = self.client.get(source_url)
                if response.status_code != 200 or not response.text:
                    return []
                people = loop.run_until_complete(self.extract_from_html(org_name, response.text, source_url))
                return [
                    {
                        "name": p.name,
                        "title": p.title,
                        "bio": p.bio,
                        "confidence": p.confidence,
                        "source_url": source_url,
                    }
                    for p in people
                ]
            finally:
                loop.close()
        except Exception as exc:
            logger.error("LLM URL extraction failed for %s: %s", org_name, exc)
            return []

    def _clean_html(self, html: str) -> str:
        cleaned = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.DOTALL | re.IGNORECASE)
        cleaned = re.sub(r"<[^>]+>", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned)
        return cleaned.strip()

    def _parse_llm_response(self, response: str) -> List[Dict]:
        if not response:
            return []
        try:
            data = json.loads(response)
            return data if isinstance(data, list) else []
        except Exception:
            pass

        code_block = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", response)
        if code_block:
            try:
                data = json.loads(code_block.group(1))
                return data if isinstance(data, list) else []
            except Exception:
                pass

        array_match = re.search(r"\[\s*\{[\s\S]*\}\s*\]", response)
        if array_match:
            try:
                data = json.loads(array_match.group(0))
                return data if isinstance(data, list) else []
            except Exception:
                pass

        logger.warning("Failed to parse LLM response: %s", response[:200])
        return []

    def _validate_person(self, name: str, title: str, org_name: str) -> bool:
        if not name or not title:
            return False
        if len(name) < 3 or len(name) > 50:
            return False
        if len(title) < 2 or len(title) > 100:
            return False

        invalid_patterns = [
            r"^(about|contact|home|menu|search|login|subscribe|copyright|privacy)",
            r"^(follow|share|twitter|facebook|instagram|linkedin)",
            r"^\d+$",
        ]
        name_lower = name.lower()
        for pattern in invalid_patterns:
            if re.match(pattern, name_lower):
                return False

        title_keywords = [
            "ceo",
            "president",
            "founder",
            "pastor",
            "director",
            "bishop",
            "chairman",
            "leader",
            "head",
            "chief",
            "senior",
            "executive",
            "manager",
            "coordinator",
            "minister",
            "elder",
            "deacon",
            "principal",
            "dean",
            "superintendent",
            "secretary",
        ]
        title_lower = title.lower()
        if not any(keyword in title_lower for keyword in title_keywords):
            return False
        if name_lower == (org_name or "").lower():
            return False
        if not any(char.isupper() for char in name):
            return False
        return True


def extract_people_llm_sync(org_name: str, html_content: str, source_url: str) -> List[Dict]:
    extractor = PeopleExtractorLLM()
    try:
        try:
            running_loop = asyncio.get_running_loop()
            has_running_loop = running_loop.is_running()
        except RuntimeError:
            has_running_loop = False

        if not has_running_loop:
            people = asyncio.run(extractor.extract_from_html(org_name, html_content, source_url))
        else:
            import threading

            captured: Dict[str, List[PersonLLM]] = {}
            errors: List[Exception] = []

            def _runner() -> None:
                try:
                    captured["people"] = asyncio.run(extractor.extract_from_html(org_name, html_content, source_url))
                except Exception as exc:
                    errors.append(exc)

            thread = threading.Thread(target=_runner, daemon=True)
            thread.start()
            thread.join()
            if errors:
                raise errors[0]
            people = captured.get("people", [])
        return [
            {
                "name": p.name,
                "title": p.title,
                "bio": p.bio,
                "confidence": p.confidence,
                "source_url": source_url,
            }
            for p in people
        ]
    except Exception as exc:
        logger.error("LLM People extraction failed: %s", exc)
        return []
    finally:
        extractor.close()
