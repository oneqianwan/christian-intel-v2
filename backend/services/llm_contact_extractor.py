import json
from typing import Any, Dict, List, Optional, Tuple

from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from services.llm_client import llm


def _fetch_page_html(url: str, timeout: int = 15, max_bytes: int = 250_000) -> str:
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        resp = httpx.get(url, headers=headers, timeout=timeout, follow_redirects=True, verify=False)
        resp.raise_for_status()
        text = resp.text or ""
        return text[:max_bytes]
    except Exception:
        return ""


def fetch_page_text(url: str, max_length: int = 3000) -> str:
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        resp = httpx.get(url, headers=headers, timeout=15, follow_redirects=True, verify=False)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "lxml")

        for tag in soup(["script", "style", "nav", "footer"]):
            tag.decompose()

        text = soup.get_text(separator="\n", strip=True)
        return text[:max_length]
    except Exception as e:
        return f"ERROR: {str(e)}"


def _extract_json_from_text(content: str) -> Tuple[Optional[str], Optional[str]]:
    if not content:
        return None, "empty_content"

    raw = content.strip()

    if "```json" in raw:
        try:
            json_str = raw.split("```json", 1)[1].split("```", 1)[0]
            return json_str.strip(), None
        except Exception:
            pass

    if "```" in raw:
        parts = raw.split("```")
        if len(parts) >= 3:
            return parts[1].strip(), None

    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        return raw[start : end + 1].strip(), None

    return None, "no_json_detected"


def extract_basic_from_homepage(page_text: str) -> Dict[str, Any]:
    import re

    result: Dict[str, Any] = {"general_email": None, "general_phone": None, "address": None}

    emails = re.findall(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", page_text or "")
    if emails:
        priority = [
            e
            for e in emails
            if any(kw in e.lower() for kw in ["info", "office", "contact", "admin", "communications", "media"])
        ]
        result["general_email"] = priority[0] if priority else emails[0]

    phones = re.findall(r"(\+?\d[\d\s\-\(\)]{7,}\d)", page_text or "")
    if phones:
        result["general_phone"] = phones[0][:50]

    return result


def _discover_candidate_pages(home_url: str, home_html: str) -> List[str]:
    if not home_url or not home_html:
        return []

    try:
        soup = BeautifulSoup(home_html, "lxml")
    except Exception:
        return []

    base_domain = urlparse(home_url).netloc.lower()
    keywords = [
        "leadership",
        "leaders",
        "team",
        "staff",
        "pastor",
        "pastors",
        "who-we-are",
        "about",
        "contact",
        "contact-us",
        "people",
        "our team",
        "our-team",
    ]

    urls: List[str] = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        if not href:
            continue
        text = (a.get_text(" ", strip=True) or "").strip()
        hay = (href + " " + text).lower()
        if not any(k in hay for k in keywords):
            continue
        abs_url = urljoin(home_url, href)
        d = urlparse(abs_url).netloc.lower()
        if d and base_domain and (d != base_domain):
            continue
        if abs_url in seen:
            continue
        seen.add(abs_url)
        urls.append(abs_url)
        if len(urls) >= 20:
            break
    return urls


def _choose_best_text_page(candidates: List[str]) -> Tuple[str, str]:
    best_url = ""
    best_text = ""
    best_score = -1
    keywords = ["pastor", "president", "bishop", "director", "secretary", "chairman", "founder", "executive"]

    for url in candidates:
        text = fetch_page_text(url, max_length=4000)
        if not text or text.startswith("ERROR"):
            continue
        low = text.lower()
        score = len(text)
        score += 500 if any(k in low for k in keywords) else 0
        score += 300 if any(k in low for k in ["leadership", "team", "who we are", "our team", "staff"]) else 0
        if score > best_score:
            best_score = score
            best_url = url
            best_text = text

    return best_url, best_text


async def extract_contacts_with_llm(page_text: str, org_name: str, org_website: str) -> Dict[str, Any]:
    if not page_text or page_text.startswith("ERROR"):
        return {"status": "failed", "error": "页面抓取失败"}

    if not getattr(llm, "enabled", False):
        fallback = extract_basic_from_homepage(page_text)
        return {
            "status": "failed",
            "error": "LLM未启用（缺少API Key）",
            "primary_contact": None,
            "secondary_contact": None,
            "general_email": fallback.get("general_email"),
            "general_phone": fallback.get("general_phone"),
            "address": fallback.get("address"),
            "confidence": "low",
            "notes": "LLM未启用，已使用规则降级提取",
        }

    prompt = f"""你是一个基督教机构信息提取助手。

请从以下"{org_name}"的Leadership/Team/Contact页面文本中，提取关键联系人信息。

提取优先级（从高到低）：
1. 第一优先级：项目负责人、投资负责人、对外联络人（Partnership/External Relations Director）
2. 第二优先级：机构最高负责人（Senior Pastor/President/Bishop/General Secretary/Executive Director）
3. 第三优先级：其他负责人（Associate Pastor/Director/Coordinator）
4. 第四优先级：普通联系人（Staff/Admin/Office contact）

同时提取：
- 公开邮箱（info@ / office@ / contact@ / 个人邮箱）
- 公开电话
- 办公地址

机构官网：{org_website}

页面文本：
---
{page_text}
---

请严格按以下JSON格式输出，只输出JSON，不要其他内容：

{{
    "primary_contact": {{
        "name": "负责人姓名（如找不到填null）",
        "title": "职位（如找不到填null）",
        "email": "邮箱（如找不到填null）",
        "phone": "电话（如找不到填null）",
        "priority": "1/2/3/4（对应上述优先级）"
    }},
    "secondary_contact": {{
        "name": "第二联系人姓名（如找不到填null）",
        "title": "职位（如找不到填null）",
        "email": "邮箱（如找不到填null）"
    }},
    "general_email": "通用邮箱（如info@ / office@，如找不到填null）",
    "general_phone": "通用电话（如找不到填null）",
    "address": "办公地址（如找不到填null）",
    "confidence": "high/medium/low（对结果的信心程度）",
    "notes": "额外说明（如'页面无明确负责人'或'只有通用联系方式'）"
}}

如果页面完全没有人员信息，返回：
{{
    "primary_contact": null,
    "secondary_contact": null,
    "general_email": null,
    "general_phone": null,
    "address": null,
    "confidence": "low",
    "notes": "页面无人员信息"
}}
"""

    try:
        async with httpx.AsyncClient(timeout=20, verify=False) as client:
            resp = await client.post(
                f"{llm.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {llm.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": llm.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                    "max_tokens": 800,
                },
            )

        data = resp.json()
        content = (((data or {}).get("choices") or [{}])[0].get("message") or {}).get("content") or ""

        json_str, err = _extract_json_from_text(content)
        if not json_str:
            fallback = extract_basic_from_homepage(page_text)
            return {
                "status": "failed",
                "error": f"LLM返回无法解析JSON: {err or 'unknown'}",
                "primary_contact": None,
                "secondary_contact": None,
                "general_email": fallback.get("general_email"),
                "general_phone": fallback.get("general_phone"),
                "address": fallback.get("address"),
                "confidence": "low",
                "notes": "LLM返回格式异常",
            }

        result = json.loads(json_str)
        if isinstance(result, dict):
            result["status"] = "success"
            return result

        fallback = extract_basic_from_homepage(page_text)
        return {
            "status": "failed",
            "error": "LLM输出不是JSON对象",
            "primary_contact": None,
            "secondary_contact": None,
            "general_email": fallback.get("general_email"),
            "general_phone": fallback.get("general_phone"),
            "address": fallback.get("address"),
            "confidence": "low",
            "notes": "LLM输出类型异常",
        }

    except Exception as e:
        fallback = extract_basic_from_homepage(page_text)
        return {
            "status": "failed",
            "error": f"LLM解析失败: {str(e)[:100]}",
            "primary_contact": None,
            "secondary_contact": None,
            "general_email": fallback.get("general_email"),
            "general_phone": fallback.get("general_phone"),
            "address": fallback.get("address"),
            "confidence": "low",
            "notes": "LLM解析异常",
        }


async def scrape_org_with_llm(org_name: str, org_website: str, title_hints: list) -> Dict[str, Any]:
    base_text = fetch_page_text(org_website)
    home_html = _fetch_page_html(org_website, timeout=15)

    leadership_paths = [
        "/leadership",
        "/team",
        "/about/leadership",
        "/about/team",
        "/pastors",
        "/leaders",
        "/our-team",
        "/who-we-are",
        "/about",
        "/contact",
        "/contact-us",
        "/people",
        "/staff",
    ]

    leadership_text = ""
    leadership_url = ""

    discovered = _discover_candidate_pages(org_website, home_html)
    guessed = [org_website.rstrip("/") + p for p in leadership_paths]
    candidates = []
    seen = set()
    for u in discovered + guessed:
        if u in seen:
            continue
        seen.add(u)
        candidates.append(u)

    best_url, best_text = _choose_best_text_page(candidates)
    if best_text:
        leadership_url = best_url
        leadership_text = best_text

    parse_text = leadership_text if leadership_text else base_text

    if len(parse_text) < 100:
        return {
            "status": "failed",
            "error": "页面内容太少",
            "fallback": extract_basic_from_homepage(base_text),
        }

    result = await extract_contacts_with_llm(parse_text, org_name, org_website)
    result["leadership_url"] = leadership_url or org_website
    result["source"] = "llm_extraction"
    return result
