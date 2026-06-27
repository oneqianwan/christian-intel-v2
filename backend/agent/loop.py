"""
Agent v1 - 感知Agent主循环
"""

import os
import sys
import traceback
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.actions import ActionExecutor
from agent.memory import Memory
from agent.perception import Perception
from agent.planner import Planner
from agent.safety import SafetyGuard


AGENT_COOLDOWN_MINUTES = 360
_LAST_RUN_FILE = os.path.join(os.path.dirname(__file__), ".agent_last_run")


class AgentLoop:
    def __init__(self):
        self.perception = Perception()
        self.planner = Planner()
        self.executor = ActionExecutor()
        self.memory = Memory()
        self.safety = SafetyGuard()
        self.cycle_count = 0

    def should_run(self) -> bool:
        if os.path.exists(_LAST_RUN_FILE):
            try:
                with open(_LAST_RUN_FILE, "r", encoding="utf-8") as f:
                    last_run = datetime.fromisoformat(f.read().strip())
                elapsed = datetime.utcnow() - last_run
                if elapsed < timedelta(minutes=AGENT_COOLDOWN_MINUTES):
                    remaining = timedelta(minutes=AGENT_COOLDOWN_MINUTES) - elapsed
                    print(f"[Agent] 冷却中，剩余 {remaining.seconds // 60} 分钟")
                    return False
            except Exception:
                pass
        return self.safety.pre_run_check()

    def run_cycle(self, force: bool = False) -> dict:
        if not force and not self.should_run():
            return {"status": "skipped", "reason": "cooldown_or_safety"}

        self.cycle_count += 1
        cycle_id = f"cycle-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"
        print(f"\n{'=' * 60}")
        print(f"[Agent] 循环 #{self.cycle_count} | {cycle_id}")
        print(f"{'=' * 60}")

        results = []

        try:
            print("[Agent] Step 1: 感知...")
            perceptions = self.perception.run_all()
            self.memory.log(
                "perception",
                f"感知完成: {len(perceptions)} 项",
                {
                    "items": [
                        {"type": p.type, "target": p.target, "severity": p.severity}
                        for p in perceptions
                    ]
                },
            )

            if not perceptions:
                print("[Agent] 无异常，结束")
                self._mark_run()
                return {"status": "success", "tasks_created": 0, "details": ["无异常"]}

            print(f"[Agent] Step 2: 规划 ({len(perceptions)} 项)...")
            plans = self.planner.create_plans(perceptions)

            print("[Agent] Step 3: 安全检查...")
            safe_plans = self.safety.filter_plans(plans)

            print(f"[Agent] Step 4: 执行 ({len(safe_plans)} 个)...")
            total = 0
            for plan in safe_plans:
                try:
                    result = self.executor.execute(plan)
                    total += result.get("created", 0)
                    results.append(
                        {"action": plan.action, "target": plan.target, "result": result}
                    )
                    self.memory.log("action", f"{plan.action} on {plan.target}", result)
                except Exception as exc:
                    self.memory.log("action", f"失败: {plan.action}", {"error": str(exc)})

            self._mark_run()
            self.memory.log(
                "loop",
                f"完成，创建 {total} 任务",
                {"cycle_id": cycle_id, "tasks": total},
            )
            print(f"[Agent] 完成 | 创建 {total} 任务")
            return {"status": "success", "tasks_created": total, "details": results}

        except Exception as exc:
            self.memory.log("loop", f"异常: {exc}", {"trace": traceback.format_exc()})
            return {"status": "error", "reason": str(exc)}

    def _mark_run(self):
        try:
            with open(_LAST_RUN_FILE, "w", encoding="utf-8") as f:
                f.write(datetime.utcnow().isoformat())
        except Exception:
            pass


def run_agent_cycle(force: bool = False) -> dict:
    agent = AgentLoop()
    return agent.run_cycle(force=force)
