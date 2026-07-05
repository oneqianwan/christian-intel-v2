from __future__ import annotations

from typing import Any, Dict, List

from services.repair_models import RepairAction, RepairPlan
from services.runtime_metrics import get_runtime_metrics
from services.trace_center import trace_span


class RepairPlanner:
    def __init__(self, trace_center: Any = None, runtime_metrics: Any = None):
        self.trace_center = trace_center
        self.runtime_metrics = runtime_metrics or get_runtime_metrics()

    def build_plan(
        self,
        reflection_result: Any,
        verification_result: Dict[str, Any],
        reasoning_context: Any,
        answer_context: Any,
    ) -> RepairPlan:
        with trace_span("RepairPlanner", input_obj=verification_result) as span:
            self._trace("Repair Planning Started", metadata={})
            reflection_payload = self._to_dict(reflection_result)
            verification_payload = dict(verification_result or {})
            reasoning_payload = self._to_dict(reasoning_context)
            answer_payload = self._to_dict(answer_context)

            actions: List[RepairAction] = []
            actions.extend(self.analyse_reflection(reflection_payload))
            actions.extend(self.analyse_verification(verification_payload))
            actions.extend(self.analyse_reasoning(reasoning_payload, answer_payload))
            ranked_actions = self.rank_actions(actions)
            estimated = self.estimate_cost(ranked_actions)
            repair_score = self._repair_score(reflection_payload, ranked_actions)
            plan = RepairPlan(
                actions=ranked_actions,
                overall_priority=max([int(item.priority or 0) for item in ranked_actions] or [0]),
                estimated_cost=float(estimated.get("estimated_cost") or 0.0),
                estimated_latency=float(estimated.get("estimated_latency") or 0.0),
                repair_score=float(repair_score),
                metadata={
                    "reflection_issue_count": len(reflection_payload.get("issues") or []),
                    "verification_missing_fields": list(verification_payload.get("missing_fields") or []),
                    "reasoning_node_count": len(((reasoning_payload.get("reasoning_graph") or {}).get("nodes") or [])),
                },
            )
            self._record_metrics(plan)
            self._trace(
                "Repair Planning Finished",
                metadata={
                    "action_count": len(plan.actions or []),
                    "repair_score": float(plan.repair_score or 0.0),
                    "overall_priority": int(plan.overall_priority or 0),
                },
            )
            span.set_output_obj(plan)
            return plan

    def analyse_reflection(self, reflection_result: Dict[str, Any]) -> List[RepairAction]:
        actions: List[RepairAction] = []
        for item in (reflection_result.get("issues") or []):
            if not isinstance(item, dict):
                continue
            issue_type = str(item.get("issue_type") or "").strip().lower()
            if issue_type == "coverage_insufficient":
                actions.append(self._action("RETRIEVE_MORE", 90, "coverage", str(item.get("description") or ""), 0.85, item))
            elif issue_type == "citation_missing":
                actions.append(self._action("FIND_SOURCE", 80, "citation", str(item.get("description") or ""), 0.82, item))
            elif issue_type == "unsupported_fact":
                actions.append(self._action("VERIFY_FACT", 85, "fact", str(item.get("description") or ""), 0.88, item))
            elif issue_type in {"isolated_fact", "reasoning_dependency_missing", "reasoning_conclusion_missing"}:
                actions.append(self._action("REASON_AGAIN", 70, "reasoning", str(item.get("description") or ""), 0.74, item))
            elif issue_type == "unresolved_conflict":
                actions.append(self._action("RECHECK_CONFLICT", 92, "conflict", str(item.get("description") or ""), 0.91, item))
            elif issue_type == "fact_evidence_mismatch":
                actions.append(self._action("REBUILD_CONTEXT", 65, "context", str(item.get("description") or ""), 0.69, item))
        return actions

    def analyse_verification(self, verification_result: Dict[str, Any]) -> List[RepairAction]:
        actions: List[RepairAction] = []
        missing_fields = [str(item) for item in (verification_result.get("missing_fields") or []) if str(item or "").strip()]
        if missing_fields:
            actions.append(
                self._action(
                    "RETRIEVE_MORE",
                    88,
                    "verification",
                    f"missing_fields={','.join(missing_fields)}",
                    0.84,
                    {"missing_fields": missing_fields},
                )
            )
        if list(verification_result.get("missing_sources") or []):
            actions.append(
                self._action(
                    "FIND_SOURCE",
                    78,
                    "verification",
                    "verification missing sources",
                    0.8,
                    {"missing_sources": list(verification_result.get("missing_sources") or [])},
                )
            )
        if bool(verification_result.get("blocking_conflict")):
            actions.append(
                self._action(
                    "RECHECK_CONFLICT",
                    93,
                    "verification",
                    "blocking conflict detected",
                    0.9,
                    {"blocking_conflict": True},
                )
            )
        evidence_verification = dict(verification_result.get("evidence_verification") or {})
        if list(evidence_verification.get("unsupported_facts") or []):
            actions.append(
                self._action(
                    "VERIFY_FACT",
                    84,
                    "verification",
                    "unsupported facts detected during verification",
                    0.86,
                    {"unsupported_facts": list(evidence_verification.get("unsupported_facts") or [])},
                )
            )
        return actions

    def analyse_reasoning(self, reasoning_context: Dict[str, Any], answer_context: Dict[str, Any]) -> List[RepairAction]:
        actions: List[RepairAction] = []
        graph = dict(reasoning_context.get("reasoning_graph") or {})
        nodes = [item for item in (graph.get("nodes") or []) if isinstance(item, dict)]
        edges = [item for item in (graph.get("edges") or []) if isinstance(item, dict)]
        edge_touches = {str(item.get("source") or "") for item in edges} | {str(item.get("target") or "") for item in edges}
        isolated = [
            item
            for item in nodes
            if str(item.get("node_type") or "").strip().lower() == "fact" and str(item.get("node_id") or "") not in edge_touches
        ]
        if isolated:
            actions.append(
                self._action(
                    "REASON_AGAIN",
                    72,
                    "reasoning",
                    "isolated reasoning fact nodes detected",
                    0.73,
                    {"isolated_fact_count": len(isolated)},
                )
            )
        if answer_context and not list(answer_context.get("sections") or []):
            actions.append(
                self._action(
                    "REBUILD_CONTEXT",
                    68,
                    "answer_context",
                    "answer context sections missing",
                    0.7,
                    {"section_count": 0},
                )
            )
        if nodes and not [item for item in nodes if str(item.get("node_type") or "").strip().lower() == "conclusion"]:
            actions.append(
                self._action(
                    "REASON_AGAIN",
                    66,
                    "reasoning",
                    "no conclusion node in reasoning graph",
                    0.67,
                    {"conclusion_count": 0},
                )
            )
        return actions

    def rank_actions(self, actions: List[RepairAction]) -> List[RepairAction]:
        deduped: Dict[tuple[str, str], RepairAction] = {}
        for action in actions or []:
            key = (str(action.action_type or ""), str(action.target or ""))
            current = deduped.get(key)
            if current is None or int(action.priority or 0) > int(current.priority or 0):
                deduped[key] = action
        ranked = sorted(
            deduped.values(),
            key=lambda item: (int(item.priority or 0), float(item.confidence or 0.0), str(item.action_type or "")),
            reverse=True,
        )
        for item in ranked:
            self._trace(
                "Repair Action Ranked",
                metadata={"action_type": item.action_type, "priority": int(item.priority or 0), "target": item.target},
            )
        return ranked

    def estimate_cost(self, actions: List[RepairAction]) -> Dict[str, float]:
        cost_map = {
            "RETRIEVE_MORE": (5.0, 250.0),
            "FIND_SOURCE": (3.0, 180.0),
            "VERIFY_FACT": (2.5, 140.0),
            "REASON_AGAIN": (1.5, 90.0),
            "REBUILD_CONTEXT": (1.2, 70.0),
            "RECHECK_CONFLICT": (2.0, 120.0),
        }
        estimated_cost = 0.0
        estimated_latency = 0.0
        for item in actions or []:
            base_cost, base_latency = cost_map.get(str(item.action_type or ""), (1.0, 60.0))
            estimated_cost += base_cost
            estimated_latency += base_latency
        return {
            "estimated_cost": round(estimated_cost, 2),
            "estimated_latency": round(estimated_latency, 2),
        }

    def export_plan(self, plan: RepairPlan | Dict[str, Any]) -> Dict[str, Any]:
        if isinstance(plan, RepairPlan):
            return plan.to_dict()
        return RepairPlan.from_dict(plan or {}).to_dict()

    def _action(
        self,
        action_type: str,
        priority: int,
        target: str,
        reason: str,
        confidence: float,
        metadata: Dict[str, Any] | None = None,
    ) -> RepairAction:
        action = RepairAction(
            action_type=action_type,
            priority=priority,
            target=target,
            reason=reason,
            confidence=confidence,
            metadata=dict(metadata or {}),
        )
        self._trace(
            "Repair Action Generated",
            metadata={"action_type": action.action_type, "priority": int(action.priority or 0), "target": action.target},
        )
        return action

    def _repair_score(self, reflection_result: Dict[str, Any], actions: List[RepairAction]) -> float:
        base = float(reflection_result.get("overall_score") or 0.0)
        penalty = len(actions or []) * 7.5
        return round(max(0.0, 100.0 - penalty + (base * 0.15)), 2)

    def _record_metrics(self, plan: RepairPlan) -> None:
        self.runtime_metrics.inc("repair_plan_count", value=1.0)
        self.runtime_metrics.set("repair_action_count", float(len(plan.actions or [])))
        self.runtime_metrics.set("repair_score", float(plan.repair_score or 0.0))
        self.runtime_metrics.set("repair_estimated_cost", float(plan.estimated_cost or 0.0))
        self.runtime_metrics.set("repair_estimated_latency", float(plan.estimated_latency or 0.0))

    def _to_dict(self, value: Any) -> Dict[str, Any]:
        if isinstance(value, dict):
            return dict(value)
        if hasattr(value, "to_dict"):
            try:
                return dict(value.to_dict())
            except Exception:
                return {}
        return {}

    def _trace(self, name: str, metadata: Dict[str, Any] | None = None) -> None:
        if self.trace_center is None:
            return
        self.trace_center.record_event("REPAIR", name, metadata=metadata or {})
