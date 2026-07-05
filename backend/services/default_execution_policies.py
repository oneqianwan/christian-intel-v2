from __future__ import annotations

from services.execution_policy import PolicyRule


def _cache_policies() -> list[PolicyRule]:
    return [
        PolicyRule(
            name="CachePolicy.UseCacheHit",
            description="Use retrieval cache when a valid hit exists.",
            priority=100,
            enabled=True,
            condition="cache_hit_available",
            action="use_cache",
            metadata={
                "policy_type": "cache",
                "reason_template": "cache hit accepted",
                "confidence": 0.95,
            },
        ),
        PolicyRule(
            name="CachePolicy.WriteCache",
            description="Allow cache write for executed retrieval results.",
            priority=80,
            enabled=True,
            condition="cache_write_ready",
            action="write_cache",
            metadata={
                "policy_type": "cache",
                "reason_template": "cache write accepted for {tool_name}",
                "confidence": 0.9,
            },
        ),
    ]


def _memory_policies() -> list[PolicyRule]:
    return [
        PolicyRule(
            name="MemoryPolicy.RestoreSnapshot",
            description="Restore knowledge only when memory snapshots exist.",
            priority=100,
            enabled=True,
            condition="memory_restore_available",
            action="restore_memory",
            metadata={
                "policy_type": "memory",
                "reason_template": "memory restore accepted",
                "confidence": 0.92,
            },
        ),
        PolicyRule(
            name="MemoryPolicy.CreateSnapshot",
            description="Create snapshot only when there is knowledge to preserve.",
            priority=90,
            enabled=True,
            condition="memory_snapshot_ready",
            action="create_snapshot",
            metadata={
                "policy_type": "memory",
                "reason_template": "memory snapshot accepted",
                "confidence": 0.9,
            },
        ),
    ]


def _pipeline_policies() -> list[PolicyRule]:
    return [
        PolicyRule(
            name="PipelinePolicy.CostGuard",
            description="Downgrade expensive medium/high-cost pipelines for ambiguous queries with weak confidence.",
            priority=100,
            enabled=True,
            condition="pipeline_cost_guard",
            action="use_fallback_pipeline",
            metadata={
                "policy_type": "pipeline",
                "max_confidence": 0.75,
                "override_reason": "ambiguous query prefers lower-cost fallback pipeline",
                "override_confidence": 0.72,
                "reason_template": "pipeline override triggered for {question_type}",
                "confidence": 0.84,
            },
        ),
        PolicyRule(
            name="PipelinePolicy.KeepSelection",
            description="Keep the governor selection when no override rule applies.",
            priority=10,
            enabled=True,
            condition="pipeline_keep_current",
            action="keep_pipeline",
            metadata={
                "policy_type": "pipeline",
                "reason_template": "pipeline kept as {pipeline}",
                "confidence": 0.8,
            },
        ),
    ]


def _retrieval_policies() -> list[PolicyRule]:
    return [
        PolicyRule(
            name="RetrievalPolicy.RejectMissingTool",
            description="Reject retrieval when the tool name is missing.",
            priority=100,
            enabled=True,
            condition="retrieval_tool_missing",
            action="reject_retrieval",
            metadata={
                "policy_type": "retrieval",
                "reason_template": "retrieval rejected because tool name is missing",
                "confidence": 0.98,
            },
        ),
        PolicyRule(
            name="RetrievalPolicy.AllowExecution",
            description="Allow retrieval when a concrete tool is selected.",
            priority=80,
            enabled=True,
            condition="retrieval_tool_allowed",
            action="allow_retrieval",
            metadata={
                "policy_type": "retrieval",
                "reason_template": "retrieval allowed for {tool_name}",
                "confidence": 0.92,
            },
        ),
    ]


def _verification_policies() -> list[PolicyRule]:
    return [
        PolicyRule(
            name="VerificationPolicy.Pass",
            description="Mark verification as ready when coverage and citations pass threshold and no blocking conflict remains.",
            priority=100,
            enabled=True,
            condition="verification_ready",
            action="verification_pass",
            metadata={
                "policy_type": "verification",
                "reason_template": "verification passed",
                "confidence": 0.94,
            },
        ),
        PolicyRule(
            name="VerificationPolicy.Retry",
            description="Keep verification open when evidence or coverage remains insufficient.",
            priority=80,
            enabled=True,
            condition="verification_retry",
            action="verification_retry",
            metadata={
                "policy_type": "verification",
                "reason_template": "verification requires more evidence",
                "confidence": 0.9,
            },
        ),
    ]


def _loop_policies() -> list[PolicyRule]:
    return [
        PolicyRule(
            name="LoopPolicy.StopAtMaxLoop",
            description="Stop retrieval loop when the max loop limit has been reached.",
            priority=120,
            enabled=True,
            condition="loop_stop_max",
            action="stop_loop",
            metadata={
                "policy_type": "loop",
                "reason_template": "loop stopped at max loop",
                "confidence": 0.99,
            },
        ),
        PolicyRule(
            name="LoopPolicy.StopOnStagnation",
            description="Stop retrieval loop when evidence, facts, and coverage stop improving.",
            priority=110,
            enabled=True,
            condition="loop_stop_stagnation",
            action="stop_loop",
            metadata={
                "policy_type": "loop",
                "reason_template": "loop stopped because stagnation was detected",
                "confidence": 0.97,
            },
        ),
        PolicyRule(
            name="LoopPolicy.StopOnVerificationPass",
            description="Stop retrieval loop when verification has already passed.",
            priority=100,
            enabled=True,
            condition="loop_stop_verified",
            action="stop_loop",
            metadata={
                "policy_type": "loop",
                "reason_template": "loop stopped because verification already passed",
                "confidence": 0.95,
            },
        ),
        PolicyRule(
            name="LoopPolicy.ContinueOnGap",
            description="Continue retrieval loop when coverage, fields, or conflicts indicate missing information.",
            priority=90,
            enabled=True,
            condition="loop_continue_gap",
            action="continue_loop",
            metadata={
                "policy_type": "loop",
                "reason_template": "loop continues because gaps remain",
                "confidence": 0.93,
            },
        ),
    ]


def _llm_policies() -> list[PolicyRule]:
    return [
        PolicyRule(
            name="LLMPolicy.BlockStreamWhenUnsupported",
            description="Disable stream mode when the selected pipeline does not support streaming.",
            priority=100,
            enabled=True,
            condition="llm_stream_blocked",
            action="deny_stream",
            metadata={
                "policy_type": "llm",
                "reason_template": "stream denied for {pipeline}",
                "confidence": 0.96,
            },
        ),
        PolicyRule(
            name="LLMPolicy.AllowStream",
            description="Allow stream mode when the pipeline supports it.",
            priority=90,
            enabled=True,
            condition="llm_stream_allowed",
            action="allow_stream",
            metadata={
                "policy_type": "llm",
                "reason_template": "stream allowed for {pipeline}",
                "confidence": 0.92,
            },
        ),
        PolicyRule(
            name="LLMPolicy.AllowGenerate",
            description="Allow final generate call once the pipeline reaches generation stage.",
            priority=80,
            enabled=True,
            condition="llm_generate_ready",
            action="allow_llm",
            metadata={
                "policy_type": "llm",
                "reason_template": "llm generation allowed",
                "confidence": 0.88,
            },
        ),
    ]


def _knowledge_policies() -> list[PolicyRule]:
    return [
        PolicyRule(
            name="KnowledgePolicy.AllowMerge",
            description="Allow graph merge when current or previous knowledge exists.",
            priority=100,
            enabled=True,
            condition="knowledge_merge_ready",
            action="allow_merge",
            metadata={
                "policy_type": "knowledge_merge",
                "reason_template": "knowledge merge allowed",
                "confidence": 0.9,
            },
        ),
        PolicyRule(
            name="KnowledgePolicy.SkipEmptyMerge",
            description="Skip graph merge when neither current nor previous knowledge exists.",
            priority=80,
            enabled=True,
            condition="knowledge_merge_skip",
            action="skip_merge",
            metadata={
                "policy_type": "knowledge_merge",
                "reason_template": "knowledge merge skipped because graph is empty",
                "confidence": 0.9,
            },
        ),
        PolicyRule(
            name="KnowledgePolicy.PreserveConflict",
            description="Preserve existing values and collect conflict history when scalar values disagree.",
            priority=100,
            enabled=True,
            condition="knowledge_conflict_detected",
            action="preserve_existing",
            metadata={
                "policy_type": "conflict",
                "reason_template": "conflict preserved for auditability",
                "confidence": 0.95,
            },
        ),
    ]


def get_default_execution_policies() -> list[PolicyRule]:
    return [
        *_cache_policies(),
        *_memory_policies(),
        *_pipeline_policies(),
        *_retrieval_policies(),
        *_verification_policies(),
        *_loop_policies(),
        *_llm_policies(),
        *_knowledge_policies(),
    ]
