from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List

from services.feature_flags import feature_flag_enabled
from services.runtime_metrics import get_runtime_metrics


def _feature_enabled(name: str, default: bool = True) -> bool:
    return feature_flag_enabled(name, default=default)


@dataclass(frozen=True)
class PolicyRule:
    name: str
    description: str
    priority: int
    enabled: bool
    condition: str
    action: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "priority": int(self.priority or 0),
            "enabled": bool(self.enabled),
            "condition": str(self.condition or ""),
            "action": str(self.action or ""),
            "metadata": dict(self.metadata or {}),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PolicyRule":
        payload = data or {}
        return cls(
            name=str(payload.get("name") or ""),
            description=str(payload.get("description") or ""),
            priority=int(payload.get("priority") or 0),
            enabled=bool(payload.get("enabled", True)),
            condition=str(payload.get("condition") or ""),
            action=str(payload.get("action") or ""),
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass(frozen=True)
class PolicyDecision:
    decision: Any
    reason: str
    confidence: float
    matched_rule: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision": self._serialize(self.decision),
            "reason": self.reason,
            "confidence": float(self.confidence or 0.0),
            "matched_rule": self.matched_rule,
            "metadata": dict(self.metadata or {}),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PolicyDecision":
        payload = data or {}
        return cls(
            decision=payload.get("decision"),
            reason=str(payload.get("reason") or ""),
            confidence=float(payload.get("confidence") or 0.0),
            matched_rule=str(payload.get("matched_rule") or ""),
            metadata=dict(payload.get("metadata") or {}),
        )

    @staticmethod
    def _serialize(value: Any) -> Any:
        if hasattr(value, "to_dict"):
            try:
                return value.to_dict()
            except Exception:
                return value
        return value


@dataclass(frozen=True)
class ExecutionPolicyContext:
    question: str = ""
    question_type: str = "UNKNOWN"
    requirement: Any = None
    capabilities: List[Any] = field(default_factory=list)
    pipeline: Any = None
    memory: Any = None
    knowledge: Any = None
    verification: Any = None
    trace: Any = None
    loop_count: int = 0
    coverage: float = 0.0
    tool_results: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "question": self.question,
            "question_type": self.question_type,
            "requirement": self._serialize(self.requirement),
            "capabilities": [self._serialize(item) for item in (self.capabilities or [])],
            "pipeline": self._serialize(self.pipeline),
            "memory": self._serialize(self.memory),
            "knowledge": self._serialize(self.knowledge),
            "verification": self._serialize(self.verification),
            "trace": self._serialize(self.trace),
            "loop_count": int(self.loop_count or 0),
            "coverage": float(self.coverage or 0.0),
            "tool_results": [dict(item) for item in (self.tool_results or []) if isinstance(item, dict)],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExecutionPolicyContext":
        payload = data or {}
        return cls(
            question=str(payload.get("question") or ""),
            question_type=str(payload.get("question_type") or "UNKNOWN"),
            requirement=payload.get("requirement"),
            capabilities=list(payload.get("capabilities") or []),
            pipeline=payload.get("pipeline"),
            memory=payload.get("memory"),
            knowledge=payload.get("knowledge"),
            verification=payload.get("verification"),
            trace=payload.get("trace"),
            loop_count=int(payload.get("loop_count") or 0),
            coverage=float(payload.get("coverage") or 0.0),
            tool_results=[dict(item) for item in (payload.get("tool_results") or []) if isinstance(item, dict)],
        )

    @staticmethod
    def _serialize(value: Any) -> Any:
        if hasattr(value, "to_dict"):
            try:
                return value.to_dict()
            except Exception:
                return value
        return value


class ExecutionPolicyEngine:
    def __init__(
        self,
        rules: List[PolicyRule] | None = None,
        *,
        trace_center: Any = None,
        enabled: bool | None = None,
    ):
        self.trace_center = trace_center
        self.runtime_metrics = get_runtime_metrics()
        self.enabled = _feature_enabled("EXECUTION_POLICY_ENABLED", default=True) if enabled is None else bool(enabled)
        if rules is None:
            from services.default_execution_policies import get_default_execution_policies

            rules = get_default_execution_policies()
        self.rules = sorted(
            [item if isinstance(item, PolicyRule) else PolicyRule.from_dict(item) for item in (rules or [])],
            key=lambda item: int(item.priority or 0),
            reverse=True,
        )

    def evaluate(
        self,
        policy_type: str,
        context: ExecutionPolicyContext | Dict[str, Any],
        *,
        default_decision: Any = None,
        resolver: Callable[[PolicyRule, ExecutionPolicyContext, Any], PolicyDecision] | None = None,
    ) -> PolicyDecision:
        ctx = self._ensure_context(context)
        default = PolicyDecision(
            decision=default_decision,
            reason="execution_policy_disabled" if not self.enabled else "no_policy_matched",
            confidence=1.0 if not self.enabled else 0.5,
            matched_rule="",
            metadata={"policy_type": policy_type, "default_applied": True},
        )
        if not self.enabled:
            return default

        scoped_rules = [
            rule
            for rule in (self.rules or [])
            if rule.enabled and str((rule.metadata or {}).get("policy_type") or "").strip().lower() == str(policy_type or "").strip().lower()
        ]
        self._trace(
            "Policy Evaluated",
            metadata={
                "policy_type": policy_type,
                "rule_count": len(scoped_rules),
                "question_type": ctx.question_type,
                "loop_count": int(ctx.loop_count or 0),
            },
        )
        for rule in scoped_rules:
            if self._rule_matches(rule, ctx):
                self.runtime_metrics.inc("policy_hit", labels={"policy_type": policy_type, "rule_name": rule.name})
                decision = resolver(rule, ctx, default_decision) if resolver is not None else PolicyDecision(
                    decision=default_decision,
                    reason=f"matched:{rule.name}",
                    confidence=0.7,
                    matched_rule=rule.name,
                    metadata={"policy_type": policy_type},
                )
                self._trace(
                    "Policy Matched",
                    metadata={
                        "policy_type": policy_type,
                        "rule_name": rule.name,
                        "action": rule.action,
                        "reason": decision.reason,
                    },
                )
                event_name = self._policy_event_name(policy_type)
                if event_name:
                    self._trace(
                        event_name,
                        metadata={
                            "rule_name": rule.name,
                            "action": rule.action,
                            "decision": self._serialize(decision.decision),
                        },
                    )
                if self._serialize(decision.decision) != self._serialize(default_decision):
                    self.runtime_metrics.inc("policy_override", labels={"policy_type": policy_type, "rule_name": rule.name})
                    self._trace(
                        "Policy Override",
                        metadata={
                            "policy_type": policy_type,
                            "rule_name": rule.name,
                            "default_decision": self._serialize(default_decision),
                            "override_decision": self._serialize(decision.decision),
                        },
                    )
                return decision
            self.runtime_metrics.inc("policy_reject", labels={"policy_type": policy_type, "rule_name": rule.name})
            self._trace(
                "Policy Rejected",
                metadata={"policy_type": policy_type, "rule_name": rule.name, "condition": rule.condition},
            )
        return default

    def evaluate_cache(
        self,
        context: ExecutionPolicyContext | Dict[str, Any],
        *,
        default_decision: Any = False,
    ) -> PolicyDecision:
        return self.evaluate("cache", context, default_decision=default_decision, resolver=self._resolve_cache_decision)

    def evaluate_memory(
        self,
        context: ExecutionPolicyContext | Dict[str, Any],
        *,
        default_decision: Any = False,
    ) -> PolicyDecision:
        return self.evaluate("memory", context, default_decision=default_decision, resolver=self._resolve_memory_decision)

    def evaluate_pipeline(
        self,
        context: ExecutionPolicyContext | Dict[str, Any],
        *,
        default_decision: Any = None,
    ) -> PolicyDecision:
        return self.evaluate("pipeline", context, default_decision=default_decision, resolver=self._resolve_pipeline_decision)

    def evaluate_retrieval(
        self,
        context: ExecutionPolicyContext | Dict[str, Any],
        *,
        default_decision: Any = True,
    ) -> PolicyDecision:
        return self.evaluate("retrieval", context, default_decision=default_decision, resolver=self._resolve_retrieval_decision)

    def evaluate_loop(
        self,
        context: ExecutionPolicyContext | Dict[str, Any],
        *,
        default_decision: Any = None,
    ) -> PolicyDecision:
        fallback = default_decision
        if fallback is None:
            fallback = {"continue": False, "reason": "VERIFICATION_PASS"}
        return self.evaluate("loop", context, default_decision=fallback, resolver=self._resolve_loop_decision)

    def evaluate_llm(
        self,
        context: ExecutionPolicyContext | Dict[str, Any],
        *,
        default_decision: Any = None,
    ) -> PolicyDecision:
        fallback = default_decision
        if fallback is None:
            fallback = {
                "allow_generate": True,
                "allow_stream": True,
                "allow_long_answer": True,
                "allow_follow_up": True,
                "needs_second_generate": False,
            }
        return self.evaluate("llm", context, default_decision=fallback, resolver=self._resolve_llm_decision)

    def evaluate_verification(
        self,
        context: ExecutionPolicyContext | Dict[str, Any],
        *,
        default_decision: Any = None,
    ) -> PolicyDecision:
        return self.evaluate(
            "verification",
            context,
            default_decision=default_decision or {},
            resolver=self._resolve_verification_decision,
        )

    def evaluate_knowledge_merge(
        self,
        context: ExecutionPolicyContext | Dict[str, Any],
        *,
        default_decision: Any = True,
    ) -> PolicyDecision:
        return self.evaluate(
            "knowledge_merge",
            context,
            default_decision=default_decision,
            resolver=self._resolve_knowledge_merge_decision,
        )

    def evaluate_conflict(
        self,
        context: ExecutionPolicyContext | Dict[str, Any],
        *,
        default_decision: Any = None,
    ) -> PolicyDecision:
        fallback = default_decision or {"preserve_existing": True, "overwrite": False}
        return self.evaluate("conflict", context, default_decision=fallback, resolver=self._resolve_conflict_decision)

    def _resolve_cache_decision(self, rule: PolicyRule, context: ExecutionPolicyContext, default_decision: Any) -> PolicyDecision:
        decision = bool(default_decision)
        if rule.action in {"use_cache", "write_cache"}:
            decision = True
        elif rule.action in {"skip_cache", "skip_cache_write"}:
            decision = False
        return PolicyDecision(
            decision=decision,
            reason=self._rule_reason(rule, context, fallback=f"cache:{rule.action}"),
            confidence=self._rule_confidence(rule, fallback=0.9),
            matched_rule=rule.name,
            metadata={"policy_type": "cache", "operation": self._operation(context)},
        )

    def _resolve_memory_decision(self, rule: PolicyRule, context: ExecutionPolicyContext, default_decision: Any) -> PolicyDecision:
        decision = bool(default_decision)
        if rule.action in {"restore_memory", "create_snapshot"}:
            decision = True
        elif rule.action in {"skip_restore", "skip_snapshot"}:
            decision = False
        return PolicyDecision(
            decision=decision,
            reason=self._rule_reason(rule, context, fallback=f"memory:{rule.action}"),
            confidence=self._rule_confidence(rule, fallback=0.88),
            matched_rule=rule.name,
            metadata={"policy_type": "memory", "operation": self._operation(context)},
        )

    def _resolve_pipeline_decision(self, rule: PolicyRule, context: ExecutionPolicyContext, default_decision: Any) -> PolicyDecision:
        selection = default_decision or context.pipeline
        decision = selection
        if rule.action == "use_fallback_pipeline":
            decision = self._override_pipeline_selection(selection, rule, context)
        return PolicyDecision(
            decision=decision,
            reason=self._rule_reason(rule, context, fallback=f"pipeline:{rule.action}"),
            confidence=self._rule_confidence(rule, fallback=0.82),
            matched_rule=rule.name,
            metadata={"policy_type": "pipeline", "selected_pipeline": self._selected_pipeline_name(decision)},
        )

    def _resolve_retrieval_decision(self, rule: PolicyRule, context: ExecutionPolicyContext, default_decision: Any) -> PolicyDecision:
        decision = bool(default_decision)
        if rule.action == "allow_retrieval":
            decision = True
        elif rule.action == "reject_retrieval":
            decision = False
        return PolicyDecision(
            decision=decision,
            reason=self._rule_reason(rule, context, fallback=f"retrieval:{rule.action}"),
            confidence=self._rule_confidence(rule, fallback=0.9),
            matched_rule=rule.name,
            metadata={"policy_type": "retrieval", "tool_name": self._tool_name(context)},
        )

    def _resolve_loop_decision(self, rule: PolicyRule, context: ExecutionPolicyContext, default_decision: Any) -> PolicyDecision:
        decision = dict(default_decision or {})
        if rule.action == "stop_loop":
            decision = {
                "continue": False,
                "reason": self._loop_stop_reason(rule, context),
            }
        elif rule.action == "continue_loop":
            decision = {
                "continue": True,
                "reason": self._continue_reason(context),
            }
        return PolicyDecision(
            decision=decision,
            reason=self._rule_reason(rule, context, fallback=str(decision.get("reason") or "")),
            confidence=self._rule_confidence(rule, fallback=0.92),
            matched_rule=rule.name,
            metadata={"policy_type": "loop", "loop_count": int(context.loop_count or 0)},
        )

    def _resolve_llm_decision(self, rule: PolicyRule, context: ExecutionPolicyContext, default_decision: Any) -> PolicyDecision:
        base = dict(default_decision or {})
        if not base:
            base = {
                "allow_generate": True,
                "allow_stream": True,
                "allow_long_answer": True,
                "allow_follow_up": True,
                "needs_second_generate": False,
            }
        if rule.action == "deny_stream":
            base["allow_stream"] = False
        elif rule.action == "allow_stream":
            base["allow_stream"] = True
        elif rule.action == "deny_llm":
            base["allow_generate"] = False
            base["allow_stream"] = False
        elif rule.action == "allow_llm":
            base["allow_generate"] = True
        return PolicyDecision(
            decision=base,
            reason=self._rule_reason(rule, context, fallback=f"llm:{rule.action}"),
            confidence=self._rule_confidence(rule, fallback=0.86),
            matched_rule=rule.name,
            metadata={"policy_type": "llm", "operation": self._operation(context)},
        )

    def _resolve_verification_decision(self, rule: PolicyRule, context: ExecutionPolicyContext, default_decision: Any) -> PolicyDecision:
        payload = dict(default_decision or {})
        if rule.action == "verification_pass":
            payload["evidence_enough"] = True
            payload["citation_ready"] = bool(payload.get("citation_ready", payload.get("evidence_count", 0) > 0))
            payload["has_conflict"] = bool(payload.get("has_conflict"))
            payload["answer_ready"] = not bool(payload.get("has_conflict"))
        elif rule.action == "verification_retry":
            payload["evidence_enough"] = False
            payload["answer_ready"] = False
        return PolicyDecision(
            decision=payload,
            reason=self._rule_reason(rule, context, fallback=f"verification:{rule.action}"),
            confidence=self._rule_confidence(rule, fallback=0.9),
            matched_rule=rule.name,
            metadata={"policy_type": "verification"},
        )

    def _resolve_knowledge_merge_decision(self, rule: PolicyRule, context: ExecutionPolicyContext, default_decision: Any) -> PolicyDecision:
        decision = bool(default_decision)
        if rule.action == "allow_merge":
            decision = True
        elif rule.action == "skip_merge":
            decision = False
        return PolicyDecision(
            decision=decision,
            reason=self._rule_reason(rule, context, fallback=f"knowledge_merge:{rule.action}"),
            confidence=self._rule_confidence(rule, fallback=0.84),
            matched_rule=rule.name,
            metadata={"policy_type": "knowledge_merge"},
        )

    def _resolve_conflict_decision(self, rule: PolicyRule, context: ExecutionPolicyContext, default_decision: Any) -> PolicyDecision:
        decision = dict(default_decision or {"preserve_existing": True, "overwrite": False})
        if rule.action == "overwrite_conflict":
            decision["preserve_existing"] = False
            decision["overwrite"] = True
        elif rule.action == "preserve_existing":
            decision["preserve_existing"] = True
            decision["overwrite"] = False
        return PolicyDecision(
            decision=decision,
            reason=self._rule_reason(rule, context, fallback=f"conflict:{rule.action}"),
            confidence=self._rule_confidence(rule, fallback=0.91),
            matched_rule=rule.name,
            metadata={"policy_type": "conflict"},
        )

    def _rule_matches(self, rule: PolicyRule, context: ExecutionPolicyContext) -> bool:
        condition = str(rule.condition or "").strip()
        operation = self._operation(context)
        verification = self._verification_payload(context)
        memory = self._as_dict(context.memory)
        knowledge = self._as_dict(context.knowledge)
        trace = self._as_dict(context.trace)
        coverage = float(verification.get("coverage") or context.coverage or 0.0)
        threshold = float(verification.get("coverage_threshold") or 0.0)
        missing_fields = list(verification.get("missing_fields") or [])
        blocking_conflict = bool(verification.get("blocking_conflict"))

        if condition == "cache_hit_available":
            return operation == "read" and bool(memory.get("cache_hit"))
        if condition == "cache_write_ready":
            return operation == "write" and bool(self._tool_name(context))
        if condition == "memory_restore_available":
            return operation == "restore" and int(memory.get("snapshot_count") or 0) > 0
        if condition == "memory_snapshot_ready":
            return operation == "snapshot" and (int(knowledge.get("node_count") or 0) > 0 or int(knowledge.get("relation_count") or 0) > 0)
        if condition == "pipeline_cost_guard":
            selected = self._selected_pipeline(context.pipeline)
            if selected is None:
                return False
            selected_name = str(getattr(selected, "name", "") or self._as_dict(selected).get("name") or "")
            selected_cost = str(getattr(selected, "cost", "") or self._as_dict(selected).get("cost") or "").lower()
            confidence = float(trace.get("selection_confidence") or self._pipeline_confidence(context.pipeline))
            has_entities = bool(trace.get("has_entities"))
            return (
                operation == "select"
                and selected_name not in {"", "StandardPipeline"}
                and selected_cost in {"medium", "high"}
                and confidence < float((rule.metadata or {}).get("max_confidence") or 0.75)
                and not has_entities
                and str(context.question_type or "UNKNOWN").upper().strip() in {"UNKNOWN", "NEWS", "COUNTRY"}
            )
        if condition == "pipeline_keep_current":
            return operation == "select"
        if condition == "retrieval_tool_missing":
            return operation == "execute" and not bool(self._tool_name(context))
        if condition == "retrieval_tool_allowed":
            return operation == "execute" and bool(self._tool_name(context))
        if condition == "verification_ready":
            return (not missing_fields) and coverage >= threshold and not blocking_conflict and bool(verification.get("citation_ready"))
        if condition == "verification_retry":
            return not ((not missing_fields) and coverage >= threshold and not blocking_conflict and bool(verification.get("citation_ready")))
        if condition == "loop_stop_max":
            return operation == "continue" and int(context.loop_count or 0) >= int(trace.get("max_loop") or 0)
        if condition == "loop_stop_stagnation":
            return operation == "continue" and bool(trace.get("stagnation_reason"))
        if condition == "loop_stop_verified":
            return operation == "continue" and (not missing_fields) and coverage >= threshold and not blocking_conflict
        if condition == "loop_continue_gap":
            return operation == "continue" and (bool(missing_fields) or coverage < threshold or blocking_conflict)
        if condition == "knowledge_merge_ready":
            return operation == "merge" and (
                bool(context.tool_results)
                or bool(knowledge.get("has_previous_graph"))
                or int(knowledge.get("node_count") or 0) > 0
                or int(knowledge.get("relation_count") or 0) > 0
            )
        if condition == "knowledge_merge_skip":
            return operation == "merge" and not (
                bool(context.tool_results)
                or bool(knowledge.get("has_previous_graph"))
                or int(knowledge.get("node_count") or 0) > 0
                or int(knowledge.get("relation_count") or 0) > 0
            )
        if condition == "knowledge_conflict_detected":
            existing_value = knowledge.get("existing_value")
            new_value = knowledge.get("new_value")
            return operation == "conflict" and existing_value not in (None, "", [], {}) and new_value not in (None, "", [], {}) and existing_value != new_value
        if condition == "llm_stream_blocked":
            return operation == "stream" and not bool(trace.get("supports_stream", True))
        if condition == "llm_stream_allowed":
            return operation == "stream" and bool(trace.get("supports_stream", True))
        if condition == "llm_generate_ready":
            return operation == "generate"
        return False

    def _override_pipeline_selection(self, selection: Any, rule: PolicyRule, context: ExecutionPolicyContext) -> Any:
        if selection is None:
            return selection
        payload = self._serialize(selection)
        if not isinstance(payload, dict):
            return selection
        fallback = payload.get("fallback_pipeline") if isinstance(payload.get("fallback_pipeline"), dict) else None
        current = payload.get("selected_pipeline") if isinstance(payload.get("selected_pipeline"), dict) else None
        if fallback is None or current is None:
            return selection
        payload["selected_pipeline"] = fallback
        payload["fallback_pipeline"] = current
        current_reason = str(payload.get("selection_reason") or "")
        override_reason = str((rule.metadata or {}).get("override_reason") or "policy_override")
        payload["selection_reason"] = f"{current_reason} Policy override: {override_reason}".strip()
        payload["confidence"] = min(float(payload.get("confidence") or 0.0), float((rule.metadata or {}).get("override_confidence") or 0.72))
        selection_type = type(selection)
        if hasattr(selection_type, "from_dict"):
            try:
                return selection_type.from_dict(payload)
            except Exception:
                return payload
        return payload

    def _policy_event_name(self, policy_type: str) -> str:
        mapping = {
            "cache": "Cache Policy",
            "memory": "Memory Policy",
            "pipeline": "Pipeline Policy",
            "loop": "Loop Policy",
            "llm": "LLM Policy",
            "verification": "Verification Policy",
            "retrieval": "Retrieval Policy",
            "knowledge_merge": "Knowledge Policy",
            "conflict": "Conflict Policy",
        }
        return mapping.get(str(policy_type or "").strip().lower(), "")

    def _operation(self, context: ExecutionPolicyContext) -> str:
        for payload in [context.trace, context.memory, context.knowledge, context.verification]:
            data = self._as_dict(payload)
            operation = str(data.get("operation") or "").strip().lower()
            if operation:
                return operation
        return ""

    def _tool_name(self, context: ExecutionPolicyContext) -> str:
        trace = self._as_dict(context.trace)
        return str(trace.get("tool_name") or "").strip()

    def _verification_payload(self, context: ExecutionPolicyContext) -> Dict[str, Any]:
        payload = self._as_dict(context.verification)
        if "coverage" not in payload:
            payload["coverage"] = float(context.coverage or 0.0)
        return payload

    def _selected_pipeline(self, payload: Any) -> Any:
        if payload is None:
            return None
        selected = getattr(payload, "selected_pipeline", None)
        if selected is not None:
            return selected
        data = self._as_dict(payload)
        selected = data.get("selected_pipeline")
        if isinstance(selected, dict):
            return selected
        return payload

    def _selected_pipeline_name(self, payload: Any) -> str:
        selected = self._selected_pipeline(payload)
        if selected is None:
            return ""
        if isinstance(selected, dict):
            return str(selected.get("name") or "")
        return str(getattr(selected, "name", "") or "")

    def _pipeline_confidence(self, payload: Any) -> float:
        if payload is None:
            return 0.0
        return float(getattr(payload, "confidence", 0.0) or self._as_dict(payload).get("confidence") or 0.0)

    def _loop_stop_reason(self, rule: PolicyRule, context: ExecutionPolicyContext) -> str:
        trace = self._as_dict(context.trace)
        if rule.condition == "loop_stop_max":
            return "MAX_LOOP"
        if rule.condition == "loop_stop_stagnation":
            return str(trace.get("stagnation_reason") or "NO_PROGRESS")
        return "VERIFICATION_PASS"

    def _continue_reason(self, context: ExecutionPolicyContext) -> str:
        verification = self._verification_payload(context)
        missing_fields = list(verification.get("missing_fields") or [])
        coverage = float(verification.get("coverage") or 0.0)
        threshold = float(verification.get("coverage_threshold") or 0.0)
        blocking_conflict = bool(verification.get("blocking_conflict"))
        reasons: List[str] = []
        if missing_fields:
            reasons.append("MISSING_FIELDS")
        if coverage < threshold:
            reasons.append("LOW_COVERAGE")
        if blocking_conflict:
            reasons.append("BLOCKING_CONFLICT")
        return "+".join(reasons) or "CONTINUE"

    def _rule_reason(self, rule: PolicyRule, context: ExecutionPolicyContext, *, fallback: str) -> str:
        template = str((rule.metadata or {}).get("reason_template") or "").strip()
        if not template:
            return fallback
        return (
            template.replace("{question_type}", str(context.question_type or "UNKNOWN"))
            .replace("{pipeline}", self._selected_pipeline_name(context.pipeline))
            .replace("{tool_name}", self._tool_name(context))
        )

    def _rule_confidence(self, rule: PolicyRule, *, fallback: float) -> float:
        return round(float((rule.metadata or {}).get("confidence") or fallback), 2)

    def _ensure_context(self, context: ExecutionPolicyContext | Dict[str, Any]) -> ExecutionPolicyContext:
        if isinstance(context, ExecutionPolicyContext):
            return context
        return ExecutionPolicyContext.from_dict(context or {})

    def _trace(self, event_name: str, *, metadata: Dict[str, Any] | None = None) -> None:
        if self.trace_center is None:
            return
        try:
            self.trace_center.record_event("POLICY", event_name, metadata=metadata or {})
        except Exception:
            pass

    def _as_dict(self, value: Any) -> Dict[str, Any]:
        if isinstance(value, dict):
            return dict(value)
        if hasattr(value, "to_dict"):
            try:
                payload = value.to_dict()
                if isinstance(payload, dict):
                    return payload
            except Exception:
                return {}
        return {}

    def _serialize(self, value: Any) -> Any:
        if hasattr(value, "to_dict"):
            try:
                return value.to_dict()
            except Exception:
                return value
        return value
