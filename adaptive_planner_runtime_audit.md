# Adaptive Planner Runtime Audit

Date: 2026-07-02
Scope: Phase 14.5 Runtime Audit for `AdaptivePlanner`
Mode: Read-only runtime verification, no business logic changes

## 1. Audit Scope

This phase validates whether Adaptive Planner dynamic replanning is truly active at runtime and whether it delivers measurable benefit.

Audit constraints respected:

- No business capability changes
- No new planner capability
- No Tool / Prompt / LLM / Memory / Knowledge / API / Frontend / Database / Redis modifications
- Only runtime verification, statistics, compatibility check, architecture review, and documentation

## 2. Audit Method

The audit used a controlled runtime harness built on the existing runtime classes:

- `WorkflowExecutor`
- `AdaptivePlanner`
- `TaskPlanner`
- `TraceCenter`
- `RuntimeMetrics`
- `StandardWorkflow` / `ResearchWorkflow` execution model

Seven controlled scenarios were executed:

1. `healthy`
2. `missing_entity`
3. `missing_evidence`
4. `knowledge_gap`
5. `verification_failed`
6. `policy_retry`
7. `loop_continue`

Each scenario was executed twice:

- `ADAPTIVE_PLANNER_ENABLED=0`
- `ADAPTIVE_PLANNER_ENABLED=1`

This produced a direct ON/OFF compatibility comparison without modifying production code.

## 3. Revision Statistics

### 3.1 Overall

- Revision total: `6`
- Revision applied count: `6`
- Revision apply success rate: `100%`
- Revision abandon count: `2`

Note:

- "Applied count" means `PlanningRevision` objects were actually created and merged into `TaskGraph`
- "Abandon count" in this audit means scenarios expected to expose adaptive value but produced `0` runtime revision hits under `ADAPTIVE_PLANNER_ENABLED=1`
- "Applied" does **not** mean "effective"

### 3.2 RevisionReason Hit Counts

- `MissingEntity`: `1`
- `MissingEvidence`: `3`
- `KnowledgeGap`: `0`
- `VerificationFailed`: `1`
- `PolicyRetry`: `1`
- `LoopContinue`: `0`

### 3.3 Key Verdict

- `MissingEntity`, `MissingEvidence`, `VerificationFailed`, `PolicyRetry` are runtime-triggerable
- `KnowledgeGap` and `LoopContinue` were not triggered in runtime audit
- Runtime trigger coverage for defined reasons: `4 / 6 = 66.7%`

## 4. TaskGraph Diff

### 4.1 Observed Revisions

#### Case: `missing_entity`

- Revision 1
  - Reason: `MissingEntity`
  - Before: `5 tasks`
  - After: `5 tasks`
  - Added: `None`
  - Removed: `None`
  - Reprioritized:
    - `research.search`
    - `research.retrieve`
    - `research.verify`

- Revision 2
  - Reason: `MissingEvidence`
  - Before: `5 tasks`
  - After: `5 tasks`
  - Added: `None`
  - Removed: `None`
  - Reprioritized:
    - `research.retrieve`
    - `research.verify`

#### Case: `missing_evidence`

- Revision 1
  - Reason: `MissingEvidence`
  - Before: `5 tasks`
  - After: `5 tasks`
  - Added: `None`
  - Removed: `None`
  - Reprioritized:
    - `research.retrieve`
    - `research.verify`

- Revision 2
  - Reason: `MissingEvidence`
  - Before: `5 tasks`
  - After: `5 tasks`
  - Added: `None`
  - Removed: `None`
  - Reprioritized: `None`

#### Case: `verification_failed`

- Revision 1
  - Reason: `VerificationFailed`
  - Before: `5 tasks`
  - After: `5 tasks`
  - Added: `None`
  - Removed: `None`
  - Reprioritized:
    - `research.reason`
    - `research.verify`
    - `research.final`

#### Case: `policy_retry`

- Revision 1
  - Reason: `PolicyRetry`
  - Before: `5 tasks`
  - After: `5 tasks`
  - Added: `None`
  - Removed: `None`
  - Reprioritized: `None`

### 4.2 Diff Verdict

- Observed runtime revisions were almost entirely "reprioritize only"
- Runtime `Task Added` count: `0`
- Runtime `Task Removed` count: `0`
- Runtime task count delta: `0` in all observed applied revisions

This means current Adaptive Planner mainly rewrites priority metadata, but almost never expands the executable TaskGraph in real runs.

## 5. Workflow Revisit Analysis

Two layers must be separated:

1. Node was re-queued / revisited in `WorkflowExecutor.node_sequence`
2. Node service was actually re-executed

### 5.1 Queue-Level Revisit Counts

- `retrieval`: `6`
- `knowledge`: `2`
- `memory_update`: `2`
- `answer_composer`: `2`
- `verification`: `2`
- `retrieval_loop`: `0`
- `memory_snapshot`: `1`
- `llm`: `0`

### 5.2 Actual Service Re-execution

Observed from service call counts:

- `retrieval`: `0` extra actual executions
- `knowledge`: `0`
- `memory_update`: `0`
- `answer_composer`: `0`
- `verification`: `0`
- `retrieval_loop`: `0`
- `memory_snapshot`: `1`
- `llm`: `0`

### 5.3 Revisit Verdict

Adaptive Planner is currently able to re-queue existing workflow nodes, but in most cases those revisits are later skipped by `TaskGraph` status gating.

This is the single most important runtime finding of this audit.

## 6. Adaptive Planner Effect

Revision effectiveness was measured against:

- Coverage
- Citation Ready
- Verification Pass
- Answer Ready
- Knowledge Nodes
- Knowledge Relations

### 6.1 Observed Improvement

Across all applied revisions:

- Coverage improvement: `0 / 6`
- Citation Ready improvement: `0 / 6`
- Verification Pass improvement: `0 / 6`
- Answer Ready improvement: `0 / 6`
- Knowledge Nodes improvement: `0 / 6`
- Knowledge Relations improvement: `0 / 6`

### 6.2 Per-Case Summary

- `missing_entity`
  - Before coverage: `0.0`
  - After coverage: `0.0`
  - No improvement

- `missing_evidence`
  - Before coverage: `0.0`
  - After coverage: `0.0`
  - No improvement

- `verification_failed`
  - Before coverage: `0.35`
  - After coverage: `0.35`
  - No improvement

- `policy_retry`
  - Before verification pass: `true`
  - After verification pass: `true`
  - No measurable gain

### 6.3 Effect Verdict

Observed revision application rate is high enough to prove the mechanism runs.

Observed quality improvement rate is effectively:

- `0%`

So the current system has:

- real revision triggering
- weak revision effectiveness

## 7. Runtime Cost

Only cases with applied revisions were counted.

### 7.1 Average Additional Runtime Cost

- Average added latency: `3.54 ms`
- Average added tool executions: `0`
- Average added workflow node executions: `4.25`
- Average added LLM calls: `0`

### 7.2 Per-Case Cost

- `missing_entity`
  - Extra latency: `3.48 ms`
  - Extra tool calls: `0`
  - Extra node executions: `2`
  - Extra LLM calls: `0`

- `missing_evidence`
  - Extra latency: `1.32 ms`
  - Extra tool calls: `0`
  - Extra node executions: `2`
  - Extra LLM calls: `0`

- `verification_failed`
  - Extra latency: `4.93 ms`
  - Extra tool calls: `0`
  - Extra node executions: `5`
  - Extra LLM calls: `0`

- `policy_retry`
  - Extra latency: `4.43 ms`
  - Extra tool calls: `0`
  - Extra node executions: `8`
  - Extra LLM calls: `0`

### 7.3 Cost Verdict

Adaptive Planner currently adds orchestration overhead but does not add retrieval/tool/LLM work in the audited paths.

This is good for safety, but bad for effectiveness:

- low cost
- low benefit

## 8. Compatibility Verification

### 8.1 `ADAPTIVE_PLANNER_ENABLED=0`

Observed behavior:

- Revision count always `0`
- Workflow returns to plain `TaskGraph -> Workflow` execution
- No planning revision trace events
- No extra node revisits

### 8.2 `ADAPTIVE_PLANNER_ENABLED=1`

Observed behavior:

- Revisions appear only in targeted failure scenarios
- Healthy path remains unchanged
- LLM call count remains unchanged in all audited runs

### 8.3 ON/OFF Comparison

#### Healthy Path

- OFF revision count: `0`
- ON revision count: `0`
- OFF answer ready: `true`
- ON answer ready: `true`
- OFF LLM calls: `1`
- ON LLM calls: `1`

Verdict:

- healthy path is backward compatible

#### Failure Paths

- OFF: no revisions, no extra node visits
- ON: revisions may appear, node count increases, final result is usually unchanged

Verdict:

- backward compatibility is good
- side effects are limited to planning/runtime orchestration
- current ON path mostly increases orchestration work rather than answer quality

## 9. Trace Coverage

Expected events:

- `Planning Revision Started`
- `Planning Revision Finished`
- `Task Added`
- `Task Removed`
- `Task Reprioritized`

Observed events:

- `Planning Revision Started`
- `Planning Revision Finished`
- `Task Reprioritized`

Missing events:

- `Task Added`
- `Task Removed`

### Trace Verdict

Trace coverage for revision-specific events:

- `3 / 5 = 60%`

This is not enough for enterprise-grade runtime explainability.

## 10. Architecture Review

### 10.1 Major Findings

#### 1. Revision is real, but often not effective

`WorkflowExecutor` does create and merge `PlanningRevision`, but in many cases the updated TaskGraph still marks relevant tasks as `completed`, so revisit nodes are queued and then immediately skipped.

Impact:

- revision happened
- workflow did not actually re-execute useful work
- no quality gain

#### 2. `KnowledgeGap` appears unreachable in audited runtime path

In the audited `ResearchPipeline` / `ResearchWorkflow` path:

- `knowledge` service was skipped in every run
- therefore `AdaptivePlanner.analyse_execution_result()` never got a runtime chance to emit `KnowledgeGap`

Impact:

- declared revision reason exists in code
- no runtime evidence it can trigger in the audited default path

#### 3. `LoopContinue` appears unreachable in audited runtime path

`retrieval_loop` was skipped in every audited run, so `LoopContinue` never fired.

Impact:

- declared reason exists
- runtime trigger path is effectively absent in audited flow

#### 4. `Task Added` is not observed at runtime

Even though the code supports `added_tasks`, the observed revisions did not add new executable tasks.

Impact:

- Adaptive Planner is behaving like a reprioritizer, not a real graph expander

#### 5. `Task Removed` is currently dead runtime behavior

Code inspection shows:

- `removed_tasks` is defined in `PlanningRevision`
- metrics and trace consume it
- but no current implementation populates it

Impact:

- `Task Removed` trace and metrics are effectively dead paths

#### 6. Duplicate revision prevention is only partial

The duplicate guard uses:

- `node_id`
- `reason`
- `revision_count`

This prevents exact same signature inside the same revision count window, but allows related repeated revisions across different counts.

Observed example:

- `MissingEvidence` can fire once at `retrieval`
- then again at `verification`

Impact:

- bounded, but still noisy

#### 7. Infinite revision risk is bounded

Code inspection confirms:

- `revision_count >= 2` stops further revision generation

Verdict:

- no infinite replanning observed
- hard stop exists and works as intended

#### 8. Trace helper dead code exists

Static scan result:

- `TraceCenter.start_planning_revision()`
- `TraceCenter.finish_planning_revision()`

were defined, but not used by runtime revision flow in this audit.

Impact:

- small dead helper footprint
- trace API is partially bypassed

### 10.2 Architecture Verdict

Current Adaptive Planner is:

- `runtime-active`
- `backward-compatible`
- `safe`
- but only `partially effective`

It currently behaves more like:

- `Dynamic Revision Signaller`

than:

- `Dynamic Task Replanner that materially improves execution`

## 11. Runtime Score

### 11.1 Scorecard

- Runtime Score: `58 / 100`
- Stability: `78 / 100`
- Accuracy: `34 / 100`
- Performance: `71 / 100`
- Maintainability: `49 / 100`

### 11.2 Why

#### Stability `78`

- compile clean
- diagnostics clean
- no crashes in audit runs
- revision loop is bounded

#### Accuracy `34`

- runtime trigger exists
- measurable answer/coverage gain is `0%`
- `KnowledgeGap` and `LoopContinue` lack runtime evidence

#### Performance `71`

- added cost is small
- no extra tool calls
- no extra LLM calls
- but there is wasted orchestration work from skipped revisits

#### Maintainability `49`

- trace coverage incomplete
- dead helper paths exist
- removed task path is not wired
- revision semantics and execution semantics are not aligned

## 12. Top 10 Improvement List

1. Align `TaskGraph` status merge with revision semantics so reprioritized tasks can become executable again when revision explicitly requires revisit.
2. Separate `re-queued` from `actually re-executed` in runtime metrics and dashboard outputs.
3. Make `KnowledgeGap` runtime-triggerable in default workflow path, or remove it from default claims until it is truly reachable.
4. Make `LoopContinue` runtime-triggerable in default workflow path, or mark it as non-default capability.
5. Populate `added_tasks` in at least one meaningful default revision path to prove graph expansion is real.
6. Either implement real `removed_tasks` semantics or remove related trace/metric claims to avoid dead-path observability.
7. Replace current duplicate revision signature with a stronger semantic dedupe key that does not allow low-value repeated revisions on nearby nodes.
8. Route runtime revision trace through `TraceCenter.start_planning_revision()` / `finish_planning_revision()` to eliminate helper dead code and standardize observability.
9. Add a dedicated runtime metric for `revision_effective` based on post-revision improvement in coverage / answer_ready / evidence_enough.
10. Add an Adaptive Planner regression suite with expected `before -> after` improvements, not just revision presence.

## 13. Compile & Diagnostics

Compile command executed:

```bash
python -m py_compile backend/services/adaptive_planner.py backend/services/planning_revision.py backend/services/task_planner.py backend/services/workflow_executor.py backend/services/pipeline_orchestrator.py
```

Result:

- `exit_code=0`

Global diagnostics:

- `[]`

## 14. Final Verdict

Adaptive Planner V1 is not fake.

It does:

- trigger revisions
- update TaskGraph
- emit revision trace
- preserve backward compatibility

But it is not yet an effective runtime replanning system.

Current maturity:

- `Mechanism Verified`
- `Benefit Not Verified`

Plain-language conclusion:

The engine has started to "notice problems and rewrite the plan", but in most audited paths it still cannot convert that rewritten plan into real additional execution and measurable quality improvement.
