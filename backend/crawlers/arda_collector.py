"""
ARDA National Profiles 采集器 — Step 2
抓取 thearda.com 国家宗教概况，提取结构化数据入库
"""

import html as html_lib
import json
import os
import re
import sys
import uuid
from datetime import datetime
from typing import Dict, Optional

import requests

script_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.dirname(script_dir)
os.chdir(backend_dir)
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlalchemy import text

from models.database import IntelligenceItem, SessionLocal, Source


ARDA_BASE = "https://thearda.com"
NATIONAL_PROFILES_URL = f"{ARDA_BASE}/world-religion/national-profiles"

CORE_COUNTRIES = {
    "Philippines": "178c",
    "South Korea": "122c",
    "Nigeria": "162c",
    "United States": "228c",
    "Brazil": "31c",
    "China": "48c",
    "India": "101c",
    "Indonesia": "104c",
    "Kenya": "121c",
    "South Africa": "205c",
    "Mexico": "143c",
    "Egypt": "67c",
    "Iran": "108c",
    "Turkey": "229c",
    "Pakistan": "167c",
    "Bangladesh": "19c",
    "Japan": "114c",
    "Russia": "183c",
    "Germany": "83c",
    "United Kingdom": "233c",
    "France": "77c",
    "Australia": "14c",
    "Canada": "41c",
    "Argentina": "12c",
    "Colombia": "50c",
    "Peru": "177c",
    "Venezuela": "239c",
    "Chile": "45c",
    "Guatemala": "91c",
    "Ethiopia": "73c",
    "Ghana": "84c",
    "Uganda": "235c",
    "Tanzania": "226c",
    "Congo DR": "57c",
    "Sudan": "211c",
    "Myanmar": "153c",
    "Vietnam": "242c",
    "Thailand": "223c",
    "Malaysia": "135c",
    "Singapore": "197c",
    "Taiwan": "225c",
    "Hong Kong": "96c",
    "Israel": "109c",
    "Saudi Arabia": "188c",
    "Afghanistan": "1c",
    "Albania": "3c",
    "Algeria": "4c",
    "Angola": "7c",
    "Austria": "16c",
    "Belarus": "22c",
    "Belgium": "23c",
    "Bolivia": "29c",
    "Bulgaria": "35c",
    "Burkina Faso": "36c",
    "Cambodia": "40c",
    "Cameroon": "42c",
    "Central African Republic": "47c",
    "Chad": "46c",
    "Costa Rica": "54c",
    "Croatia": "55c",
    "Cuba": "56c",
    "Czech Republic": "58c",
    "Denmark": "60c",
    "Dominican Republic": "63c",
    "Ecuador": "65c",
    "El Salvador": "71c",
    "Eritrea": "72c",
    "Estonia": "74c",
    "Finland": "79c",
    "Greece": "88c",
    "Guinea": "93c",
    "Haiti": "95c",
    "Honduras": "97c",
    "Hungary": "98c",
    "Iceland": "100c",
    "Iraq": "107c",
    "Ireland": "110c",
    "Italy": "112c",
    "Jamaica": "113c",
    "Jordan": "115c",
    "Kazakhstan": "117c",
    "Kuwait": "124c",
    "Laos": "127c",
    "Latvia": "128c",
    "Lebanon": "129c",
    "Liberia": "132c",
    "Libya": "133c",
    "Lithuania": "138c",
    "Madagascar": "140c",
    "Malawi": "141c",
    "Mali": "142c",
    "Morocco": "152c",
    "Mozambique": "154c",
    "Nepal": "158c",
    "Netherlands": "159c",
    "New Zealand": "160c",
    "Nicaragua": "161c",
    "Norway": "165c",
    "Oman": "169c",
    "Panama": "172c",
    "Paraguay": "176c",
    "Poland": "179c",
    "Portugal": "180c",
    "Qatar": "181c",
    "Romania": "182c",
    "Rwanda": "184c",
    "Senegal": "190c",
    "Serbia": "191c",
    "Sierra Leone": "196c",
    "Slovakia": "198c",
    "Slovenia": "199c",
    "Somalia": "201c",
    "Spain": "204c",
    "Sri Lanka": "208c",
    "Sweden": "212c",
    "Switzerland": "214c",
    "Syria": "215c",
    "Togo": "224c",
    "Tunisia": "230c",
    "Ukraine": "234c",
    "United Arab Emirates": "232c",
    "Uruguay": "238c",
    "Uzbekistan": "240c",
    "Yemen": "245c",
    "Zambia": "246c",
    "Zimbabwe": "247c",
}


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _strip_tags(value: str) -> str:
    return _clean_text(re.sub(r"<[^>]+>", " ", value or ""))


def _extract_first_percent_after(html: str, marker: str) -> Optional[str]:
    idx = html.find(marker)
    if idx == -1:
        return None
    snippet = html[idx : idx + 500]
    match = re.search(
        r"</td>\s*<td[^>]*>\s*(?:<b>)?([\d.]+%)(?:</b>)?\s*</td>",
        snippet,
        re.IGNORECASE,
    )
    if match:
        return match.group(1)
    return None


class ARDACollector:
    """ARDA 国家宗教概况采集器"""

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
        self.source_id = self._ensure_source()
        self.country_map_cache: Optional[Dict[str, str]] = None

    def _ensure_source(self) -> str:
        existing = (
            self.db.query(Source)
            .filter(Source.name == "ARDA")
            .order_by(Source.created_at.asc())
            .first()
        )
        if existing:
            return existing.id

        source = Source(
            id=str(uuid.uuid4()),
            name="ARDA",
            url=NATIONAL_PROFILES_URL,
            type="website",
            country="全球",
            scope="global",
            trust_level="high",
            is_active=True,
            created_at=datetime.utcnow(),
        )
        self.db.add(source)
        self.db.commit()
        return source.id

    def close(self):
        self.db.close()

    def build_country_map(self) -> Dict[str, str]:
        """从 ARDA 国家列表页实时解析国家 ID"""
        if self.country_map_cache is not None:
            return self.country_map_cache

        html = self.session.get(NATIONAL_PROFILES_URL, timeout=30).text
        pairs = re.findall(r'new Array\("([^"]+)",\s*"([^"]+)"\)', html)
        country_map = {_clean_text(name): code for name, code in pairs if code.endswith("c")}
        self.country_map_cache = country_map
        print(f"[ARDA] 已加载国家映射: {len(country_map)} 个")
        return country_map

    def resolve_country_id(self, country_name: str) -> Optional[str]:
        country_map = self.build_country_map()
        normalized = _clean_text(country_name)
        if normalized in country_map:
            return country_map[normalized]

        aliases = {
            "United States": "United States of America",
            "South Korea": "South Korea",
            "Congo DR": "Democratic Republic of the Congo",
            "Hong Kong": "Hong Kong",
        }
        alias_name = aliases.get(normalized)
        if alias_name and alias_name in country_map:
            return country_map[alias_name]

        return CORE_COUNTRIES.get(normalized)

    def fetch_country_page(self, country_name: str, country_id: str) -> Optional[str]:
        """抓取单个国家页面"""
        url = f"{NATIONAL_PROFILES_URL}?u={country_id}"
        try:
            print(f"[ARDA] 抓取: {country_name} → {url}")
            resp = self.session.get(url, timeout=30)
            if resp.status_code == 200:
                print(f"[ARDA] ✅ {country_name} 成功 ({len(resp.text)} bytes)")
                return resp.text
            print(f"[ARDA] ❌ {country_name} HTTP {resp.status_code}")
            return None
        except Exception as exc:
            print(f"[ARDA] ❌ {country_name} 异常: {exc}")
            return None

    def extract_summary(self, html: str, country_name: str) -> Dict:
        """提取宗教人口概况"""
        data = {
            "country": country_name,
            "christian_population": None,
            "christian_percent": None,
            "catholic_percent": None,
            "protestant_percent": None,
            "orthodox_percent": None,
            "independent_percent": None,
            "population": None,
        }

        row_markers = {
            "christian_percent": 'var=ADH_415',
            "catholic_percent": 'var=ADH_609',
            "protestant_percent": 'var=ADH_606',
            "orthodox_percent": 'var=ADH_603',
            "independent_percent": 'var=ADH_585',
        }
        for field, marker in row_markers.items():
            value = _extract_first_percent_after(html, marker)
            if value:
                data[field] = value

        pop_match = re.search(
            r'TOTPOP.*?<td[^>]*>\s*([\d,]+)\s*</td>',
            html,
            re.IGNORECASE | re.DOTALL,
        )
        if pop_match:
            data["population"] = int(pop_match.group(1).replace(",", ""))

        if data["population"] and data["christian_percent"]:
            try:
                percent_value = float(data["christian_percent"].replace("%", ""))
                data["christian_population"] = str(int(data["population"] * percent_value / 100))
            except Exception:
                pass

        if not data["christian_percent"]:
            narrative = _strip_tags(html)
            narrative_match = re.search(
                r"approximately\s+(\d+(?:\.\d+)?)\s+percent\s+of\s+the\s+population\s+is\s+Christian",
                narrative,
                re.IGNORECASE,
            )
            if narrative_match:
                data["christian_percent"] = f"{narrative_match.group(1)}%"
            catholic_match = re.search(
                r"Roman Catholics.*?comprise\s+(\d+(?:\s*to\s*\d+)?)\s+percent",
                narrative,
                re.IGNORECASE,
            )
            if catholic_match:
                value = catholic_match.group(1).replace(" to ", "-")
                data["catholic_percent"] = f"{value}%"

        return data

    def extract_ras_indexes(self, html: str) -> Dict:
        """提取宗教自由/限制排名"""
        indexes = {}
        rank_patterns = [
            (r"Government\s+Restriction.*?Ranking:\s*(\d+)/(\d+)", "government_restriction_rank"),
            (r"Societal\s+Discrimination.*?Ranking:\s*(\d+)/(\d+)", "societal_discrimination_rank"),
            (r"State\s+Funding.*?Ranking:\s*(\d+)/(\d+)", "state_funding_rank"),
        ]

        for pattern, key in rank_patterns:
            match = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
            if match:
                indexes[key] = f"{match.group(1)}/{match.group(2)}"
        return indexes

    def extract_page_title(self, html: str, country_name: str) -> str:
        match = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        if not match:
            return f"{country_name} - ARDA National Profile"
        return _strip_tags(match.group(1))

    def process_country(self, country_name: str, country_id: str) -> Optional[Dict]:
        """处理单个国家"""
        html = self.fetch_country_page(country_name, country_id)
        if not html:
            return None

        summary = self.extract_summary(html, country_name)
        ras = self.extract_ras_indexes(html)
        title = self.extract_page_title(html, country_name)
        return {
            "country": country_name,
            "country_id": country_id,
            "source_url": f"{NATIONAL_PROFILES_URL}?u={country_id}",
            "page_title": title,
            "summary": summary,
            "ras_indexes": ras,
        }

    def save_to_database(self, data: Dict):
        """保存为 intelligence_items"""
        try:
            summary = data.get("summary", {})
            ras = data.get("ras_indexes", {})
            title = f"{data['country']} — 宗教概况"

            content_lines = [
                f"国家: {data['country']}",
                f"页面标题: {data.get('page_title') or title}",
                "数据来源: ARDA (Association of Religion Data Archives)",
                f"数据URL: {data['source_url']}",
                f"采集时间: {datetime.utcnow().strftime('%Y-%m-%d')}",
                "",
                "## 宗教人口概况",
            ]

            if summary.get("population"):
                content_lines.append(f"总人口: {summary['population']:,}")
            if summary.get("christian_population"):
                content_lines.append(f"基督徒人口: {int(summary['christian_population']):,}")
            if summary.get("christian_percent"):
                content_lines.append(f"基督徒比例: {summary['christian_percent']}")
            if summary.get("catholic_percent"):
                content_lines.append(f"天主教: {summary['catholic_percent']}")
            if summary.get("protestant_percent"):
                content_lines.append(f"新教: {summary['protestant_percent']}")
            if summary.get("orthodox_percent"):
                content_lines.append(f"东正教: {summary['orthodox_percent']}")
            if summary.get("independent_percent"):
                content_lines.append(f"独立教会: {summary['independent_percent']}")

            if ras:
                content_lines.extend(["", "## 宗教自由指数"])
                for key, value in ras.items():
                    label = key.replace("_", " ").title()
                    content_lines.append(f"{label}: {value}")

            content = "\n".join(content_lines)

            existing = (
                self.db.query(IntelligenceItem)
                .filter(
                    IntelligenceItem.title == title,
                    IntelligenceItem.source_name == "ARDA",
                )
                .first()
            )

            if existing:
                existing.content = content
                existing.country = data["country"]
                existing.source_url = data["source_url"]
                existing.entity_name = data["country"]
                existing.entity_type = "country_profile"
                existing.category = "religion_profile"
                existing.ingested_at = datetime.utcnow()
                existing.confidence = 0.95
                existing.scope = "global"
                print(f"[ARDA] 📝 更新: {data['country']}")
            else:
                self.db.add(
                    IntelligenceItem(
                        id=str(uuid.uuid4()),
                        source_id=self.source_id,
                        title=title,
                        content=content,
                        entity_name=data["country"],
                        entity_type="country_profile",
                        country=data["country"],
                        category="religion_profile",
                        source_url=data["source_url"],
                        source_name="ARDA",
                        published_at=None,
                        ingested_at=datetime.utcnow(),
                        confidence=0.95,
                        scope="global",
                    )
                )
                print(f"[ARDA] ➕ 新增: {data['country']}")

            self.db.commit()
        except Exception as exc:
            self.db.rollback()
            print(f"[ARDA] ❌ 保存失败 {data['country']}: {exc}")

    def run_batch(self, countries: Dict[str, str] = None):
        """批量处理"""
        countries = countries or self.build_country_map()
        print("=" * 60)
        print(f"ARDA National Profiles 批量采集 — {len(countries)}个国家")
        print("=" * 60)

        success = 0
        failed = 0
        for country_name, country_id in countries.items():
            data = self.process_country(country_name, country_id)
            if data:
                self.save_to_database(data)
                success += 1
            else:
                failed += 1

        print(f"\n{'=' * 60}")
        print(f"完成: {success}成功 / {failed}失败 / {len(countries)}总计")
        print(f"{'=' * 60}")
        return {"success": success, "failed": failed, "total": len(countries)}


def collect_arda_countries():
    """一键采集"""
    collector = ARDACollector()
    try:
        return collector.run_batch()
    finally:
        collector.close()


if __name__ == "__main__":
    print("测试：ARDA菲律宾")
    print("=" * 50)

    collector = ARDACollector()
    try:
        country_id = collector.resolve_country_id("Philippines") or "178c"
        result = collector.process_country("Philippines", country_id)
        if result:
            print(json.dumps(result, indent=2, ensure_ascii=False))
            collector.save_to_database(result)
    finally:
        collector.close()
