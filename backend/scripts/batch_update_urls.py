import argparse
import os
import sys
from typing import List
from urllib.parse import unquote, urlparse

script_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.dirname(script_dir)
os.chdir(backend_dir)
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from services.wikidata_url_finder import find_urls_from_wikipedia_sync, find_urls_sync
from models.database import OrganizationProfile, SessionLocal


def _normalize_name(value: str) -> str:
    return " ".join((value or "").strip().lower().split())


def _is_url_plausible(org_name: str, url: str) -> bool:
    if not org_name or not url:
        return False

    try:
        parsed = urlparse(url)
        domain = (parsed.netloc or "").lower().strip()
        domain = domain.replace("www.", "")
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

    if "giving-thanks" in url.lower() or "pray" in url.lower():
        return False

    if domain.endswith("blogspot.com") or domain.endswith("wordpress.com") or domain.endswith("wixsite.com"):
        return False

    org_words = (
        org_lower.replace("-", " ")
        .replace(",", " ")
        .replace("(", " ")
        .replace(")", " ")
        .replace("/", " ")
        .split()
    )

    stopwords = {
        "the",
        "and",
        "for",
        "of",
        "in",
        "to",
        "a",
        "an",
        "ministry",
        "ministries",
        "international",
        "inc",
        "ltd",
        "association",
        "council",
        "committee",
        "movement",
        "mission",
        "missions",
        "fellowship",
        "foundation",
        "society",
        "network",
        "university",
    }

    name_words = [w for w in org_words if len(w) >= 3 and w not in stopwords]
    if not name_words:
        name_words = [w for w in org_words if w not in stopwords] or org_words

    for word in name_words:
        if word and word in domain:
            return True

    if domain_core and domain_core in org_lower:
        return True

    acronym_letters = [w[0] for w in name_words if w and w[0].isalpha()]
    if len(acronym_letters) >= 2:
        acronym = "".join(acronym_letters)
        if len(acronym) >= 2 and acronym in domain_core:
            return True

    return True


def batch_update_urls(batch_size: int = 100, dry_run: bool = False) -> None:
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

        print(f"找到 {len(missing_orgs)} 个缺失URL的机构")

        org_names = [o.name for o in missing_orgs if o.name and o.name.strip()]
        if not org_names:
            print("缺失URL的机构中没有可用name字段")
            return

        print("开始查询Wikidata (Wikipedia->Wikidata优先)...")
        wikipedia_map = {}
        for org in missing_orgs:
            if not org.name or not org.source_url:
                continue
            su = str(org.source_url)
            if "wikipedia.org/wiki/" in su:
                try:
                    parsed = urlparse(su)
                    title = unquote((parsed.path or "").split("/wiki/", 1)[1]).replace("_", " ").lower()
                    tokens = [w for w in org.name.lower().replace("-", " ").replace(",", " ").split() if len(w) >= 4]
                    if any(t in title for t in tokens[:6]):
                        wikipedia_map[org.name] = su
                except Exception:
                    continue

        wiki_results = find_urls_from_wikipedia_sync(wikipedia_map) if wikipedia_map else {}
        remaining = [n for n in org_names if n not in wiki_results]
        name_results = find_urls_sync(remaining) if remaining else {}
        url_results = {}
        url_results.update(name_results)
        url_results.update(wiki_results)

        normalized_map = {_normalize_name(k): v for k, v in (url_results or {}).items() if k and v}

        updated_count = 0
        not_found: List[str] = []
        suspicious: List[str] = []

        for org in missing_orgs:
            key = _normalize_name(org.name)
            new_url = normalized_map.get(key, "")
            if new_url:
                if not _is_url_plausible(org.name, new_url):
                    suspicious.append(f"{org.name} (suspicious: {new_url})")
                    print(f"[SUSPICIOUS] 跳过: {org.name} -> {new_url}")
                    continue
                if dry_run:
                    print(f"[DRY RUN] 将更新 {org.name}: {new_url}")
                else:
                    org.official_website = new_url
                    print(f"更新 {org.name}: {new_url}")
                updated_count += 1
            else:
                not_found.append(org.name)

        if not dry_run:
            db.commit()
            print("数据库已提交")

        print("=" * 50)
        print("URL更新报告")
        print("=" * 50)
        print(f"查询机构数: {len(missing_orgs)}")
        print(f"找到URL: {updated_count}")
        print(f"未找到: {len(not_found)}")
        print(f"可疑跳过: {len(suspicious)}")
        print(f"成功率: {updated_count / len(missing_orgs) * 100:.1f}%")

        if not_found:
            print(f"未找到URL的机构（前20）: {not_found[:20]}")
        if suspicious:
            print(f"可疑URL（前20）: {suspicious[:20]}")

        total = db.query(OrganizationProfile).count()
        has_url = (
            db.query(OrganizationProfile)
            .filter((OrganizationProfile.official_website != None) & (OrganizationProfile.official_website != ""))
            .count()
        )
        print(f"更新后URL覆盖率: {has_url}/{total} ({has_url / total * 100:.1f}%)")
    except Exception as e:
        print(f"批量更新失败: {str(e)[:200]}")
        if not dry_run:
            db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="批量更新机构官网URL")
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    batch_update_urls(batch_size=args.batch_size, dry_run=args.dry_run)
