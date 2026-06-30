"""
Joshua Project 数据接入器 — Phase 1 Day 3
接入 joshuaproject.net 的国家宣教概况数据
优先使用公开国家页；如未来补充 API key，可扩展到 API 入口
"""

import html as html_lib
import os
import re
import sys
import uuid
from datetime import datetime
from typing import Dict, List, Optional
from urllib.parse import urljoin

import requests

script_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.dirname(script_dir)
os.chdir(backend_dir)
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from models.database import IntelligenceItem, SessionLocal, Source


JP_API_BASE = "https://api.joshuaproject.net/v1"
JP_COUNTRIES_URL = "https://m.joshuaproject.net/global/countries"


def _clean_text(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value or "")
    value = html_lib.unescape(value)
    return re.sub(r"\s+", " ", value).strip()


class JoshuaProjectCollector:
    """Joshua Project 国家数据采集器"""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("JOSHUA_PROJECT_API_KEY")
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

    def _ensure_source(self) -> str:
        existing = (
            self.db.query(Source)
            .filter(Source.name == "JoshuaProject")
            .order_by(Source.created_at.asc())
            .first()
        )
        if existing:
            return existing.id

        source = Source(
            id=str(uuid.uuid4()),
            name="JoshuaProject",
            url=JP_COUNTRIES_URL,
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

    def fetch_countries_page(self) -> Optional[str]:
        try:
            print(f"[JoshuaProject] fetch: {JP_COUNTRIES_URL}")
            response = self.session.get(JP_COUNTRIES_URL, timeout=30)
            response.raise_for_status()
            print(f"[JoshuaProject] ok ({len(response.text)} bytes)")
            return response.text
        except Exception as exc:
            print(f"[JoshuaProject] failed: {exc}")
            return None

    def fetch_country_data_api(self, country_code: str = "RP") -> Optional[Dict]:
        if not self.api_key:
            print("[JoshuaProject] no API key, skip API mode")
            return None
        url = f"{JP_API_BASE}/countries/{country_code}.json"
        try:
            response = self.session.get(url, params={"api_key": self.api_key}, timeout=30)
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            print(f"[JoshuaProject] API failed {country_code}: {exc}")
            return None

    def extract_country_overview(self, html: str) -> List[Dict[str, str]]:
        countries: List[Dict[str, str]] = []
        map_pattern = re.compile(
            r'customData:\s*\{\s*"x1":\s*"([^"]+)",\s*"x2":\s*"([^"]+)",\s*"x3":\s*"([^"]+)",\s*"x4":\s*"([^"]+)",\s*"x5":\s*"([^"]+)",\s*"x6":\s*"([^"]+)",\s*"x7":\s*"([^"]+)",\s*"x8":\s*"([^"]+)"\s*\}',
            re.IGNORECASE | re.DOTALL,
        )

        for name_raw, population_raw, people_groups, unreached_groups, unreached_percent, href, primary_religion, evangelical_percent in map_pattern.findall(html):
            name = _clean_text(name_raw).title()
            code = href.rstrip("/").split("/")[-1]
            population = _clean_text(population_raw).replace(",", "")
            if not name or not population:
                continue

            countries.append(
                {
                    "name": name,
                    "code": code,
                    "population": population,
                    "people_groups": _clean_text(people_groups),
                    "unreached_groups": _clean_text(unreached_groups),
                    "unreached_percent": _clean_text(unreached_percent),
                    "primary_religion": _clean_text(primary_religion),
                    "progress_scale": None,
                    "evangelical_percent": _clean_text(evangelical_percent),
                    "christian_percent": None,
                    "url": urljoin("https://m.joshuaproject.net", href),
                }
            )

        deduped: List[Dict[str, str]] = []
        seen = set()
        for item in countries:
            key = item["code"]
            if key in seen:
                continue
            deduped.append(item)
            seen.add(key)

        print(f"[JoshuaProject] 提取到 {len(deduped)} 个国家概览")
        return deduped

    def save_country_data(self, country: Dict[str, str]) -> None:
        try:
            title = f"{country['name']} — 宣教概况 (Joshua Project)"
            source_url = country["url"]
            now = datetime.utcnow()

            content = "\n".join(
                [
                    f"国家: {country['name']}",
                    f"Joshua Project国家代码: {country['code']}",
                    "数据来源: Joshua Project (joshuaproject.net)",
                    f"采集时间: {now.strftime('%Y-%m-%d')}",
                    "",
                    "## 基础数据",
                    f"- 人口: {country.get('population', 'N/A')}",
                    f"- 福音派比例: {country.get('evangelical_percent', 'N/A')}",
                    f"- 主要宗教: {country.get('primary_religion', 'N/A')}",
                    f"- 人群总数: {country.get('people_groups', 'N/A')}",
                    f"- 未得群体数: {country.get('unreached_groups', 'N/A')}",
                    f"- 未得群体占比: {country.get('unreached_percent', 'N/A')}",
                    "",
                    "## 关于Joshua Project",
                    "Joshua Project 是全球宣教领域的重要数据来源之一，长期追踪未得之民、福音化程度和跨文化宣教需求。",
                    "",
                    "## 数据价值",
                    "- 评估国家福音化程度",
                    "- 识别宣教优先地区",
                    "- 支持宣教策略制定",
                    "- 补充 ARDA 的国家宗教基线数据",
                ]
            )

            existing = (
                self.db.query(IntelligenceItem)
                .filter(
                    IntelligenceItem.title == title,
                    IntelligenceItem.source_name == "JoshuaProject",
                )
                .first()
            )
            if existing:
                existing.content = content
                existing.entity_name = country["name"]
                existing.entity_type = "country_profile"
                existing.country = country["name"]
                existing.category = "mission_country_profile"
                existing.source_url = source_url
                existing.ingested_at = now
                existing.confidence = 0.9
                print(f"[JoshuaProject] update: {country['name']}")
            else:
                self.db.add(
                    IntelligenceItem(
                        id=str(uuid.uuid4()),
                        source_id=self.source_id,
                        title=title,
                        content=content,
                        entity_name=country["name"],
                        entity_type="country_profile",
                        country=country["name"],
                        category="mission_country_profile",
                        source_url=source_url,
                        source_name="JoshuaProject",
                        published_at=None,
                        ingested_at=now,
                        confidence=0.9,
                        scope="global",
                    )
                )
                print(f"[JoshuaProject] new: {country['name']}")

            self.db.commit()
        except Exception as exc:
            print(f"[JoshuaProject] save failed {country.get('name')}: {exc}")
            self.db.rollback()

    def run(self):
        print("=" * 60)
        print("Joshua Project 数据接入")
        print("=" * 60)

        html = self.fetch_countries_page()
        if not html:
            return {"countries": 0}

        countries = self.extract_country_overview(html)
        for country in countries:
            self.save_country_data(country)

        print("\n" + "=" * 60)
        print("Joshua Project 接入完成")
        print("=" * 60)
        return {"countries": len(countries)}


def collect_joshua_project(api_key: Optional[str] = None):
    collector = JoshuaProjectCollector(api_key=api_key)
    try:
        return collector.run()
    finally:
        collector.close()


if __name__ == "__main__":
    collect_joshua_project()
