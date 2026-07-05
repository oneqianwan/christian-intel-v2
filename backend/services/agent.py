"""
CIO Agent Module - Mission 提交中心
负责：缺口补采提交、定时巡检提交、提交记录查询
"""

import json
from typing import Dict, List, Optional

try:
    from backend.services.mission_service import create_collection_mission
except ImportError:
    from services.mission_service import create_collection_mission

try:
    from backend.models.database import Mission, SessionLocal
except ImportError:
    from models.database import Mission, SessionLocal


COUNTRY_ENGLISH_NAMES = {
    "菲律宾": "Philippines",
    "新加坡": "Singapore",
    "韩国": "South Korea",
    "肯尼亚": "Kenya",
    "尼日利亚": "Nigeria",
    "印度": "India",
    "中国": "China",
    "印尼": "Indonesia",
    "马来西亚": "Malaysia",
    "美国": "United States",
    "全球": "Global",
}

MISSION_PAYLOAD_PREFIX = "__mission_payload__:"


class CIOAgent:
    """CIO Mission 提交 Agent。"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._initialized = True

    def _get_agent_mission_query(self, db):
        return (
            db.query(Mission)
            .filter(Mission.query.contains('"entry":"agent.'))
        )

    def _parse_mission_payload(self, mission: Mission) -> dict:
        query = mission.query or ""
        if not query.startswith(MISSION_PAYLOAD_PREFIX):
            return {}
        try:
            return json.loads(query[len(MISSION_PAYLOAD_PREFIX):])
        except Exception:
            return {}

    def _map_mission_status(self, mission_status: Optional[str]) -> str:
        return {
            "queued": "pending",
            "running": "running",
            "done": "completed",
            "failed": "failed",
            "cancelled": "failed",
        }.get((mission_status or "").strip().lower(), "pending")

    def _mission_to_task_dict(self, mission: Mission) -> Dict:
        payload = self._parse_mission_payload(mission)
        metadata = payload.get("metadata") or {}
        status = self._map_mission_status(mission.status)
        created_at = mission.created_at.isoformat() if mission.created_at else ""
        updated_at = mission.updated_at.isoformat() if mission.updated_at else created_at
        started_at = updated_at if status != "pending" else None
        finished_at = updated_at if status in {"completed", "failed"} else None
        return {
            "id": mission.id,
            "task_type": metadata.get("task_type") or "mission",
            "keywords": list(payload.get("keywords") or []),
            "country": mission.country,
            "status": status,
            "source": payload.get("source") or "mission",
            "items_collected": 0,
            "created_at": created_at,
            "started_at": started_at,
            "finished_at": finished_at,
            "error_message": None,
        }

    def submit_gap_collection(self, keywords: List[str], country: Optional[str] = None) -> Optional[Mission]:
        """提交缺口补采任务，统一委托给 Mission。"""
        normalized_keywords = [(item or "").strip() for item in keywords if (item or "").strip()]
        if not normalized_keywords:
            normalized_keywords = ["global christian news"]
        expanded_keywords: List[str] = []
        seen = set()
        for keyword in normalized_keywords:
            for query in self._expand_queries(keyword, country):
                normalized = query.strip().lower()
                if not normalized or normalized in seen:
                    continue
                seen.add(normalized)
                expanded_keywords.append(query)

        mission = create_collection_mission(
            query=f"Agent Gap Collection | {', '.join(normalized_keywords)}",
            country=country or "全球",
            source="newsapi",
            keywords=expanded_keywords or normalized_keywords,
            limit_per_keyword=5,
            metadata={
                "entry": "agent.submit_gap_collection",
                "task_type": "gap_collection",
            },
        )
        if not mission:
            print(f"[Agent] Mission未创建，跳过提交记录: keywords={normalized_keywords}, country={country}")
            return None
        return mission

    def submit_scheduled_scan(self, source_type: str = "rss") -> Optional[Mission]:
        """提交定时巡检任务，统一委托给 Mission。"""
        source_value = (source_type or "rss").strip().lower()
        mission = create_collection_mission(
            query=f"Agent Scheduled Scan | {source_value}",
            country="全球",
            source=source_value,
            keywords=[source_value],
            limit_per_keyword=10,
            metadata={
                "entry": "agent.submit_scheduled_scan",
                "task_type": "scheduled_scan",
            },
        )
        if not mission:
            print(f"[Agent] Mission未创建，跳过定时巡检记录: source={source_value}")
            return None
        return mission

    def get_task_status(self, task_id: str) -> Optional[Dict]:
        db = SessionLocal()
        try:
            mission = (
                self._get_agent_mission_query(db)
                .filter(Mission.id == task_id)
                .first()
            )
            if not mission:
                return None
            return self._mission_to_task_dict(mission)
        finally:
            db.close()

    def get_recent_tasks(self, limit: int = 10) -> List[Dict]:
        db = SessionLocal()
        try:
            missions = (
                self._get_agent_mission_query(db)
                .order_by(Mission.created_at.desc())
                .limit(max(1, limit))
                .all()
            )
            return [self._mission_to_task_dict(mission) for mission in missions]
        finally:
            db.close()

    def get_stats(self) -> Dict:
        db = SessionLocal()
        try:
            missions = self._get_agent_mission_query(db).all()
            total = len(missions)
            pending = 0
            running = 0
            completed = 0
            failed = 0
            for mission in missions:
                status = self._map_mission_status(mission.status)
                if status == "pending":
                    pending += 1
                elif status == "running":
                    running += 1
                elif status == "completed":
                    completed += 1
                elif status == "failed":
                    failed += 1
            return {
                "total_tasks": total,
                "pending": pending,
                "running": running,
                "completed": completed,
                "failed": failed,
                "is_worker_alive": False,
            }
        finally:
            db.close()

    def _expand_queries(self, keyword: str, country: Optional[str]) -> List[str]:
        country_en = COUNTRY_ENGLISH_NAMES.get(country or "", "")
        lowered = (keyword or "").lower()
        candidates = [keyword]

        if country and country_en:
            candidates.append(country_en)
            if "faithtech" in lowered:
                candidates.extend(
                    [
                        f"{country_en} FaithTech",
                        f"{country_en} Christian technology",
                        f"{country_en} Christian startup",
                        f"{country_en} church technology",
                    ]
                )
            elif any(token in lowered for token in ["教会网络", "church network"]):
                candidates.extend(
                    [
                        f"{country_en} church network",
                        f"{country_en} Christian network",
                        f"{country_en} church",
                    ]
                )
            elif any(token in lowered for token in ["宣教", "mission"]):
                candidates.extend(
                    [
                        f"{country_en} mission",
                        f"{country_en} missionary",
                        f"{country_en} Christianity",
                    ]
                )

        deduped = []
        seen = set()
        for item in candidates:
            value = (item or "").strip()
            if not value:
                continue
            normalized = value.lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            deduped.append(value)
        return deduped

_agent_instance = None


def get_agent() -> CIOAgent:
    """获取Agent单例。"""
    global _agent_instance
    if _agent_instance is None:
        _agent_instance = CIOAgent()
    return _agent_instance


def submit_gap_collection(keywords: List[str], country: Optional[str] = None) -> Optional[Mission]:
    """便捷入口：提交缺口补采。"""
    agent = get_agent()
    return agent.submit_gap_collection(keywords, country)
