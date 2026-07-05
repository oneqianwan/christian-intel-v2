from __future__ import annotations

from typing import Any, Callable, Dict, List

from services.repair_models import RepairAction, RepairPlan
from services.trace_center import trace_span


class RepairExecutor:
    SUPPORTED_ACTIONS = {
        "RETRIEVE_MORE",
        "FIND_SOURCE",
        "VERIFY_FACT",
        "REASON_AGAIN",
        "RECHECK_CONFLICT",
        "REBUILD_CONTEXT",
    }

    PARALLEL_ACTIONS = {"RETRIEVE_MORE", "FIND_SOURCE", "VERIFY_FACT"}

    def __init__(self, action_handler: Callable[[RepairAction, Dict[str, Any]], Dict[str, Any]] | None = None):
        self.action_handler = action_handler

    def execute_plan(self, repair_plan: RepairPlan | Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
        with trace_span("RepairExecutor", input_obj=repair_plan) as span:
            plan = repair_plan if isinstance(repair_plan, RepairPlan) else RepairPlan.from_dict(repair_plan or {})
            actions = [item for item in (plan.actions or []) if str(item.action_type or "") in self.SUPPORTED_ACTIONS]
            parallel_actions = [item for item in actions if item.action_type in self.PARALLEL_ACTIONS]
            sequence_actions = [item for item in actions if item.action_type not in self.PARALLEL_ACTIONS]
            working_state = dict(state or {})
            action_results: List[Dict[str, Any]] = []

            if parallel_actions:
                parallel_result = self.execute_parallel(parallel_actions, working_state)
                working_state = dict(parallel_result.get("state") or working_state)
                action_results.extend(list(parallel_result.get("actions") or []))
            if sequence_actions:
                sequence_result = self.execute_sequence(sequence_actions, working_state)
                working_state = dict(sequence_result.get("state") or working_state)
                action_results.extend(list(sequence_result.get("actions") or []))

            execution = {
                "status": "completed",
                "supported_action_count": len(actions),
                "total_action_count": len(plan.actions or []),
                "actions": action_results,
                "progress": self.estimate_progress({"actions": action_results, "supported_action_count": len(actions)}),
                "state": working_state,
            }
            span.set_output_obj(execution)
            return execution

    def execute_action(self, action: RepairAction | Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
        item = action if isinstance(action, RepairAction) else RepairAction.from_dict(action or {})
        result: Dict[str, Any] = {
            "action_type": item.action_type,
            "target": item.target,
            "priority": int(item.priority or 0),
            "status": "skipped",
            "metadata": dict(item.metadata or {}),
        }
        if item.action_type not in self.SUPPORTED_ACTIONS or self.action_handler is None:
            return {"result": result, "state": dict(state or {})}
        try:
            next_state = self.action_handler(item, dict(state or {})) or dict(state or {})
            result["status"] = "completed"
            return {"result": result, "state": dict(next_state or {})}
        except Exception as exc:
            result["status"] = "failed"
            result["error"] = str(exc)
            return {"result": result, "state": dict(state or {})}

    def execute_sequence(self, actions: List[RepairAction], state: Dict[str, Any]) -> Dict[str, Any]:
        working_state = dict(state or {})
        action_results: List[Dict[str, Any]] = []
        for item in actions or []:
            executed = self.execute_action(item, working_state)
            working_state = dict(executed.get("state") or working_state)
            action_results.append(dict(executed.get("result") or {}))
        return {"mode": "sequence", "actions": action_results, "state": working_state}

    def execute_parallel(self, actions: List[RepairAction], state: Dict[str, Any]) -> Dict[str, Any]:
        # Parallel execution is simulated to preserve current runtime behavior and reuse existing nodes safely.
        working_state = dict(state or {})
        action_results: List[Dict[str, Any]] = []
        for item in actions or []:
            executed = self.execute_action(item, working_state)
            working_state = dict(executed.get("state") or working_state)
            payload = dict(executed.get("result") or {})
            payload["mode"] = "parallel_simulated"
            action_results.append(payload)
        return {"mode": "parallel_simulated", "actions": action_results, "state": working_state}

    def estimate_progress(self, execution: Dict[str, Any]) -> float:
        actions = [item for item in (execution.get("actions") or []) if isinstance(item, dict)]
        total = int(execution.get("supported_action_count") or len(actions or []))
        if total <= 0:
            return 100.0
        completed = len([item for item in actions if str(item.get("status") or "").strip().lower() == "completed"])
        return round((completed / total) * 100.0, 2)

    def export_execution(self, execution: Dict[str, Any]) -> Dict[str, Any]:
        payload = dict(execution or {})
        return {
            "status": str(payload.get("status") or "unknown"),
            "supported_action_count": int(payload.get("supported_action_count") or 0),
            "total_action_count": int(payload.get("total_action_count") or 0),
            "progress": float(payload.get("progress") or 0.0),
            "actions": [dict(item or {}) for item in (payload.get("actions") or []) if isinstance(item, dict)],
            "final_verification": self._to_dict(payload.get("final_verification")),
            "final_reflection": self._to_dict(payload.get("final_reflection")),
            "repair_completed": bool(payload.get("repair_completed")),
            "stopped": bool(payload.get("stopped", True)),
            "metadata": dict(payload.get("metadata") or {}),
        }

    def _to_dict(self, value: Any) -> Dict[str, Any]:
        if isinstance(value, dict):
            return dict(value)
        if hasattr(value, "to_dict"):
            try:
                return dict(value.to_dict())
            except Exception:
                return {}
        return {}
