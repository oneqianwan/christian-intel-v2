import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import redis
from rq import Queue, SimpleWorker, Connection
from rq.timeouts import TimerDeathPenalty

from models.database import init_db

# Redis连接
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
conn = redis.from_url(REDIS_URL)

# 任务队列
queue = Queue("collection", connection=conn)

# === Agent自动感知（每完成N个用户任务后触发一次）===
_agent_task_counter = 0
AGENT_TRIGGER_INTERVAL = 5


class WindowsSimpleWorker(SimpleWorker):
    death_penalty_class = TimerDeathPenalty

    def execute_job(self, job, queue):
        global _agent_task_counter

        result = super().execute_job(job, queue)
        _check_composite_completion(_get_mission_id(job))
        _check_pending_notifications(job)
        try:
            from services.api_collectors import run_all_api_collectors

            api_added = run_all_api_collectors()
            print(f"[Worker] API采集: +{api_added} 条global情报")
        except Exception as exc:
            print(f"[Worker] API采集跳过: {exc}")

        _agent_task_counter += 1
        if _agent_task_counter >= AGENT_TRIGGER_INTERVAL:
            _agent_task_counter = 0
            _try_run_agent_cycle()
        return result


def _try_run_agent_cycle():
    """尝试运行Agent循环（不阻塞主流程）"""
    try:
        import threading

        def run_async():
            try:
                from agent.loop import run_agent_cycle

                result = run_agent_cycle(force=False)
                print(f"[Worker] Agent结果: {result.get('tasks_created', 0)} 任务")
            except Exception as exc:
                print(f"[Worker] Agent异常: {exc}")

        thread = threading.Thread(target=run_async, daemon=True)
        thread.start()
    except Exception as exc:
        print(f"[Worker] Agent触发失败: {exc}")


def _get_mission_id(job):
    if getattr(job, "args", None):
        return job.args[0]
    return None


def _check_composite_completion(mission_id: str):
    """
    检查某 Mission 所属的 composite_task_id 是否全部完成。
    如果全部完成且有待通知任务，则发送通知。
    """
    if not mission_id:
        return

    try:
        from models.database import Mission, get_db

        db_gen = get_db()
        db = next(db_gen)
        try:
            mission = db.query(Mission).filter(Mission.id == mission_id).first()
            if not mission or not mission.composite_task_id:
                return

            composite_id = mission.composite_task_id
            total = db.query(Mission).filter(Mission.composite_task_id == composite_id).count()
            done = (
                db.query(Mission)
                .filter(
                    Mission.composite_task_id == composite_id,
                    Mission.status == "done",
                )
                .count()
            )

            if total > 0 and total == done:
                _send_pending_notifications(db, composite_id)
        finally:
            db_gen.close()
    except Exception as exc:
        print(f"[Worker] 复合任务检查失败: {exc}")


def _send_pending_notifications(db, composite_id: str):
    """发送关联 composite_task_id 的 pending 通知。"""
    try:
        from sqlalchemy import text

        from agent.actions import ActionExecutor
        from agent.memory import Memory
        from agent.planner import ActionPlan

        memory = Memory()
        pending = db.execute(
            text(
                """
                SELECT id, plan
                FROM agent_tasks
                WHERE task_type = 'query_gap_notification'
                  AND status = 'pending'
                  AND plan->>'composite_task_id' = :cid
                """
            ),
            {"cid": composite_id},
        ).fetchall()

        for task_id, plan_json in pending:
            plan_data = plan_json if isinstance(plan_json, dict) else (plan_json or {})
            notify_plan_data = plan_data.get("notify_plan", {})

            try:
                memory.update_task(task_id, "running")
                plan = ActionPlan(
                    action="notify_user",
                    target=notify_plan_data.get("country", "全球"),
                    priority=1,
                    params=notify_plan_data,
                    reason=f"复合任务 {composite_id[:8]} 完成，发送通知",
                )
                executor = ActionExecutor()
                result = executor.execute(plan)
                memory.update_task(
                    task_id,
                    "done" if result.get("status") == "success" else "failed",
                    result,
                )
                print(f"[Worker] 通知已发送: {notify_plan_data.get('original_query', '')[:50]}...")
            except Exception as exc:
                print(f"[Worker] 单条通知失败: {exc}")
                memory.update_task(task_id, "failed", {"error": str(exc)})
    except Exception as exc:
        print(f"[Worker] 发送通知失败: {exc}")


def _check_pending_notifications(job):
    """Mission完成后检查是否有对应的Agent通知任务。"""
    try:
        from sqlalchemy import text

        from agent.actions import ActionExecutor
        from agent.memory import Memory
        from agent.planner import ActionPlan
        from models.database import Mission

        mission_id = _get_mission_id(job)
        if not mission_id:
            return

        memory = Memory()
        db = memory.db
        mission = db.query(Mission).filter(Mission.id == mission_id).first()
        if not mission or mission.status != "done":
            return

        pending = db.execute(
            text(
                """
                SELECT id, plan
                FROM agent_tasks
                WHERE task_type = 'pending_notification'
                  AND target = :country
                  AND status = 'pending'
                ORDER BY created_at ASC
                """
            ),
            {"country": mission.country},
        ).fetchall()

        for task_id, plan_json in pending:
            plan_data = plan_json if isinstance(plan_json, dict) else (plan_json or {})
            notify_plan = plan_data.get("notify_plan", {})
            composite_id = notify_plan.get("composite_id") or plan_data.get("composite_task_id")

            if composite_id and composite_id != mission.composite_task_id:
                continue

            if composite_id:
                remaining = db.execute(
                    text(
                        """
                        SELECT COUNT(*)
                        FROM missions
                        WHERE composite_task_id = :composite_id
                          AND status != 'done'
                        """
                    ),
                    {"composite_id": composite_id},
                ).scalar()
                if (remaining or 0) > 0:
                    continue

            memory.update_task(task_id, "running")
            executor = ActionExecutor()
            result = executor.execute(
                ActionPlan(
                    action="notify_user",
                    target=mission.country,
                    priority=9,
                    params=notify_plan,
                    reason="Worker完成，发送通知",
                )
            )
            memory.update_task(task_id, "done" if result.get("status") == "success" else "failed", result)
    except Exception as exc:
        print(f"[Worker] 通知检查失败: {exc}")


def bootstrap_worker():
    """初始化数据库（如果表不存在）"""
    init_db()


def run_worker():
    """启动Worker进程，监听collection队列"""
    bootstrap_worker()
    with Connection(conn):
        # Windows 本地开发同时缺少 os.fork() 和 SIGALRM，需要两层兼容。
        w = WindowsSimpleWorker([queue])
        w.work()


# 具体采集任务（步骤3-5再实现）
def scan_rss_feed(source_id: str):
    """扫描单个RSS源"""
    pass


def extract_page(url: str, source_id: str):
    """抓取并解析单个页面"""
    pass


if __name__ == "__main__":
    run_worker()
