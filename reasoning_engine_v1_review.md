# Christian Intelligence V2 — Reasoning Engine V1 Architecture Review & Refactor

## Current Architecture

```
User
  ↓
backend/routers/chat.py:chat_stream → _stream_chat_response
  ↓
backend/services/brain.py:Brain.think / Brain.think_stream
  ↓
Retriever (existing tools; unchanged)
  ↓
Reasoning Engine V1 (enabled by env var)
  - backend/services/reasoning_engine_v1.py:ReasoningEngineV1
    - classify_question
    - infer_information_requirements
    - plan_tools
    - evaluate_evidence
    - detect_conflicts
    - rank_evidence
    - merge_duplicate_facts
    - build_answer_outline
    - verification
  ↓
LLM
  - brain.py:_call_llm / _call_llm_stream
  ↓
Delivery
  - backend/routers/chat.py:_finalize_delivery
```

## Remaining Logic In Brain

1. Tool-call construction and argument sourcing (entity picking, calling `_build_*_args`, mapping tool_plan → tool_calls) remains in `Brain.think/think_stream`.
2. Runtime gating and fallback orchestration remains in `Brain` (env enable, prefetched tool selection priority, direct-render bypass).
3. Prompt assembly responsibility remains in `Brain` (`_build_messages` + appending one additional system message).

## Review: “Prompt Builder” vs “Decision Layer”

### Current (Before Refactor)

```
ReasoningEngineV1 → format_reasoning_message() → "Reasoning Plan" system prompt text
```

### Target (After Refactor)

```
ReasoningEngineV1 → ReasoningResult (data)
Brain (Prompt Builder) → renders ReasoningResult into one additional system message
```

## Coverage Calculation Flow

```
Requirement.required_fields
  ↓
tool_results (dict) + tool_results[].evidence (Evidence JSON list)
  ↓
for each field:
  - evidence fields: title/url/snippet/source_name/confidence/published_at/updated_at/type
  - payload fields (recursive scan): leader_name, member_count/member_estimate, official_website, country, denomination, name
  ↓
coverage = hits / len(required_fields)
missing_fields = required_fields - hits
minimum_sources check uses distinct evidence.source_name
```

Notes:
- Coverage is field-based (not a heuristic “score”), computed as real hit ratio.
- Field discovery for payload facts is recursive and alias-aware (leader→leader_name, website→official_website/source_url, member_count→member_estimate).

## Conflict Object Completeness

Target structure:

```json
{
  "field": "...",
  "severity": "...",
  "type": "...",
  "values": ["...", "..."],
  "sources": ["...", "..."],
  "evidence": []
}
```

Current status:
- field: Present
- severity: Present (default "medium")
- type: Present (default "field_conflict")
- values: Present
- sources: Present (currently aggregated from all evidence source_name, not per-value)
- evidence: Present but currently empty (no per-field/per-value linkage)

## Evidence Ranking

### Current Ranking

1. Newest timestamp (max(published_at, updated_at))
2. Highest confidence
3. Authoritative source score
4. Duplicate removal (url or title+source+published_at)

### Target Ranking (Requested Direction)

Requirement
  ↓
Evidence Match
  ↓
Authority
  ↓
Confidence
  ↓
Time

This target is not implemented in this refactor to avoid behavior drift; only architecture responsibilities were adjusted.

## Answer Outline

Current:
- Fixed templates per QuestionType (static list of section headings)

Target:
- Per QuestionType planner (dedicated outline builder for Timeline/Organization/Graph/Comparison/Ranking/Investment/Relationship)

Not implemented in this refactor.

## Testability

ReasoningEngineV1 testability:
- Pure deterministic functions (no DB, no tool execution, no LLM calls).
- Inputs are plain python objects (str/dict/list), outputs are dict/list/Enum.

Functions that depend on external state:
- None (source trust mapping is static in constructor).

## Migration Candidates (Brain → Reasoning Engine)

Priority 1:
- Tool-call construction (mapping tool_plan → tool_calls + entity picking), currently in Brain.

Priority 2:
- “Reasoning Plan” system message formatting (still in Brain by design; keep, but could be isolated in a minimal adapter).

Priority 3:
- Prefetch tool selection priority chain (currently Brain `_build_prefetched_tool_calls`), could become a Reasoning strategy layer if allowed.

## Top20 Remaining Problems (Reasoning Gaps)

1. No requirement-to-evidence matching score (ranking ignores what fields are missing).
2. Conflict evidence linkage is missing (conflict has no per-field citations).
3. Conflict severity is not derived (fixed “medium”).
4. Authority score is simplistic substring match on source_name.
5. Evidence ranking uses time first; may be undesirable for “authoritative baseline” questions.
6. Coverage uses recursive key scan; can over-match unrelated nested structures.
7. Tool planning does not plan “query_contacts” for CONTACT unless specific fields match.
8. Tool planning does not explicitly plan “query_graph” for INVESTMENT unless needs_graph=true.
9. No explicit “need_more_retrieval” decision object (only evaluation fields exist).
10. No stop-condition object beyond sufficient/missing fields.
11. merge_duplicate_facts groups by url/title-source-date only; no semantic merging.
12. No per-question-type requirement templates beyond a small set of fields.
13. No per-domain field dictionary (leader/member_count naming variants beyond current aliases).
14. No handling of partial country extraction (country empty).
15. No handling of multiple target entities (single entity pick).
16. No explicit “unknown question” fallback strategy in engine (only UNKNOWN type).
17. No ranking table schema for RANKING type (outline only).
18. No structured answer plan with paragraph→evidence mapping.
19. No verification of “citation_ready” beyond evidence non-empty.
20. No consistency checks across tool_results (only conflict detection by value diversity).

## Refactor Summary (This Change)

- Removed prompt string generation from ReasoningEngineV1.
- Introduced data objects (ReasoningResult/EvidenceEvaluation/Conflict) and pre/post builders.
- Moved “Reasoning Plan” system message formatting into Brain as a prompt adapter.
- Preserved existing integration behavior (enable flag, existing tool executions unchanged).

## Final Architecture

```
ReasoningEngineV1 (data decision layer)
  ↓ produces ReasoningResult (data)
Brain (prompt adapter)
  ↓ appends one system message derived from ReasoningResult
LLM
```

## Review Score

| 项目 | 分数（10分） | 说明 |
|---|---:|---|
| 模块解耦 | 7.5 | Engine 不再拼 prompt 文本；Brain 保留最小适配层 |
| Tool Planning | 6.5 | 可用但较粗粒度；依赖 Brain 进行 tool_call 构造 |
| Evidence Planning | 6.0 | 具备 coverage/ranking/merge 基础，但缺 match-to-requirement |
| Conflict Detection | 5.5 | 能检测多值冲突；缺 evidence 链接与 severity 推导 |
| Coverage | 7.0 | 字段覆盖率真实计算；field_coverage 可直接断言 |
| Ranking | 6.0 | time/confidence/authority 可用；缺 requirement-aware ranking |
| Verification | 5.5 | 有基础 gating；缺更严格的 sufficiency/consistency checks |
| Testability | 8.5 | 纯函数、无外部依赖、易做输入输出断言 |
| Extensibility | 7.0 | 已有 QuestionType/Requirement 框架；planner 仍偏模板 |

Overall Score: 6.6 / 10

企业级差距（仅列现状差距，不引入新依赖/新DB）：
- 缺完整的 requirement→evidence matching / citation plan / conflict evidence linkage
- 缺统一的 stop-conditions 与 multi-step retrieval policy
- 缺领域字段字典与多实体处理策略
