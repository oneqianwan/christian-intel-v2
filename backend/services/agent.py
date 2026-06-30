"""
CIO Agent Module - 情报采集执行中心
负责：自动补采、定时巡检、状态监控
"""

import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Dict, List, Optional

try:
    from backend.services.api_collectors import NewsAPICollector
    from backend.services.rss_collector import collect_rss
    from backend.models.database import SessionLocal, engine, IntelligenceItem, RSSSource, JobRun
except ImportError:
    from services.api_collectors import NewsAPICollector
    from services.rss_collector import collect_rss
    from models.database import SessionLocal, engine, IntelligenceItem, RSSSource, JobRun


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


@dataclass
class AgentTask:
    """Agent任务记录（当前为内存态）。"""

    id: str
    task_type: str
    keywords: List[str]
    country: Optional[str]
    status: str
    source: str
    items_collected: int = 0
    created_at: str = ""
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    error_message: Optional[str] = None

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.utcnow().isoformat()


class CIOAgent:
    """CIO情报采集Agent。"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._initialized = True
        self.tasks: List[AgentTask] = []
        self.max_tasks = 100
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def submit_gap_collection(self, keywords: List[str], country: Optional[str] = None) -> str:
        """提交缺口补采任务。"""
        normalized_keywords = [(item or "").strip() for item in keywords if (item or "").strip()]
        if not normalized_keywords:
            normalized_keywords = ["global christian news"]

        for existing in self.tasks:
            if (
                existing.status in {"pending", "running"}
                and existing.task_type == "gap_collection"
                and existing.keywords == normalized_keywords
                and existing.country == country
            ):
                return existing.id

        task_id = f"gap-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{len(self.tasks)}"
        task = AgentTask(
            id=task_id,
            task_type="gap_collection",
            keywords=normalized_keywords,
            country=country,
            status="pending",
            source="api_collectors",
        )
        self.tasks.append(task)
        if len(self.tasks) > self.max_tasks:
            self.tasks = self.tasks[-self.max_tasks :]

        self._start_worker()
        return task_id

    def submit_scheduled_scan(self, source_type: str = "rss") -> str:
        """提交定时巡检任务。"""
        task_id = f"sched-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
        task = AgentTask(
            id=task_id,
            task_type="scheduled_scan",
            keywords=[source_type],
            country=None,
            status="pending",
            source=source_type,
        )
        self.tasks.append(task)
        if len(self.tasks) > self.max_tasks:
            self.tasks = self.tasks[-self.max_tasks :]

        self._start_worker()
        return task_id

    def get_task_status(self, task_id: str) -> Optional[Dict]:
        for task in self.tasks:
            if task.id == task_id:
                return asdict(task)
        return None

    def get_recent_tasks(self, limit: int = 10) -> List[Dict]:
        recent = sorted(self.tasks, key=lambda item: item.created_at, reverse=True)[:limit]
        return [asdict(item) for item in recent]

    def get_stats(self) -> Dict:
        total = len(self.tasks)
        pending = sum(1 for item in self.tasks if item.status == "pending")
        running = sum(1 for item in self.tasks if item.status == "running")
        completed = sum(1 for item in self.tasks if item.status == "completed")
        failed = sum(1 for item in self.tasks if item.status == "failed")
        return {
            "total_tasks": total,
            "pending": pending,
            "running": running,
            "completed": completed,
            "failed": failed,
            "is_worker_alive": self._thread is not None and self._thread.is_alive(),
        }

    def _start_worker(self):
        if self._thread is not None and self._thread.is_alive():
            return

        self._running = True
        self._thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._thread.start()

    def _worker_loop(self):
        while self._running:
            task = next((item for item in self.tasks if item.status == "pending"), None)
            if task is None:
                self._running = False
                break

            task.status = "running"
            task.started_at = datetime.utcnow().isoformat()

            try:
                collected = self._execute_task(task)
                task.items_collected = collected
                task.status = "completed"
            except Exception as exc:
                task.status = "failed"
                task.error_message = str(exc)

            task.finished_at = datetime.utcnow().isoformat()
            time.sleep(0.5)

    def _execute_task(self, task: AgentTask) -> int:
        total_collected = 0
        for keyword in task.keywords:
            try:
                if task.task_type == "gap_collection":
                    total_collected += self._collect_via_api(keyword, task.country)
                elif task.task_type == "scheduled_scan":
                    total_collected += self._collect_via_rss()
            except Exception as exc:
                print(f"[Agent] 关键词 '{keyword}' 采集失败: {exc}")
        return total_collected

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

    def _collect_via_api(self, keyword: str, country: Optional[str]) -> int:
        db = SessionLocal()
        try:
            collector = NewsAPICollector(db)
            if not collector.api_key:
                print(f"[Agent] NewsAPI key 未配置，跳过 '{keyword}'")
                return 0

            total = 0
            label = f"{country} {keyword}".strip() if country else keyword
            for query in self._expand_queries(keyword, country):
                added = collector._collect_keyword(query, label=label, limit_per_keyword=5)
                print(f"[Agent] API采集 '{query}': {added} 条")
                total += added
                if total > 0:
                    break
            return total
        except Exception as exc:
            print(f"[Agent] API采集异常: {exc}")
            return 0
        finally:
            db.close()

    def _collect_via_rss(self) -> int:
        try:
            result = collect_rss(limit_per_source=10)
            if isinstance(result, tuple) and result:
                total = int(result[0] or 0)
            else:
                total = int(result or 0)
            print(f"[Agent] RSS定时采集已触发: {total} 条")
            return total
        except Exception as exc:
            print(f"[Agent] RSS采集异常: {exc}")
            return 0


_agent_instance = None


def get_agent() -> CIOAgent:
    """获取Agent单例。"""
    global _agent_instance
    if _agent_instance is None:
        _agent_instance = CIOAgent()
    return _agent_instance


def submit_gap_collection(keywords: List[str], country: Optional[str] = None) -> str:
    """便捷入口：提交缺口补采。"""
    agent = get_agent()
    return agent.submit_gap_collection(keywords, country)
