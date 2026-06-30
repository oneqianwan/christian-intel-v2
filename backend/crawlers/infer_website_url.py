"""
官网URL推断器 — Phase 2 Day 2
对无官网URL的机构，用LLM+规则推断官网地址
"""

import os
import re
import sys

from sqlalchemy import text

script_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.dirname(script_dir)
os.chdir(backend_dir)
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from models.database import SessionLocal

try:
    from services.llm_client import call_llm
except Exception:
    call_llm = None


DOMAIN_PATTERNS = {
    "Philippines": [".org.ph", ".com.ph", ".ph"],
    "United States": [".org", ".com", ".net"],
    "India": [".org.in", ".in", ".co.in"],
    "Indonesia": [".or.id", ".id", ".co.id"],
    "Nigeria": [".org.ng", ".ng", ".com.ng"],
    "South Africa": [".org.za", ".co.za", ".za"],
    "Egypt": [".org.eg", ".eg"],
    "Brazil": [".org.br", ".com.br", ".br"],
    "Japan": [".or.jp", ".jp", ".co.jp"],
    "Mexico": [".org.mx", ".mx"],
    "default": [".org", ".com", ".net"],
}


def _normalize_country(country: str | None) -> str:
    if not country:
        return "default"
    return country.strip() or "default"


def _slugify(org_name: str) -> str:
    clean_name = re.sub(r"\([^)]*\)", "", org_name).strip()
    slug = re.sub(r"[^a-zA-Z0-9\s]", "", clean_name).lower()
    slug = re.sub(r"\s+", "", slug)
    return slug


def infer_url(org_name: str, country: str | None) -> str | None:
    if not org_name:
        return None

    clean_name = re.sub(r"\([^)]*\)", "", org_name).strip()
    slug = _slugify(org_name)
    if not slug:
        return None

    country_key = _normalize_country(country)
    suffixes = DOMAIN_PATTERNS.get(country_key, DOMAIN_PATTERNS["default"])

    candidates: list[str] = []
    for suffix in suffixes:
        candidates.append(f"https://www.{slug}{suffix}")
        if len(slug) > 20:
            words = clean_name.split()
            if len(words) > 2:
                acronym = "".join(w[0] for w in words if w)
                if len(acronym) >= 2:
                    candidates.append(f"https://www.{acronym.lower()}{suffix}")

    if call_llm is not None:
        prompt = f"""你是一个基督教机构官网推断专家。

机构名称: {org_name}
国家: {country_key}

请推断该机构的官网URL。

规则:
1. 大多数基督教机构使用 .org 域名
2. 菲律宾机构常用 .org.ph
3. 去掉名称中的括号内容和缩写
4. 域名通常是机构名称的小写无空格版本

只输出一个URL，不要其他文字。
如果不确定，输出 "UNKNOWN"。

输出格式:
https://www.example.org
"""

        try:
            response = call_llm(prompt, max_tokens=120, temperature=0.1)
            if response:
                if "UNKNOWN" not in response.upper():
                    url_match = re.search(r"https?://\S+", response)
                    if url_match:
                        url = url_match.group().rstrip(".),;\"'")
                        if url.startswith(("http://", "https://")):
                            candidates.insert(0, url)
        except Exception as e:
            print(f"[WARN] LLM推断失败: {str(e)[:120]}")

    seen: set[str] = set()
    for url in candidates:
        if url not in seen:
            seen.add(url)
            return url

    return None


def batch_infer_urls(batch_size: int = 50):
    db = SessionLocal()
    try:
        print("=" * 60)
        print(f"官网URL推断 (batch={batch_size})")
        print("=" * 60)

        rows = db.execute(
            text(
                """
                SELECT id, name, country
                FROM organization_profiles
                WHERE (official_website IS NULL OR official_website = '')
                  AND source_name = 'wiki_extracted'
                ORDER BY country, name
                LIMIT :limit
                """
            ),
            {"limit": batch_size},
        ).fetchall()

        print(f"\n待推断: {len(rows)} 家")

        updated = 0
        failed = 0

        for org_id, name, country in rows:
            url = infer_url(name, country)
            if url:
                db.execute(
                    text("UPDATE organization_profiles SET official_website = :url WHERE id = :id"),
                    {"url": url, "id": org_id},
                )
                print(f"  [OK] {name[:40]:40s} -> {url}")
                updated += 1
            else:
                print(f"  [ERR] {name[:40]:40s} -> UNKNOWN")
                failed += 1

        db.commit()

        print(f"\n{'=' * 60}")
        print(f"完成: 推断成功 {updated} / 失败 {failed}")
        print(f"{'=' * 60}")

        return {"updated": updated, "failed": failed}
    finally:
        db.close()


if __name__ == "__main__":
    result = batch_infer_urls(batch_size=50)
    print(f"\n结果: {result}")
