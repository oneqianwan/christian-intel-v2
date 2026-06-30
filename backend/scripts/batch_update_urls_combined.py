import argparse
import os
import sys
from typing import Dict, List
from urllib.parse import urlparse

script_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.dirname(script_dir)
os.chdir(backend_dir)
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from models.database import OrganizationProfile, SessionLocal
from services.wikidata_url_finder import find_urls_sync
from services.wikipedia_url_extractor import find_urls_from_wikipedia


def _normalize_name(value: str) -> str:
    return " ".join((value or "").strip().lower().split())

def _chunk(items: List[str], size: int) -> List[List[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _is_url_plausible(org_name: str, url: str) -> bool:
    if not org_name or not url:
        return False

    try:
        parsed = urlparse(url)
        domain = (parsed.netloc or "").lower().strip().replace("www.", "")
        parts = [p for p in domain.split(".") if p]
        domain_core = parts[0] if parts else ""
        tld = parts[-1] if len(parts) >= 2 else ""
        if not domain_core:
            return True
    except Exception:
        return True

    org_lower = org_name.lower()
    if "newyork" in domain_core and "new york" not in org_lower and "newyork" not in org_lower:
        return False

    if "international" in org_lower and tld in {
        "at",
        "de",
        "fr",
        "es",
        "it",
        "nl",
        "no",
        "se",
        "fi",
        "dk",
        "pl",
        "cz",
        "sk",
        "hu",
        "ro",
        "bg",
        "gr",
        "pt",
        "br",
        "mx",
        "kr",
        "jp",
        "cn",
        "ru",
        "ua",
        "tr",
    }:
        if tld and tld not in org_lower:
            return False

    lower_url = url.lower()
    if "giving-thanks" in lower_url or "pray" in lower_url:
        return False

    if domain.endswith("blogspot.com") or domain.endswith("wordpress.com") or domain.endswith("wixsite.com"):
        return False

    return True


def batch_update_urls_combined(batch_size: int = 200, dry_run: bool = False, aggressive: bool = False) -> None:
    db = SessionLocal()
    try:
        missing_orgs: List[OrganizationProfile] = (
            db.query(OrganizationProfile)
            .filter((OrganizationProfile.official_website == None) | (OrganizationProfile.official_website == ""))
            .order_by((OrganizationProfile.source_name == "wiki_extracted").desc(), OrganizationProfile.name)
            .limit(batch_size)
            .all()
        )

        if not missing_orgs:
            print("没有缺失URL的机构")
            return

        org_names = [o.name for o in missing_orgs if o.name and o.name.strip()]
        print(f"找到 {len(missing_orgs)} 个缺失URL的机构")

        wikidata_results: Dict[str, str] = {}
        for batch in _chunk(org_names, 50):
            wikidata_results.update(find_urls_sync(batch))
        remaining = [n for n in org_names if n not in wikidata_results]
        wikipedia_results: Dict[str, str] = find_urls_from_wikipedia(remaining) if remaining else {}

        combined = {}
        combined.update(wikidata_results or {})
        combined.update(wikipedia_results or {})

        normalized_map = {_normalize_name(k): v for k, v in combined.items() if k and v}

        updated_count = 0
        suspicious = 0
        found_wikidata = 0
        found_wikipedia = 0
        aggressive_written = 0

        for org in missing_orgs:
            key = _normalize_name(org.name)
            url = normalized_map.get(key, "")
            if not url:
                continue
            if not aggressive and not _is_url_plausible(org.name, url):
                suspicious += 1
                continue

            if aggressive and not _is_url_plausible(org.name, url):
                aggressive_written += 1
                org.confidence = min(org.confidence or 50, 30)

            if org.name in (wikipedia_results or {}):
                found_wikipedia += 1
            elif org.name in (wikidata_results or {}):
                found_wikidata += 1

            if not dry_run:
                org.official_website = url
                if aggressive and _is_url_plausible(org.name, url):
                    org.confidence = org.confidence or 50
            updated_count += 1

        if not dry_run:
            db.commit()

        total = db.query(OrganizationProfile).count()
        has_url = (
            db.query(OrganizationProfile)
            .filter((OrganizationProfile.official_website != None) & (OrganizationProfile.official_website != ""))
            .count()
        )

        print("=" * 50)
        print("URL更新报告（Wikidata + Wikipedia）")
        print("=" * 50)
        print(f"查询机构数: {len(missing_orgs)}")
        print(f"命中Wikidata: {found_wikidata}")
        print(f"命中Wikipedia: {found_wikipedia}")
        print(f"可疑跳过: {suspicious}")
        print(f"激进写入: {aggressive_written}")
        print(f"写入URL: {updated_count}" + (" (dry_run)" if dry_run else ""))
        print(f"更新后URL覆盖率: {has_url}/{total} ({has_url / total * 100:.1f}%)")
    except Exception as e:
        if not dry_run:
            db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="批量更新机构官网URL（Wikidata + Wikipedia）")
    parser.add_argument("--batch-size", type=int, default=200)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--aggressive", action="store_true", help="激进模式：标记可疑但写入，提高覆盖率")
    args = parser.parse_args()
    batch_update_urls_combined(batch_size=args.batch_size, dry_run=args.dry_run, aggressive=args.aggressive)
