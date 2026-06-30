#!/usr/bin/env python3
"""
导出 T1 People 缺口清单
生成一份用户友好的文本文件，方便手动录入。
"""

import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models.database import OrganizationProfile, SessionLocal


def export_people_gaps():
    db = SessionLocal()
    try:
        gaps = (
            db.query(OrganizationProfile)
            .filter(
                OrganizationProfile.priority_tier == "T1",
                (OrganizationProfile.leader_name == None) | (OrganizationProfile.leader_name == ""),
            )
            .order_by(OrganizationProfile.country.asc().nullsfirst(), OrganizationProfile.name.asc())
            .all()
        )

        output_lines = []
        output_lines.append("# T1 People Gaps - Manual Entry List")
        output_lines.append(f"# Total: {len(gaps)} organizations need People info")
        output_lines.append("# Format: Organization Name | Website | Suggested Leader | Title")
        output_lines.append("#" + "-" * 80)
        output_lines.append("")

        current_country = None
        for org in gaps:
            country = org.country or "Unknown"
            if country != current_country:
                current_country = country
                output_lines.append(f"## {current_country}")
                output_lines.append("")

            website = org.official_website or "NO_URL"
            output_lines.append(f"{org.name} | {website} | ??? | ???")

        json_data = [
            {
                "org_name": org.name,
                "country": org.country,
                "website": org.official_website,
                "current_leader": org.leader_name,
                "suggested_leader": "",
                "suggested_title": "",
                "source": "",
            }
            for org in gaps
        ]

        txt_path = os.path.join(os.getcwd(), "t1_people_gaps.txt")
        json_path = os.path.join(os.getcwd(), "t1_people_gaps_template.json")

        with open(txt_path, "w", encoding="utf-8") as file_obj:
            file_obj.write("\n".join(output_lines))

        with open(json_path, "w", encoding="utf-8") as file_obj:
            json.dump(json_data[:50], file_obj, indent=2, ensure_ascii=False)

        print(f"Exported {len(gaps)} T1 People gaps")
        print("Files created:")
        print(f"  - {txt_path}")
        print(f"  - {json_path}")

        country_counts = Counter((org.country or "Unknown") for org in gaps)
        print("\nTop countries with gaps:")
        for country, count in country_counts.most_common(10):
            print(f"  {country}: {count}")
    finally:
        db.close()


if __name__ == "__main__":
    export_people_gaps()
