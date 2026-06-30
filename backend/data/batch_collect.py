"""
一键批量采集脚本 — Day 7
依次启动预设关键词的采集任务
"""

import argparse
import os
import sys
import time

import httpx

script_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.dirname(script_dir)
os.chdir(backend_dir)
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

try:
    from backend.data.preset_keywords import PRESET_KEYWORDS
except ImportError:
    from data.preset_keywords import PRESET_KEYWORDS

API_BASE = "http://localhost:8000"


def start_collection(keywords, country, source="newsapi"):
    """启动单个采集任务"""
    try:
        with httpx.Client(timeout=10) as client:
            res = client.post(
                f"{API_BASE}/api/collection/start",
                json={
                    "keywords": keywords,
                    "country": country,
                    "source": source,
                    "limit_per_keyword": 20,
                },
            )
            data = res.json()
            return data.get("task_id"), data.get("message", "")
    except Exception as exc:
        return None, str(exc)


def run_batch_collection(source="newsapi", delay=5, limit=None):
    """
    依次启动预设关键词的采集
    delay: 每个任务间隔秒数（防API限制）
    limit: 仅启动前N组，便于测试
    """
    presets = PRESET_KEYWORDS[:limit] if limit else PRESET_KEYWORDS

    print("=" * 60)
    print(f"批量采集启动 — 源: {source}")
    print(f"共 {len(presets)} 组关键词")
    print("=" * 60)

    results = []

    for i, preset in enumerate(presets, 1):
        print(f"\n[{i}/{len(presets)}] {preset['label']}")
        print(f"  关键词: {preset['keywords']}")
        print(f"  国家: {preset.get('country') or '全球'}")

        task_id, message = start_collection(
            keywords=preset["keywords"],
            country=preset.get("country"),
            source=source,
        )

        if task_id:
            print(f"  [OK] 已启动: {task_id}")
            results.append(
                {
                    "label": preset["label"],
                    "task_id": task_id,
                    "status": "started",
                }
            )
        else:
            print(f"  [ERR] 失败: {message}")
            results.append(
                {
                    "label": preset["label"],
                    "task_id": None,
                    "status": "failed",
                    "error": message,
                }
            )

        if i < len(presets):
            print(f"  [WAIT] 等待 {delay}s...")
            time.sleep(delay)

    success = sum(1 for row in results if row["status"] == "started")
    print(f"\n{'=' * 60}")
    print(f"批量采集完成: {success}/{len(presets)} 成功")
    print(f"{'=' * 60}")
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="批量采集基督教机构信息")
    parser.add_argument("--source", default="newsapi", choices=["newsapi", "rss", "webpage"])
    parser.add_argument("--delay", type=int, default=5, help="任务间隔秒数")
    parser.add_argument("--api-base", default="http://localhost:8000", help="API基础URL")
    parser.add_argument("--limit", type=int, default=0, help="仅启动前N组，0表示全部")

    args = parser.parse_args()
    API_BASE = args.api_base

    run_batch_collection(
        source=args.source,
        delay=args.delay,
        limit=args.limit or None,
    )
