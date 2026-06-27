import json
import os
from datetime import datetime
from typing import Any, Dict, List


PREFERENCES_FILE = r"C:\Users\baiwan\christian-intel-v2\backend\data\user_preferences.json"


def ensure_data_dir():
    os.makedirs(os.path.dirname(PREFERENCES_FILE), exist_ok=True)


def load_preferences() -> Dict[str, Any]:
    ensure_data_dir()
    if not os.path.exists(PREFERENCES_FILE):
        return {"countries": {}, "organizations": {}, "last_updated": None}

    with open(PREFERENCES_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_preferences(prefs: Dict[str, Any]):
    ensure_data_dir()
    prefs["last_updated"] = datetime.utcnow().isoformat()
    with open(PREFERENCES_FILE, "w", encoding="utf-8") as f:
        json.dump(prefs, f, ensure_ascii=False, indent=2)


def record_query(countries: List[str], organizations: List[str]):
    """记录一次查询偏好"""
    prefs = load_preferences()

    for country in countries:
        prefs["countries"][country] = prefs["countries"].get(country, 0) + 1

    for organization in organizations:
        prefs["organizations"][organization] = prefs["organizations"].get(organization, 0) + 1

    save_preferences(prefs)


def get_top_preferences(limit: int = 3) -> Dict[str, List[str]]:
    """获取用户最常查询的国家和机构"""
    prefs = load_preferences()

    top_countries = sorted(prefs["countries"].items(), key=lambda item: item[1], reverse=True)[:limit]
    top_organizations = sorted(prefs["organizations"].items(), key=lambda item: item[1], reverse=True)[:limit]

    return {
        "countries": [country[0] for country in top_countries],
        "organizations": [organization[0] for organization in top_organizations],
    }


def format_recommendation_prompt() -> str:
    """生成推荐 prompt 片段"""
    top = get_top_preferences()
    if not top["countries"] and not top["organizations"]:
        return ""

    parts = []
    if top["organizations"]:
        parts.append(f"用户经常查询的机构：{', '.join(top['organizations'])}")
    if top["countries"]:
        parts.append(f"用户经常关注的国家：{', '.join(top['countries'])}")

    return "\n".join(parts)
