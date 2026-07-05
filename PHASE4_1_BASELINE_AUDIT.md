# PHASE4_1_BASELINE_AUDIT

## 0. 审计结论摘要

- 审计目标：确认当前工作树未提交改动分别属于哪个已完成阶段，并为 Phase 4.1 建立安全基线
- 审计范围：只读 Git / 只读代码 / 仓库外补丁备份
- 本阶段未执行：
  - `git reset`
  - `git restore`
  - `git checkout <file>`
  - `git stash`
  - `git clean`
  - `git commit`
  - 切换分支
  - 删除未跟踪文件
- 结论：
  - 当前工作树包含大规模 tracked 修改与大量 untracked 新文件
  - `backend/config.py` 与 `backend/models/database.py` 均已存在未提交改动，且正好是 Phase 4.1 需要触达的核心文件
  - 当前工作树中，Phase 2 Insight Engine 的一部分改动可明确识别并应视为已认可基线
  - 同时还存在一批无法仅凭当前上下文完全归因的大型架构改动

---

## 1. Git 状态快照

### 1.1 当前仓库路径

- `C:\Users\baiwan\christian-intel-v2`

### 1.2 当前分支

- `main`

### 1.3 当前 HEAD commit

- `c08a9eae00b8e28db3517c6e1fc59ba4c307b9d9`

### 1.4 staged 状态

- `git diff --cached --name-status` 为空
- 结论：当前无 staged 改动

### 1.5 git diff --stat

```text
backend/agent/actions.py                        |   23 +-
backend/config.py                               |  153 +-
backend/crawlers/arda_collector.py              |    1 +
backend/crawlers/arda_denomination_collector.py |    1 +
backend/crawlers/dynamic_crawler.py             |    1 +
backend/crawlers/infer_website_url.py           |    1 +
backend/crawlers/joshua_project_collector.py    |    1 +
backend/crawlers/pew_research_collector.py      |    1 +
backend/crawlers/website_deep_crawler.py        |    1 +
backend/crawlers/wiki_christian_collector.py    |    1 +
backend/crawlers/wiki_website_extractor.py      |    1 +
backend/daily_run.bat                           |    2 +-
backend/data/preset_keywords.py                 |    4 +
backend/data/rss_global_seed.py                 |   24 +
backend/data/schedule_daily.py                  |    2 +-
backend/data/tag_existing_orgs.py               |   52 +
backend/main.py                                 |   30 +-
backend/models/database.py                      |  887 ++++++-
backend/routers/chat.py                         |  630 ++++-
backend/routers/collection.py                   |  372 +--
backend/routers/dashboard.py                    |  403 ++-
backend/routers/missions.py                     |   24 +-
backend/routers/tasks.py                        |   75 +-
backend/services/__init__.py                    |    5 +-
backend/services/agent.py                       |  339 ++-
backend/services/api_collectors.py              |   49 +-
backend/services/brain.py                       | 3018 ++++++++++++++++++++---
backend/services/delivery.py                    |   43 +-
backend/services/llm_client.py                  |   24 +-
backend/services/mission_runner.py              |  213 ++
backend/services/rss_collector.py               |  311 ++-
backend/test_rss.py                             |    1 +
backend/workers/collector.py                    |   61 +-
docs/MEMORY.md                                  |  219 ++
docs/TODO.md                                    |   53 +-
frontend/package-lock.json                      |  455 ++++
frontend/package.json                           |    2 +
frontend/src/App.tsx                            |   15 +-
frontend/src/components/ChatArea.tsx            |  514 ++--
frontend/src/components/Dashboard.tsx           |  468 +++-
frontend/src/components/TaskPanel.tsx           |   99 +-
frontend/src/main.tsx                           |    5 +-
frontend/src/services/api.ts                    |    7 +
frontend/src/stores/messageStore.ts             |    2 +
44 files changed, 7445 insertions(+), 1148 deletions(-)
```

### 1.6 所有 tracked modified 文件

```text
M backend/agent/actions.py
M backend/config.py
M backend/crawlers/arda_collector.py
M backend/crawlers/arda_denomination_collector.py
M backend/crawlers/dynamic_crawler.py
M backend/crawlers/infer_website_url.py
M backend/crawlers/joshua_project_collector.py
M backend/crawlers/pew_research_collector.py
M backend/crawlers/website_deep_crawler.py
M backend/crawlers/wiki_christian_collector.py
M backend/crawlers/wiki_website_extractor.py
M backend/daily_run.bat
M backend/data/preset_keywords.py
M backend/data/rss_global_seed.py
M backend/data/schedule_daily.py
M backend/data/tag_existing_orgs.py
M backend/main.py
M backend/models/database.py
M backend/routers/chat.py
M backend/routers/collection.py
M backend/routers/dashboard.py
M backend/routers/missions.py
M backend/routers/tasks.py
M backend/services/__init__.py
M backend/services/agent.py
M backend/services/api_collectors.py
M backend/services/brain.py
M backend/services/delivery.py
M backend/services/llm_client.py
M backend/services/mission_runner.py
M backend/services/rss_collector.py
M backend/test_rss.py
M backend/workers/collector.py
M docs/MEMORY.md
M docs/TODO.md
M frontend/package-lock.json
M frontend/package.json
M frontend/src/App.tsx
M frontend/src/components/ChatArea.tsx
M frontend/src/components/Dashboard.tsx
M frontend/src/components/TaskPanel.tsx
M frontend/src/main.tsx
M frontend/src/services/api.ts
M frontend/src/stores/messageStore.ts
```

### 1.7 所有 tracked added / deleted 文件

- `tracked added`: 无
- `tracked deleted`: 无

### 1.8 所有 untracked 文件

```text
.dbg/single-answer-source.env
.dbg/trae-debug-log-single-answer-source.ndjson
PHASE2_6_FINAL_RENDER_UAT.md
V1.0_Architecture_Freeze_Report.md
adaptive_planner_runtime_audit.md
architecture_runtime_audit.md
backend/.tmp_q1_chat_simple.json
backend/.tmp_q2_chat_simple.json
backend/.tmp_q3_chat_simple.json
backend/_tmp_relation_recon.py
backend/agents/__init__.py
backend/agents/analysis_agent.py
backend/agents/base_agent.py
backend/agents/data_agent.py
backend/agents/intent_agent.py
backend/agents/orchestrator.py
backend/agents/report_agent.py
backend/data/developed_markets_graph.json
backend/data/philippines_media_tech_seed.py
backend/data/relation_graph.json
backend/routers/org_detail.py
backend/scripts/build_relation_graph.py
backend/scripts/calculate_digital_scores.py
backend/scripts/calculate_intel_scores.py
backend/scripts/calculate_people_scores.py
backend/scripts/extract_relations_from_news.py
backend/scripts/generate_us_investment_report.py
backend/scripts/migrate_investments_to_edges.py
backend/services/adaptive_planner.py
backend/services/answer_composer.py
backend/services/answer_context_builder.py
backend/services/answer_models.py
backend/services/architecture_governor.py
backend/services/baseline_manager.py
backend/services/benchmark_framework.py
backend/services/benchmark_runner.py
backend/services/capability_planner.py
backend/services/core_models.py
backend/services/default_benchmark_suite.py
backend/services/default_evidence_rules.py
backend/services/default_execution_policies.py
backend/services/default_pipeline_registry.py
backend/services/default_registry.py
backend/services/default_services.py
backend/services/default_task_templates.py
backend/services/default_workflows.py
backend/services/digital_scorer.py
backend/services/e2e_dataset.py
backend/services/e2e_evaluator.py
backend/services/e2e_metrics.py
backend/services/evidence_engine.py
backend/services/evidence_graph.py
backend/services/evidence_models.py
backend/services/evidence_reasoner.py
backend/services/evidence_verifier.py
backend/services/execution_policy.py
backend/services/feature_flags.py
backend/services/insight_answer_renderer.py
backend/services/insight_engine.py
backend/services/insight_models.py
backend/services/intel_scorer.py
backend/services/knowledge_layer.py
backend/services/memory_layer.py
backend/services/mission_service.py
backend/services/people_scorer.py
backend/services/pipeline_orchestrator.py
backend/services/planning_revision.py
backend/services/query_parser.py
backend/services/reasoning_context.py
backend/services/reasoning_engine.py
backend/services/reasoning_engine_v1.py
backend/services/reasoning_graph.py
backend/services/reflection_models.py
backend/services/regression_framework.py
backend/services/regression_runner.py
backend/services/relation_mapper.py
backend/services/repair_executor.py
backend/services/repair_models.py
backend/services/repair_planner.py
backend/services/retrieval_loop_controller.py
backend/services/runtime_dashboard.py
backend/services/runtime_health.py
backend/services/runtime_metrics.py
backend/services/self_reflection.py
backend/services/service_container.py
backend/services/task_graph.py
backend/services/task_planner.py
backend/services/tool_registry.py
backend/services/trace_center.py
backend/services/verification.py
backend/services/welcome_trace.py
backend/services/workflow_engine.py
backend/services/workflow_executor.py
debug-brain-governor-close.md
debug-chat-stream-close.md
debug-governor-stream-wrapper.md
debug-greeting-source.md
debug-knowledge-skip-audit.md
debug-llm-stream-closed.md
debug-llm-stream-finish.md
debug-retrieval-return-stop.md
debug-single-answer-source.md
debug-sqlite-io-e2e.md
debug-streaming-stall.md
debug-welcome-reply-trace.md
debug-workflow-stop-early.md
docs/ARCHITECTURE_AUDIT_2026-07-01.md
docs/INVESTOR_DECK.md
docs/US_CHRISTIAN_TECH_INVESTMENT_REPORT.md
docs/screenshots/01-overview-home.png
docs/screenshots/02-coverage-progress.png
docs/screenshots/03-priority-gaps.png
docs/screenshots/04-brain-chat-philippines-ai-churches.png
docs/screenshots/05-relation-network-overview.png
frontend/phase28_7_network_probe.mjs
frontend/pw_debug.png
frontend/pw_frontend.png
frontend/pw_frontend_after_new.png
frontend/pw_frontend_after_select.png
frontend/src/pages/OrgDetailPage.tsx
frontend/src/pages/PricingPage.tsx
reasoning_engine_v1_review.md
```

---

## 2. 当前数据库规范确认

### 2.1 ORM 模型位置

- 主 ORM 注册文件：`backend/models/database.py`

### 2.2 Base 定义位置

- `backend/models/database.py`
- 当前定义：`Base = declarative_base()`

### 2.3 Session 管理方式

- `backend/models/database.py`
- 当前通过：
  - `engine = create_engine(settings.DATABASE_URL, **_ENGINE_KWARGS)`
  - `_SessionLocalFactory = sessionmaker(..., class_=TrackedSession)`
  - `SessionLocal()`
  - `get_db()` / `get_db_session()`

### 2.4 SQLite 建表或迁移方式

- 当前不是 Alembic
- 当前仓库内未发现 `alembic` 目录，也未发现 `migrations` 目录
- 当前实际机制：
  - `Base.metadata.create_all(bind=engine)`
  - `_ensure_schema_compatibility()`
- 结论：
  - 当前项目使用“ORM 建表 + 启动期 schema compatibility 补丁”模式
  - Phase 4.1 不应引入第二套迁移体系

### 2.5 用户表、机构表真实表名与主键类型

- 用户表：
  - 未发现统一 `users` ORM 表
  - 当前多数用户侧字段采用自由字符串 `user_id`
  - 现有 `UserProfile` 表真实表名为 `user_profiles`，但不是统一鉴权用户主表
- 机构主表：
  - `organization_profiles`
  - 主键类型：`String`
- 通用实体表：
  - `knowledge_entities`
  - 主键类型：`String`

### 2.6 是否使用 Alembic

- 否

---

## 3. 重点文件逐项审计

## 3.1 `backend/config.py`

文件参考：[config.py](file:///C:/Users/baiwan/christian-intel-v2/backend/config.py)

### 当前改动内容

- 从简单 `Settings` 扩展为完整 Feature Flag 注册中心
- 增加：
  - `load_dotenv(BACKEND_DIR / ".env", override=True)`
  - `FEATURE_FLAG_DEFAULTS`
  - `FeatureFlags` 数据模型
  - `Settings.FEATURE_FLAGS`
  - `settings.feature_flag()`
  - `sync_feature_flags_to_env()`
- 当前已存在的重要 flags：
  - `INSIGHT_ENGINE_ENABLED=False`
  - `INSIGHT_FINAL_RENDER_ENABLED=False`
  - 大量架构级 flags，如：
    - `ARCHITECTURE_GOVERNOR_ENABLED`
    - `PIPELINE_ORCHESTRATOR_ENABLED`
    - `SERVICE_CONTAINER_ENABLED`
    - `TRACE_CENTER_ENABLED`
    - `ANSWER_COMPOSER_ENABLED`
    - `REASONING_ENGINE_V1_ENABLED`

### 属于哪个已完成阶段

- 可明确识别：
  - Phase 2 Insight Engine 基线中的一部分
  - 以及更大范围的架构总线 / Feature Flag 体系建设

### 是否是 Phase 2 Insight Engine 的有效改动

- 是，部分有效
- 已认可部分：
  - `INSIGHT_ENGINE_ENABLED`
  - `INSIGHT_FINAL_RENDER_ENABLED`

### 是否存在无法识别的改动

- 是
- 原因：
  - 文件中不只包含 Insight 两个 flags
  - 还引入了完整架构特性开关体系，超出 Phase 2.6 明确验收范围

### Phase 4.1 是否需要继续修改该文件

- 需要，但只能极小改动
- Phase 4.1 需要在这里安全追加：
  - `WATCH_ALERT_V1_ENABLED=false`
- 风险判断：
  - 这是正确的追加位置
  - 但文件当前处于未提交状态，且已是“全局特性开关中心”
  - 继续修改前建议先做基线隔离

### 结论

- `config.py` 是 Phase 4.1 的必要触点之一
- 但它当前不是干净文件
- 只能在独立 worktree 或基线 commit 后继续改

---

## 3.2 `backend/models/database.py`

文件参考：[database.py](file:///C:/Users/baiwan/christian-intel-v2/backend/models/database.py)

### 当前改动内容

- 大量数据库层基础设施增强，重点包括：
  - SQLite `NullPool`
  - `check_same_thread=False`
  - SQLite `timeout=5`
  - 连接与 Session 调试追踪
  - `TrackedSession`
  - SQLite PRAGMA 调试与一次性执行
  - 启动期数据库备份 `_backup_sqlite_db()`
  - 启动期 `_apply_startup_sqlite_pragmas()`
  - `Base.metadata.create_all()`
  - `_ensure_schema_compatibility()` 自动补列与补索引
- 模型面也已扩展出多张非旧版表，如：
  - `FieldChangeHistory`
  - `OrganizationContactHistory`
  - `RequestTrace`
  - `Task`
  - `Watchlist`
  - `FundingRound`
  - `Investment`
  - `RelationEdge`

### 属于哪个已完成阶段

- 可明确识别：
  - 之前已完成的 DB Session / SQLite / NullPool / schema compatibility 修复链
  - 以及多个历史阶段累积的数据模型扩展

### 是否是 Phase 2 Insight Engine 的有效改动

- 否，主体并不属于 Phase 2 Insight Engine
- 该文件主要是数据库基础设施与模型层改动

### 是否存在无法识别的改动

- 存在部分无法仅靠当前上下文精准归因的模型扩展
- 但可明确判断：
  - 主体改动与 Watch / Alert 无直接关系
  - 主体改动以 DB 稳定性、兼容性、观测性、历史模型扩展为主

### 本文件与 DB Session / SQLite / NullPool / schema compatibility 修复关系

- 明确相关
- 可直接确认的关键实现：
  - `NullPool`
  - `check_same_thread=False`
  - SQLite timeout
  - `TrackedSession`
  - `_ensure_schema_compatibility()`
  - 启动时 DB 备份与 PRAGMA

### 是否与 Watch / Alert 无关

- 基本无关
- 仅有已有 `Watchlist` 预留表与 Watch / Alert 概念沾边
- 但当前 Phase 4.1 目标的五张表并不存在于本文件现有结构中

### 能否在不覆盖现有修改的情况下新增模型注册

- 能，但必须采用最小侵入方式
- 推荐方式：
  - 新增 `backend/models/watch_alert.py`
  - 在 `backend/models/database.py` 中只做最小 import / 注册接入
  - 不重写现有 engine / session / compatibility 逻辑
- 风险：
  - 当前文件已处于深度脏状态
  - 直接大改很容易覆盖现有 DB 稳定性修复

### Phase 4.1 是否需要继续修改该文件

- 需要
- 但仅限：
  - 模型注册
  - 若坚持沿用当前 schema compatibility 机制，则只追加与新表相关的最小兼容逻辑

### 结论

- `database.py` 是 Phase 4.1 的必要触点之一
- 也是当前最容易发生冲突的文件
- 在当前工作树上直接继续改，风险高

---

## 3.3 `backend/main.py`

文件参考：[main.py](file:///C:/Users/baiwan/christian-intel-v2/backend/main.py)

### 当前改动内容

- 明确可见改动是新增：
  - `from routers import org_detail`
  - `app.include_router(org_detail.router)`

### 属于哪个已完成阶段

- 更接近机构详情页 / 前后端联动阶段
- 不属于 Phase 2 Insight Engine 的核心修复链

### 是否是 Phase 2 Insight Engine 的有效改动

- 否

### 是否存在无法识别的改动

- 有一定不确定性
- 目前能确认的是 `org_detail` 路由挂载
- 但其来源阶段无法仅凭当前证据精确定位

### Phase 4.1 是否需要继续修改该文件

- 不需要
- Phase 4.1 只做数据底座，不做 API Router

### 结论

- `main.py` 不应纳入 Phase 4.1 触达范围

---

## 3.4 `backend/services/pipeline_orchestrator.py`

文件参考：[pipeline_orchestrator.py](file:///C:/Users/baiwan/christian-intel-v2/backend/services/pipeline_orchestrator.py)

### 当前改动内容

- 该文件当前为 untracked 新文件
- 文件内容远超单一 Insight 接入，包含：
  - `InsightEngine`
  - `InsightAnswerRenderer`
  - `InsightInput / InsightResult`
  - `_build_insight_result()`
  - `_build_final_answer_override()`
  - `_format_insight_context()`
  - stream finalization 对 `insight_result` 的兜底重建
  - `RetrievalSkipped` / `ResearchRetrievalDisabledReason` 等研究链路可观测
  - 同时还包含大量：
    - `AnswerContextBuilder`
    - `CapabilityPlanner`
    - `EvidenceEngine`
    - `MemoryLayer`
    - `TaskGraph`
    - `WorkflowExecutor`
    - `ServiceContainer`

### 属于哪个已完成阶段

- 明确可识别部分：
  - Phase 2.6 中已认可的 `Pipeline Insight 接入`
  - Phase 2.6 `流式 insight_result 兜底构建`
- 其余大范围工作流 / 推理 / 证据引擎接入，不完全属于已明确批准范围

### 是否是 Phase 2 Insight Engine 的有效改动

- 是，部分有效
- 依据：
  - [PHASE2_6_FINAL_RENDER_UAT.md](file:///C:/Users/baiwan/christian-intel-v2/PHASE2_6_FINAL_RENDER_UAT.md) 已明确确认：
    - `ctx.insight_result` 在流式 finalize 路径兜底重建
    - `final_answer_override` 确定性接管

### 是否存在无法识别的改动

- 是
- 文件远超“仅 Insight 接入”的范围
- 无法把整份 untracked 文件全部无条件视为已认可基线

### Phase 4.1 是否需要继续修改该文件

- 不需要

### 结论

- `pipeline_orchestrator.py` 中的 Insight 相关改动可作为基线保留
- 但整文件不能简单判定为“全部已认可”
- Phase 4.1 不得触达

---

## 3.5 `backend/services/insight_engine.py`

文件参考：[insight_engine.py](file:///C:/Users/baiwan/christian-intel-v2/backend/services/insight_engine.py)

### 当前改动内容

- 当前为 untracked 新文件
- 提供独立 Insight Engine
- 明确可见能力：
  - `query_mode` 识别
  - `mismatch_guard`
  - `source_query`
  - 数据缺口构建
  - 评分解释构建
  - 错对象防护
  - source URL 过滤

### 属于哪个已完成阶段

- 属于已完成的 Phase 2 Insight Engine 主体

### 是否是 Phase 2 Insight Engine 的有效改动

- 是

### 是否存在无法识别的改动

- 未见明显无法识别部分
- 与当前 memory / discovery 基线一致

### Phase 4.1 是否需要继续修改该文件

- 不需要

### 结论

- 应视为已认可历史改动
- 不得回滚
- Phase 4.1 不得触达

---

## 3.6 `backend/services/insight_models.py`

文件参考：[insight_models.py](file:///C:/Users/baiwan/christian-intel-v2/backend/services/insight_models.py)

### 当前改动内容

- 当前为 untracked 新文件
- 定义：
  - `InsightInput`
  - `InsightFinding`
  - `InsightRisk`
  - 以及整套 `InsightResult` 结构化模型

### 属于哪个已完成阶段

- 属于已完成的 Phase 2 Insight Models

### 是否是 Phase 2 Insight Engine 的有效改动

- 是

### 是否存在无法识别的改动

- 未见明显无法识别部分

### Phase 4.1 是否需要继续修改该文件

- 不需要

### 结论

- 应视为已认可历史改动
- 不得回滚
- Phase 4.1 不得触达

---

## 3.7 `backend/services/insight_answer_renderer.py`

文件参考：[insight_answer_renderer.py](file:///C:/Users/baiwan/christian-intel-v2/backend/services/insight_answer_renderer.py)

### 当前改动内容

- 当前为 untracked 新文件
- 明确可见：
  - `InsightAnswerRenderer`
  - 支持：
    - `score_query`
    - `organization`
    - `media_list`
    - `comparison`
    - `missing_entity`
    - `source_query`
- 负责确定性最终回答生成

### 属于哪个已完成阶段

- 属于已完成的 Phase 2 Final Renderer

### 是否是 Phase 2 Insight Engine 的有效改动

- 是

### 是否存在无法识别的改动

- 未见明显无法识别部分

### Phase 4.1 是否需要继续修改该文件

- 不需要

### 结论

- 应视为已认可历史改动
- 不得回滚
- Phase 4.1 不得触达

---

## 3.8 `backend/services/brain.py`

文件参考：[brain.py](file:///C:/Users/baiwan/christian-intel-v2/backend/services/brain.py)

### 当前改动内容

- 当前为 tracked 大型修改
- 可直接识别的几类内容：
  - Prompt route 分流：`Assistant Prompt` / `Research Prompt`
  - `_looks_like_entity_source_query()`
  - `entity_source_query -> Research Prompt`
  - `feature_flag_enabled("INSIGHT_ENGINE_ENABLED")`
  - `feature_flag_enabled("INSIGHT_FINAL_RENDER_ENABLED")`
  - `Intent / SelectedPrompt / RetrievalSkipped` 观测输出
  - `service container` 接入
  - `architecture_governor`
  - `pipeline_service`
  - `answer_composer`
  - `reasoning_engine`
  - 大规模系统提示词重写与产品介绍模板

### 属于哪个已完成阶段

- 可明确识别部分：
  - Phase 2.6 中已认可的 `Product Source Router 修复`
  - Q9 来源查询改走 `Research`
  - 与 Insight render 偏好相关的 gating
- 其余大量改动超出 Phase 2.6 已明确确认范围

### 是否是 Phase 2 Insight Engine 的有效改动

- 是，部分有效
- 有效部分包括：
  - 来源查询走 `Research Prompt`
  - Insight flags 配合 pipeline 的入口逻辑

### 是否存在无法识别的改动

- 是，且很多
- 包括但不限于：
  - service container 架构
  - answer composer 接入
  - 大规模产品化 prompt 重写
  - 其他推理/治理链路

### Phase 4.1 是否需要继续修改该文件

- 不需要
- 严格按你的限制，Phase 4.1 不得触达

### 结论

- `brain.py` 中只有部分改动可安全视为已认可基线
- 文件整体不能视为“全部可识别”
- Phase 4.1 不得触达

---

## 4. 已认可基线识别

以下改动可明确视为已认可历史改动，不得回滚：

- `INSIGHT_ENGINE_ENABLED`
- `INSIGHT_FINAL_RENDER_ENABLED`
- `backend/services/insight_models.py`
- `backend/services/insight_engine.py`
- `backend/services/insight_answer_renderer.py`
- `backend/services/pipeline_orchestrator.py` 中与以下事项直接对应的部分：
  - `Pipeline Insight 接入`
  - `Phase 2.6 流式 insight_result 兜底构建`
  - `final_answer_override` 确定性接管
- `backend/services/brain.py` 中与以下事项直接对应的部分：
  - Product Source Router 修复
  - entity-specific source query 走 `Research Prompt`

证据参考：

- [PHASE2_6_FINAL_RENDER_UAT.md](file:///C:/Users/baiwan/christian-intel-v2/PHASE2_6_FINAL_RENDER_UAT.md)

---

## 5. `database.py` 专项判断

### 当前未提交修改具体是什么

- 不是单点模型追加
- 而是一整组数据库基础设施与 schema compatibility 修复

### 是否属于之前的 DB Session、SQLite、NullPool 或 schema compatibility 修复

- 是，明确属于

### 是否与 Watch / Alert 无关

- 主体无关
- 仅已有 `watchlists` 预留表与 Watch / Alert 概念相关

### 能否在不覆盖现有修改的情况下新增模型注册

- 能
- 但前提是：
  - 不重写 engine / session / init_db
  - 不覆盖 `_ensure_schema_compatibility()`
  - 只做最小 import / metadata 注册

### 审计判断

- `database.py` 可作为 Phase 4.1 模型接入点
- 但不能在当前脏工作树里无隔离地继续改

---

## 6. `config.py` 专项判断

### 当前现有 Feature Flags

已确认存在：

- `INSIGHT_ENGINE_ENABLED`
- `INSIGHT_FINAL_RENDER_ENABLED`
- 其他现有 flags：
  - `ARCHITECTURE_GOVERNOR_ENABLED`
  - `PIPELINE_ORCHESTRATOR_ENABLED`
  - `WORKFLOW_ENGINE_ENABLED`
  - `TASK_PLANNER_ENABLED`
  - `ADAPTIVE_PLANNER_ENABLED`
  - `EXECUTION_POLICY_ENABLED`
  - `RUNTIME_METRICS_ENABLED`
  - `EVIDENCE_ENGINE_ENABLED`
  - `EVIDENCE_REASONER_ENABLED`
  - `EVIDENCE_VERIFICATION_ENABLED`
  - `ANSWER_CONTEXT_ENABLED`
  - `STRUCTURED_REASONING_ENABLED`
  - `SELF_REFLECTION_ENABLED`
  - `AUTO_REPAIR_PLANNER_ENABLED`
  - `AUTO_REPAIR_EXECUTION_ENABLED`
  - `REGRESSION_FRAMEWORK_ENABLED`
  - `E2E_EVALUATION_ENABLED`
  - `ANSWER_COMPOSER_ENABLED`
  - `RETRIEVAL_LOOP_ENABLED`
  - `KNOWLEDGE_LAYER_ENABLED`
  - `MEMORY_LAYER_ENABLED`
  - `TRACE_CENTER_ENABLED`
  - `SERVICE_CONTAINER_ENABLED`
  - `TOOL_REGISTRY_ENABLED`
  - `CAPABILITY_PLANNER_ENABLED`
  - `REASONING_ENGINE_V1_ENABLED`
  - `BENCHMARK_FRAMEWORK_ENABLED`

### 能否安全追加 `WATCH_ALERT_V1_ENABLED=false`

- 技术上可以
- 规范上也应该追加在这里
- 但风险上不建议直接在当前脏树继续改

### 审计判断

- `config.py` 是正确追加点
- 但应在基线 commit 或独立 worktree 中追加

---

## 7. 安全备份

### 仓库外完整差异补丁

- 已生成：
  - `C:\Users\baiwan\christian-intel-v2_pre_phase4_backup.patch`

### 备份内容

- 包含：
  - `git diff --cached`
  - `git diff`
- 由于当前无 staged 改动：
  - `git diff --cached` 为空
- 未执行：
  - 自动恢复
  - 自动应用补丁

### 未跟踪文件清单

- 已在本报告 `1.8` 完整列出

---

## 8. Phase 4.1 安全基线判断

### A. 已认可历史改动

- `backend/services/insight_models.py`
- `backend/services/insight_engine.py`
- `backend/services/insight_answer_renderer.py`
- `backend/services/pipeline_orchestrator.py` 中与以下明确相关的部分：
  - `Pipeline Insight 接入`
  - `Phase 2.6 流式 insight_result 兜底构建`
- `backend/services/brain.py` 中与以下明确相关的部分：
  - `Product Source Router 修复`
  - 实体来源查询改走 `Research`
- `backend/config.py` 中的：
  - `INSIGHT_ENGINE_ENABLED`
  - `INSIGHT_FINAL_RENDER_ENABLED`

### B. 与 Phase 4.1 可能冲突的改动

- `backend/config.py`
  - 原因：Phase 4.1 需要追加新 flag，而该文件已是大型未提交重构
- `backend/models/database.py`
  - 原因：Phase 4.1 需要注册新模型，而该文件已存在大量 DB 基础设施与 schema 兼容逻辑改动
- `backend/services/brain.py`
  - 原因：虽然 Phase 4.1 不应触达，但它是当前最大型的核心脏文件之一，任何误触都会高风险
- `backend/services/pipeline_orchestrator.py`
  - 原因：Insight 基线与更大架构改动混杂，不能误触

### C. 无法确认来源的改动

- `backend/main.py` 的 `org_detail` 路由接入
- `backend/services/brain.py` 中超出来源查询修复与 Insight flags gating 的大规模改动
- `backend/services/pipeline_orchestrator.py` 中超出 Insight 接入之外的大量工作流/证据/推理/容器改动
- 大批 untracked 架构文件，如：
  - `architecture_governor.py`
  - `answer_composer.py`
  - `reasoning_engine.py`
  - `workflow_engine.py`
  - `workflow_executor.py`
  - `service_container.py`
  - `default_services.py`
  - 以及整组 benchmark / regression / evidence / planner 相关文件

### D. Phase 4.1 可安全触达的文件

以下是在“建立隔离基线后”可安全触达的文件：

- `backend/models/watch_alert.py`
  - 新增文件，最安全
- Watch / Alert 模型测试文件
  - 新增文件，最安全
- `backend/config.py`
  - 仅允许最小追加 `WATCH_ALERT_V1_ENABLED=false`
- `backend/models/database.py`
  - 仅允许最小模型注册接入
  - 如需 schema compatibility 逻辑，必须只追加，不得重写
- `PHASE4_1_DATA_MODEL_UAT.md`
  - 新增验收报告文件

补充说明：

- 当前仓库不存在既有 Alembic / migrations 体系
- 因此 Phase 4.1 不应凭空创建第二套迁移框架

### E. Phase 4.1 不得触达的文件

- `backend/main.py`
- `backend/services/brain.py`
- `backend/services/pipeline_orchestrator.py`
- `backend/services/insight_engine.py`
- `backend/services/insight_models.py`
- `backend/services/insight_answer_renderer.py`
- 所有 Router
- 所有 Crawler
- 所有 Queue / Scheduler
- 所有 Frontend 文件

---

## 9. 最终判断

- `SAFE_TO_CONTINUE=false`

### 是否可以在当前工作树继续

- 不建议
- 原因：
  - 当前工作树不是局部脏，而是大范围脏
  - Phase 4.1 必须触达的 `config.py` / `database.py` 均已存在未提交改动
  - 当前存在大量无法完全归因的大型架构增量

### 是否需要先做基线 commit

- 需要，强烈建议
- 但本阶段按你的约束未执行 commit

### 是否建议使用独立 git worktree

- 建议，且优先级高于“直接在当前树继续”

### 推荐顺序

1. 先把当前工作树作为基线冻结
2. 生成或保留当前仓库外补丁：已完成
3. 由你决定：
   - 基线 commit
   - 或独立 `git worktree`
4. 在隔离环境中执行 Phase 4.1

### 最终结论

- 当前工作树可用于“基线识别”
- 不适合直接作为 Phase 4.1 开发起点
- 最安全方案是：
  - 保留当前补丁备份
  - 先建立可回退的隔离基线
  - 再开始数据模型与 Feature Flag 开发
