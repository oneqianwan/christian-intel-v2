"""
批量计算 People Score V2
优化：批量 commit + 每 50 条 commit 一次 + 取消 sleep
"""

import json
import os
import sys
from datetime import datetime

from sqlalchemy import func

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models.database import OrganizationProfile, get_db_session
from services.people_scorer import PeopleScorerV2


def main():
    scorer = PeopleScorerV2(timeout=3)

    db = get_db_session()
    try:
        orgs = (
            db.query(OrganizationProfile)
            .filter(
                OrganizationProfile.official_website.isnot(None),
                OrganizationProfile.official_website != "",
            )
            .all()
        )

        print(f"Total organizations with website: {len(orgs)}")

        scored = 0
        failed = 0
        grade_counts = {"A": 0, "B": 0, "C": 0, "D": 0, "F": 0}
        source_counts = {"record": 0, "pages_crawled": 0, "probe": 0}

        batch = []

        for i, org in enumerate(orgs):
            try:
                result = scorer.score_from_record(org)

                org.people_score = result["total_score"]
                org.people_score_grade = result["grade"]
                org.people_score_dimensions = json.dumps(
                    {
                        "dimensions": result["dimensions"],
                        "data_source": result["data_source"],
                        "pages_found": result["pages_found"],
                        "error": result["error"],
                    },
                    ensure_ascii=True,
                )
                org.people_score_calculated_at = datetime.utcnow()

                batch.append(org)
                scored += 1
                grade_counts[result["grade"]] = grade_counts.get(result["grade"], 0) + 1
                source_counts[result["data_source"]] = source_counts.get(result["data_source"], 0) + 1

                if len(batch) >= 50:
                    db.commit()
                    print(f"  Committed {i + 1}/{len(orgs)}")
                    batch = []

                if i % 10 == 0 and i > 0:
                    print(f"Progress: {i}/{len(orgs)} scored={scored} failed={failed}")
            except Exception as exc:
                failed += 1
                db.rollback()
                if failed <= 3:
                    print(f"  ERROR {org.name}: {exc}")
                batch = []
                continue

        if batch:
            db.commit()

        print(f"\n{'=' * 50}")
        print(f"DONE: {scored} scored, {failed} failed")

        print("\nGrade Distribution:")
        for grade in ["A", "B", "C", "D", "F"]:
            print(f"  {grade}: {grade_counts.get(grade, 0)}")

        print("\nData Source Distribution:")
        for source in ["record", "pages_crawled", "probe"]:
            print(f"  {source}: {source_counts.get(source, 0)}")

        avg = db.query(func.avg(OrganizationProfile.people_score)).scalar()
        print(f"\nAverage Score: {round(avg or 0, 1)}/100")

        avg_leader = (
            db.query(func.avg(OrganizationProfile.people_score))
            .filter(
                OrganizationProfile.leader_name.isnot(None),
                OrganizationProfile.leader_name != "",
            )
            .scalar()
        )
        print(f"Avg (has leader): {round(avg_leader or 0, 1)}/100")

        top = (
            db.query(OrganizationProfile)
            .filter(OrganizationProfile.people_score > 0)
            .order_by(OrganizationProfile.people_score.desc())
            .limit(10)
            .all()
        )

        print("\nTop 10:")
        for org in top:
            print(f"  {org.people_score:3d} [{org.people_score_grade}] {org.name[:50]}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
