"""
批量计算 Intel Score
一次性加载 + 内存匹配。
"""

import json
import os
import sys
from datetime import datetime

from sqlalchemy import func

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models.database import OrganizationProfile, get_db_session
from services.intel_scorer import IntelScorer


def main():
    scorer = IntelScorer()
    db = get_db_session()

    try:
        orgs = db.query(OrganizationProfile).all()
        print(f"Loaded {len(orgs)} organizations")

        results = scorer.calculate_all(db, orgs)

        batch = []
        scored_with_intel = 0
        grade_counts = {"A": 0, "B": 0, "C": 0, "D": 0, "F": 0}
        calculated_at = datetime.utcnow()

        for org in orgs:
            result = results.get(org.id, {})
            org.intel_score = result.get("total_score", 0)
            org.intel_score_grade = result.get("grade", "F")
            org.intel_score_dimensions = json.dumps(result.get("dimensions", {}), ensure_ascii=True)
            org.intel_score_calculated_at = calculated_at

            batch.append(org)
            grade_counts[org.intel_score_grade] = grade_counts.get(org.intel_score_grade, 0) + 1
            if result.get("total_score", 0) > 0:
                scored_with_intel += 1

            if len(batch) >= 100:
                db.commit()
                batch = []

        if batch:
            db.commit()

        print(f"\nDone: {scored_with_intel}/{len(orgs)} have intelligence coverage")
        print("\nGrade Distribution:")
        for grade in ["A", "B", "C", "D", "F"]:
            print(f"  {grade}: {grade_counts.get(grade, 0)}")

        avg = db.query(func.avg(OrganizationProfile.intel_score)).scalar()
        avg_with = (
            db.query(func.avg(OrganizationProfile.intel_score))
            .filter(OrganizationProfile.intel_score > 0)
            .scalar()
        )
        print(f"\nAvg (all): {round(avg or 0, 1)}/100")
        print(f"Avg (with intel): {round(avg_with or 0, 1)}/100")

        top = (
            db.query(OrganizationProfile)
            .filter(OrganizationProfile.intel_score > 0)
            .order_by(OrganizationProfile.intel_score.desc(), OrganizationProfile.name.asc())
            .limit(10)
            .all()
        )

        print("\nTop 10:")
        for org in top:
            print(f"  {org.intel_score:3d} [{org.intel_score_grade}] {org.name[:50]}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
