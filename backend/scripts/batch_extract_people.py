import argparse
import asyncio
import logging
import os
import sys
import uuid
from typing import Dict, Optional, Tuple

script_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.dirname(script_dir)
os.chdir(backend_dir)
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from models.database import LeaderCandidate, OrganizationProfile, SessionLocal
from services.people_extractor import PeopleExtractor, PeopleExtractorBatch, extract_people_sync
from services.people_extractor_llm import extract_people_llm_sync
from services.history_recorder import record_change
from services.people_validator import PeopleValidator

logger = logging.getLogger(__name__)


def _to_confidence_float(confidence_0_100: int) -> float:
    value = max(0, min(int(confidence_0_100), 100))
    return value / 100.0


async def _fetch_leadership_html(org_name: str, website_url: str) -> Tuple[Optional[str], Optional[str]]:
    extractor = PeopleExtractor()
    try:
        if extractor._should_skip_url(website_url):
            return None, None
        base_url = extractor._normalize_website_url(website_url)
        leadership_page = await extractor._quick_find_leadership_page(base_url)
        if not leadership_page:
            leadership_page = await extractor._find_leadership_page(base_url)
        if not leadership_page:
            return None, None

        try:
            response = await extractor.client.get(leadership_page, timeout=10.0)
            html = response.text or ""
            if response.status_code == 200 and len(html) >= 500:
                return html, leadership_page
        except Exception:
            pass

        rendered_html = await extractor._fetch_with_playwright(leadership_page)
        return rendered_html, leadership_page
    except Exception as exc:
        print(f"[LLM-FALLBACK-ERR] {org_name}: {str(exc)[:200]}")
        return None, None
    finally:
        await extractor.close()


def extract_people_mixed(org_name: str, website_url: str) -> Optional[Dict]:
    """混合策略：先规则提取，规则失败再尝试 LLM。"""
    result = extract_people_sync(org_name, website_url)
    if result and result.get("name"):
        result["method"] = "rule"
        return result

    try:
        html_content, source_url = asyncio.run(_fetch_leadership_html(org_name, website_url))
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            html_content, source_url = loop.run_until_complete(_fetch_leadership_html(org_name, website_url))
        finally:
            loop.close()

    if not html_content or not source_url:
        return None

    people = extract_people_llm_sync(org_name, html_content, source_url)
    if people:
        person = dict(people[0])
        person["method"] = "llm"
        return person
    return None


def batch_extract_people(
    batch_size: int = 30,
    source_filter: Optional[str] = None,
    field_filter: Optional[str] = None,
    tier_filter: Optional[str] = None,
    use_llm: bool = False,
    to_candidates: bool = False,
) -> None:
    db = SessionLocal()
    try:
        validator = PeopleValidator()
        query = db.query(OrganizationProfile).filter(
            OrganizationProfile.official_website != None,
            OrganizationProfile.official_website != "",
        )

        normalized_field = (field_filter or "people").strip().lower()
        if normalized_field in {"people", "leader"}:
            query = query.filter((OrganizationProfile.leader_name == None) | (OrganizationProfile.leader_name == ""))
        elif normalized_field == "website":
            query = query.filter((OrganizationProfile.official_website == None) | (OrganizationProfile.official_website == ""))
        elif normalized_field == "about":
            query = query.filter((OrganizationProfile.description == None) | (OrganizationProfile.description == ""))
        elif normalized_field == "mission":
            query = query.filter((OrganizationProfile.mission_statement == None) | (OrganizationProfile.mission_statement == ""))

        if source_filter:
            query = query.filter(OrganizationProfile.source_name == source_filter)
        if tier_filter:
            query = query.filter(OrganizationProfile.priority_tier == tier_filter)

        orgs = (
            query.order_by(
                (OrganizationProfile.priority_tier == "T1").desc(),
                (OrganizationProfile.source_name == "manual_seed").desc(),
                (OrganizationProfile.source_name == "auto_extracted_verified").desc(),
                (OrganizationProfile.source_name == "wiki_extracted").desc(),
                OrganizationProfile.id,
            )
            .limit(batch_size)
            .all()
        )

        print(f"找到 {len(orgs)} 个待提取People的机构")

        eligible_orgs = []
        skipped = 0
        for org in orgs:
            ow = (org.official_website or "").lower()
            if "google.com/search" in ow or "wikipedia.org" in ow or "wikidata.org" in ow:
                skipped += 1
                print(f"跳过: {org.name} ({org.official_website}) [非官网URL]")
                continue
            eligible_orgs.append((org.name, org.official_website))

        async def _run_batch():
            extractor = PeopleExtractorBatch(max_concurrent_tabs=3)
            try:
                return await extractor.extract_batch(eligible_orgs)
            finally:
                await extractor.close()

        batch_results = asyncio.run(_run_batch()) if eligible_orgs else []
        results_by_name = {item["org_name"]: item for item in batch_results}

        llm_fallback_success = 0
        if use_llm:
            failed_orgs = [org for org in orgs if org.name not in results_by_name and (org.official_website or "").strip()]
            for org in failed_orgs:
                fallback_result = extract_people_mixed(org.name, org.official_website)
                if fallback_result and fallback_result.get("name"):
                    results_by_name[org.name] = {
                        "org_name": org.name,
                        "name": fallback_result["name"],
                        "title": fallback_result["title"],
                        "source_url": fallback_result.get("source_url", org.official_website),
                        "confidence": fallback_result.get("confidence", 75),
                        "method": fallback_result.get("method", "llm"),
                    }
                    llm_fallback_success += 1
                    print(
                        f"[LLM] {org.name}: {fallback_result['name']} - {fallback_result['title']} "
                        f"(conf={fallback_result.get('confidence')})"
                    )

        updated = 0
        rejected_count = 0
        pending_count = 0
        approved_candidate_count = 0
        direct_write_count = 0
        duplicate_candidate_count = 0
        for org in orgs:
            result = results_by_name.get(org.name)
            if not result:
                continue

            method_label = result.get("method", "rule")
            validation_result = validator.validate(
                candidate_name=result["name"],
                candidate_title=result["title"],
                org_name=org.name,
                org_country=org.country or "",
                source_url=result.get("source_url", org.official_website or ""),
                extraction_method=method_label,
            )

            if validation_result.action == "reject":
                rejected_count += 1
                print(
                    f"[REJECT] {org.name}: {result['name']} - {result['title']} "
                    f"reason={validation_result.reason}"
                )
                continue

            extracted_conf = validation_result.confidence
            if not to_candidates:
                old_leader_name = org.leader_name
                old_leader_title = org.leader_title
                old_leadership_page = org.has_leadership_page
                org.leader_name = result["name"]
                org.leader_title = result["title"]
                org.leader_bio_url = result["source_url"]
                org.has_leadership_page = True

                existing_conf = org.confidence if org.confidence is not None else 0.0
                if (org.source_name or "") in ("manual_seed", "auto_extracted_verified"):
                    org.confidence = max(float(existing_conf), float(extracted_conf))
                else:
                    org.confidence = min(float(extracted_conf), 0.60)

                updated += 1
                record_change(
                    org_id=org.id,
                    field_name="leader_name",
                    old_value=old_leader_name,
                    new_value=org.leader_name,
                    source="batch_people_extract",
                    changed_by="system",
                    db=db,
                )
                record_change(
                    org_id=org.id,
                    field_name="leader_title",
                    old_value=old_leader_title,
                    new_value=org.leader_title,
                    source="batch_people_extract",
                    changed_by="system",
                    db=db,
                )
                record_change(
                    org_id=org.id,
                    field_name="has_leadership_page",
                    old_value=old_leadership_page,
                    new_value=org.has_leadership_page,
                    source="batch_people_extract",
                    changed_by="system",
                    db=db,
                )
                print(
                    f"[OK] {org.name}: {result['name']} - {result['title']} "
                    f"(conf={extracted_conf}, method={method_label})"
                )
                continue

            existing_candidate = (
                db.query(LeaderCandidate)
                .filter(
                    LeaderCandidate.organization_id == org.id,
                    LeaderCandidate.candidate_name == result["name"],
                    LeaderCandidate.candidate_title == result["title"],
                    LeaderCandidate.source_url == result.get("source_url", org.official_website or ""),
                    LeaderCandidate.status.in_(["pending", "approved"]),
                )
                .first()
            )
            if existing_candidate:
                duplicate_candidate_count += 1
                print(f"[DUP] {org.name}: {result['name']} - {result['title']}")
                continue

            candidate_status = "approved" if validation_result.action == "approve" else "pending"
            candidate = LeaderCandidate(
                id=str(uuid.uuid4()),
                organization_id=org.id,
                candidate_name=result["name"],
                candidate_title=result["title"],
                candidate_bio=result.get("bio", ""),
                source_url=result.get("source_url", org.official_website or ""),
                extraction_method=method_label,
                confidence=extracted_conf,
                status=candidate_status,
                validation_notes=validation_result.reason,
            )
            db.add(candidate)

            if candidate_status == "approved":
                approved_candidate_count += 1
            else:
                pending_count += 1

            if validation_result.action == "approve" and validation_result.confidence >= 0.8:
                old_leader_name = org.leader_name
                old_leader_title = org.leader_title
                old_leadership_page = org.has_leadership_page
                org.leader_name = result["name"]
                org.leader_title = result["title"]
                org.leader_bio_url = result.get("source_url", org.official_website or "")
                org.has_leadership_page = True
                existing_conf = org.confidence if org.confidence is not None else 0.0
                if (org.source_name or "") in ("manual_seed", "auto_extracted_verified"):
                    org.confidence = max(float(existing_conf), float(extracted_conf))
                else:
                    org.confidence = min(float(extracted_conf), 0.60)
                direct_write_count += 1
                record_change(
                    org_id=org.id,
                    field_name="leader_name",
                    old_value=old_leader_name,
                    new_value=org.leader_name,
                    source="batch_people_extract",
                    changed_by="system",
                    db=db,
                )
                record_change(
                    org_id=org.id,
                    field_name="leader_title",
                    old_value=old_leader_title,
                    new_value=org.leader_title,
                    source="batch_people_extract",
                    changed_by="system",
                    db=db,
                )
                record_change(
                    org_id=org.id,
                    field_name="has_leadership_page",
                    old_value=old_leadership_page,
                    new_value=org.has_leadership_page,
                    source="batch_people_extract",
                    changed_by="system",
                    db=db,
                )

            updated += 1
            print(
                f"[CANDIDATE] {org.name}: {result['name']} - {result['title']} "
                f"(status={candidate_status}, conf={extracted_conf}, method={method_label})"
            )

        failed = max(0, len(eligible_orgs) - len(batch_results))

        db.commit()

        total_with_people = (
            db.query(OrganizationProfile)
            .filter(OrganizationProfile.leader_name != None, OrganizationProfile.leader_name != "")
            .count()
        )

        print("=" * 50)
        print("People提取报告")
        print("=" * 50)
        print(f"本次处理: {len(orgs)}")
        print(f"合格官网: {len(eligible_orgs)}")
        print(f"跳过伪URL: {skipped}")
        print(f"通过校验: {updated}")
        print(f"规则未提取到: {failed}")
        print(f"LLM补充成功: {llm_fallback_success}")
        print(f"拒绝候选: {rejected_count}")
        print(f"候选待审核: {pending_count}")
        print(f"候选自动通过: {approved_candidate_count}")
        print(f"正式表直写: {direct_write_count}")
        print(f"重复候选跳过: {duplicate_candidate_count}")
        print(f"People覆盖总数: {total_with_people}")
    except Exception as e:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="批量提取机构People信息")
    parser.add_argument("--batch-size", type=int, default=30)
    parser.add_argument("--source", type=str, default=None)
    parser.add_argument("--field", type=str, default="people")
    parser.add_argument("--tier", type=str, default=None)
    parser.add_argument("--use-llm", action="store_true")
    parser.add_argument("--to-candidates", action="store_true")
    args = parser.parse_args()
    batch_extract_people(
        batch_size=args.batch_size,
        source_filter=args.source,
        field_filter=args.field,
        tier_filter=args.tier,
        use_llm=args.use_llm,
        to_candidates=args.to_candidates,
    )
