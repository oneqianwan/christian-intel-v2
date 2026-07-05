"""
Digital Score 计算服务
纯基于数据库已有字段，零 HTTP 请求
评估机构的数字化/在线化能力
"""

import json
from typing import Dict

from models.database import OrganizationProfile


class DigitalScorer:
    def score(self, org: OrganizationProfile) -> Dict:
        """
        计算 Digital Score，0-100，四个维度各 25 分
        """
        result = {
            "total_score": 0,
            "grade": "F",
            "dimensions": {
                "online_presence": 0,
                "content_media": 0,
                "financial_digital": 0,
                "technical_depth": 0,
            },
            "error": None,
        }

        op = 0
        if org.official_website and len(org.official_website) > 5:
            op += 8

        social_count = 0
        for field in ["facebook_url", "youtube_url", "twitter_url", "telegram_username"]:
            value = getattr(org, field, None)
            if value and len(str(value)) > 3:
                social_count += 1
        op += min(social_count * 3, 12)

        if org.social_accounts_json and len(str(org.social_accounts_json)) > 10:
            op += 3
        if org.has_mobile_app:
            op += 2
        result["dimensions"]["online_presence"] = min(op, 25)

        cm = 0
        content_flags = [
            ("has_blog", 6),
            ("has_podcast", 6),
            ("has_video", 6),
            ("has_sermons", 4),
            ("has_press", 3),
        ]
        for flag, points in content_flags:
            if getattr(org, flag, False):
                cm += points
        result["dimensions"]["content_media"] = min(cm, 25)

        fd = 0
        financial_flags = [
            ("has_online_giving", 10),
            ("has_donate", 8),
            ("has_annual_report", 4),
            ("has_financial_report", 3),
        ]
        for flag, points in financial_flags:
            if getattr(org, flag, False):
                fd += points
        result["dimensions"]["financial_digital"] = min(fd, 25)

        td = 0
        if org.has_ai_initiative:
            td += 10
        if org.ai_maturity_score and org.ai_maturity_score > 0:
            td += min(org.ai_maturity_score // 10, 10)

        if org.tech_stack_json and len(str(org.tech_stack_json)) > 5:
            td += 3
            try:
                stack = json.loads(org.tech_stack_json)
                if isinstance(stack, (list, dict)) and len(stack) > 0:
                    td += 2
            except (json.JSONDecodeError, TypeError):
                pass

        base_flags = [
            ("has_about", 2),
            ("has_mission", 2),
            ("has_contact", 2),
            ("has_resources", 2),
        ]
        for flag, points in base_flags:
            if getattr(org, flag, False):
                td += points
        result["dimensions"]["technical_depth"] = min(td, 25)

        result["total_score"] = sum(result["dimensions"].values())
        result["grade"] = self._to_grade(result["total_score"])
        return result

    def _to_grade(self, score: int) -> str:
        if score >= 80:
            return "A"
        if score >= 60:
            return "B"
        if score >= 40:
            return "C"
        if score >= 20:
            return "D"
        return "F"
