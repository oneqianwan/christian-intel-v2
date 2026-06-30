#!/usr/bin/env python3
"""
批量手动录入 People 信息

用法:
1. 准备一个 JSON 文件:
[
  {"org_name": "Christ's Commission Fellowship", "leader_name": "Peter Tan-Chi", "leader_title": "Senior Pastor"},
  {"org_name": "Victory Philippines", "leader_name": "Steve Murrell", "leader_title": "Founding Pastor"}
]

2. 运行:
python scripts/bulk_manual_people_entry.py people_entries.json
"""

import json
import os
import sys

import requests

API_BASE = os.getenv("API_BASE", "http://localhost:8000")


def _load_entries(json_file: str):
    with open(json_file, "r", encoding="utf-8-sig") as file_obj:
        return json.load(file_obj)


def bulk_entry_http(json_file: str):
    entries = _load_entries(json_file)

    success = 0
    failed = 0

    for entry in entries:
        try:
            response = requests.post(
                f"{API_BASE}/api/dashboard/quick-people-entry",
                json=entry,
                timeout=15,
            )
            payload = response.json()
            if response.ok and payload.get("success"):
                success += 1
                print(f"[OK] {entry['org_name']}: {entry['leader_name']}")
            else:
                failed += 1
                print(f"[ERR] {entry['org_name']}: {payload.get('error', 'Unknown error')}")
        except Exception as exc:
            failed += 1
            print(f"[ERR] {entry.get('org_name', 'unknown')}: {exc}")

    print(f"\nDone: {success} success, {failed} failed")


def bulk_entry_internal(json_file: str):
    from fastapi.testclient import TestClient

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from main import app

    entries = _load_entries(json_file)
    client = TestClient(app)
    success = 0
    failed = 0

    for entry in entries:
        try:
            response = client.post("/api/dashboard/quick-people-entry", json=entry)
            payload = response.json()
            if response.status_code == 200 and payload.get("success"):
                success += 1
                print(f"[OK] {entry['org_name']}: {entry['leader_name']}")
            else:
                failed += 1
                print(f"[ERR] {entry['org_name']}: {payload.get('error', payload)}")
        except Exception as exc:
            failed += 1
            print(f"[ERR] {entry.get('org_name', 'unknown')}: {exc}")

    print(f"\nDone: {success} success, {failed} failed")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/bulk_manual_people_entry.py <people_entries.json> [--internal]")
        sys.exit(1)

    use_internal = "--internal" in sys.argv[2:]
    if use_internal:
        bulk_entry_internal(sys.argv[1])
    else:
        bulk_entry_http(sys.argv[1])
