import argparse
import json
import logging
import os
import re
import sys
import uuid
from typing import Dict, List, Optional, Tuple
from urllib.parse import unquote, urlparse

import httpx
from sqlalchemy import or_

script_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.dirname(script_dir)
os.chdir(backend_dir)
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from models.database import LeaderCandidate, OrganizationProfile, SessionLocal
from services.llm_client import call_llm
from services.people_validator import PeopleValidator

logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


WIKI_PROMPT = """从以下Wikipedia文章内容中提取{org_name}的领导信息。

文章内容：
{text_content}

指令：
1. 提取最高级别的现任领导（CEO, President, Founder, Senior Pastor, Bishop等）
2. 优先从"Leadership"、"Organization"、"Structure"相关段落和infobox提取
3. 只提取现任领导，不要历史人物
4. 返回JSON数组：[{{"name": "全名", "title": "职位", "note": "备注"}}]
5. 没有具体人名返回[]
"""


def _wiki_title_from_url(wiki_url: str) -> Optional[str]:
    raw = (wiki_url or "").strip()
    if not raw:
        return None

    if "/wiki/" in raw:
        title = raw.split("/wiki/")[-1].split("#")[0].split("?")[0]
        return unquote(title).replace("_", " ").strip() or None

    if "title=" in raw:
        try:
            title = raw.split("title=")[-1].split("&")[0]
            return unquote(title).replace("_", " ").strip() or None
        except Exception:
            return None

    parsed = urlparse(raw)
    if parsed.netloc.endswith("wikipedia.org") and parsed.path:
        title = parsed.path.strip("/").split("/")[-1]
        return unquote(title).replace("_", " ").strip() or None

    return None


def fetch_wiki_extract(title: str) -> Optional[str]:
    url = "https://en.wikipedia.org/w/api.php"
    params = {
        "action": "query",
        "format": "json",
        "titles": title,
        "prop": "extracts",
        "explaintext": True,
        "exsectionformat": "wiki",
    }
    try:
        resp = httpx.get(url, params=params, timeout=20.0, follow_redirects=True)
        if resp.status_code != 200:
            return None
        data = resp.json()
        pages = (data.get("query") or {}).get("pages") or {}
        for pid, pd in pages.items():
            if str(pid) == "-1":
                return None
            content = (pd or {}).get("extract") or ""
            return content if len(content) > 200 else None
        return None
    except Exception:
        return None


def fetch_wiki_wikitext(title: str) -> Optional[str]:
    url = "https://en.wikipedia.org/w/api.php"
    params = {
        "action": "parse",
        "format": "json",
        "page": title,
        "prop": "wikitext",
        "formatversion": 2,
    }
    try:
        resp = httpx.get(url, params=params, timeout=20.0, follow_redirects=True)
        if resp.status_code != 200:
            return None
        data = resp.json()
        wikitext = ((data.get("parse") or {}).get("wikitext") or "")
        if isinstance(wikitext, dict):
            wikitext = wikitext.get("*") or ""
        return wikitext if len(wikitext) > 200 else None
    except Exception:
        return None


def _extract_focus_section(text: str) -> str:
    truncated = (text or "")[:12000]
    patterns = [
        r"(?i)==\s*leadership\s*==(.*?)(?:==|\Z)",
        r"(?i)==\s*organization\s*==(.*?)(?:==|\Z)",
        r"(?i)==\s*structure\s*==(.*?)(?:==|\Z)",
        r"(?i)==\s*government\s*==(.*?)(?:==|\Z)",
    ]
    for pat in patterns:
        m = re.search(pat, truncated, flags=re.DOTALL)
        if m and m.group(1).strip():
            return m.group(1).strip()
    return truncated


def _extract_infobox_leaders_from_wikitext(wikitext: str) -> List[str]:
    if not wikitext:
        return []
    snippet = wikitext[:20000]
    leaders: List[str] = []
    for m in re.finditer(
        r"\|\s*(?:leader|head|president|bishop|archbishop|moderator|chairman|ceo)\s*[_\w]*\s*=\s*([^\n|]+)",
        snippet,
        flags=re.IGNORECASE,
    ):
        value = (m.group(1) or "").strip()
        value = re.sub(r"\{\{.*?\}\}", "", value)
        value = re.sub(r"\[\[([^\]|]+)\|?[^\]]*\]\]", r"\1", value)
        value = re.sub(r"<[^>]+>", "", value).strip()
        value = re.sub(r"\s+", " ", value)
        if 2 < len(value) <= 80:
            leaders.append(value)

    seen = set()
    unique: List[str] = []
    for name in leaders:
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(name)
    return unique[:12]


def _parse_json_array(response: str) -> List[Dict]:
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

    array_match = re.search(r"(\[\s*\{[\s\S]*\}\s*\])", response)
    if array_match:
        try:
            data = json.loads(array_match.group(1))
            return data if isinstance(data, list) else []
        except Exception:
            pass
    return []


def extract_from_wiki(org_name: str, extract_text: str, wikitext: Optional[str]) -> List[Dict]:
    if not extract_text or len(extract_text) < 200:
        return []

    focus_text = _extract_focus_section(extract_text)
    infobox_leaders = _extract_infobox_leaders_from_wikitext(wikitext or "")

    if infobox_leaders:
        combined = (
            f"Organization: {org_name}\n"
            f"Infobox leaders:\n"
            + "\n".join(f"- {leader}" for leader in infobox_leaders)
            + "\n\nLeadership-related section:\n"
            + focus_text
        )
    else:
        combined = focus_text

    prompt = WIKI_PROMPT.format(org_name=org_name, text_content=combined[:9000])
    response = call_llm(prompt, max_tokens=600, temperature=0.1)
    return _parse_json_array(response)


def batch_extract(tier: str = "T1", batch_size: int = 100) -> None:
    db = SessionLocal()
    validator = PeopleValidator()
    try:
        orgs = (
            db.query(OrganizationProfile)
            .filter(
                OrganizationProfile.priority_tier == tier,
                or_(OrganizationProfile.leader_name == None, OrganizationProfile.leader_name == ""),
                OrganizationProfile.wikipedia_url != None,
                OrganizationProfile.wikipedia_url != "",
            )
            .order_by(OrganizationProfile.id)
            .limit(batch_size)
            .all()
        )

        print(f"找到 {len(orgs)} 家")
        updated = 0
        rejected = 0
        no_content = 0
        no_people = 0
        dup = 0

        for org in orgs:
            wiki_url = (org.wikipedia_url or "").strip()
            title = _wiki_title_from_url(wiki_url)
            if not title:
                no_content += 1
                print(f"[NO_CONTENT] {org.name}")
                continue

            extract_text = fetch_wiki_extract(title)
            if not extract_text:
                no_content += 1
                print(f"[NO_CONTENT] {org.name}")
                continue

            wikitext = fetch_wiki_wikitext(title)
            people = extract_from_wiki(org.name, extract_text, wikitext)
            if not people:
                no_people += 1
                print(f"[NO_PEOPLE] {org.name}")
                continue

            person = people[0] or {}
            name = str(person.get("name", "")).strip()
            title_str = str(person.get("title", "")).strip()
            if not name or len(name) < 3:
                no_people += 1
                print(f"[NO_PEOPLE] {org.name}")
                continue

            validation = validator.validate(
                candidate_name=name,
                candidate_title=title_str,
                org_name=org.name,
                org_country=org.country or "",
                source_url=wiki_url,
                extraction_method="wikipedia",
            )
            if validation.action == "reject":
                rejected += 1
                print(f"[REJECT] {org.name}: {name}")
                continue

            existing = (
                db.query(LeaderCandidate)
                .filter(
                    LeaderCandidate.organization_id == org.id,
                    LeaderCandidate.candidate_name == name,
                    LeaderCandidate.candidate_title == title_str,
                    LeaderCandidate.status.in_(["pending", "approved"]),
                )
                .first()
            )
            if existing:
                dup += 1
                print(f"[DUP] {org.name}: {name}")
                continue

            status = "approved" if validation.action == "approve" else "pending"
            db.add(
                LeaderCandidate(
                    id=str(uuid.uuid4()),
                    organization_id=org.id,
                    candidate_name=name,
                    candidate_title=title_str,
                    candidate_bio=str(person.get("note", "")).strip()[:120],
                    source_url=wiki_url,
                    extraction_method="wikipedia",
                    confidence=float(validation.confidence),
                    status=status,
                    validation_notes=validation.reason,
                )
            )

            if status == "approved" and float(validation.confidence) >= 0.75:
                org.leader_name = name
                org.leader_title = title_str
                org.leader_bio_url = wiki_url
                org.has_leadership_page = True
                org.confidence = max(float(org.confidence or 0.0), float(validation.confidence))
                updated += 1

            print(f"[OK] {org.name}: {name} - {title_str}")

        db.commit()
        t1_total = db.query(OrganizationProfile).filter(OrganizationProfile.priority_tier == tier).count()
        t1_people = (
            db.query(OrganizationProfile)
            .filter(
                OrganizationProfile.priority_tier == tier,
                OrganizationProfile.leader_name != None,
                OrganizationProfile.leader_name != "",
            )
            .count()
        )
        print(f"\nT1 People: {t1_people}/{t1_total} ({(t1_people / t1_total * 100) if t1_total else 0:.1f}%)")
        print(f"回写: {updated}")
        print(f"无内容: {no_content}")
        print(f"无人名: {no_people}")
        print(f"重复: {dup}")
        print(f"拒绝: {rejected}")
    finally:
        db.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--tier", default="T1")
    p.add_argument("--batch-size", type=int, default=100)
    a = p.parse_args()
    batch_extract(a.tier, a.batch_size)
