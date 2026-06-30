import argparse
import os
import sys

script_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.dirname(script_dir)
os.chdir(backend_dir)
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from models.database import OrganizationProfile, SessionLocal
from services.domain_guesser import guess_url_sync


def batch_guess_urls(batch_size: int = 50) -> None:
    db = SessionLocal()
    try:
        missing_orgs = (
            db.query(OrganizationProfile)
            .filter((OrganizationProfile.official_website == None) | (OrganizationProfile.official_website == ""))
            .order_by((OrganizationProfile.source_name == "wiki_extracted").desc(), OrganizationProfile.name)
            .limit(batch_size)
            .all()
        )

        updated = 0
        for org in missing_orgs:
            if not org.name:
                continue

            url = guess_url_sync(org.name, org.country)
            if url:
                org.official_website = url
                org.confidence = min(org.confidence or 50, 35)
                updated += 1
                print(f"猜测成功: {org.name} -> {url}")

        db.commit()

        total = db.query(OrganizationProfile).count()
        has_url = (
            db.query(OrganizationProfile)
            .filter((OrganizationProfile.official_website != None) & (OrganizationProfile.official_website != ""))
            .count()
        )
        guessed_urls = db.query(OrganizationProfile).filter(OrganizationProfile.confidence <= 35).count()
        print(f"更新: {updated}, 覆盖率: {has_url}/{total} ({has_url / total * 100:.1f}%), guessed_urls={guessed_urls}")
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="域名猜测补充机构官网URL")
    parser.add_argument("--batch-size", type=int, default=50)
    args = parser.parse_args()
    batch_guess_urls(args.batch_size)
