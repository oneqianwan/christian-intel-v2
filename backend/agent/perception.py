"""
Agent感知层：监测情报缺口和来源健康
"""

import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List

import httpx
from sqlalchemy import func, text

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models.database import IntelligenceItem, get_db


@dataclass
class PerceptionResult:
    type: str
    target: str
    severity: str
    detail: dict = field(default_factory=dict)
    suggested_action: str = ""


class Perception:
    GAP_THRESHOLDS = {
        "菲律宾": 500,
        "韩国": 100,
        "尼日利亚": 300,
        "美国": 100,
        "全球": 300,
    }
    STALE_DAYS = 7
    SURGE_KEYWORDS = {
        "宗教迫害": ["persecution", "迫害", "killed", "arrested", "church attack", "教堂袭击"],
        "宗教自由": ["religious freedom", "宗教自由", "blasphemy", "apostasy", "叛教"],
        "重大事件": ["earthquake", "tsunami", "war", "conflict", "humanitarian", "crisis", "灾难", "地震", "战争"],
        "政策变化": ["ban", "restrict", "law", "legislation", "regulation", "禁止", "法律", "政策"],
    }
    SURGE_THRESHOLD = 3

    API_CHECKS = {
        "newsapi": {
            "url": "https://newsapi.org/v2/top-headlines?country=us&pageSize=1&apiKey={key}",
            "timeout": 10,
        },
        "scrapingbee": {
            "url": "https://app.scrapingbee.com/api/v1?api_key={key}&url=https://worldea.org&render_js=false",
            "timeout": 15,
        },
        "youtube": {
            "url": "https://www.googleapis.com/youtube/v3/search?key={key}&part=snippet&q=test&maxResults=1",
            "timeout": 10,
        },
    }

    def __init__(self):
        self._db_gen = get_db()
        self.db = next(self._db_gen)
        self.findings: List[PerceptionResult] = []

    def __del__(self):
        try:
            self._db_gen.close()
        except Exception:
            pass

    def run_all(self) -> List[PerceptionResult]:
        self.findings = []
        self._check_intelligence_gaps()
        self._check_api_health()
        self._check_source_staleness()
        self._check_user_query_gaps()
        self._check_keyword_surge()
        return self.findings

    def _check_intelligence_gaps(self):
        print("[Perception] P1: 情报量缺口...")
        for scope, threshold in self.GAP_THRESHOLDS.items():
            if scope == "全球":
                count = (
                    self.db.query(func.count(IntelligenceItem.id))
                    .filter(IntelligenceItem.scope == "global")
                    .scalar()
                )
            else:
                count = (
                    self.db.query(func.count(IntelligenceItem.id))
                    .filter(
                        IntelligenceItem.country == scope,
                        IntelligenceItem.scope == "country",
                    )
                    .scalar()
                )

            count = count or 0
            if count < threshold:
                sev = "high" if count < threshold * 0.5 else "medium"
                self.findings.append(
                    PerceptionResult(
                        "gap",
                        scope,
                        sev,
                        {"current": count, "threshold": threshold, "gap": threshold - count},
                        "auto_collect",
                    )
                )
                print(f"  [WARN] {scope}: {count}/{threshold} ({sev})")
            else:
                print(f"  [OK] {scope}: {count}/{threshold}")

    def _check_api_health(self):
        print("[Perception] P2: API健康...")
        try:
            from services.api_config_service import get_api_key
        except Exception:
            get_api_key = None

        configs = self.db.execute(
            text(
                "SELECT api_name, encrypted_api_key, status FROM api_configs "
                "WHERE status IN ('active', 'configured', 'error')"
            )
        ).fetchall()

        for cfg in configs:
            name, encrypted_api_key, status = cfg
            if name not in self.API_CHECKS:
                continue

            check = self.API_CHECKS[name]
            try:
                key = ""
                if get_api_key:
                    try:
                        key = get_api_key(self.db, name) or ""
                    except Exception:
                        key = ""
                if not key and encrypted_api_key:
                    # key 已加密但当前环境无法解密，仍然视为待人工处理的异常。
                    raise RuntimeError("API key 已配置，但当前环境无法解密或读取")
                if not key:
                    raise RuntimeError("API key 未配置")

                url = check["url"].format(key=key)
                resp = httpx.get(
                    url,
                    timeout=check["timeout"],
                    follow_redirects=True,
                )
                ok = resp.status_code == 200 and len(resp.text) > 10

                if not ok and status != "error":
                    self.findings.append(
                        PerceptionResult(
                            "api_health",
                            name,
                            "high",
                            {"status_code": resp.status_code},
                            "mark_api_error",
                        )
                    )
                    print(f"  [ERR] {name}: HTTP {resp.status_code}")
                elif ok:
                    print(f"  [OK] {name}: OK")
                else:
                    print(f"  [WARN] {name}: 已处于 error 状态")
            except Exception as exc:
                if status != "error":
                    self.findings.append(
                        PerceptionResult(
                            "api_health",
                            name,
                            "high",
                            {"error": str(exc)},
                            "mark_api_error",
                        )
                    )
                print(f"  [ERR] {name}: {exc}")

    def _check_source_staleness(self):
        print("[Perception] P3: 来源陈旧度...")
        threshold = datetime.utcnow() - timedelta(days=self.STALE_DAYS)
        sources = self.db.execute(
            text(
                """
                SELECT source_name, MAX(ingested_at) AS last_update
                FROM intelligence_items
                WHERE scope = 'global' AND source_name IS NOT NULL AND source_name != ''
                GROUP BY source_name
                HAVING MAX(ingested_at) < :threshold
                """
            ),
            {"threshold": threshold},
        ).fetchall()

        for src in sources:
            name, last_update = src
            self.findings.append(
                PerceptionResult(
                    "source_stale",
                    name,
                    "medium",
                    {"last_update": last_update.isoformat() if last_update else None},
                    "auto_collect",
                )
            )
            print(f"  [WARN] {name}: 最后更新 {last_update}")

    def _check_user_query_gaps(self):
        """
        P4: 检查用户查询中未得到满意回答的。
        """
        print("[Perception] P4: 用户查询缺口...")
        recent = datetime.utcnow() - timedelta(hours=24)

        gaps = self.db.execute(
            text(
                """
                SELECT
                    um.conversation_id,
                    um.content AS user_query,
                    um.created_at AS query_time
                FROM messages um
                WHERE um.role = 'user'
                  AND um.created_at >= :recent
                  AND LENGTH(um.content) > 3
                  AND um.content NOT LIKE '%/%'
                  AND EXISTS (
                      SELECT 1
                      FROM messages am
                      WHERE am.conversation_id = um.conversation_id
                        AND am.role = 'assistant'
                        AND am.created_at >= um.created_at
                        AND am.delivery_type IN ('no_data', 'clarify', 'error')
                  )
                  AND NOT EXISTS (
                      SELECT 1
                      FROM messages am2
                      WHERE am2.conversation_id = um.conversation_id
                        AND am2.role = 'assistant'
                        AND am2.created_at >= um.created_at
                        AND am2.delivery_type IN (
                            'intelligence_brief',
                            'analysis_brief',
                            'contact_partial',
                            'contact_full',
                            'global_brief'
                        )
                  )
                ORDER BY query_time DESC
                LIMIT 20
                """
            ),
            {"recent": recent},
        ).fetchall()

        for conv_id, user_query, query_time in gaps:
            normalized_query = (user_query or "").strip()[:100]
            already_handled = self.db.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM agent_tasks
                    WHERE task_type = 'query_gap'
                      AND target = :query
                      AND created_at >= :recent
                    """
                ),
                {"query": normalized_query, "recent": recent},
            ).scalar()

            if (already_handled or 0) > 0:
                continue

            extractable = self._extract_collectable_entities(user_query or "")
            if not extractable:
                continue

            self.findings.append(
                PerceptionResult(
                    type="user_query_gap",
                    target=extractable.get("country") or extractable.get("entity") or "未知",
                    severity="high",
                    detail={
                        "user_query": user_query,
                        "conversation_id": conv_id,
                        "entity": extractable.get("entity"),
                        "country": extractable.get("country"),
                        "query_time": query_time.isoformat() if query_time else None,
                    },
                    suggested_action="auto_collect_and_notify",
                )
            )
            print(f"  [WARN] 查询缺口: {(user_query or '')[:50]}... -> {extractable}")

    def _extract_collectable_entities(self, query: str) -> dict | None:
        """从用户查询中提取可采集的国家名和机构名。"""
        result = {"country": None, "entity": None}
        query_lower = (query or "").lower()

        countries = {
            "菲律宾": "菲律宾",
            "philippines": "菲律宾",
            "韩国": "韩国",
            "korea": "韩国",
            "south korea": "韩国",
            "尼日利亚": "尼日利亚",
            "nigeria": "尼日利亚",
            "美国": "美国",
            "america": "美国",
            "usa": "美国",
        }
        for keyword, country in countries.items():
            if keyword in query_lower:
                result["country"] = country
                break

        org_keywords = [
            "PCEC",
            "Victory",
            "CBN",
            "CCF",
            "WEA",
            "WCC",
            "church",
            "教会",
            "协会",
            "联盟",
            "机构",
        ]
        for keyword in org_keywords:
            if keyword.lower() in query_lower:
                result["entity"] = keyword
                break

        return result if (result["country"] or result["entity"]) else None

    def _check_keyword_surge(self):
        """
        P5: 监测突发关键词。
        检查24小时内某类关键词相关情报是否异常增加。
        """
        print("[Perception] P5: 突发关键词监测...")
        recent = datetime.utcnow() - timedelta(hours=24)
        week_ago_start = datetime.utcnow() - timedelta(days=8)
        week_ago_end = datetime.utcnow() - timedelta(days=1)

        for category, keywords in self.SURGE_KEYWORDS.items():
            keyword_sql, keyword_params = self._build_keyword_match_sql(keywords)
            recent_count = self.db.execute(
                text(
                    f"""
                    SELECT COUNT(*)
                    FROM intelligence_items
                    WHERE ingested_at >= :recent
                      AND ({keyword_sql})
                    """
                ),
                {"recent": recent, **keyword_params},
            ).scalar()
            count = recent_count or 0

            if count < self.SURGE_THRESHOLD:
                print(f"  [OK] {category}: {count}条/24h (未达阈值)")
                continue

            week_count = self.db.execute(
                text(
                    f"""
                    SELECT COUNT(*)
                    FROM intelligence_items
                    WHERE ingested_at BETWEEN :start AND :end
                      AND ({keyword_sql})
                    """
                ),
                {"start": week_ago_start, "end": week_ago_end, **keyword_params},
            ).scalar()
            week_avg = round((week_count or 0) / 7, 1)
            surge_baseline = max(week_avg * 3, self.SURGE_THRESHOLD)

            if count < surge_baseline:
                print(f"  [OK] {category}: {count}条/24h (正常)")
                continue

            severity = "high" if count >= max(week_avg * 5, self.SURGE_THRESHOLD) else "medium"
            samples = self.db.execute(
                text(
                    f"""
                    SELECT title, source_url, source_name
                    FROM intelligence_items
                    WHERE ingested_at >= :recent
                      AND ({keyword_sql})
                    ORDER BY ingested_at DESC
                    LIMIT 3
                    """
                ),
                {"recent": recent, **keyword_params},
            ).fetchall()

            multiplier = round(count / max(week_avg, 1), 1)
            self.findings.append(
                PerceptionResult(
                    type="keyword_surge",
                    target=category,
                    severity=severity,
                    detail={
                        "24h_count": count,
                        "daily_avg_7d": week_avg,
                        "multiplier": multiplier,
                        "sample_titles": [sample[0] for sample in samples if sample[0]],
                        "keywords_matched": keywords[:3],
                    },
                    suggested_action="notify_user",
                )
            )
            print(f"  [WARN] {category}: {count}条/24h (日均{week_avg:.1f}, {severity})")

    def _build_keyword_match_sql(self, keywords: List[str]) -> tuple[str, dict]:
        clauses = []
        params = {}
        for index, keyword in enumerate(keywords):
            param_name = f"kw_{index}"
            clauses.append(
                f"(LOWER(COALESCE(title, '')) LIKE :{param_name} OR LOWER(COALESCE(content, '')) LIKE :{param_name})"
            )
            params[param_name] = f"%{keyword.lower()}%"
        return " OR ".join(clauses) or "1=0", params
