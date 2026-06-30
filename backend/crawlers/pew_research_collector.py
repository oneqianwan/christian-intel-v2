"""
Pew Research Center 宗教数据接入器 — Phase 1 Day 3
抓取 pewresearch.org 的公开宗教研究报告并入库
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


PEW_RELIGION_URL = "https://www.pewresearch.org/research-teams/religion/"
PEW_RELIGION_TOPIC_URL = "https://www.pewresearch.org/topic/religion/"

RELIGION_KEYWORDS = [
    "christian",
    "religion",
    "faith",
    "church",
    "religious",
    "catholic",
    "protestant",
    "evangelical",
    "muslim",
    "islam",
    "judaism",
    "buddhism",
    "hinduism",
    "atheist",
    "spirituality",
    "pope",
    "worship",
]

GENERIC_TITLES = {
    "Christianity",
    "Non-Religion & Secularism",
    "Religious Freedom & Restrictions",
}


def _clean_text(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value or "")
    value = html_lib.unescape(value)
    return re.sub(r"\s+", " ", value).strip()


class PewResearchCollector:
    """Pew Research 宗教报告采集器"""

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
            .filter(Source.name == "PewResearch")
            .order_by(Source.created_at.asc())
            .first()
        )
        if existing:
            return existing.id

        source = Source(
            id=str(uuid.uuid4()),
            name="PewResearch",
            url=PEW_RELIGION_URL,
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

    def fetch_religion_pages(self) -> List[str]:
        pages: List[str] = []
        for url in [PEW_RELIGION_URL, PEW_RELIGION_TOPIC_URL]:
            try:
                print(f"[PewResearch] fetch: {url}")
                response = self.session.get(url, timeout=30)
                response.raise_for_status()
                pages.append(response.text)
                print(f"[PewResearch] ok ({len(response.text)} bytes)")
            except Exception as exc:
                print(f"[PewResearch] failed {url}: {exc}")
        return pages

    def extract_featured_reports(self, html: str) -> List[Dict[str, str]]:
        reports: List[Dict[str, str]] = []
        seen = set()

        card_pattern = re.compile(
            r'<a[^>]+href="([^"]+)"[^>]*>\s*(.*?)\s*</a>',
            re.IGNORECASE | re.DOTALL,
        )
        for href, raw_block in card_pattern.findall(html):
            title = _clean_text(raw_block)
            if not title or len(title) < 12:
                continue

            full_url = href if href.startswith("http") else urljoin("https://www.pewresearch.org", href)
            lower_blob = f"{title} {full_url}".lower()
            if "pewresearch.org" not in full_url:
                continue
            if title in GENERIC_TITLES:
                continue
            if not any(keyword in lower_blob for keyword in RELIGION_KEYWORDS):
                continue
            if any(skip in lower_blob for skip in ["/staff/", "/about/", "/topic/", "/research-teams/", "/wp-content/", "/category/"]):
                continue
            if not re.search(r"/(religion|short-reads)/\d{4}/\d{2}/\d{2}/", full_url):
                continue
            if title in seen:
                continue

            snippet = None
            nearby_match = re.search(
                re.escape(href) + r'".{0,800}?(?:<p[^>]*>|<div[^>]*class="[^"]*excerpt[^"]*"[^>]*>)(.*?)(?:</p>|</div>)',
                html,
                re.IGNORECASE | re.DOTALL,
            )
            if nearby_match:
                snippet = _clean_text(nearby_match.group(1))[:500]

            reports.append(
                {
                    "title": title,
                    "url": full_url,
                    "snippet": snippet or "",
                    "source": "Pew Research Center",
                    "type": "research_report",
                }
            )
            seen.add(title)

        return reports[:20]

    def save_report_as_intelligence(self, report: Dict[str, str]) -> None:
        try:
            title = f"{report['title']} (Pew Research)"
            now = datetime.utcnow()
            content_lines = [
                f"Report Title: {report['title']}",
                "Source: Pew Research Center",
                "Type: Religion research report",
                f"URL: {report['url']}",
                f"Collected At: {now.strftime('%Y-%m-%d')}",
            ]
            if report.get("snippet"):
                content_lines.append(f"Summary: {report['snippet']}")
            content_lines.append(
                "Pew Research Center 是全球权威的宗教与社会研究机构，其宗教研究覆盖宗教人口、宗教自由、宗教实践与教会公共影响。"
            )
            content = "\n".join(content_lines)

            existing = (
                self.db.query(IntelligenceItem)
                .filter(
                    IntelligenceItem.title == title,
                    IntelligenceItem.source_name == "PewResearch",
                )
                .first()
            )
            if existing:
                existing.content = content
                existing.entity_name = report["title"]
                existing.entity_type = "research_report"
                existing.category = "religion_research"
                existing.source_url = report["url"]
                existing.ingested_at = now
                existing.confidence = 0.95
                print(f"[PewResearch] update: {report['title'][:70]}")
            else:
                self.db.add(
                    IntelligenceItem(
                        id=str(uuid.uuid4()),
                        source_id=self.source_id,
                        title=title,
                        content=content,
                        entity_name=report["title"],
                        entity_type="research_report",
                        country="全球",
                        category="religion_research",
                        source_url=report["url"],
                        source_name="PewResearch",
                        published_at=None,
                        ingested_at=now,
                        confidence=0.95,
                        scope="global",
                    )
                )
                print(f"[PewResearch] new: {report['title'][:70]}")

            self.db.commit()
        except Exception as exc:
            print(f"[PewResearch] save failed: {exc}")
            self.db.rollback()

    def run(self):
        print("=" * 60)
        print("Pew Research Center 宗教数据接入")
        print("=" * 60)

        pages = self.fetch_religion_pages()
        if not pages:
            return {"reports": 0}

        self.db.query(IntelligenceItem).filter(
            IntelligenceItem.source_name == "PewResearch",
            IntelligenceItem.title.in_([f"{title} (Pew Research)" for title in GENERIC_TITLES]),
        ).delete(synchronize_session=False)
        self.db.commit()

        merged_reports: List[Dict[str, str]] = []
        seen_urls = set()
        for html in pages:
            for report in self.extract_featured_reports(html):
                if report["url"] in seen_urls:
                    continue
                seen_urls.add(report["url"])
                merged_reports.append(report)

        print(f"\n提取到 {len(merged_reports)} 条宗教研究报告")
        for report in merged_reports:
            self.save_report_as_intelligence(report)

        print("\n" + "=" * 60)
        print("Pew Research 接入完成")
        print("=" * 60)
        return {"reports": len(merged_reports)}


def collect_pew_research():
    collector = PewResearchCollector()
    try:
        return collector.run()
    finally:
        collector.close()


if __name__ == "__main__":
    collect_pew_research()
