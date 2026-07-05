"""
批量计算 Digital Score
纯字段计算，零 HTTP，秒级完成。
"""

import json
import os
import sys
from datetime import datetime

from sqlalchemy import func

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models.database import OrganizationProfile, get_db_session
from services.digital_scorer import DigitalScorer


def main():
    scorer = DigitalScorer()
    db = get_db_session()

    try:
        orgs = db.query(OrganizationProfile).all()
        print(f"Total organizations: {len(orgs)}")

        batch = []
        scored = 0

        for org in orgs:
            try:
                result = scorer.score(org)

                org.digital_score = result["total_score"]
                org.digital_score_grade = result["grade"]
                org.digital_score_dimensions = json.dumps(result["dimensions"], ensure_ascii=True)
                org.digital_score_calculated_at = datetime.utcnow()

                batch.append(org)
                scored += 1

                if len(batch) >= 100:
                    db.commit()
                    batch = []
            except Exception:
                db.rollback()
                batch = []
                continue

        if batch:
            db.commit()

        print(f"\nDone: {scored}/{len(orgs)} scored")

        dist = (
            db.query(OrganizationProfile.digital_score_grade, func.count(OrganizationProfile.id))
            .group_by(OrganizationProfile.digital_score_grade)
            .all()
        )

        print("\nGrade Distribution:")
        for grade, count in sorted(dist):
            print(f"  {grade}: {count}")

        avg = db.query(func.avg(OrganizationProfile.digital_score)).scalar()
        print(f"\nAverage: {round(avg or 0, 1)}/100")

        has_website = (
            db.query(func.count(OrganizationProfile.id))
            .filter(
                OrganizationProfile.official_website.isnot(None),
                OrganizationProfile.official_website != "",
            )
            .scalar()
        )
        has_social = db.query(func.count(OrganizationProfile.id)).filter(OrganizationProfile.facebook_url.isnot(None)).scalar()
        has_ai = (
            db.query(func.count(OrganizationProfile.id))
            .filter(OrganizationProfile.has_ai_initiative == True)  # noqa: E712
            .scalar()
        )
        has_giving = (
            db.query(func.count(OrganizationProfile.id))
            .filter(OrganizationProfile.has_online_giving == True)  # noqa: E712
            .scalar()
        )

        print("\nKey Metrics:")
        print(f"  Has website: {has_website}/{len(orgs)} ({round(100 * has_website / len(orgs), 1)}%)")
        print(f"  Has Facebook: {has_social}/{len(orgs)} ({round(100 * has_social / len(orgs), 1)}%)")
        print(f"  Has AI initiative: {has_ai}/{len(orgs)} ({round(100 * has_ai / len(orgs), 1)}%)")
        print(f"  Has online giving: {has_giving}/{len(orgs)} ({round(100 * has_giving / len(orgs), 1)}%)")

        with_website_avg = (
            db.query(func.avg(OrganizationProfile.digital_score))
            .filter(
                OrganizationProfile.official_website.isnot(None),
                OrganizationProfile.official_website != "",
            )
            .scalar()
        )
        without_website_avg = (
            db.query(func.avg(OrganizationProfile.digital_score))
            .filter(
                (OrganizationProfile.official_website.is_(None)) | (OrganizationProfile.official_website == "")
            )
            .scalar()
        )
        print(f"  Avg with website: {round(with_website_avg or 0, 1)}/100")
        print(f"  Avg without website: {round(without_website_avg or 0, 1)}/100")

        top = (
            db.query(OrganizationProfile)
            .filter(OrganizationProfile.digital_score > 0)
            .order_by(OrganizationProfile.digital_score.desc())
            .limit(10)
            .all()
        )

        print("\nTop 10:")
        for org in top:
            print(f"  {org.digital_score:3d} [{org.digital_score_grade}] {org.name[:50]}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
