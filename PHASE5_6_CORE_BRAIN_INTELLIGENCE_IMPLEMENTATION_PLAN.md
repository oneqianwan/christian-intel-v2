# Phase 5.6 Core Brain Intelligence Implementation Plan

## Title

Phase 5.6 Core Brain Intelligence Implementation Plan

## 1. Current State Summary

- `backend/services/brain.py` 当前约 `9260` 行，仍是 Brain Intelligence Core 的核心 God Object。
- 当前公开入口包括：
  - `services.brain.think()`
  - `services.brain.Brain.think_stream()`
- `/chat/simple` 已接入 authenticated user ownership 和 message persistence。
- `/chat/stream` 已接入 authenticated user ownership，但 `persist_db/history` 策略与 simple 不完全一致。
- `Database factual lookup` 当前状态为 `READY`。
- `Organization score direct answer` 当前状态为 `PASS`。
- `Victory Philippines` 当前支持直接评分查询，已确认：
  - `people_score=64`
  - `digital_score=28`
  - `intel_score=65`
- `Mission / Agent / Collector / Scorer integration` 当前整体为 `PARTIAL`。
- `LLM fallback control` 当前为 `PARTIAL`。
- `Brain performance observability` 当前为 `PARTIAL`。
- 当前不建议马上拆分 `brain.py`，应优先补齐 contract、测试与 instrumentation，再决定是否拆分结构。

## 2. Phase 5.6 Core Scope Lock

Phase 5.6 Core 只围绕 Brain Intelligence Core 的最小可执行闭环，不继续 CI、环境治理、Admin、普通后台功能。

### A. Score Intent Contract 固化

目标：

- 明确什么问题属于机构评分查询。
- 支持以下评分类问题稳定命中：
  - `Victory Philippines 的评分是多少？`
  - `Victory Philippines people score?`
  - `Victory Philippines digital score?`
  - `Victory Philippines intel score?`
  - `给我 Victory Philippines 的三项评分`
  - `对比 Victory Philippines 和其他机构评分`
- `QueryParser` 必须能稳定识别：
  - `intent=organization_score_lookup` 或等价命名
  - `organization_name`
  - `requested_scores`
  - `response_contract`

计划要求：

- 优先在 `QueryParser` 中固化 score intent 识别规则。
- 将 score query 的实体抽取、字段抽取、响应合同从隐式逻辑提升为显式 contract。
- 若项目实际实现更适合使用结构化 dict 返回，也必须保持 contract 字段稳定。

### B. simple / stream 统一 score factual lookup

目标：

- `/chat/simple` 和 `/chat/stream` 对评分查询必须走同一套 factual lookup。
- 不能出现 `simple` 查库、`stream` 走 planner/LLM 的分叉。
- 不能让 `stream` 因 `persist_db/history` 策略差异影响 score intent 命中。
- `simple` 和 `stream` 的最终事实内容必须一致。
- `stream` 可以分块输出，但最终文本合同必须一致。

计划要求：

- 抽出共用 score factual lookup 路径，供 `think()` 与 `think_stream()` 统一调用。
- 统一 DB hit / DB miss 的 contract 决策，不允许两条入口分别实现。
- 保留 `stream` 的流式外层包装，但事实正文与字段语义必须和 `simple` 对齐。

### C. DB hit no LLM

目标：

当数据库命中机构评分时：

- 直接返回数据库分数。
- 不调用 `_call_llm`。
- 不调用 `_call_llm_stream`。
- 不进入自由发挥 planner。
- 不编造额外机构。
- 不编造置信度。
- 可以使用固定模板解释来源为 database factual lookup。

硬性示例：

- `Victory Philippines` 必须返回：
  - `people_score=64`
  - `digital_score=28`
  - `intel_score=65`

计划要求：

- 将 DB factual hit 设为 score 查询的最高优先级路径。
- 若返回 composite score，必须来自数据库字段或明确写出由三项分数计算而来。
- 在测试中显式断言 DB hit 时 `llm_used=false`。

### D. DB miss no hallucination

目标：

当机构不存在或评分缺失时：

- 明确返回 `not found` 或 `insufficient data`。
- 不编造分数。
- 不编造置信度。
- 不编造机构背景。
- 不建议基于虚假数据的行动。
- 可提示后续可创建 Mission / Collector 补采，但本阶段默认不自动触发补采闭环。

计划要求：

- DB miss contract 必须是显式否定回答，而不是自由扩写。
- 即使 fallback 保留，也必须禁止在 score factual miss 场景下输出虚构数字、虚构 confidence、虚构机构分析。

### E. Brain Path Instrumentation

目标：

为 Brain 增加最小路径观测，记录：

- `request_id`
- `route=simple/stream`
- `intent_detection_ms`
- `db_lookup_ms`
- `scorer_lookup_ms`
- `planner_ms`
- `llm_ms`
- `total_ms`
- `db_hit=true/false`
- `llm_called=true/false`
- `fallback_used=true/false`
- `organization_name`
- `answer_contract=score_lookup/not_found/llm_fallback`

注意事项：

- 不记录 password、session token。
- 不记录敏感 API key。
- 不输出过量日志。
- 目标是帮助定位用户感知的“大脑回复慢”。
- 本阶段不建设完整 observability 平台，只做最小 instrumentation。

### F. 最小测试套件

必须新增或更新测试覆盖：

- `QueryParser score intent`
- `/chat/simple score DB hit`
- `/chat/stream score DB hit`
- `simple / stream score contract 一致`
- `DB hit 不调用 LLM`
- `DB miss 不编造分数`
- `DB miss 不编造置信度`
- `unknown organization 返回 not found`
- `instrumentation 记录 db_hit / llm_called / total_ms`
- 现有 Chat ownership 测试不受影响

## 3. Non-Goals

Phase 5.6 Core 不做：

- 大规模拆分 `brain.py`
- 重构全部 planner
- 重写 `AgentOrchestrator`
- 重写 Mission 系统
- 完整 CI/CD
- 新 Admin 页面
- 新权限系统
- 多租户
- MCP 接入
- crawler 大重构
- 复杂缓存层
- 完整 observability 平台
- 前端大改版
- Brain 性能全面优化

## 4. Suggested Phase Breakdown

### Phase 5.6A: Score Intent Contract + QueryParser 测试

输出：

- 评分查询意图定义
- `Victory Philippines` score query parser tests
- 不改 `simple/stream` 主逻辑，或只做最小必要调整

核心目标：

- 先把 score lookup 的 contract 明确化、可测试化。
- 把“机构名 + 评分字段 + response contract”变成稳定输入输出。

### Phase 5.6B: simple / stream 统一 score factual lookup

输出：

- `simple` 与 `stream` 共用 score factual lookup
- DB hit 返回固定评分合同
- `DB hit no LLM` tests
- `simple / stream same contract` tests

核心目标：

- 抹平 `think()` 与 `think_stream()` 在 score factual path 上的行为分叉。
- 保证 DB hit 时两条入口都不进入 LLM。

### Phase 5.6C: DB miss no hallucination

输出：

- `unknown organization not found`
- `no fabricated scores`
- `no fabricated confidence`
- `no irrelevant organization`
- anti-hallucination tests

核心目标：

- 将 DB miss 从“模糊 fallback”收紧为“明确 not found / insufficient data”。
- 保护系统不在评分场景下编造事实。

### Phase 5.6D: Brain Path Instrumentation

输出：

- `intent / db / scorer / planner / llm / total` latency spans
- `request_id` 贯通
- `llm_called / db_hit` 标记
- latency tests
- 不做完整监控平台

核心目标：

- 能回答“慢在哪里”。
- 能静态或测试性证明 DB hit 时是否真的绕开 LLM。

### Phase 5.6E: 浏览器 UAT + Final Audit

输出：

- 用户在浏览器询问 `Victory Philippines` 评分
- `simple / stream` 行为确认
- DB hit 直接返回
- unknown organization 不编造
- 大脑耗时可观察
- 最终审计报告

核心目标：

- 将合同、实现、测试、浏览器行为闭环。

## 5. Score Lookup Response Contract Draft

### DB Hit Contract

DB hit 响应必须包含：

- `organization_name`
- `people_score`
- `digital_score`
- `intel_score`
- `data_source=database`
- `llm_used=false`
- 简短解释

建议字段语义：

- `organization_name`: 机构标准名称
- `people_score`: 数据库中的 People Score
- `digital_score`: 数据库中的 Digital Score
- `intel_score`: 数据库中的 Intel Score
- `composite_score`: 如存在则明确来源为数据库字段或三项求和
- `data_source`: 固定为 `database`
- `llm_used`: 固定为 `false`
- `answer_contract`: 固定为 `score_lookup`

示例：

```text
Victory Philippines 的数据库评分如下：

People Score: 64
Digital Score: 28
Intel Score: 65

数据来源：本地 intelligence database。
本次回答未调用 LLM 生成评分。
```

### DB Miss Contract

DB miss 响应必须包含：

- `organization_name`
- `status=not_found` 或 `insufficient_data`
- `llm_used=false`
- 不包含任何数字评分
- 不包含置信度
- 不包含虚构建议

建议字段语义：

- `organization_name`: 用户请求的机构名
- `status`: `not_found` 或 `insufficient_data`
- `data_source`: `database`
- `llm_used`: `false`
- `answer_contract`: `not_found`

示例：

```text
未在当前数据库中找到 "X Organization" 的评分数据。
因此我不能给出 people_score / digital_score / intel_score。
可创建情报采集任务补充数据。
```

## 6. Required Test Files

计划新增以下测试文件：

- `backend/tests/test_query_parser_score_query.py`
- `backend/tests/test_chat_score_query_simple.py`
- `backend/tests/test_chat_score_query_stream.py`
- `backend/tests/test_no_llm_on_db_hit.py`
- `backend/tests/test_no_hallucinated_score_on_db_miss.py`
- `backend/tests/test_stream_simple_same_contract.py`
- `backend/tests/test_brain_latency_spans.py`

说明：

- 如果实施时发现项目结构更适合合并测试文件，可以合并，但必须在实施说明中明确合并原因。
- 无论是否合并，上述测试主题都必须被覆盖，不能省略。

## 7. Required Regression Commands

### 新增 Phase 5.6 Core 测试

- `cd backend && python -m pytest -q tests/test_query_parser_score_query.py`
- `cd backend && python -m pytest -q tests/test_chat_score_query_simple.py`
- `cd backend && python -m pytest -q tests/test_chat_score_query_stream.py`
- `cd backend && python -m pytest -q tests/test_no_llm_on_db_hit.py`
- `cd backend && python -m pytest -q tests/test_no_hallucinated_score_on_db_miss.py`
- `cd backend && python -m pytest -q tests/test_stream_simple_same_contract.py`
- `cd backend && python -m pytest -q tests/test_brain_latency_spans.py`

### 现有 Chat Ownership 回归

- `cd backend && python -m pytest -q tests/test_chat_user_ownership.py tests/test_chat_stream_ownership.py tests/test_chat_owner_migration.py`

### Auth / RBAC 基线按需回归

- `cd backend && python scripts/verify_admin_rbac.py`
- `cd backend && python scripts/verify_admin_user_management.py`
- `cd backend && python scripts/verify_high_risk_admin_protection.py`

### 前端回归触发条件

- 前端如未改，可不跑。
- 若实施阶段改动 `ChatArea` 或 API contract，则必须运行：
  - `cd frontend && npm run check:chat-user-auth`
  - `cd frontend && npm run test:chat-user-auth`
  - `cd frontend && npm run build`

## 8. Risk Control

- 不直接大拆 `brain.py`。
- 不把 LLM 完全禁用，只在 DB factual hit 的评分场景下禁止 LLM 参与事实生成。
- 不影响普通开放问答。
- 不影响 authenticated Chat ownership。
- 不影响 Admin / RBAC。
- 不影响 Watch / Alert。
- 不影响已有 conversation persistence。
- `stream` 可以保持流式输出，但 score factual result 的事实合同必须和 `simple` 一致。
- 所有改动必须有测试保护。

## 9. Final Recommendation

- RecommendedNextStep=Phase 5.6A score intent contract and tests
- READY_FOR_PHASE5_6A=true
- READY_FOR_CODE_CHANGES=false until user approves
