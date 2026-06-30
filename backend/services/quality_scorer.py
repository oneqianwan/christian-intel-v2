from dataclasses import dataclass
from typing import Dict, List

from models.database import OrganizationProfile, SessionLocal


@dataclass
class QualityBreakdown:
    org_id: str
    org_name: str
    tier: str
    overall_score: float
    field_scores: Dict[str, float]
    missing_fields: List[str]
    priority_rank: int


FIELD_WEIGHTS = {
    "website": 10.0,
    "people": 15.0,
    "contact": 5.0,
    "about": 10.0,
    "mission": 8.0,
    "vision": 5.0,
    "programs": 7.0,
    "leadership_page": 5.0,
    "annual_report": 5.0,
    "ai_score": 10.0,
    "digital_score": 10.0,
    "social": 5.0,
    "funding": 5.0,
}


class ProfileQualityScorer:
    def score_organization(self, org: OrganizationProfile) -> QualityBreakdown:
        field_scores: Dict[str, float] = {}
        missing: List[str] = []

        if org.official_website and org.url_tier in {"A", "B"}:
            field_scores["website"] = FIELD_WEIGHTS["website"]
        elif org.official_website:
            field_scores["website"] = 7.0
        else:
            field_scores["website"] = 0.0
            missing.append("website")

        if org.leader_name and len(org.leader_name.strip()) > 2:
            field_scores["people"] = FIELD_WEIGHTS["people"]
        else:
            field_scores["people"] = 0.0
            missing.append("people")

        if org.contact_email or org.phone_public:
            field_scores["contact"] = FIELD_WEIGHTS["contact"]
        else:
            field_scores["contact"] = 0.0
            missing.append("contact")

        if org.description and len(org.description.strip()) > 50:
            field_scores["about"] = FIELD_WEIGHTS["about"]
        elif org.description:
            field_scores["about"] = 5.0
        else:
            field_scores["about"] = 0.0
            missing.append("about")

        if org.mission_statement and len(org.mission_statement.strip()) > 20:
            field_scores["mission"] = FIELD_WEIGHTS["mission"]
        else:
            field_scores["mission"] = 0.0
            missing.append("mission")

        if org.vision_statement and org.vision_statement.strip():
            field_scores["vision"] = FIELD_WEIGHTS["vision"]
        else:
            field_scores["vision"] = 0.0
            missing.append("vision")

        if org.has_programs:
            field_scores["programs"] = FIELD_WEIGHTS["programs"]
        else:
            field_scores["programs"] = 0.0
            missing.append("programs")

        if org.has_leadership_page:
            field_scores["leadership_page"] = FIELD_WEIGHTS["leadership_page"]
        else:
            field_scores["leadership_page"] = 0.0
            missing.append("leadership_page")

        if org.has_annual_report:
            field_scores["annual_report"] = FIELD_WEIGHTS["annual_report"]
        else:
            field_scores["annual_report"] = 0.0
            missing.append("annual_report")

        if org.ai_maturity_score is not None:
            field_scores["ai_score"] = min(FIELD_WEIGHTS["ai_score"], float(org.ai_maturity_score) * 2)
        else:
            field_scores["ai_score"] = 0.0
            missing.append("ai_score")

        if org.digital_score is not None:
            field_scores["digital_score"] = min(FIELD_WEIGHTS["digital_score"], float(org.digital_score) * 2)
        else:
            field_scores["digital_score"] = 0.0
            missing.append("digital_score")

        if org.facebook_url or org.youtube_url or org.social_accounts_json:
            field_scores["social"] = FIELD_WEIGHTS["social"]
        else:
            field_scores["social"] = 0.0
            missing.append("social")

        if org.annual_revenue or org.budget_scale:
            field_scores["funding"] = FIELD_WEIGHTS["funding"]
        else:
            field_scores["funding"] = 0.0
            missing.append("funding")

        overall = round(sum(field_scores.values()), 1)

        return QualityBreakdown(
            org_id=org.id,
            org_name=org.name,
            tier=org.priority_tier or "T3",
            overall_score=overall,
            field_scores=field_scores,
            missing_fields=missing,
            priority_rank=0,
        )

    def score_all_t1(self) -> List[QualityBreakdown]:
        db = SessionLocal()
        try:
            orgs = db.query(OrganizationProfile).filter(OrganizationProfile.priority_tier == "T1").all()
            results = [self.score_organization(org) for org in orgs]
            results.sort(key=lambda item: (item.overall_score, item.org_name.lower()))
            for index, result in enumerate(results, start=1):
                result.priority_rank = index
            return results
        finally:
            db.close()

    def get_tier_summary(self, tier: str = "T1") -> Dict:
        db = SessionLocal()
        try:
            orgs = db.query(OrganizationProfile).filter(OrganizationProfile.priority_tier == tier).all()
            results = [self.score_organization(org) for org in orgs]
        finally:
            db.close()

        if not results:
            return {}

        results.sort(key=lambda item: (item.overall_score, item.org_name.lower()))
        for index, result in enumerate(results, start=1):
            result.priority_rank = index

        scores = [result.overall_score for result in results]
        below_target = len([result for result in results if result.overall_score < 60])

        return {
            "total": len(results),
            "avg_score": round(sum(scores) / len(scores), 1),
            "min_score": round(min(scores), 1),
            "max_score": round(max(scores), 1),
            "below_target": below_target,
            "top_10_weakest": [
                {
                    "name": result.org_name,
                    "score": result.overall_score,
                    "missing": result.missing_fields[:5],
                }
                for result in results[:10]
            ],
        }


def get_t1_quality_summary() -> Dict:
    scorer = ProfileQualityScorer()
    results = scorer.score_all_t1()
    if not results:
        return {}

    scores = [result.overall_score for result in results]
    below_target = len([result for result in results if result.overall_score < 60])

    return {
        "total": len(results),
        "avg_score": round(sum(scores) / len(scores), 1),
        "min_score": round(min(scores), 1),
        "max_score": round(max(scores), 1),
        "below_target": below_target,
        "top_10_weakest": [
            {
                "name": result.org_name,
                "score": result.overall_score,
                "missing": result.missing_fields[:5],
            }
            for result in results[:10]
        ],
    }
