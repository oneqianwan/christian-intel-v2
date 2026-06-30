import argparse
import json
import logging
import os
import sys
import uuid
from typing import Dict, List, Optional, Tuple

from sqlalchemy import and_, or_

script_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.dirname(script_dir)
os.chdir(backend_dir)
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from models.database import LeaderCandidate, OrganizationProfile, SessionLocal
from services.llm_client import call_llm
from services.people_validator import PeopleValidator

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
logging.getLogger("httpx").setLevel(logging.WARNING)


EXTRACTION_PROMPT = """You are a data extraction specialist. Extract leadership information from the following text content about {org_name}.

Text Content:
{text_content}

Instructions:
1. Extract the TOP 3 most senior leaders (CEO, President, Founder, Senior Pastor, Director, Chairman, Bishop, etc.)
2. For each person, extract:
   - Full name
   - Title/Position
   - Brief bio (if available, max 100 chars)
3. Return ONLY a JSON array:
[
  {{"name": "Full Name", "title": "Job Title", "bio": "Brief description"}}
]

CRITICAL RULES:
- Only extract CURRENT leaders of THIS organization
- DO NOT extract: journalists, columnists, writers, contributors, editors
- DO NOT extract: Admin, Webmaster, IT Support, generic roles
- DO NOT extract: authors of articles unless they are the org's leaders
- Prioritize: CEO, President, Founder, Senior Pastor, Lead Pastor, Bishop, Executive Director
- If no person names found, return []
"""


def _parse_people_response(response: str) -> List[Dict]:
    if not response:
        return []
    try:
        data = json.loads(response)
        return data if isinstance(data, list) else []
    except Exception:
        pass

    import re

    code_block = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", response)
    if code_block:
        try:
            data = json.loads(code_block.group(1))
            return data if isinstance(data, list) else []
        except Exception:
            pass

    array_match = re.search(r"\[\s*\{[\s\S]*\}\s*\]", response)
    if array_match:
        try:
            data = json.loads(array_match.group(0))
            return data if isinstance(data, list) else []
        except Exception:
            pass
    return []


def extract_people_from_text(org_name: str, text_content: str) -> List[Dict]:
    if not text_content or len(text_content) < 100:
        return []

    truncated = (text_content or "")[:6000]
    prompt = EXTRACTION_PROMPT.format(org_name=org_name, text_content=truncated)

    try:
        response = call_llm(prompt, max_tokens=800, temperature=0.1)
        return _parse_people_response(response)
    except Exception as exc:
        logger.error("LLM extraction failed for %s: %s", org_name, str(exc)[:200])
        return []


def _build_text_source(org: OrganizationProfile) -> str:
    parts: List[str] = []
    if org.about_text:
        parts.append(org.about_text)
    if org.description:
        parts.append(org.description)
    return "\n\n".join(parts).strip()


def _upsert_candidate(
    db,
    org: OrganizationProfile,
    name: str,
    title: str,
    bio: str,
    status: str,
    confidence: float,
    validation_notes: str,
    extraction_method: str,
) -> Tuple[bool, Optional[LeaderCandidate]]:
    existing = (
        db.query(LeaderCandidate)
        .filter(
            LeaderCandidate.organization_id == org.id,
            LeaderCandidate.candidate_name == name,
            LeaderCandidate.candidate_title == title,
            LeaderCandidate.status.in_(["pending", "approved"]),
        )
        .first()
    )
    if existing:
        return False, existing

    candidate = LeaderCandidate(
        id=str(uuid.uuid4()),
        organization_id=org.id,
        candidate_name=name,
        candidate_title=title,
        candidate_bio=(bio or "")[:100],
        source_url=org.official_website or "",
        extraction_method=extraction_method,
        confidence=float(confidence),
        status=status,
        validation_notes=validation_notes,
    )
    db.add(candidate)
    return True, candidate


def batch_extract_from_existing_text(
    tier_filter: str = "T1",
    batch_size: int = 100,
    to_candidates: bool = True,
) -> None:
    db = SessionLocal()
    validator = PeopleValidator()

    try:
        query = (
            db.query(OrganizationProfile)
            .filter(
                OrganizationProfile.priority_tier == tier_filter,
                or_(OrganizationProfile.leader_name == None, OrganizationProfile.leader_name == ""),
                or_(
                    and_(OrganizationProfile.about_text != None, OrganizationProfile.about_text != ""),
                    and_(OrganizationProfile.description != None, OrganizationProfile.description != ""),
                ),
            )
            .order_by(OrganizationProfile.id)
            .limit(batch_size)
        )

        orgs = query.all()
        print(f"找到 {len(orgs)} 家有文本但无People的{tier_filter}机构")

        extracted_any = 0
        accepted = 0
        rejected = 0
        pending_count = 0
        approved_count = 0
        no_people_found = 0
        duplicate_count = 0
        direct_written = 0

        for org in orgs:
            combined_text = _build_text_source(org)
            people = extract_people_from_text(org.name, combined_text)

            if not people:
                no_people_found += 1
                print(f"[NO_PEOPLE] {org.name}: 文本中未找到人名")
                continue

            extracted_any += 1
            person = people[0] or {}
            name = str(person.get("name", "")).strip()
            title = str(person.get("title", "")).strip()
            bio = str(person.get("bio", "")).strip()[:100]

            if not name or not title:
                no_people_found += 1
                continue

            validation_result = validator.validate(
                candidate_name=name,
                candidate_title=title,
                org_name=org.name,
                org_country=org.country or "",
                source_url=org.official_website or "",
                extraction_method="text_llm",
            )

            if validation_result.action == "reject":
                rejected += 1
                print(f"[REJECT] {org.name}: {name} - {title} | reason={validation_result.reason}")
                continue

            accepted += 1

            candidate_status = "approved" if validation_result.action == "approve" else "pending"

            created, _ = _upsert_candidate(
                db=db,
                org=org,
                name=name,
                title=title,
                bio=bio,
                status=candidate_status,
                confidence=float(validation_result.confidence),
                validation_notes=validation_result.reason,
                extraction_method="text_llm",
            )
            if not created:
                duplicate_count += 1
                print(f"[DUP] {org.name}: {name}")
                continue

            if candidate_status == "approved":
                approved_count += 1
            else:
                pending_count += 1

            if (not to_candidates) or (candidate_status == "approved" and float(validation_result.confidence) >= 0.8):
                org.leader_name = name
                org.leader_title = title
                org.leader_bio_url = org.official_website or ""
                org.has_leadership_page = True
                org.confidence = min(float(validation_result.confidence), 0.75)
                direct_written += 1

                if candidate_status != "approved":
                    _upsert_candidate(
                        db=db,
                        org=org,
                        name=name,
                        title=title,
                        bio=bio,
                        status="approved",
                        confidence=max(float(validation_result.confidence), 0.75),
                        validation_notes="direct_write",
                        extraction_method="text_llm",
                    )

            print(
                f"[CANDIDATE] {org.name}: {name} - {title} "
                f"(status={candidate_status}, conf={validation_result.confidence:.2f})"
            )

        db.commit()

        total_with_people = (
            db.query(OrganizationProfile).filter(OrganizationProfile.leader_name != None, OrganizationProfile.leader_name != "").count()
        )
        tier_with_people = (
            db.query(OrganizationProfile)
            .filter(
                OrganizationProfile.priority_tier == tier_filter,
                OrganizationProfile.leader_name != None,
                OrganizationProfile.leader_name != "",
            )
            .count()
        )
        tier_total = db.query(OrganizationProfile).filter(OrganizationProfile.priority_tier == tier_filter).count()

        print("\n" + "=" * 50)
        print("People提取报告（从已有文本）")
        print("=" * 50)
        print(f"处理机构: {len(orgs)}")
        print(f"文本提取到候选: {extracted_any}")
        print(f"文本中未找到人名: {no_people_found}")
        print(f"通过校验: {accepted}")
        print(f"拒绝: {rejected}")
        print(f"重复候选跳过: {duplicate_count}")
        print(f"候选自动通过: {approved_count}")
        print(f"候选待审核: {pending_count}")
        print(f"正式表直写: {direct_written}")
        if tier_total:
            print(f"\n{tier_filter} People覆盖: {tier_with_people}/{tier_total} ({tier_with_people / tier_total * 100:.1f}%)")
        else:
            print(f"\n{tier_filter} People覆盖: {tier_with_people}/{tier_total} (N/A)")
        print(f"全局People覆盖: {total_with_people}")
    except Exception as e:
        db.rollback()
        print(f"ERROR: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="从已有文本字段提取People")
    parser.add_argument("--tier", type=str, default="T1")
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--direct-write", action="store_true", help="直接写入正式表（默认入候选表）")
    args = parser.parse_args()

    batch_extract_from_existing_text(
        tier_filter=args.tier,
        batch_size=args.batch_size,
        to_candidates=not args.direct_write,
    )
