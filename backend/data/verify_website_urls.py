"""
推断URL可达性验证 — Phase 2 Day 3
用HTTP HEAD请求验证推断的官网URL是否真实存在
"""

import os
import sys
from typing import Tuple

import requests
from sqlalchemy import text

script_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.dirname(script_dir)
os.chdir(backend_dir)
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from models.database import SessionLocal


def check_url_reachable(url: str, timeout: int = 10) -> Tuple[bool, int, str]:
    """
    检查URL是否可达
    返回: (是否可达, HTTP状态码(或负值错误码), 重定向后的URL)
    """
    if not url or not isinstance(url, str) or not url.startswith("http"):
        return False, 0, url

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "*/*",
    }

    try:
        resp = requests.head(url, timeout=timeout, allow_redirects=True, headers=headers)
        if resp.status_code == 405:
            resp = requests.get(url, timeout=timeout, allow_redirects=True, stream=True, headers=headers)
            resp.close()

        final_url = resp.url
        status = resp.status_code

        if 200 <= status < 400:
            return True, status, final_url
        return False, status, final_url
    except requests.exceptions.Timeout:
        return False, -1, url
    except requests.exceptions.ConnectionError:
        return False, -2, url
    except Exception:
        return False, -3, url


def verify_inferred_urls(batch_size: int = 50):
    db = SessionLocal()
    try:
        print("=" * 60)
        print(f"推断URL可达性验证 (batch={batch_size})")
        print("=" * 60)

        rows = db.execute(
            text(
                """
                SELECT id, name, country, official_website
                FROM organization_profiles
                WHERE official_website IS NOT NULL
                  AND official_website != ''
                  AND last_website_crawl IS NULL
                  AND source_name = 'wiki_extracted'
                ORDER BY id
                LIMIT :limit
                """
            ),
            {"limit": batch_size},
        ).fetchall()

        print(f"\n待验证: {len(rows)} 条URL")

        reachable = 0
        unreachable = 0

        for org_id, name, country, url in rows:
            display_name = (name or "")[:40]
            display_country = country or "UNKNOWN"

            print(f"\n  检查: {display_name} ({display_country})")
            print(f"        URL: {url}")

            ok, status, final_url = check_url_reachable(url)

            if ok:
                if final_url and final_url != url:
                    db.execute(
                        text("UPDATE organization_profiles SET official_website = :url WHERE id = :id"),
                        {"url": final_url, "id": org_id},
                    )
                    print(f"        [OK] HTTP {status} -> 重定向至 {final_url}")
                else:
                    print(f"        [OK] HTTP {status}")
                reachable += 1
            else:
                status_str = str(status) if status > 0 else "连接失败"
                print(f"        [FAIL] HTTP {status_str}")
                db.execute(
                    text("UPDATE organization_profiles SET official_website = NULL WHERE id = :id"),
                    {"id": org_id},
                )
                unreachable += 1

        db.commit()

        print(f"\n{'=' * 60}")
        print(f"验证完成: 可达 {reachable} / 不可达 {unreachable} / 总计 {len(rows)}")
        print("不可达URL已清空")
        print(f"{'=' * 60}")

        return {"reachable": reachable, "unreachable": unreachable}
    finally:
        db.close()


if __name__ == "__main__":
    result = verify_inferred_urls(batch_size=50)
    print(f"\n结果: {result}")
