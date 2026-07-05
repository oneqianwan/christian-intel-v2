"""
官网深度采集器 — Phase 1 Day 1
对已有官网URL的机构进行深度抓取，提取完整档案字段
"""

import asyncio
import json
import os
import re
import sys
from datetime import datetime
from typing import Any, Dict, Optional
from urllib.parse import urljoin, urlparse

from sqlalchemy import text

script_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.dirname(script_dir)
os.chdir(backend_dir)
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from models.database import SessionLocal, init_db

try:
    from backend.services.llm_client import call_llm
except ImportError:
    from services.llm_client import call_llm

try:
    from backend.crawlers.dynamic_crawler import DynamicCrawler
except ImportError:
    from crawlers.dynamic_crawler import DynamicCrawler


def is_valid_website_url(url: str) -> bool:
    """预校验URL是否可直接抓取。"""
    if not url:
        return False

    candidate = url.strip()
    if not candidate.startswith(("http://", "https://")):
        return False

    lowered = candidate.lower()
    if "thearda.com" in lowered and ("/us-religion/" in lowered or "/world-religion/" in lowered):
        return False

    skip_tokens = [
        "/wiki/",
        "/rss",
        "/feed",
        "/search",
        "facebook.com",
        "twitter.com",
        "instagram.com",
        "youtube.com",
        "linkedin.com",
    ]
    return not any(token in lowered for token in skip_tokens)


EXTRACTION_PROMPT = """你是一个基督教机构信息提取专家。请从以下官网内容中提取机构的关键信息。

机构名称: {org_name}
官网URL: {website_url}

抓取到的网页内容:
{page_text}

请提取以下字段（如果内容中有的话）：
1. description: 机构简短描述（1-3句话）
2. founded_year: 成立年份（4位数字）
3. denomination: 宗派/神学立场
4. leadership: 负责人信息（JSON格式：[{{"name":"姓名", "title":"职位"}}]）
5. contact_email: 联系邮箱
6. contact_phone: 联系电话
7. address: 地址
8. city: 城市
9. mission_statement: 使命宣言
10. has_ai_content: 是否有AI/科技/数字化相关内容（true/false）
11. has_online_giving: 是否有在线奉献（true/false）
12. has_mobile_app: 是否提到手机APP（true/false）
13. social_accounts: 社交账号（JSON格式：{{"facebook":"url", "youtube":"url", "telegram":"username"}}）
14. key_activities: 主要活动/事工领域

输出格式（严格JSON）：
{{
  "description": "...",
  "founded_year": "2010",
  "denomination": "...",
  "leadership": [],
  "contact_email": null,
  "contact_phone": null,
  "address": null,
  "city": null,
  "mission_statement": null,
  "has_ai_content": false,
  "has_online_giving": false,
  "has_mobile_app": false,
  "social_accounts": {{}},
  "key_activities": []
}}

注意：
- 只输出JSON，不要其他文字
- 信息不存在时填null或false
- 对不确定的信息填null，不要猜测
"""


def _extract_json_blob(response: str) -> Dict[str, Any]:
    if not response:
        return {}
    match = re.search(r"\{[\s\S]*\}", response)
    if not match:
        return {}
    try:
        return json.loads(match.group(0))
    except Exception:
        return {}


def _heuristic_extract(page_text: str, website_url: str) -> Dict[str, Any]:
    lowered = (page_text or "").lower()
    email_match = re.search(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", page_text or "", re.IGNORECASE)
    phone_match = re.search(r"(\+?\d[\d\-\s()]{7,}\d)", page_text or "")
    founded_match = re.search(r"(founded|since|established)\D{0,20}(18|19|20)\d{2}", page_text or "", re.IGNORECASE)

    social_accounts: Dict[str, str] = {}
    for platform in ["facebook", "youtube", "instagram", "linkedin", "telegram"]:
        social_match = re.search(rf"https?://[^\s\"'<>()]*{platform}[^\s\"'<>()]*", page_text or "", re.IGNORECASE)
        if social_match:
            social_accounts[platform] = social_match.group(0)

    description = None
    lines = [line.strip() for line in (page_text or "").splitlines() if line.strip()]
    if lines:
        description = " ".join(lines[:3])[:400]

    return {
        "description": description,
        "founded_year": founded_match.group(0)[-4:] if founded_match else None,
        "denomination": None,
        "leadership": [],
        "contact_email": email_match.group(0) if email_match else None,
        "contact_phone": phone_match.group(1) if phone_match else None,
        "address": None,
        "city": None,
        "mission_statement": None,
        "has_ai_content": any(
            token in lowered
            for token in ["artificial intelligence", " ai ", "machine learning", "automation", "digital ministry", "technology"]
        ),
        "has_online_giving": any(token in lowered for token in ["give online", "online giving", "donate online", "donation"]),
        "has_mobile_app": any(token in lowered for token in ["app store", "google play", "mobile app"]),
        "social_accounts": social_accounts,
        "key_activities": [],
    }


def _extract_from_website_sync(org_name: str, website_url: str, page_text: str) -> Dict[str, Any]:
    """调用LLM从官网内容提取机构信息。"""
    prompt = EXTRACTION_PROMPT.format(
        org_name=org_name,
        website_url=website_url,
        page_text=(page_text or "")[:6000],
    )

    extracted: Dict[str, Any] = {}
    try:
        response = call_llm(prompt, max_tokens=1500)
        extracted = _extract_json_blob(response)
        if extracted:
            return extracted
        print("  [Extract] LLM未返回可解析JSON，改用规则提取")
    except Exception as exc:
        print(f"  [Extract] LLM提取失败，改用规则提取: {exc}")

    return _heuristic_extract(page_text, website_url)


async def extract_from_website(org_name: str, website_url: str, page_text: str) -> Dict[str, Any]:
    return await asyncio.to_thread(_extract_from_website_sync, org_name, website_url, page_text)


def assess_ai_maturity_v2(has_ai_content: bool, page_text: str) -> int:
    """
    AI成熟度评估 v2 — 收紧规则
    """
    if not page_text or len(page_text) < 50:
        return 0

    page_lower = page_text.lower()
    ai_core_terms = [
        "artificial intelligence",
        "machine learning",
        "deep learning",
        "natural language processing",
        "nlp",
        "chatbot",
        "ai strategy",
        "ai initiative",
        "ai-powered",
        "ai driven",
        "generative ai",
        "large language model",
        "llm",
        "openai",
        "chatgpt",
        "人工智能",
        "机器学习",
        "深度学习",
    ]
    has_core = any(term in page_lower for term in ai_core_terms)
    if not has_core:
        return 0

    score = 2
    strategy_terms = [
        "ai strategy",
        "ai team",
        "ai department",
        "ai project",
        "ai program",
        "ai roadmap",
        "ai adoption",
        "ai implementation",
        "ai ethics",
        "ai governance",
        "ai policy",
    ]
    if any(term in page_lower for term in strategy_terms):
        score += 1

    product_terms = [
        "ai tool",
        "ai platform",
        "ai solution",
        "ai product",
        "ai application",
        "ai service",
        "ai software",
        "chatbot",
        "virtual assistant",
        "ai-powered platform",
    ]
    if any(term in page_lower for term in product_terms):
        score += 1

    content_terms = [
        "ai-generated",
        "ai content",
        "ai media",
        "ai video",
        "ai translation",
        "ai sermon",
        "ai bible",
    ]
    if any(term in page_lower for term in content_terms):
        score += 1

    return min(score, 5)


def assess_digital_score_v2(extracted: Dict[str, Any], page_text: str) -> int:
    """
    数字化评分 v2 — 收紧规则
    """
    score = 0
    page_lower = page_text.lower() if page_text else ""

    if extracted.get("has_online_giving"):
        giving_terms = [
            "online giving",
            "give online",
            "online donation",
            "digital offering",
            "electronic giving",
            "e-giving",
        ]
        if any(term in page_lower for term in giving_terms):
            score += 1

    if extracted.get("has_mobile_app"):
        score += 1

    if extracted.get("has_ai_content") and assess_ai_maturity_v2(True, page_text) >= 2:
        score += 1

    streaming_terms = [
        "livestream",
        "live stream",
        "watch online",
        "online service",
        "virtual service",
        "zoom",
    ]
    if any(term in page_lower for term in streaming_terms):
        score += 1

    platform_terms = [
        "online community",
        "digital ministry",
        "online bible study",
        "virtual small group",
        "digital discipleship",
        "app download",
    ]
    if any(term in page_lower for term in platform_terms):
        score += 1

    return min(score, 5)


def save_deep_data(org_id: str, org_name: str, website_url: str, extracted: Dict[str, Any], about_text: str, db_session) -> None:
    """将深度采集数据保存到数据库。"""
    try:
        ai_maturity = assess_ai_maturity_v2(bool(extracted.get("has_ai_content")), about_text)
        digital_score = assess_digital_score_v2(extracted, about_text)

        leadership = extracted.get("leadership") or []
        leader_name = None
        leader_title = None
        if isinstance(leadership, list) and leadership:
            first_leader = leadership[0] or {}
            leader_name = first_leader.get("name")
            leader_title = first_leader.get("title")

        social_accounts = extracted.get("social_accounts") or {}
        updates = {
            "description": extracted.get("description"),
            "founded_year": extracted.get("founded_year"),
            "denomination": extracted.get("denomination"),
            "contact_email": extracted.get("contact_email"),
            "phone_public": extracted.get("contact_phone"),
            "address": extracted.get("address"),
            "city": extracted.get("city"),
            "mission_statement": extracted.get("mission_statement"),
            "has_ai_initiative": bool(extracted.get("has_ai_content")),
            "has_online_giving": bool(extracted.get("has_online_giving")),
            "has_mobile_app": bool(extracted.get("has_mobile_app")),
            "social_accounts": json.dumps(social_accounts, ensure_ascii=False) if social_accounts else None,
            "key_activities": json.dumps(extracted.get("key_activities") or [], ensure_ascii=False),
            "ai_maturity_score": ai_maturity,
            "digital_score": digital_score,
            "about_text": (about_text or "")[:3000] if about_text else None,
            "last_website_crawl": datetime.utcnow(),
            "official_website": website_url,
            "leader_name": leader_name,
            "leader_title": leader_title,
            "facebook_url": social_accounts.get("facebook"),
            "youtube_url": social_accounts.get("youtube"),
            "telegram_username": social_accounts.get("telegram"),
        }

        set_clauses = []
        params: Dict[str, Any] = {"org_id": org_id}
        for field, value in updates.items():
            if value is not None:
                set_clauses.append(f"{field} = :{field}")
                params[field] = value

        if not set_clauses:
            print(f"  [Save] 无数据可更新: {org_name}")
            return

        db_session.execute(
            text(f"UPDATE organization_profiles SET {', '.join(set_clauses)}, updated_at = :updated_at WHERE id = :org_id"),
            {**params, "updated_at": datetime.utcnow()},
        )
        db_session.commit()

        print(f"  [Save] [OK] {org_name}")
        print(f"         AI成熟度: {ai_maturity}/5 | 数字化: {digital_score}/5")
        if extracted.get("description"):
            print(f"         描述: {str(extracted['description'])[:60]}...")
    except Exception as exc:
        db_session.rollback()
        print(f"  [Save] [ERR] {org_name}: {exc}")


async def _fetch_best_text(crawler: DynamicCrawler, website_url: str) -> tuple[str, str]:
    result = await crawler.fetch_page(website_url, wait_for="domcontentloaded", timeout=20000)
    if not result.get("success"):
        raise RuntimeError(result.get("error") or f"HTTP {result.get('status')}")

    page_text = result.get("text", "") or ""
    best_text = page_text
    best_url = website_url

    # 只有首页内容明显不足时，才继续探测极少数高价值 About 页面。
    if len(page_text) >= 1500:
        return best_text, best_url

    for path in ["/about", "/about-us"]:
        try:
            candidate_url = urljoin(website_url.rstrip("/") + "/", path.lstrip("/"))
            about_result = await crawler.fetch_page(candidate_url, wait_for="domcontentloaded", timeout=15000)
            if about_result.get("success") and about_result.get("text"):
                about_text = about_result.get("text") or ""
                if len(about_text) > len(best_text):
                    best_text = about_text
                    best_url = candidate_url
                    print(f"  [OK] {path} 页更丰富 ({len(about_text)} chars)")
                if len(best_text) > 2500:
                    break
        except Exception:
            continue

    return best_text, best_url


async def crawl_organization_website(org_id: str, org_name: str, website_url: str, crawler: DynamicCrawler, db_session) -> bool:
    """抓取单个机构官网，提取信息并保存。"""
    print(f"\n[DeepCrawl] {org_name}")
    print(f"  URL: {website_url}")

    if not is_valid_website_url(website_url):
        print(f"  [Skip] URL无效: {website_url}")
        return False

    try:
        page_text, used_url = await _fetch_best_text(crawler, website_url)
        print(f"  [OK] 抓取成功 ({len(page_text)} chars)")
        if len(page_text) < 100:
            print("  [Warn] 内容太少，跳过提取")
            return False
    except Exception as exc:
        print(f"  [Fail] 抓取失败: {exc}")
        return False

    extracted = await extract_from_website(org_name, used_url, page_text)
    if not extracted:
        print("  [Warn] 提取为空")
        return False

    save_deep_data(org_id, org_name, used_url, extracted, page_text, db_session)
    return True


async def _run_batch_crawl(batch_size: int = 10, source_filter: Optional[str] = None) -> None:
    db = SessionLocal()
    crawler = DynamicCrawler()
    try:
        if source_filter:
            result = db.execute(
                text(
                    """
                    SELECT id, name, official_website, country, source_name
                    FROM organization_profiles
                    WHERE official_website IS NOT NULL
                      AND official_website != ''
                      AND source_name = :source
                    ORDER BY id
                    LIMIT :limit
                    """
                ),
                {"source": source_filter, "limit": batch_size},
            )
        else:
            result = db.execute(
                text(
                    """
                    SELECT id, name, official_website, country, source_name
                    FROM organization_profiles
                    WHERE official_website IS NOT NULL
                      AND official_website != ''
                      AND (last_website_crawl IS NULL OR last_website_crawl < :old)
                    ORDER BY
                      CASE source_name
                        WHEN 'manual_seed' THEN 1
                        WHEN 'auto_extracted_verified' THEN 2
                        WHEN 'auto_extracted' THEN 3
                        ELSE 4
                      END,
                      id
                    LIMIT :limit
                    """
                ),
                {"old": "2026-01-01", "limit": batch_size},
            )

        orgs = result.fetchall()
        if not orgs:
            print("没有待抓取的机构")
            return

        print(f"\n{'=' * 60}")
        print(f"官网深度采集: {len(orgs)}家机构")
        print(f"{'=' * 60}")

        await crawler.start()

        success = 0
        failed = 0
        for row in orgs:
            org_id, name, website, country, source = row
            ok = await crawl_organization_website(org_id, name, website, crawler, db)
            if ok:
                success += 1
            else:
                failed += 1

        print(f"\n{'=' * 60}")
        print(f"完成: {success}成功 / {failed}失败 / {len(orgs)}总计")
        print(f"{'=' * 60}")
    finally:
        await crawler.stop()
        db.close()


def run_batch_crawl(batch_size: int = 10, source_filter: Optional[str] = None) -> None:
    asyncio.run(_run_batch_crawl(batch_size=batch_size, source_filter=source_filter))


if __name__ == "__main__":
    # Development/Test entry. Not production collection path.
    print("测试：官网深度采集（第一批5家）")
    print("=" * 60)
    init_db()
    run_batch_crawl(batch_size=5, source_filter="manual_seed")
