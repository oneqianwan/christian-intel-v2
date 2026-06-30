"""
LLM自动提取+打标签模块 — Day 6
从网页HTML/文本自动提取机构信息，自动写入organization_profiles并打Ontology标签
"""

import asyncio
import json
import os
import re
import sys
import threading
import uuid
from datetime import datetime
from typing import Dict, List, Optional

import httpx

script_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.dirname(script_dir)
os.chdir(backend_dir)
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

try:
    from backend.services.llm_client import get_llm_client
    from backend.models.database import (
        IntelligenceItem,
        OrganizationOntologyTag,
        OrganizationProfile,
        SessionLocal,
    )
except ImportError:
    from services.llm_client import get_llm_client
    from models.database import (
        IntelligenceItem,
        OrganizationOntologyTag,
        OrganizationProfile,
        SessionLocal,
    )


EXTRACTION_PROMPT = """你是一个基督教行业信息提取专家。请从以下网页内容中提取所有提到的基督教相关机构/组织。

网页标题: {title}
网页内容:
{text}

要求：
1. 提取所有机构名称（教会、事工、机构、基金会、媒体、科技公司等）
2. 对每个机构判断：
   - 类型（从以下选择）：church_network, local_church, mission_agency, seminary, faithtech_startup, media_outlet, relief_org, foundation, denomination, para_church, worship_ministry, bible_translation, educational_institution, research_org, conference_org, publishing_house, advocacy_org, youth_org, prayer_ministry, christian_accelerator, christian_vc, christian_marketplace, other
   - 国家（如果从内容中能判断）
   - 网站URL（如果有）
   - 简短描述（1-2句话）
   - 神学立场（从以下选择，可选）：catholic, orthodox, lutheran, reformed, anglican, baptist, methodist, pentecostal, charismatic, evangelical, interdenominational, nondenominational, fundamental, seventh_day_adventist, mennonite, wesleyan, presbyterian, congregational, anabaptist, conservative, progressive, liberation_theology, prosperity_gospel
   - 规模判断（从以下选择，可选）：mega_10000+, large_1000_10000, medium_500_1000, small_100_500, micro_50_100, house_church, unknown

输出格式（严格JSON）：
{{
  "organizations": [
    {{
      "name": "机构名称",
      "org_type": "类型代码",
      "country": "国家名或null",
      "website": "网址或null",
      "description": "描述",
      "theological_position": "神学立场代码或null",
      "scale": "规模代码或null",
      "confidence": "HIGH/MEDIUM/LOW"
    }}
  ]
}}

注意：
- 只输出JSON，不要其他文字
- 如果内容中没有基督教相关机构，返回空数组
- 不确定的信息填null
- confidence表示你对这个提取结果的置信度
"""


ORG_TYPE_TAG_MAP = {
    "church_network": "church_network",
    "local_church": "church_independent",
    "mission_agency": "mission_agency",
    "seminary": "seminary",
    "media_outlet": "media_outlet",
    "relief_org": "mission_relief",
    "foundation": "foundation_grant",
    "denomination": "church_denomination",
    "para_church": "parachurch",
    "worship_ministry": "parachurch",
    "bible_translation": "mission_bible_translation",
    "educational_institution": "seminary",
    "research_org": "association",
    "conference_org": "association",
    "publishing_house": "media_outlet",
    "advocacy_org": "ngo_christian",
    "youth_org": "parachurch",
    "prayer_ministry": "parachurch",
    "christian_accelerator": "accelerator",
    "christian_vc": "foundation_investment",
    "christian_marketplace": "faithtech_social",
    "other": "association",
}

THEOLOGY_TAG_MAP = {
    "catholic": "catholic",
    "orthodox": "orthodox",
    "lutheran": "lutheran",
    "reformed": "reformed",
    "anglican": "anglican",
    "baptist": "baptist",
    "methodist": "methodist",
    "pentecostal": "pentecostal",
    "charismatic": "charismatic",
    "evangelical": "evangelical",
    "interdenominational": "interdenominational",
    "nondenominational": "nondenominational",
}

SCALE_TAG_MAP = {
    "mega_10000+": "mega",
    "large_1000_10000": "large",
    "medium_500_1000": "medium",
    "small_100_500": "small",
    "micro_50_100": "micro",
    "house_church": "micro",
}

CONFIDENCE_SCORE_MAP = {
    "HIGH": 0.9,
    "MEDIUM": 0.75,
    "LOW": 0.55,
}

KNOWN_ORG_HINTS = {
    "Christianity Today": {
        "org_type": "media_outlet",
        "country": "美国",
        "website": "https://www.christianitytoday.com",
        "description": "领先的福音派基督教媒体机构。",
        "theological_position": "evangelical",
        "scale": "large_1000_10000",
        "confidence": "HIGH",
    },
    "World Vision International": {
        "org_type": "relief_org",
        "country": "全球",
        "website": "https://www.worldvision.org",
        "description": "全球性基督教救援与发展机构。",
        "theological_position": "interdenominational",
        "scale": "mega_10000+",
        "confidence": "HIGH",
    },
    "World Vision": {
        "org_type": "relief_org",
        "country": "全球",
        "website": "https://www.worldvision.org",
        "description": "全球性基督教救援与发展机构。",
        "theological_position": "interdenominational",
        "scale": "mega_10000+",
        "confidence": "HIGH",
    },
    "Cru": {
        "org_type": "para_church",
        "country": "美国",
        "website": "https://www.cru.org",
        "description": "大型跨校园福音与门训事工机构。",
        "theological_position": "evangelical",
        "scale": "large_1000_10000",
        "confidence": "HIGH",
    },
    "Campus Crusade for Christ": {
        "org_type": "para_church",
        "country": "美国",
        "website": "https://www.cru.org",
        "description": "Cru 的历史名称，大型跨校园福音事工。",
        "theological_position": "evangelical",
        "scale": "large_1000_10000",
        "confidence": "HIGH",
    },
    "Biola University": {
        "org_type": "educational_institution",
        "country": "美国",
        "website": "https://www.biola.edu",
        "description": "美国福音派基督教大学。",
        "theological_position": "evangelical",
        "scale": "medium_500_1000",
        "confidence": "HIGH",
    },
    "YWAM": {
        "org_type": "mission_agency",
        "country": "全球",
        "website": "https://www.ywam.org",
        "description": "Youth With A Mission，跨宗派宣教机构。",
        "theological_position": "interdenominational",
        "scale": "large_1000_10000",
        "confidence": "HIGH",
    },
    "Youth With A Mission": {
        "org_type": "mission_agency",
        "country": "全球",
        "website": "https://www.ywam.org",
        "description": "跨宗派全球宣教机构。",
        "theological_position": "interdenominational",
        "scale": "large_1000_10000",
        "confidence": "HIGH",
    },
}

EXCLUDE_PATTERNS = [
    r"^Pope\s+\w+",
    r"^Archbishop\s+\w+",
    r"^Bishop\s+\w+",
    r"^Pastor\s+\w+",
    r"^Rev\.?\s+\w+",
    r"^Dr\.?\s+\w+",
    r"Brigham Young",
    r"LDS Church",
    r"Temple\s+of\s+.*",
    r"Mosque\s+.*",
    r"Synagogue\s+.*",
    r".*colleges$",
    r".*universities$",
    r".*churches$",
]


def _truncate_text(text: str, max_length: int = 8000) -> str:
    cleaned = re.sub(r"\s+", " ", text or "").strip()
    return cleaned[:max_length]


async def _call_llm_async(prompt: str, max_tokens: int = 2000) -> str:
    llm = get_llm_client()
    if not llm.enabled:
        raise RuntimeError("LLM not enabled")

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{llm.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {llm.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": llm.model,
                "messages": [
                    {"role": "system", "content": "你是结构化信息提取器，只输出 JSON。"},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.2,
                "max_tokens": max_tokens,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()


def call_llm(prompt: str, max_tokens: int = 2000) -> str:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_call_llm_async(prompt, max_tokens=max_tokens))

    result: Dict[str, str] = {}
    error: Dict[str, Exception] = {}

    def _runner():
        try:
            result["value"] = asyncio.run(_call_llm_async(prompt, max_tokens=max_tokens))
        except Exception as exc:  # pragma: no cover
            error["value"] = exc

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    thread.join()

    if "value" in error:
        raise error["value"]
    return result.get("value", "")


def _extract_json_blob(response: str) -> Optional[dict]:
    if not response:
        return None

    fenced = re.search(r"```json\s*(\{[\s\S]*?\})\s*```", response, re.IGNORECASE)
    raw = fenced.group(1) if fenced else None
    if not raw:
        generic = re.search(r"\{[\s\S]*\}", response, re.DOTALL)
        raw = generic.group(0) if generic else None
    if not raw:
        return None

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _guess_org_type(name: str, context: str) -> str:
    lowered = f"{name} {context}".lower()
    if any(token in lowered for token in ["today", "media", "news", "post", "press", "broadcast"]):
        return "media_outlet"
    if any(token in lowered for token in ["vision", "relief", "humanitarian", "development"]):
        return "relief_org"
    if any(token in lowered for token in ["university", "college", "seminary", "school"]):
        return "educational_institution"
    if any(token in lowered for token in ["mission", "ywam", "wycliffe"]):
        return "mission_agency"
    if any(token in lowered for token in ["cru", "campus crusade", "ministry", "ministries", "fellowship"]):
        return "para_church"
    if "church" in lowered:
        return "local_church"
    return "other"


def _heuristic_extract_organizations(title: str, text: str) -> List[Dict]:
    combined = f"{title}\n{text}"
    found: List[Dict] = []
    seen = set()

    for name, metadata in KNOWN_ORG_HINTS.items():
        if re.search(rf"\b{re.escape(name)}\b", combined, re.IGNORECASE):
            payload = {"name": name, **metadata}
            normalized = name.lower().replace(" ", "")
            if normalized not in seen:
                seen.add(normalized)
                found.append(payload)

    generic_pattern = re.compile(
        r"\b([A-Z][A-Za-z&'().-]+(?:\s+[A-Z][A-Za-z&'().-]+){0,5}\s+"
        r"(?:Church|Ministries|Ministry|Mission|University|Foundation|Alliance|Network|Society|Fellowship))\b"
    )
    for match in generic_pattern.findall(combined):
        name = match.strip()
        normalized = name.lower().replace(" ", "")
        if normalized in seen:
            continue
        seen.add(normalized)
        found.append(
            {
                "name": name,
                "org_type": _guess_org_type(name, combined),
                "country": None,
                "website": None,
                "description": f"从页面内容中识别到机构：{name}",
                "theological_position": None,
                "scale": None,
                "confidence": "MEDIUM",
            }
        )

    print(f"[AutoExtract] 启发式提取到 {len(found)} 个机构")
    return found


def _normalize_org_payload(org: Dict) -> Optional[Dict]:
    name = (org.get("name") or "").strip()
    if not name:
        return None

    payload = {
        "name": name,
        "org_type": (org.get("org_type") or "other").strip(),
        "country": (org.get("country") or None),
        "website": (org.get("website") or None),
        "description": (org.get("description") or "").strip(),
        "theological_position": (org.get("theological_position") or None),
        "scale": (org.get("scale") or None),
        "confidence": (org.get("confidence") or "MEDIUM").upper(),
    }
    if payload["confidence"] not in {"HIGH", "MEDIUM", "LOW"}:
        payload["confidence"] = "MEDIUM"
    return payload


def _is_christian_relevant(org: Dict) -> bool:
    name = (org.get("name") or "").strip()
    description = (org.get("description") or "").strip()
    lowered = f"{name} {description}".lower()
    normalized_name = name.lower().replace(" ", "")

    if normalized_name in {key.lower().replace(" ", "") for key in KNOWN_ORG_HINTS}:
        return True

    christian_tokens = [
        "christ",
        "church",
        "bible",
        "gospel",
        "evangel",
        "catholic",
        "orthodox",
        "seminary",
        "mission",
        "ministry",
        "faith",
        "worship",
        "prayer",
        "apostolic",
        "vicariate",
        "diocese",
        "pastor",
        "cru",
        "ywam",
        "crusade for christ",
        "theology",
    ]
    if any(token in lowered for token in christian_tokens):
        return True

    if org.get("theological_position"):
        return True

    strongly_christian_types = {
        "church_network",
        "local_church",
        "mission_agency",
        "seminary",
        "relief_org",
        "denomination",
        "para_church",
        "worship_ministry",
        "bible_translation",
        "prayer_ministry",
    }
    return (org.get("org_type") or "").strip() in strongly_christian_types


def _resolve_org_type_tag(org: Dict) -> Optional[str]:
    raw_type = (org.get("org_type") or "other").strip()
    if raw_type == "faithtech_startup":
        hint = f"{org.get('name', '')} {org.get('description', '')}".lower()
        if "bible" in hint:
            return "faithtech_bible"
        if "worship" in hint:
            return "faithtech_worship"
        if "media" in hint or "content" in hint:
            return "faithtech_media"
        if "education" in hint or "training" in hint:
            return "faithtech_education"
        if "ai" in hint:
            return "faithtech_ai"
        return "faithtech_social"
    return ORG_TYPE_TAG_MAP.get(raw_type)


def hard_filter(organizations: List[Dict]) -> List[Dict]:
    """硬性过滤：排除人物、非基督教、泛称"""
    filtered: List[Dict] = []
    for org in organizations:
        name = (org.get("name") or "").strip()
        if not name:
            continue

        skip = False
        for pattern in EXCLUDE_PATTERNS:
            if re.search(pattern, name, re.IGNORECASE):
                print(f"[AutoExtract] 硬性过滤跳过: {name} (匹配: {pattern})")
                skip = True
                break

        if not skip:
            filtered.append(org)
    return filtered


def extract_organizations_from_text(title: str, text: str) -> List[Dict]:
    """
    调用LLM从网页文本中提取机构信息
    """
    prompt = EXTRACTION_PROMPT.format(title=title, text=_truncate_text(text))

    try:
        response = call_llm(prompt, max_tokens=2000)
        if response:
            print("[AutoExtract] LLM调用成功")
        data = _extract_json_blob(response)
        if not data:
            print(f"[AutoExtract] LLM未返回JSON，降级为启发式提取: {response[:200]}")
            return _heuristic_extract_organizations(title, text)

        organizations = data.get("organizations", []) if isinstance(data, dict) else []
        normalized = []
        for item in (_normalize_org_payload(org) for org in organizations):
            if not item or item.get("confidence") not in {"HIGH", "MEDIUM"}:
                continue
            if not _is_christian_relevant(item):
                print(f"[AutoExtract] 过滤非基督教相关机构: {item['name']}")
                continue
            normalized.append(item)

        print(f"[AutoExtract] 提取到 {len(organizations)} 个机构，{len(normalized)} 个有效")
        return normalized
    except Exception as exc:
        print(f"[AutoExtract] 提取失败，降级为启发式提取: {exc}")
        return _heuristic_extract_organizations(title, text)


def deduplicate_organizations(orgs: List[Dict], db_session) -> List[Dict]:
    """
    去重：与现有organization_profiles对比，过滤已存在的机构
    """
    existing_names = set()

    try:
        profiles = db_session.query(OrganizationProfile).all()
        for profile in profiles:
            existing_names.add((profile.name or "").lower().strip())
            existing_names.add((profile.name or "").lower().replace(" ", "").strip())
    except Exception as exc:
        print(f"[AutoExtract] 查询现有机构失败: {exc}")

    new_orgs = []
    for org in orgs:
        name_normalized = org["name"].lower().strip()
        name_no_space = name_normalized.replace(" ", "")
        if name_normalized not in existing_names and name_no_space not in existing_names:
            new_orgs.append(org)
        else:
            print(f"[AutoExtract] 跳过已存在: {org['name']}")

    print(f"[AutoExtract] 去重后: {len(new_orgs)} / {len(orgs)}")
    return new_orgs


def save_organization_with_tags(org: Dict, db_session):
    """
    保存机构到organization_profiles，并打上Ontology标签
    """
    try:
        profile = OrganizationProfile(
            id=str(uuid.uuid4()),
            name=org["name"],
            country=org.get("country") or "全球",
            official_website=org.get("website"),
            source_url=org.get("website"),
            source_name="auto_extracted",
            confidence=CONFIDENCE_SCORE_MAP.get(org.get("confidence", "MEDIUM"), 0.75),
            ingested_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db_session.add(profile)
        db_session.flush()

        tags_to_add = []
        org_type_tag = _resolve_org_type_tag(org)
        if org_type_tag:
            tags_to_add.append(("organization_type", org_type_tag))

        theology_tag = THEOLOGY_TAG_MAP.get((org.get("theological_position") or "").strip())
        if theology_tag:
            tags_to_add.append(("theology", theology_tag))

        scale_tag = SCALE_TAG_MAP.get((org.get("scale") or "").strip())
        if scale_tag:
            tags_to_add.append(("scale", scale_tag))

        for tag_type, tag_id in tags_to_add:
            db_session.add(
                OrganizationOntologyTag(
                    id=str(uuid.uuid4()),
                    organization_id=profile.id,
                    tag_type=tag_type,
                    tag_id=tag_id,
                    confidence="auto",
                    source="auto_extracted",
                    created_at=datetime.utcnow(),
                )
            )

        db_session.commit()
        print(
            f"[AutoExtract] ✅ 已保存: {org['name']} "
            f"({org.get('org_type')}) + {len(tags_to_add)} 个标签"
        )
        return profile.id
    except Exception as exc:
        db_session.rollback()
        print(f"[AutoExtract] ❌ 保存失败 {org['name']}: {exc}")
        return None


def process_page_for_organizations(title: str, text: str, html: str = None) -> Dict:
    """
    主入口：处理单个页面，提取→去重→保存→打标签
    返回统计信息
    """
    db = SessionLocal()
    content = text or html or ""

    stats = {
        "extracted": 0,
        "new": 0,
        "saved": 0,
        "skipped": 0,
        "errors": 0,
    }

    try:
        organizations = extract_organizations_from_text(title, content)
        organizations = hard_filter(organizations)
        stats["extracted"] = len(organizations)
        if not organizations:
            return stats

        new_orgs = deduplicate_organizations(organizations, db)
        stats["new"] = len(new_orgs)
        stats["skipped"] = stats["extracted"] - stats["new"]

        for org in new_orgs:
            org_id = save_organization_with_tags(org, db)
            if org_id:
                stats["saved"] += 1
            else:
                stats["errors"] += 1
        return stats
    finally:
        db.close()


def batch_extract_from_intelligence_items(limit: int = 50) -> Dict:
    """
    批量处理数据库中已有的intelligence_items，提取机构信息
    """
    db = SessionLocal()
    stats_total = {
        "processed": 0,
        "extracted": 0,
        "saved": 0,
        "skipped": 0,
        "errors": 0,
    }

    try:
        items = (
            db.query(IntelligenceItem)
            .order_by(IntelligenceItem.ingested_at.desc())
            .limit(limit)
            .all()
        )
        print(f"[AutoExtract] 批量处理 {len(items)} 条情报...")

        for item in items:
            if not item.content:
                continue
            title = item.title or "Untitled"
            stats = process_page_for_organizations(title, item.content)
            stats_total["processed"] += 1
            stats_total["extracted"] += stats["extracted"]
            stats_total["saved"] += stats["saved"]
            stats_total["skipped"] += stats["skipped"]
            stats_total["errors"] += stats["errors"]

        print("\n[AutoExtract] 批量完成:")
        print(f"  处理: {stats_total['processed']}")
        print(f"  提取: {stats_total['extracted']}")
        print(f"  保存: {stats_total['saved']}")
        print(f"  跳过: {stats_total['skipped']}")
        print(f"  错误: {stats_total['errors']}")
        return stats_total
    finally:
        db.close()


if __name__ == "__main__":
    test_title = "Christianity Today - Global Faith News"
    test_text = """
    Christianity Today is a leading evangelical Christian media outlet.
    Founded by Billy Graham, it provides news and analysis from a Christian perspective.
    Other organizations mentioned include World Vision International, a global relief organization,
    and Cru (formerly Campus Crusade for Christ), a large evangelistic ministry.
    Also mentioned is Biola University, a Christian university in California,
    and YWAM (Youth With A Mission), an interdenominational Christian missionary organization.
    """

    print("=" * 50)
    print("测试：LLM自动提取+打标签")
    print("=" * 50)

    extracted = extract_organizations_from_text(test_title, test_text)
    print("[AutoExtract] 提取的机构列表:")
    print(json.dumps(extracted, ensure_ascii=False, indent=2))

    result = process_page_for_organizations(test_title, test_text)
    print(f"\n结果: {result}")
