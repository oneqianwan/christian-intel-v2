"""
ARDA Group Profiles 宗派档案采集器
抓取 thearda.com 的宗派档案页面，提取宗派信息入库
"""

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

from models.database import IntelligenceItem, SessionLocal, Source


ARDA_BASE = "https://thearda.com"
ARDA_GROUP_URL = f"{ARDA_BASE}/us-religion/group-profiles/groups?D={{group_id}}"

CHRISTIAN_KEYWORDS = [
    "christian",
    "catholic",
    "orthodox",
    "protestant",
    "anglican",
    "lutheran",
    "methodist",
    "baptist",
    "mennonite",
    "amish",
    "pentecostal",
    "presbyterian",
    "restorationist",
    "holiness",
    "adventist",
    "anabaptist",
    "evangelical",
    "apostolic",
    "wesleyan",
    "moravian",
    "church of christ",
]

NON_CHRISTIAN_KEYWORDS = [
    "buddh",
    "hindu",
    "muslim",
    "islam",
    "jewish",
    "sikh",
    "baha",
    "bahai",
    "tao",
    "dao",
    "jain",
    "zoro",
    "shinto",
    "wicca",
    "pagan",
    "humanist",
    "ethical",
    "yoga",
    "zen",
]


def _clean_text(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value or "")
    value = value.replace("&nbsp;", " ").replace("&#160;", " ")
    return re.sub(r"\s+", " ", value).strip()


class ARDADenominationCollector:
    """ARDA 宗派档案采集器"""

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

    def _ensure_source(self) -> str:
        existing = (
            self.db.query(Source)
            .filter(Source.name == "ARDA_Denomination")
            .order_by(Source.created_at.asc())
            .first()
        )
        if existing:
            return existing.id

        source = Source(
            id=str(uuid.uuid4()),
            name="ARDA_Denomination",
            url=ARDA_GROUP_URL.format(group_id="1"),
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

    def fetch_group_profile(self, group_id: str) -> Optional[str]:
        """抓取单个宗派档案页面"""
        url = ARDA_GROUP_URL.format(group_id=group_id)
        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            return response.text
        except Exception:
            return None

    def extract_group_info(self, html: str, group_id: str) -> Optional[Dict[str, Optional[str]]]:
        """从 HTML 中提取宗派信息"""
        info: Dict[str, Optional[str]] = {
            "group_id": group_id,
            "name": None,
            "tradition": None,
            "family": None,
            "description": None,
            "official_site": None,
        }

        name_match = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.IGNORECASE | re.DOTALL)
        if name_match:
            info["name"] = _clean_text(name_match.group(1))
        if not info["name"]:
            title_match = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
            if title_match:
                title = _clean_text(title_match.group(1))
                if "Groups - Religious Profiles" not in title:
                    info["name"] = title.split("|")[0].strip(" -")
        if info["name"]:
            info["name"] = re.sub(r"\s*-\s*Religious Group$", "", info["name"]).strip()

        trad_match = re.search(
            r"Religious Tradition:.*?<a[^>]*>(.*?)</a>",
            html,
            re.IGNORECASE | re.DOTALL,
        )
        if trad_match:
            info["tradition"] = _clean_text(trad_match.group(1))

        family_match = re.search(
            r"Religious Family:.*?<a[^>]*>(.*?)</a>",
            html,
            re.IGNORECASE | re.DOTALL,
        )
        if family_match:
            info["family"] = _clean_text(family_match.group(1))

        desc_match = re.search(
            r"Description:\s*</h3>\s*<p>(.*?)</p>",
            html,
            re.IGNORECASE | re.DOTALL,
        )
        if desc_match:
            info["description"] = _clean_text(desc_match.group(1))[:1000]

        site_match = re.search(
            r"Official Site:.*?<a[^>]*href=\"([^\"]+)\"",
            html,
            re.IGNORECASE | re.DOTALL,
        )
        if site_match:
            site = site_match.group(1).strip()
            if not site.startswith("#"):
                info["official_site"] = site

        if (
            not info["name"]
            or info["name"] == "Groups - Religious Profiles"
            or info["name"] == "(Unknown)"
        ):
            return None

        return info

    def is_christian_profile(self, info: Dict[str, Optional[str]]) -> bool:
        combined = " | ".join(
            [
                info.get("name") or "",
                info.get("tradition") or "",
                info.get("family") or "",
                info.get("description") or "",
            ]
        ).lower()

        if any(token in combined for token in NON_CHRISTIAN_KEYWORDS):
            return False
        return any(token in combined for token in CHRISTIAN_KEYWORDS)

    def save_denomination(self, info: Dict[str, Optional[str]]) -> bool:
        """保存宗派档案到 intelligence_items"""
        try:
            title = f"{info['name']} - Denomination Profile (ARDA)"
            source_url = ARDA_GROUP_URL.format(group_id=info["group_id"])
            now = datetime.utcnow()

            content_lines = [
                f"Denomination Name: {info['name']}",
                "Source: ARDA Group Profiles",
                f"Religious Tradition: {info.get('tradition') or 'N/A'}",
                f"Religious Family: {info.get('family') or 'N/A'}",
            ]
            if info.get("description"):
                content_lines.append(f"Description: {info['description']}")
            if info.get("official_site"):
                content_lines.append(f"Official Site: {info['official_site']}")
            content = "\n".join(content_lines)

            existing = (
                self.db.query(IntelligenceItem)
                .filter(
                    IntelligenceItem.title == title,
                    IntelligenceItem.source_name == "ARDA_Denomination",
                )
                .first()
            )

            if existing:
                existing.content = content
                existing.entity_name = info["name"]
                existing.entity_type = "denomination_profile"
                existing.category = "denomination_profile"
                existing.source_url = source_url
                existing.ingested_at = now
                existing.confidence = 0.9
                print(f"[ARDA-Denom] update: {info['name']}")
            else:
                self.db.add(
                    IntelligenceItem(
                        id=str(uuid.uuid4()),
                        source_id=self.source_id,
                        title=title,
                        content=content,
                        entity_name=info["name"],
                        entity_type="denomination_profile",
                        country="全球",
                        category="denomination_profile",
                        source_url=source_url,
                        source_name="ARDA_Denomination",
                        published_at=None,
                        ingested_at=now,
                        confidence=0.9,
                        scope="global",
                    )
                )
                print(f"[ARDA-Denom] new: {info['name']}")

            self.db.commit()
            return True
        except Exception as exc:
            print(f"[ARDA-Denom] save failed {info.get('name')}: {exc}")
            self.db.rollback()
            return False

    def run_batch(self, start_id: int = 1, end_id: int = 800):
        """批量采集宗派档案"""
        print("=" * 60)
        print(f"ARDA Group Profiles batch: D={start_id}~{end_id}")
        print("=" * 60)

        success = 0
        empty = 0
        failed = 0
        skipped = 0

        for group_id in range(start_id, end_id + 1):
            html = self.fetch_group_profile(str(group_id))
            if not html:
                failed += 1
                continue

            info = self.extract_group_info(html, str(group_id))
            if not info:
                empty += 1
                continue

            if not self.is_christian_profile(info):
                skipped += 1
                continue

            if self.save_denomination(info):
                success += 1
            else:
                failed += 1

            if group_id % 50 == 0:
                print(
                    f"[ARDA-Denom] progress: {group_id}/{end_id} "
                    f"(success:{success} skipped:{skipped} empty:{empty} failed:{failed})"
                )

        print("\n" + "=" * 60)
        print(f"done: {success} success / {skipped} skipped / {empty} empty / {failed} failed")
        print("=" * 60)
        return {"success": success, "skipped": skipped, "empty": empty, "failed": failed}


def collect_arda_denominations():
    """一键采集 ARDA 宗派档案"""
    collector = ARDADenominationCollector()
    try:
        return collector.run_batch(1, 800)
    finally:
        collector.close()


if __name__ == "__main__":
    # Development/Test entry. Not production collection path.
    print("Test: ARDA denomination profiles (1-50)")
    print("=" * 60)
    collector = ARDADenominationCollector()
    try:
        result = collector.run_batch(1, 50)
        print(f"\nresult: {result}")
    finally:
        collector.close()
