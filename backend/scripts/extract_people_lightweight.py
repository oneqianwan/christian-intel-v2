import argparse
import asyncio
import logging
import os
import sys
import uuid
from typing import Optional, Tuple
from urllib.parse import urlparse

import httpx
from sqlalchemy import or_

script_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.dirname(script_dir)
os.chdir(backend_dir)
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from models.database import LeaderCandidate, OrganizationProfile, SessionLocal
from services.people_extractor_llm import extract_people_llm_sync
from services.people_validator import PeopleValidator

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
logging.getLogger("httpx").setLevel(logging.WARNING)

LEADERSHIP_PATHS = [
    "/leadership",
    "/team",
    "/our-team",
    "/leaders",
    "/staff",
    "/our-leadership",
    "/our-staff",
    "/meet-the-team",
    "/people",
    "/directors",
    "/executive-team",
    "/senior-leadership",
    "/board",
    "/governing-board",
    "/about/leadership",
    "/about/team",
    "/about-us/leadership",
]


def _normalize_base_url(url: str) -> Optional[str]:
    raw = (url or "").strip()
    if not raw:
        return None
    low = raw.lower()
    if any(bad in low for bad in ["google.com/search", "wikipedia.org", "wikidata.org"]):
        return None
    if not raw.startswith(("http://", "https://")):
        raw = "https://" + raw
    parsed = urlparse(raw)
    if not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")


def _is_likely_leadership_html(html: str) -> bool:
    snippet = (html or "")[:8000].lower()
    if len(snippet) < 500:
        return False
    if "<html" not in snippet and "<body" not in snippet:
        return False
    bad_markers = ["access denied", "cloudflare", "captcha", "please enable javascript"]
    if any(marker in snippet for marker in bad_markers):
        return False
    keywords = [
        "pastor",
        "president",
        "ceo",
        "director",
        "bishop",
        "founder",
        "senior",
        "lead",
        "minister",
        "reverend",
        "chairman",
        "team",
        "staff",
        "leadership",
        "executive",
    ]
    return any(k in snippet for k in keywords)


async def try_fetch_leadership_page(
    client: httpx.AsyncClient,
    base_url: str,
    org_name: str,
) -> Tuple[Optional[str], Optional[str]]:
    normalized = _normalize_base_url(base_url)
    if not normalized:
        return None, None

    for path in LEADERSHIP_PATHS:
        url = normalized + path
        try:
            resp = await client.get(url)
            if resp.status_code == 200 and _is_likely_leadership_html(resp.text or ""):
                print(f"[OK] {org_name}: Found leadership page at {str(resp.url)}")
                return resp.text or "", str(resp.url)
        except Exception:
            continue

    try:
        resp = await client.get(normalized)
        if resp.status_code == 200 and _is_likely_leadership_html(resp.text or ""):
            return resp.text or "", str(resp.url)
    except Exception:
        pass

    return None, None


async def batch_extract_lightweight(tier_filter: str = "T1", batch_size: int = 50) -> None:
    db = SessionLocal()
    validator = PeopleValidator()

    try:
        orgs = (
            db.query(OrganizationProfile)
            .filter(
                OrganizationProfile.priority_tier == tier_filter,
                or_(OrganizationProfile.leader_name == None, OrganizationProfile.leader_name == ""),
                OrganizationProfile.official_website != None,
                OrganizationProfile.official_website != "",
            )
            .order_by(OrganizationProfile.id)
            .limit(batch_size)
            .all()
        )
        print(f"找到 {len(orgs)} 家待提取People的{tier_filter}机构")

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(15.0, connect=10.0),
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
            limits=httpx.Limits(max_connections=10),
        ) as client:
            semaphore = asyncio.Semaphore(5)

            async def bounded(org: OrganizationProfile):
                async with semaphore:
                    html, url = await try_fetch_leadership_page(client, org.official_website or "", org.name)
                    return org, html, url

            results = await asyncio.gather(*[bounded(org) for org in orgs])

        updated = 0
        rejected = 0
        no_page = 0
        llm_success = 0
        dup = 0
        no_people = 0

        for org, html, source_url in results:
            if not html or not source_url:
                no_page += 1
                print(f"[NO_PAGE] {org.name}: 无法获取Leadership页面")
                continue

            people = extract_people_llm_sync(org.name, html, source_url)
            if not people:
                no_people += 1
                print(f"[NO_PEOPLE] {org.name}: LLM未提取到人名")
                continue

            person = people[0] or {}
            name = str(person.get("name", "")).strip()
            title = str(person.get("title", "")).strip()
            bio = str(person.get("bio", "")).strip()[:100]
            if not name:
                no_people += 1
                print(f"[NO_PEOPLE] {org.name}: name为空")
                continue

            validation = validator.validate(
                candidate_name=name,
                candidate_title=title,
                org_name=org.name,
                org_country=org.country or "",
                source_url=source_url,
                extraction_method="http_llm",
            )

            if validation.action == "reject":
                rejected += 1
                print(f"[REJECT] {org.name}: {name} - {title} | {validation.reason}")
                continue

            existing = (
                db.query(LeaderCandidate)
                .filter(
                    LeaderCandidate.organization_id == org.id,
                    LeaderCandidate.candidate_name == name,
                    LeaderCandidate.status.in_(["pending", "approved"]),
                )
                .first()
            )
            if existing:
                dup += 1
                print(f"[DUP] {org.name}: {name}")
                continue

            candidate_status = "approved" if validation.action == "approve" else "pending"
            candidate = LeaderCandidate(
                id=str(uuid.uuid4()),
                organization_id=org.id,
                candidate_name=name,
                candidate_title=title,
                candidate_bio=bio,
                source_url=source_url,
                extraction_method="http_llm",
                confidence=float(validation.confidence),
                status=candidate_status,
                validation_notes=validation.reason,
            )
            db.add(candidate)

            llm_success += 1

            if candidate_status == "approved" and float(validation.confidence) >= 0.75:
                org.leader_name = name
                org.leader_title = title
                org.leader_bio_url = source_url
                org.has_leadership_page = True
                org.confidence = max(float(org.confidence or 0.0), float(validation.confidence))
                updated += 1

            print(f"[OK] {org.name}: {name} - {title} (conf={validation.confidence:.2f}, status={candidate_status})")

        db.commit()

        t1_total = db.query(OrganizationProfile).filter(OrganizationProfile.priority_tier == "T1").count()
        t1_people = (
            db.query(OrganizationProfile)
            .filter(
                OrganizationProfile.priority_tier == "T1",
                OrganizationProfile.leader_name != None,
                OrganizationProfile.leader_name != "",
            )
            .count()
        )

        print("\n" + "=" * 50)
        print("People提取报告（轻量级HTTP）")
        print("=" * 50)
        print(f"处理: {len(orgs)}")
        print(f"无法获取页面: {no_page}")
        print(f"LLM提取成功: {llm_success}")
        print(f"LLM未提取到人名: {no_people}")
        print(f"重复候选跳过: {dup}")
        print(f"  - 直接入库: {updated}")
        print(f"拒绝: {rejected}")
        print(f"T1 People: {t1_people}/{t1_total} ({(t1_people / t1_total * 100) if t1_total else 0:.1f}%)")
    except Exception as e:
        db.rollback()
        print(f"ERROR: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="轻量级HTTP People提取")
    parser.add_argument("--tier", type=str, default="T1")
    parser.add_argument("--batch-size", type=int, default=50)
    args = parser.parse_args()

    asyncio.run(batch_extract_lightweight(tier_filter=args.tier, batch_size=args.batch_size))
