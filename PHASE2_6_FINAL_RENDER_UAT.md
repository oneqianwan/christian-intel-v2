# PHASE2_6_FINAL_RENDER_UAT

## Scope

- Phase: `2.6`
- Goal: `Insight Final Answer` stable takeover in browser final answer, with deterministic final render preferred over legacy database/direct/LLM answers when:
  - `INSIGHT_ENGINE_ENABLED=true`
  - `INSIGHT_FINAL_RENDER_ENABLED=true`
  - `insight_result` exists
  - `query_mode` is supported by `InsightAnswerRenderer`

## Code Changes

- `backend/services/pipeline_orchestrator.py`
  - Confirmed and retained governor bypass when insight final render is enabled.
  - Fixed stream/sync inconsistency by rebuilding `ctx.insight_result` inside `_workflow_finalize_generation_stream()` when the stream path enters the `llm` node directly via `workflow_executor`.
  - Propagated rebuilt `insight_result` into `workflow_context.metadata` so stream finalization uses the same `InsightResult` as sync.

## Root Cause

- Sync path already rebuilt `InsightResult` before `_build_final_answer_override()`.
- Stream path entered `workflow_executor -> llm node -> _workflow_finalize_generation_stream()` directly and only consumed `ctx.insight_result` if it already existed.
- In affected cases, stream finalization had empty `ctx.insight_result`, so deterministic renderer was skipped and legacy composer/direct answer content leaked into `done.full_content`.

## UAT Question Set

1. `Victory Philippines 的评分是多少？`
2. `为什么 Victory Philippines 的 Digital Score 只有 28？`
3. `Victory Philippines 有哪些优势和风险？`
4. `生成 Victory Philippines 的简要情报摘要`
5. `Victory Philippines 的机构画像`
6. `菲律宾基督教媒体有哪些？`
7. `对比 Every Nation 和 Victory Philippines`
8. `Neverland Gospel AI Institute 的机构画像`
9. `Victory Philippines 的数据来源是什么？`
10. `评估 Victory Philippines`

Supplementary route checks:

- `你的数据来源是什么？`
- `系统的数据来源是什么？`
- `你从哪里获取数据？`

## ON Validation

Configuration:

- `INSIGHT_ENGINE_ENABLED=true`
- `INSIGHT_FINAL_RENDER_ENABLED=true`

Artifacts:

- `C:\Users\baiwan\AppData\Local\Temp\phase26_uat_on.json`

### Required Gates

| Gate | Result |
|---|---|
| Q1 not just a number, must include score explanation structure | PASS |
| Q2 `query_mode=score_query` | PASS |
| Q2 `target_entities=["Victory Philippines"]` | PASS |
| Q3 complete organization insight structure | PASS |
| Q4 does not answer "没有相关信息" | PASS |
| Q7 shows `Coverage Imbalance` | PASS |
| Q7 does not claim `Victory Philippines` has no data | PASS |
| Q9 `Intent=research` | PASS |
| Q9 `RetrievalSkipped=false` | PASS |
| Q9 returns entity-specific source URL | PASS |
| Q10 `query_mode=organization` | PASS |
| Product-level source questions route to Assistant | PASS |
| Browser SSE success | PASS |
| Pseudo URL count | `0` |
| Wrong subject count | `0` |

### Observed Results

- Q1 browser final answer now renders full score explanation with:
  - current scores
  - highest/lowest item
  - visible support
  - missing support
  - data limitations
  - real `https://` sources
- Q2 now classifies as `score_query` and extracts `target_entities=["Victory Philippines"]`.
- Q3/Q4/Q10 now render organization template with:
  - `Executive Summary`
  - `Key Findings`
  - `Risks`
  - `Opportunities`
  - `Data Gaps`
  - `Sources`
- Q6 remains multi-entity `media_list` and does not collapse to a single organization.
- Q7 now renders comparison template with:
  - matched entity: `Victory Philippines`
  - unmatched entity: `Every Nation`
  - explicit `Coverage Imbalance`
  - no false claim that `Victory Philippines` also lacks data
- Q8 now renders `missing_entity` guard output and does not bind to random unrelated entities.
- Q9 now routes to research, does not skip retrieval, and returns entity-specific `https://` source output instead of product-level source explanation.

### Metrics

- HTTP/SSE success rate: `100%` (`10/10`)
- Average `OverallScore`: `10.0`
- Required failure count: `0`

## OFF Rollback Validation

Configuration:

- `INSIGHT_ENGINE_ENABLED=true`
- `INSIGHT_FINAL_RENDER_ENABLED=false`

Rollback probe cases:

- `Victory Philippines 的评分是多少？`
- `Victory Philippines 有哪些优势和风险？`
- `对比 Every Nation 和 Victory Philippines`
- `Victory Philippines 的数据来源是什么？`

Observed browser answers under OFF mode:

- Score question falls back to legacy compact score listing, not deterministic renderer.
- Organization question falls back to legacy "数据库中没有优势和风险相关数据" style answer.
- Comparison question falls back to legacy non-template comparison answer.
- Source question falls back to legacy mixed-source narrative answer.

Rollback verdict:

- Deterministic insight final renderer is no longer active when `INSIGHT_FINAL_RENDER_ENABLED=false`.
- Old chain resumes control as expected.

## Residual Notes

- Q5 (`机构画像`) now routes and renders through the organization template as intended for Phase 2.6.
- Its `Key Findings` still reflect broad retrieval scope rather than a profile-only condensation. This does not violate the Phase 2.6 hard gates, but it remains a quality-tuning candidate outside this takeover/routing fix.

## Final Verdict

- `PASS`
