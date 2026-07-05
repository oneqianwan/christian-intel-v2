"""
Wikipedia基督教页面机构提取器 — Week 1 Day 1
从 "Christianity in XXX" 页面提取基督教机构/宗派名称并入库
"""

import os
import re
import sys
import uuid
from datetime import datetime
from typing import Dict, List, Optional

import requests
from sqlalchemy import text

script_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.dirname(script_dir)
os.chdir(backend_dir)
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from models.database import SessionLocal


WIKI_API = "https://en.wikipedia.org/w/api.php"

NON_ORG_PATTERNS = [
    r"^Christianity$",
    r"^Jesus$",
    r"^Christ$",
    r"^Bible$",
    r"^Protestantism$",
    r"^Catholicism$",
    r"^Orthodoxy$",
    r"^Evangelicalism$",
    r"^Pentecostalism$",
    r"^Anglicanism$",
    r"^Methodism$",
    r"^Baptists?$",
    r"^Lutheranism?$",
    r"^Christmas$",
    r"^Easter$",
    r"^Lent$",
    r"^Philippines?$",
    r"^Filipino$",
    r"^Spanish$",
    r"^English$",
    r"^Islam$",
    r"^Buddhism$",
    r"^Hinduism$",
    r"^Religion$",
    r"^Theology$",
    r"^Missionary$",
    r"^Archbishop$",
    r"^Bishop$",
    r"^Pastor$",
    r"^\d{3,4}$",
    r"^denominations$",
    r"^third largest Catholic country$",
    r"^Eastern Orthodoxy in .+",
    r"^Seventh-day Adventist$",
    r"^The Church of Jesus Christ of Latter-day Saints$",
    r"^The Church of Almighty God$",
    r"^The Church of Jesus Christ of Latter-day Saints in .+",
    r"^Within .+",
    r"^\d{4}.+attack.+",
    r"^Congregationalism$",
    r"^Councils$",
    r"^Missionaries$",
    r"^Synods?$",
    r"^Separation of church and state$",
    r"^Christian denominations? in .+",
    r"^Christian seminaries.*",
    r"^Christian ashram movement$",
    r"^Latter Day Saint movement$",
    r"^Indian independence movement$",
    r"^March 1 Movement$",
    r"^Constituent Assembly of .+",
    r"^Federal Executive Council$",
    r"^Ministry of .+",
    r"^State Affairs Commission$",
    r"^Supreme People's Assembly$",
    r"^Office of the Registrar General.*",
    r"^University of .+",
    r"^Oxford University Press$",
    r"^Manchester University Press$",
    r"^Wilfrid Laurier University$",
    r"^Ewha Womans University$",
    r"^Catholic University of Pusan$",
    r"^Church of World Messianity$",
    r"^Vishva Hindu Parishad.*",
    r"^Christianity in .+",
    r"^History of .+",
    r"^Demographics of .+",
]

PERSON_PATTERNS = [
    r"^Pope\s+\w+",
    r"^Saint\s+.+",
    r"^St\.?\s+.+",
    r"^Ferdinand Magellan$",
    r"^[A-Z][a-z]+ [A-Z][a-z]+$",
]

BAD_SUBSTRINGS = [
    "Catholic Church in the Philippines",
    "Religion in",
    "Demographics of",
    "Christianity in",
    "List of",
    "History of",
    "Protestants in",
    "largest Catholic country",
    "Association of Religion Data Archives",
    "church and state",
    "Al-Shabaab",
    "Hindu Parishad",
    "World Messianity",
    "Latter-day Saints",
    "Latter Day Saint",
]

ORG_INDICATORS = [
    "Church",
    "Ministry",
    "Mission",
    "Fellowship",
    "Association",
    "Council",
    "Convention",
    "Conference",
    "Assembly",
    "Union",
    "Society",
    "Organization",
    "Institute",
    "Seminary",
    "Network",
    "Alliance",
    "Coalition",
    "Foundation",
    "Diocese",
    "Archdiocese",
    "Parish",
    "Congregation",
    "Synod",
    "Denomination",
    "Cathedral",
]

DENOMINATION_INDICATORS = [
    "Catholic",
    "Evangelical",
    "Baptist",
    "Lutheran",
    "Methodist",
    "Pentecostal",
    "Presbyterian",
    "Anglican",
    "Orthodox",
    "Adventist",
    "Reformed",
]

FAITH_KEYWORDS = [
    "Church",
    "Catholic",
    "Christian",
    "Gospel",
    "Bible",
    "Baptist",
    "Evangelical",
    "Lutheran",
    "Methodist",
    "Pentecostal",
    "Presbyterian",
    "Anglican",
    "Orthodox",
    "Reformed",
    "Mission",
    "Missionary",
    "Apostolic",
    "Diocese",
    "Archdiocese",
    "Cathedral",
    "Seminary",
    "Fellowship",
]


def _strip_tags(value: str) -> str:
    return re.sub(r"<[^>]+>", "", value or "").strip()


class WikiChristianCollector:
    """Wikipedia 基督教页面机构提取器"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0.0.0 Safari/537.36"
                )
            }
        )
        self.db = SessionLocal()

    def close(self):
        self.db.close()

    def _normalize_country(self, country: str) -> str:
        normalized = (country or "").replace("_", " ").strip()
        return re.sub(r"\s+", " ", normalized)

    def _candidate_page_titles(self, country: str) -> List[str]:
        normalized = self._normalize_country(country)
        slug = normalized.replace(" ", "_")
        candidates = [
            f"Christianity_in_{slug}",
            f"Christianity_in_the_{slug}",
        ]

        aliases = {
            "South Korea": ["Christianity_in_Korea", "Religion_in_South_Korea"],
            "Nigeria": ["Religion_in_Nigeria"],
            "Kenya": ["Religion_in_Kenya"],
            "India": ["Christianity_in_India", "Religion_in_India"],
            "Brazil": ["Religion_in_Brazil"],
        }
        candidates.extend(aliases.get(normalized, []))

        seen = set()
        ordered = []
        for title in candidates:
            if title not in seen:
                seen.add(title)
                ordered.append(title)
        return ordered

    def fetch_page_content(self, country: str) -> Optional[Dict[str, str]]:
        """通过 Wikipedia API 获取页面 HTML 内容"""
        normalized = self._normalize_country(country)

        try:
            print(f"[Wiki] 获取: Christianity in {normalized}")
            for page_title in self._candidate_page_titles(normalized):
                params = {
                    "action": "parse",
                    "page": page_title,
                    "prop": "text",
                    "format": "json",
                    "redirects": 1,
                }
                resp = self.session.get(WIKI_API, params=params, timeout=30)
                resp.raise_for_status()
                data = resp.json()
                if "parse" in data and "text" in data["parse"]:
                    html = data["parse"]["text"]["*"]
                    resolved_title = data["parse"].get("title", page_title.replace("_", " "))
                    print(f"[Wiki] ✅ 成功: {resolved_title} ({len(html)} bytes)")
                    return {
                        "html": html,
                        "page_title": resolved_title,
                        "page_slug": page_title,
                        "country": normalized,
                    }
                print(
                    f"[Wiki] 跳过页面: {page_title} "
                    f"({data.get('error', {}).get('info', 'unknown')})"
                )
            return None
        except Exception as exc:
            print(f"[Wiki] ❌ 异常: {exc}")
            return None

    def extract_wikilinks(self, html: str) -> List[str]:
        """从 HTML 中提取 wiki 链接文本"""
        links = re.findall(r'<a[^>]*href="/wiki/([^"#?]+)[^"]*"[^>]*>(.*?)</a>', html)
        names = set()
        for href, text in links:
            text = _strip_tags(text)
            href = href.strip()
            if not text or len(text) < 3:
                continue
            if text.startswith("[") or text.lower().startswith("edit"):
                continue
            if any(href.startswith(prefix) for prefix in ("File:", "Category:", "Help:", "Special:")):
                continue
            if text.isdigit():
                continue
            if href.startswith(("File:", "Category:")):
                continue
            names.add(text)
        return sorted(names)

    def is_likely_organization(self, name: str) -> bool:
        """判断一个名称是否可能是机构或宗派组织"""
        normalized = (name or "").strip()
        if not normalized:
            return False
        if normalized[:1].islower():
            return False

        for pattern in NON_ORG_PATTERNS:
            if re.match(pattern, normalized, re.IGNORECASE):
                return False

        for pattern in PERSON_PATTERNS:
            if re.match(pattern, normalized, re.IGNORECASE):
                return False

        if any(token.lower() in normalized.lower() for token in BAD_SUBSTRINGS):
            return False

        has_org_indicator = any(indicator.lower() in normalized.lower() for indicator in ORG_INDICATORS)
        has_denom_indicator = any(indicator.lower() in normalized.lower() for indicator in DENOMINATION_INDICATORS)
        has_faith_keyword = any(keyword.lower() in normalized.lower() for keyword in FAITH_KEYWORDS)

        if re.search(r"\b(first|second|third|largest|majority|minority)\b", normalized, re.IGNORECASE):
            return False
        if " in " in normalized.lower() and not has_org_indicator:
            return False
        if not has_faith_keyword:
            return False

        # 纯地名、短词和概念词直接排除
        if len(normalized) < 8 and not has_org_indicator:
            return False

        # 只有较强的机构信号才直接放行
        if has_org_indicator:
            return True

        # 宗派名只有在明确带有组织化后缀时才接受
        if has_denom_indicator and re.search(
            r"\b(church|churches|council|convention|association|union|assembly|synod|diocese|archdiocese)\b",
            normalized,
            re.IGNORECASE,
        ):
            return True

        return False

    def deduplicate_with_database(self, names: List[str]) -> List[str]:
        """与现有 organization_profiles 去重"""
        existing = set()
        for row in self.db.execute(text("SELECT name FROM organization_profiles")):
            current = (row[0] or "").lower().strip()
            if not current:
                continue
            existing.add(current)
            existing.add(current.replace(" ", ""))

        new_names = []
        for name in names:
            normalized = name.lower().strip()
            compact = normalized.replace(" ", "")
            if normalized not in existing and compact not in existing:
                new_names.append(name)
        return new_names

    def process_country(self, country: str) -> Dict:
        """抓取 -> 提取 -> 过滤 -> 去重"""
        page_data = self.fetch_page_content(country)
        if not page_data:
            return {"extracted": 0, "filtered": 0, "new": 0, "names": []}
        html = page_data["html"]

        all_names = self.extract_wikilinks(html)
        print(f"[Wiki] 提取到 {len(all_names)} 个wikilink")

        org_names = [name for name in all_names if self.is_likely_organization(name)]
        print(f"[Wiki] 过滤后: {len(org_names)} 个可能机构")

        new_names = self.deduplicate_with_database(org_names)
        print(f"[Wiki] 去重后: {len(new_names)} 个新机构")

        for name in new_names[:10]:
            print(f"  ➕ {name}")

        return {
            "extracted": len(all_names),
            "filtered": len(org_names),
            "new": len(new_names),
            "names": new_names,
            "country": page_data["country"],
            "page_title": page_data["page_title"],
            "page_slug": page_data["page_slug"],
        }

    def save_organizations(self, names: List[str], country: str, page_slug: Optional[str] = None) -> int:
        """保存提取出的机构"""
        saved = 0
        now = datetime.utcnow()
        normalized_country = self._normalize_country(country)
        source_slug = page_slug or f"Christianity_in_{normalized_country.replace(' ', '_')}"

        for name in names:
            try:
                exists = self.db.execute(
                    text("SELECT id FROM organization_profiles WHERE name = :name"),
                    {"name": name},
                ).fetchone()
                if exists:
                    continue

                self.db.execute(
                    text(
                        """
                        INSERT INTO organization_profiles
                        (id, name, country, source_name, source_url, confidence, ingested_at, updated_at)
                        VALUES
                        (:id, :name, :country, 'wiki_extracted', :source_url, :confidence, :ingested_at, :updated_at)
                        """
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        "name": name,
                        "country": normalized_country,
                        "source_url": f"https://en.wikipedia.org/wiki/{source_slug}",
                        "confidence": 0.72,
                        "ingested_at": now,
                        "updated_at": now,
                    },
                )
                saved += 1
                print(f"[Wiki] ✅ 保存: {name}")
            except Exception as exc:
                print(f"[Wiki] ❌ 保存失败 {name}: {exc}")

        self.db.commit()
        return saved

    def run(self, country: str) -> Dict:
        """一键运行：抓取 -> 提取 -> 保存"""
        print("=" * 60)
        print(f"Wikipedia基督教机构提取: {country}")
        print("=" * 60)

        result = self.process_country(country)
        if result["names"]:
            saved = self.save_organizations(result["names"], result.get("country", country), result.get("page_slug"))
            print(f"\n{'=' * 60}")
            print(f"保存: {saved}/{result['new']} 个新机构")
            print(f"{'=' * 60}")
        else:
            print("\n没有新机构需要保存")

        return result


def collect_wiki_christian(country: str = "Philippines"):
    """一键采集"""
    collector = WikiChristianCollector()
    try:
        return collector.run(country)
    finally:
        collector.close()


if __name__ == "__main__":
    # Development/Test entry. Not production collection path.
    print("测试：Wikipedia菲律宾基督教机构提取")
    print("=" * 60)
    result = collect_wiki_christian("Philippines")
    print(f"\n结果: {result}")
