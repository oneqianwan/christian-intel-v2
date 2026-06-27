import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from models.database import KnowledgeEntity


ARDA_BASE = "https://www.thearda.com"


PRIORITY_COUNTRIES: Dict[str, str] = {
    "178c": "Philippines",
    "234c": "United States",
    "166c": "Nigeria",
    "109c": "Indonesia",
    "124c": "South Korea",
    "50c": "Taiwan",
    "1c": "Afghanistan",
}


COUNTRY_ZH: Dict[str, str] = {
    "178c": "菲律宾",
    "234c": "美国",
    "166c": "尼日利亚",
    "109c": "印尼",
    "124c": "韩国",
    "50c": "台湾",
    "1c": "阿富汗",
}


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


def _get_included_h2(soup: BeautifulSoup) -> str:
    for h2 in soup.find_all("h2"):
        text = _normalize_text(h2.get_text(" ", strip=True))
        if text.lower().startswith("included nations/regions:"):
            return text
    return ""


def _parse_primary_country_name(included_h2: str) -> str:
    if not included_h2:
        return ""
    tail = included_h2.split(":", 1)[-1].strip()
    first_part = tail.split(",", 1)[0].strip()
    first_part = first_part.replace("[ x ]", "").replace("[x]", "").replace("[ X ]", "")
    return _normalize_text(first_part)


def _parse_table_name(table) -> str:
    caption = table.find("caption")
    if caption:
        return _normalize_text(caption.get_text(" ", strip=True))
    prev_header = table.find_previous(["h2", "h3", "h4"])
    if prev_header:
        return _normalize_text(prev_header.get_text(" ", strip=True))
    return ""


def _extract_kv_table(table) -> Dict[str, str]:
    data: Dict[str, str] = {}
    for row in table.find_all("tr"):
        cells = row.find_all(["td", "th"])
        if len(cells) < 2:
            continue
        key = _normalize_text(cells[0].get_text(" ", strip=True))
        value = _normalize_text(cells[1].get_text(" ", strip=True))
        if not key or not value:
            continue
        if key in data:
            continue
        data[key] = value
    return data


def _extract_religion_composition(table) -> Dict[str, float]:
    rows = table.find_all("tr")
    if not rows:
        return {}
    header_cells = rows[0].find_all(["td", "th"])
    header_text = " | ".join(_normalize_text(c.get_text(" ", strip=True)) for c in header_cells)
    if "Religion" not in header_text:
        return {}
    composition: Dict[str, float] = {}
    for row in rows[1:]:
        cells = row.find_all(["td", "th"])
        if len(cells) < 2:
            continue
        name = _normalize_text(cells[0].get_text(" ", strip=True))
        value = _normalize_text(cells[1].get_text(" ", strip=True))
        if not name or "%" not in value:
            continue
        m = re.search(r"([\d.]+)%", value)
        if not m:
            continue
        try:
            composition[name] = float(m.group(1))
        except Exception:
            continue
    return composition


def _extract_summary_indicators(tables: List) -> Dict[str, Any]:
    indicators: Dict[str, Any] = {}
    wanted = ["population", "area", "life expectancy", "gni", "income"]
    for table in tables:
        table_name = _parse_table_name(table).lower()
        if "summary" not in table_name and "information" not in table_name:
            continue
        kv = _extract_kv_table(table)
        for k, v in kv.items():
            lk = k.lower()
            if not any(w in lk for w in wanted):
                continue
            raw = v.replace(",", "")
            m = re.search(r"([\d.]+)", raw)
            if not m:
                indicators[k] = v
                continue
            try:
                indicators[k] = float(m.group(1))
            except Exception:
                indicators[k] = v
    return indicators


def _extract_religion_state(tables: List) -> Dict[str, str]:
    combined: Dict[str, str] = {}
    for table in tables:
        name = _parse_table_name(table).lower()
        if ("religion and state" not in name) and ("constitution" not in name) and ("features of constitution" not in name):
            continue
        kv = _extract_kv_table(table)
        for k, v in kv.items():
            if k not in combined:
                combined[k] = v
    return combined


def fetch_arda_country(country_code: str) -> Dict[str, Any]:
    url = f"{ARDA_BASE}/world-religion/national-profiles?u={country_code}"
    print(f"抓取ARDA: {url}")

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }
        resp = httpx.get(url, headers=headers, timeout=20, verify=False, follow_redirects=True)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "lxml")

        included_h2 = _get_included_h2(soup)
        country_name_from_h2 = _parse_primary_country_name(included_h2)

        extracted_fields: Dict[str, Dict[str, str]] = {}
        tables = soup.find_all("table")
        religion_composition: Dict[str, float] = {}

        for table in tables:
            table_name = _parse_table_name(table)
            if table_name:
                extracted_fields[table_name] = _extract_kv_table(table)
            if not religion_composition:
                religion_composition = _extract_religion_composition(table)

        summary_indicators = _extract_summary_indicators(tables)
        religion_state = _extract_religion_state(tables)

        return {
            "country_code": country_code,
            "url": url,
            "status": "success",
            "country_name": country_name_from_h2 or PRIORITY_COUNTRIES.get(country_code, ""),
            "included": included_h2,
            "extracted_fields": extracted_fields,
            "religion_composition": religion_composition,
            "summary_indicators": summary_indicators,
            "religion_state": religion_state,
        }
    except Exception as e:
        return {
            "country_code": country_code,
            "status": "failed",
            "error": str(e)[:200],
        }


def store_arda_data(db: Session, country_code: str, arda_data: Dict[str, Any]) -> Dict[str, Any]:
    if arda_data.get("status") != "success":
        return {"status": "failed", "error": "数据抓取失败"}

    en_name = arda_data.get("country_name") or PRIORITY_COUNTRIES.get(country_code, "Unknown")
    zh_name = COUNTRY_ZH.get(country_code)
    display_name = f"{en_name}（{zh_name}）" if zh_name else en_name
    country_field = zh_name or en_name

    entity_data: Dict[str, Any] = {
        "description": f"ARDA国家概况: {display_name}",
        "included": arda_data.get("included", ""),
        "religion_composition": arda_data.get("religion_composition", {}),
        "summary_indicators": arda_data.get("summary_indicators", {}),
        "religion_state": arda_data.get("religion_state", {}),
        "extracted_fields": arda_data.get("extracted_fields", {}),
        "source": "ARDA",
        "source_url": arda_data.get("url"),
        "ingested_at": datetime.utcnow().isoformat(),
    }

    source_url = arda_data.get("url") or ""
    existing = (
        db.query(KnowledgeEntity)
        .filter(KnowledgeEntity.entity_type == "country_profile", KnowledgeEntity.source_url == source_url)
        .first()
    )

    if existing:
        existing.name = display_name
        existing.country = country_field
        existing.category = "arda_national_profile"
        existing.data = entity_data
        existing.ingested_at = datetime.utcnow()
        existing.confidence = 0.95
        db.commit()
        return {"status": "updated", "entity_id": existing.id}

    entity = KnowledgeEntity(
        id=str(uuid.uuid4()),
        entity_type="country_profile",
        name=display_name,
        country=country_field,
        category="arda_national_profile",
        data=entity_data,
        source_url=source_url,
        source_name="ARDA (Association of Religion Data Archives)",
        ingested_at=datetime.utcnow(),
        confidence=0.95,
    )
    db.add(entity)
    db.commit()
    return {"status": "created", "entity_id": entity.id}


def collect_arda_priority_countries(db: Session) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    for code, name in PRIORITY_COUNTRIES.items():
        print(f"\n--- 采集 {name} ({code}) ---")
        arda_data = fetch_arda_country(code)
        if arda_data.get("status") == "success":
            stored = store_arda_data(db, code, arda_data)
            results.append(
                {
                    "country": name,
                    "code": code,
                    "status": stored.get("status"),
                    "fields_count": len(arda_data.get("extracted_fields", {})),
                }
            )
        else:
            results.append(
                {
                    "country": name,
                    "code": code,
                    "status": "failed",
                    "error": arda_data.get("error", "未知错误"),
                }
            )
    return results
