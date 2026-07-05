# Christian Intel v2 Architecture Audit

生成时间：2026-07-01

说明：
- 本报告以当前代码为准，不以仓库中的旧文档为准。
- 这是静态架构审计，不是营销材料。
- `响应时间` 一栏若未特别说明，均表示 `未实测`。

## 第一部分 Project Architecture Report

### # Project Overview

#### 1. 项目定位
- 项目是一个面向基督教机构情报查询、组织评分、关系网络、采集任务和投资匹配的情报系统。
- 用户界面同时承担聊天入口、看板入口、机构详情页和采集控制台。
- 当前系统有三个主要使用面：
  - Chat / CIO 对话问答
  - Dashboard / 评分与覆盖率看板
  - Org Detail / 单机构详情与关系网络

#### 2. 技术栈
- 前端：React 19、TypeScript、Vite、React Router、Zustand、Recharts
- 后端：FastAPI、SQLAlchemy、Pydantic v2、httpx
- LLM：DeepSeek Chat Completions
- 数据库：默认 SQLite，本地文件 `backend/cio_intelligence.db`
- 队列：Redis + RQ，主要用于 `missions` / `worker`
- 采集：RSS、NewsAPI、YouTube、Telegram、网页抓取、自定义 crawler

#### 3. 整体架构
- 前端是单页应用，分为聊天壳、看板页、详情页和设置侧栏。
- 后端是单体 FastAPI 应用，没有按 bounded context 做明确拆分。
- 对话大脑同时存在 4 条执行路径：
  - `QueryParser` 规则直答
  - `AgentOrchestrator` 多 Agent 路径
  - `BrainPlanner` 规划执行路径
  - `Brain + TOOLS` 的 LLM Tool Calling 路径
- Agent 自动化体系还并行存在一条独立的 `backend/agent/*` 感知-规划-执行链路。

#### 4. 目录结构（Tree）
```text
christian-intel-v2/
├── backend/
│   ├── main.py
│   ├── config.py
│   ├── models/
│   │   ├── database.py
│   │   └── schemas.py
│   ├── routers/
│   │   ├── chat.py
│   │   ├── dashboard.py
│   │   ├── org_detail.py
│   │   ├── collection.py
│   │   ├── conversations.py
│   │   ├── tasks.py
│   │   ├── search.py
│   │   ├── agent.py
│   │   └── ...
│   ├── services/
│   │   ├── brain.py
│   │   ├── query_parser.py
│   │   ├── brain_planner.py
│   │   ├── llm_client.py
│   │   ├── relation_mapper.py
│   │   └── ...
│   ├── agents/
│   │   ├── orchestrator.py
│   │   ├── intent_agent.py
│   │   ├── data_agent.py
│   │   ├── analysis_agent.py
│   │   └── report_agent.py
│   ├── agent/
│   │   ├── loop.py
│   │   ├── perception.py
│   │   ├── planner.py
│   │   ├── actions.py
│   │   ├── memory.py
│   │   └── safety.py
│   ├── workers/
│   │   └── collector.py
│   └── queue_client.py
├── frontend/
│   ├── src/
│   │   ├── App.tsx
│   │   ├── components/
│   │   │   ├── Layout.tsx
│   │   │   ├── Sidebar.tsx
│   │   │   ├── ChatArea.tsx
│   │   │   ├── Dashboard.tsx
│   │   │   ├── CollectionPanel.tsx
│   │   │   ├── TaskPanel.tsx
│   │   │   └── ...
│   │   ├── pages/
│   │   │   ├── OrgDetailPage.tsx
│   │   │   └── PricingPage.tsx
│   │   └── services/
│   │       ├── api.ts
│   │       └── missionApi.ts
└── docs/
```

#### 5. 前端架构
- 路由：
  - `/dashboard`
  - `/dashboard/org/:orgId`
  - `/pricing`
  - `* -> Layout -> ChatArea`
- `Layout.tsx` 是外层壳：
  - 左侧 `Sidebar`
  - 中间 `ChatArea`
  - 右侧可选 `ApiKeyManager`
- `ChatArea.tsx` 是真正的主交互容器，内部包含：
  - 顶部搜索条
  - 中部消息滚动区
  - 采集面板 `CollectionPanel`
  - 任务面板 `TaskPanel`
  - 底部输入区
- 状态管理使用 Zustand：
  - `conversationStore`
  - `messageStore`

#### 6. 后端架构
- `main.py` 挂载所有路由，是典型单体 FastAPI。
- 路由层直接连服务层和 ORM，没有 service boundary 统一约束。
- 许多业务逻辑散落在：
  - `routers/*`
  - `services/*`
  - `agents/*`
  - `agent/*`
- 部分 router 很厚，例如 `dashboard.py` 已经承担大量读写逻辑。

#### 7. Agent 架构
- 存在两套 Agent 架构：
  - `backend/agents/*`：对话型多 Agent
  - `backend/agent/*`：自动感知型 Agent Loop
- 两套 Agent 的职责、状态、日志和入口都不统一。

#### 8. 数据流
- 典型聊天数据流：
  - 用户输入 -> 前端本地 store -> `/api/chat/stream`
  - 后端写入 `conversations/messages/request_traces`
  - `Brain` 选择规则 / Agent / LLM / Tool Calling
  - 返回 SSE 片段
  - 前端累计流式内容 -> 最终落地一条 assistant message
- 典型采集数据流：
  - UI 触发 `collection/start`
  - 当前实现走内存任务表 `_collection_tasks`
  - NewsAPI / RSS / Webpage 采集后写入 `intelligence_items`
- 典型 mission 流：
  - `/missions` -> Redis RQ -> `workers/collector.py` -> `services.mission_runner`

#### 9. 请求流
- Chat Stream：
  - `ChatArea.handleSend()`
  - `sendChatStream()`
  - `POST /api/chat/stream`
  - `_prepare_chat_request()`
  - `Brain.think_stream()`
  - SSE 回传
- Dashboard：
  - `Dashboard.tsx` 多个 `fetch()`
  - `/api/dashboard/*`
  - ORM 直查
- Org Detail：
  - `OrgDetailPage.tsx`
  - `/api/dashboard/org/{org_id}`
  - `/api/dashboard/org/{org_id}/relations`
  - `/api/dashboard/org/{org_id}/timeline`

#### 10. Prompt 管理
- Prompt 分散，未集中管理。
- 主要分布：
  - `services/brain.py`：主系统提示词 + Tool 定义
  - `services/llm_client.py`：系统约束 + 任务级提示词
  - `agents/*.py`：每个 Agent 独立系统提示词
  - `scripts/*` / `services/*` / `crawlers/*`：大量一次性提取 prompt
- 结论：
  - Prompt 无 registry
  - 无版本号
  - 无测试矩阵
  - 存在重复提示词和风格冲突

#### 11. Memory 机制
- Memory 不是单一机制，而是 5 套并存：
  - `Conversation / Message`：主聊天历史
  - `RequestTrace`：请求过程事件日志
  - `agent.memory.Memory`：`agent_logs` / `agent_tasks`
  - `BaseAgent.context`：进程内最近 6 轮上下文
  - `QueryParser._CONVERSATION_LANG_PREF`：进程内语言偏好字典
- 结论：
  - 记忆分散
  - 部分持久化，部分只在进程内有效
  - 无统一 memory abstraction

#### 12. RAG 机制
- 当前系统没有真正的向量型 RAG。
- 实际检索方式主要是：
  - SQLAlchemy + `ilike`
  - `knowledge_entities` 文本模糊查询
  - `intelligence_items` 标题 / content 模糊搜索
  - `QueryParser` 的规则 SQL
- 因此它更接近：
  - `structured retrieval`
  - `SQL-first retrieval`
  - 而不是 embedding RAG

#### 13. Tool Calling
- `services/brain.py` 中定义了大量 `TOOLS`。
- LLM 可以触发的工具包括：
  - `query_database`
  - `query_intelligence`
  - `query_contacts`
  - `auto_collect`
  - `get_user_profile`
  - `save_user_profile`
  - `query_ontology`
  - `get_ontology_types`
  - `query_investors`
  - `match_investors`
  - `generate_outreach_email`
  - `create_task`
  - `match_acquirers`
  - `match_users`
  - `query_graph`
  - `query_funding_rounds`
  - `query_fused`
  - `get_agent_status`
  - `query_arda_country`
  - `query_organization_profile`

#### 14. MCP
- 代码库中没有项目级 MCP 实现。
- 仓库内没有业务代码使用 MCP 协议。
- 结论：`MCP = 不存在 / 未接入`

#### 15. Authentication
- 当前几乎没有认证层。
- 无 JWT
- 无 Session Auth
- 无 RBAC
- 无管理员鉴权
- `/api/agent/run`、`/api/tasks`、`/api/dashboard/manual-update` 等管理型入口默认可调用
- CORS 还是 `allow_origins=["*"]`

#### 16. Database Schema
- ORM 定义表总数：30 张
- 核心域：
  - 会话与消息：`conversations`, `messages`
  - 知识与机构：`knowledge_entities`, `organization_profiles`
  - 采集来源与情报：`sources`, `rss_sources`, `pages`, `intelligence_items`
  - 评分与质检辅助：`leader_candidates`, `field_change_history`
  - 任务与 Mission：`missions`, `job_runs`, `tasks`, `watchlists`
  - 投资与关系：`investors`, `funding_rounds`, `investments`, `relation_edges`
  - Ontology：`organization_types`, `theological_positions`, `scale_levels`, `ai_maturity_levels`, `collaboration_preferences`, `organization_ontology_tags`
  - 用户侧：`bookmarks`, `user_feedbacks`, `user_profiles`

#### 17. ORM
- ORM 使用 SQLAlchemy Declarative。
- 数据访问模式混合：
  - ORM query
  - 原生 SQL `text()`
  - schema compatibility 时直接 `ALTER TABLE`
- 结论：
  - 有 ORM，但未完全 ORM-first
  - 迁移策略混杂，边界不干净

#### 18. Cache
- 没有明确业务缓存层。
- 没有 Redis cache 读写路径用于查询缓存。
- 前端只有 React/Zustand 内存态。
- Agent 有少量进程内上下文，但不算 cache 层。

#### 19. Queue
- 存在 Redis + RQ 队列，但只覆盖一部分任务流。
- `queue_client.py` / `workers/collector.py` 使用 `collection` 队列。
- 但 `routers/collection.py` 又自己维护 `_collection_tasks` 内存任务表，不走 Redis。
- 结论：队列体系不统一。

#### 20. Logger
- 日志体系碎片化：
  - `logging`
  - `print`
  - `request_traces`
  - `agent_logs`
  - 前端 `console.error`
- 没有统一 trace id 穿透到全部层级。

#### 21. Config
- 核心配置在 `backend/config.py`，使用 Pydantic Settings。
- 但很多关键配置直接 `os.getenv()`，未统一收口。
- 配置来源：
  - `.env`
  - 代码默认值
  - 前端硬编码 API base

#### 22. Deployment
- 当前更接近本地开发型部署，而不是完整生产部署。
- 后端默认 `uvicorn main:app`
- 前端默认 `vite`
- Vercel 仅覆盖前端静态构建
- 后端部署配置未成体系

#### 23. Docker
- 只有 `docker-compose.yml`
- 只定义了：
  - `postgres`
  - `redis`
- 没有 backend Dockerfile
- 没有 frontend Dockerfile
- 没有 app compose service
- 与当前 SQLite 默认路径不一致

#### 24. CI/CD
- 仓库中没有 `.github/workflows`
- 没有看到 CI / test / lint / build pipeline
- 结论：`CI/CD = 缺失`

#### 25. Third-party APIs
- DeepSeek
- NewsAPI
- YouTube Data API
- Telegram Bot API
- Google Custom Search
- ScrapingBee
- Joshua Project API
- 以及多种 RSS / 网页抓取目标站点

#### 26. Environment Variables
- 已确认 / 推断使用的变量：
  - `DATABASE_URL`
  - `DEEPSEEK_API_KEY`
  - `DEEPSEEK_BASE_URL`
  - `DEEPSEEK_MODEL`
  - `REDIS_URL`
  - `NEWSAPI_KEY`
  - `YOUTUBE_API_KEY`
  - `GOOGLE_CSE_API_KEY`
  - `SCRAPINGBEE_API_KEY`
  - `TELEGRAM_BOT_TOKEN`
  - `JOSHUA_PROJECT_API_KEY`
  - `API_BASE`

#### 27. Streaming Architecture
- 真实流式路径是 SSE：
  - FastAPI `StreamingResponse`
  - `text/event-stream`
  - 前端 `ReadableStream` 手动解析
- 后端内部流事件：
  - `start`
  - `thinking`
  - `tool_call`
  - `content`
  - `done`
  - `error`
- 流式逻辑主要在 `chat.py` 和 `brain.py`

#### 28. Error Handling
- 风格不统一：
  - 有些地方抛 `HTTPException`
  - 有些地方捕获后返回 fallback 内容
  - 有些地方仅 `print`
  - 有些地方 silent ignore
- 用户可见层面，Chat 已有一定 graceful fallback
- 系统层面没有统一 error taxonomy

#### 29. Retry 机制
- 采集器部分有 retry / rate limiting / smart retry
- LLM 调用层没有统一 retry wrapper
- SSE / chat 主路径也没有明确幂等重试设计

#### 30. Security
- 认证缺失
- 管理型接口无保护
- CORS 全开放
- API key 管理 UI 目前是“本地草稿模式”，没有真正安全写入后端
- docker-compose 明文密码示例
- 前端存在大量硬编码 `http://localhost:8000`

## 第二部分 Agent Report

### A. 对话型 Multi-Agent（`backend/agents/*`）

#### IntentAgent
- 职责：意图识别、实体抽取、复杂度判断
- 输入：用户自然语言
- 输出：`intent / entities / complexity / required_agents`
- 调用链：`AgentOrchestrator.process()` -> `IntentAgent.recognize()`
- Prompt：`INTENT_SYSTEM_PROMPT`
- LLM 调用：是，失败时回退到 `_heuristic_intent()`
- 依赖模块：`BaseAgent`, `llm_client`
- 失败 Fallback：启发式规则识别

#### DataAgent
- 职责：基于意图执行 SQL / ORM 查询
- 输入：`intent_result`
- 输出：`organizations / relations / intelligence / country_stats`
- 调用链：`AgentOrchestrator.process()` -> `DataAgent.query()`
- Prompt：有 `DATA_SYSTEM_PROMPT`，但实际查询主要靠 ORM，不靠 LLM
- LLM 调用：基本无直接 LLM 调用
- 依赖模块：`OrganizationProfile`, `RelationEdge`, `IntelligenceItem`
- 失败 Fallback：空结果返回

#### AnalysisAgent
- 职责：对 DataAgent 结果做推理性总结
- 输入：`intent_result`, `data_result`
- 输出：Markdown 分析文本
- 调用链：`AgentOrchestrator.process()` 在 `complexity == multi_step` 时调用
- Prompt：`ANALYSIS_SYSTEM_PROMPT`
- LLM 调用：是
- 依赖模块：`BaseAgent`
- 失败 Fallback：`_fallback_analysis()`

#### ReportAgent
- 职责：把 analysis 整理成结构化报告
- 输入：`user_message`, `intent_result`, `data_result`, `analysis`
- 输出：最终报告 Markdown
- 调用链：`AgentOrchestrator.process()` 最后阶段
- Prompt：`REPORT_SYSTEM_PROMPT`
- LLM 调用：是
- 依赖模块：`BaseAgent`
- 失败 Fallback：`_fallback_report()`

#### AgentOrchestrator
- 职责：调度 `Intent -> Data -> Analysis -> Report`
- 输入：用户问题
- 输出：结构化 `response`
- 调用链：`Brain.think()` / `Brain.think_stream()` 的一条可选路径
- Prompt：无自己的系统 prompt，内部依赖各 Agent prompt
- LLM 调用：间接调用
- 依赖模块：上述四个 Agent
- 失败 Fallback：统一返回错误文本

### B. 自动感知型 Agent（`backend/agent/*`）

#### Perception
- 职责：检测情报缺口、API 健康、来源陈旧、用户查询缺口、关键词突增
- 输入：数据库状态、API 配置、时间窗口
- 输出：`PerceptionResult[]`
- 调用链：`AgentLoop.run_cycle()` -> `Perception.run_all()`
- Prompt：无
- LLM 调用：无
- 依赖模块：DB, httpx, `api_config_service`
- 失败 Fallback：局部异常吞掉，继续其他检查

#### Planner
- 职责：把 `PerceptionResult` 变成 `ActionPlan`
- 输入：`PerceptionResult[]`
- 输出：`ActionPlan[]`
- 调用链：`AgentLoop.run_cycle()` -> `Planner.create_plans()`
- Prompt：无
- LLM 调用：无
- 依赖模块：无外部重依赖
- 失败 Fallback：没有显式 fallback

#### SafetyGuard
- 职责：限额、去重、冷却期、防重复通知
- 输入：`ActionPlan[]`
- 输出：过滤后的 `ActionPlan[]`
- 调用链：`AgentLoop.run_cycle()` -> `SafetyGuard.filter_plans()`
- Prompt：无
- LLM 调用：无
- 依赖模块：DB
- 失败 Fallback：前置检查失败直接阻止 Agent 运行

#### ActionExecutor
- 职责：执行自动采集、标记 API 异常、发通知
- 输入：`ActionPlan`
- 输出：执行结果 dict
- 调用链：`AgentLoop.run_cycle()` -> `ActionExecutor.execute()`
- Prompt：无
- LLM 调用：无
- 依赖模块：`Mission`, `Memory`, `Message`
- 失败 Fallback：返回 `failed` / `unknown_action`

#### Memory
- 职责：写入 `agent_logs` 和 `agent_tasks`
- 输入：log / task / result
- 输出：数据库持久化记录
- 调用链：几乎整个自动 Agent 体系
- Prompt：无
- LLM 调用：无
- 依赖模块：DB
- 失败 Fallback：打印错误并 rollback

#### AgentLoop
- 职责：调度 `Perception -> Planner -> Safety -> Executor`
- 输入：`force` 标志
- 输出：任务执行统计
- 调用链：`/api/agent/run` 或 Worker 间接触发
- Prompt：无
- LLM 调用：无
- 依赖模块：`Perception`, `Planner`, `ActionExecutor`, `Memory`, `SafetyGuard`
- 失败 Fallback：返回 `status=error`

### C. 缺失或不存在的 Agent
- `MemoryAgent`：不存在独立类，只有 `agent.memory.Memory`
- `Planner`：存在，但属于 `backend/agent/planner.py`，不是对话型 Agent
- `AnalysisAgent` / `ReportAgent`：存在于 `backend/agents/*`
- `DataAgent` / `IntentAgent`：存在于 `backend/agents/*`
- 结论：命名体系已冲突，`agent` 和 `agents` 两棵树职责重叠但不统一

## 第三部分 Database Report

### 1. 全部表
- `conversations`
- `messages`
- `knowledge_entities`
- `organization_profiles`
- `leader_candidates`
- `field_change_history`
- `organization_contact_history`
- `sources`
- `rss_sources`
- `pages`
- `intelligence_items`
- `api_configs`
- `bookmarks`
- `missions`
- `job_runs`
- `request_traces`
- `organization_types`
- `theological_positions`
- `scale_levels`
- `ai_maturity_levels`
- `collaboration_preferences`
- `organization_ontology_tags`
- `investors`
- `funding_rounds`
- `investments`
- `relation_edges`
- `tasks`
- `watchlists`
- `user_feedbacks`
- `user_profiles`

### 2. 核心实体分组

#### Entity
- `knowledge_entities`
- `organization_profiles`
- `organization_ontology_tags`

#### Score
- `organization_profiles`
  - `people_score`
  - `digital_score`
  - `intel_score`
  - 各自 grade / dimensions / calculated_at

#### Organization
- `organization_profiles`
- `organization_contact_history`
- `field_change_history`

#### People
- `leader_candidates`

#### News
- `sources`
- `rss_sources`
- `pages`
- `intelligence_items`

#### Relationship
- `relation_edges`
- `funding_rounds`
- `investments`
- `investors`

#### Event / Task / Workflow
- `missions`
- `job_runs`
- `tasks`
- `watchlists`
- `request_traces`
- `user_feedbacks`

### 3. 关键字段示意

#### organization_profiles
- 身份：`id`, `name`, `official_name`, `short_name`, `english_name`, `country`
- 档案：`description`, `mission_statement`, `official_website`
- 负责人：`leader_name`, `leader_title`, `leader_bio_url`
- 社交：`facebook_url`, `youtube_url`, `twitter_url`, `telegram_username`
- 评分：`people_score`, `digital_score`, `intel_score`
- 标志：`has_ai_initiative`, `has_online_giving`, `has_mobile_app`, `has_about`, `has_mission`
- 运维：`url_tier`, `priority_tier`, `last_website_crawl`, `last_deep_crawl`, `pages_crawled`

#### intelligence_items
- `id`, `page_id`, `source_id`
- `title`, `content`
- `entity_name`, `entity_type`, `country`, `category`
- `source_url`, `source_name`
- `published_at`, `ingested_at`
- `confidence`, `scope`

#### relation_edges
- `source_id`, `source_type`
- `target_id`, `target_type`
- `relation_type`, `confidence`
- `investment_amount`, `investment_currency`, `investment_round`
- `evidence_url`, `evidence_date`, `evidence_source`, `is_verified`

### 4. 关系
- `leader_candidates.organization_id -> organization_profiles.id`
- `field_change_history.organization_id -> organization_profiles.id`
- `pages.source_id -> sources.id`
- `intelligence_items.page_id -> pages.id`
- `intelligence_items.source_id -> sources.id`
- `bookmarks.intelligence_item_id -> intelligence_items.id`
- `job_runs.mission_id -> missions.id`
- `job_runs.source_id -> sources.id`
- `organization_ontology_tags.organization_id -> organization_profiles.id`
- `funding_rounds.entity_id -> knowledge_entities.id`
- `investments.funding_round_id -> funding_rounds.id`
- `investments.investor_id -> investors.id`
- `tasks.entity_id -> knowledge_entities.id`
- `watchlists.entity_id -> knowledge_entities.id`

### 5. 索引 / 约束
- 显式索引：
  - `field_change_history.organization_id`
  - `field_change_history.created_at`
  - `request_traces.request_id`
  - `relation_edges.source_id`
  - `relation_edges.target_id`
  - `relation_edges.relation_type`
  - `user_feedbacks.session_id`
  - `user_profiles.session_id`
- 唯一约束：
  - `relation_edges(source_id, target_id, relation_type, source_item)`
  - `user_profiles(session_id)`
- 问题：
  - 大量模糊查询字段没有索引，例如 `organization_profiles.name`, `english_name`, `short_name`
  - `intelligence_items.title/content` 是全文模糊查，但没有全文检索方案

## 第四部分 API Report

说明：
- 下表按代码声明列出全部 API。
- `响应时间` 统一标记为 `未实测`。

### Chat / Conversation / Search

| Method | URL | Request | Response | 调用链 | Stream | LLM | SQL | 响应时间 |
|---|---|---|---|---|---|---|---|---|
| POST | `/api/chat/stream` | `ChatRequest{message, conversation_id?}` | SSE event stream | `chat.py -> Brain.think_stream()` | 是 | 可能 | 是 | 未实测 |
| POST | `/api/chat/simple` | `ChatRequest` | `{reply, delivery, conversation_id}` | `chat.py -> think()` | 否 | 可能 | 是 | 未实测 |
| POST | `/api/conversations` | `ConversationCreate{title}` | `ConversationResponse` | router -> ORM | 否 | 否 | 是 | 未实测 |
| GET | `/api/conversations` | 无 | `ConversationResponse[]` | router -> ORM | 否 | 否 | 是 | 未实测 |
| PUT | `/api/conversations/{conversation_id}` | `{title}` | `ConversationResponse` | router -> ORM | 否 | 否 | 是 | 未实测 |
| PUT | `/api/conversations/{conversation_id}/pin` | `{pinned}` | pin 状态对象 | router -> ORM | 否 | 否 | 是 | 未实测 |
| DELETE | `/api/conversations/{conversation_id}` | path | 删除统计 | router -> ORM + trace 清理 | 否 | 否 | 是 | 未实测 |
| GET | `/api/conversations/{id}/messages` | path | `MessageResponse[]` | router -> ORM | 否 | 否 | 是 | 未实测 |
| GET | `/api/search` | `q`, `country?` | `{query,count,results[]}` | router -> `IntelligenceItem + Source` | 否 | 否 | 是 | 未实测 |

### Dashboard / Org Detail

| Method | URL | Request | Response | 调用链 | Stream | LLM | SQL | 响应时间 |
|---|---|---|---|---|---|---|---|---|
| GET | `/api/dashboard/coverage` | query | 覆盖率统计 | dashboard router | 否 | 否 | 是 | 未实测 |
| GET | `/api/dashboard/coverage/tier1` | query | T1 覆盖率 | dashboard router | 否 | 否 | 是 | 未实测 |
| GET | `/api/dashboard/quality-scores` | `limit?` | 质量分列表 | dashboard router | 否 | 否 | 是 | 未实测 |
| GET | `/api/dashboard/top-priority` | query | 优先级机构 | dashboard router | 否 | 否 | 是 | 未实测 |
| GET | `/api/dashboard/tier-distribution` | 无 | Tier 分布 | dashboard router | 否 | 否 | 是 | 未实测 |
| GET | `/api/dashboard/tier1-gaps` | `field`, `limit?` | 缺口列表 | dashboard router | 否 | 否 | 是 | 未实测 |
| POST | `/api/dashboard/manual-update` | `ManualUpdateRequest` | 更新结果 | dashboard router | 否 | 否 | 是 | 未实测 |
| POST | `/api/dashboard/inline-entry` | `InlineEntryRequest` | 写入结果 | dashboard router | 否 | 否 | 是 | 未实测 |
| POST | `/api/dashboard/inline-entry/bulk` | `BulkInlineEntryRequest` | 批量结果 | dashboard router | 否 | 否 | 是 | 未实测 |
| GET | `/api/dashboard/recommend-next` | `field` | 推荐补录项 | dashboard router | 否 | 否 | 是 | 未实测 |
| GET | `/api/dashboard/people-candidates` | `status`, `limit` | 候选人列表 | dashboard router | 否 | 否 | 是 | 未实测 |
| POST | `/api/dashboard/people-candidates/review` | `ApproveCandidateRequest` | 审核结果 | dashboard router | 否 | 否 | 是 | 未实测 |
| POST | `/api/dashboard/quick-people-entry` | `QuickPeopleEntry` | 快速录入结果 | dashboard router | 否 | 否 | 是 | 未实测 |
| GET | `/api/dashboard/overview` | 无 | 看板概览 | dashboard router | 否 | 否 | 是 | 未实测 |
| GET | `/api/dashboard/country-stats` | query | 国家统计 | dashboard router | 否 | 否 | 是 | 未实测 |
| GET | `/api/dashboard/relations/network-overview` | query | 关系网络概览 | dashboard router | 否 | 否 | 是 | 未实测 |
| GET | `/api/dashboard/relations/investor/{investor_id}` | path | 投资人关系 | dashboard router | 否 | 否 | 是 | 未实测 |
| GET | `/api/dashboard/relations/{org_id}` | path | 机构关系 | dashboard router | 否 | 否 | 是 | 未实测 |
| GET | `/api/dashboard/history/summary` | query | 历史汇总 | dashboard router | 否 | 否 | 是 | 未实测 |
| GET | `/api/dashboard/history/{org_id}` | path | 单机构历史 | dashboard router | 否 | 否 | 是 | 未实测 |
| GET | `/api/dashboard/scores` | query | 综合评分汇总 | dashboard router | 否 | 否 | 是 | 未实测 |
| GET | `/api/dashboard/scores/top` | `limit`, `country?` | Top 评分榜 | dashboard router | 否 | 否 | 是 | 未实测 |
| GET | `/api/dashboard/org/{org_id}` | path | 单机构详情 | org_detail router | 否 | 否 | 是 | 未实测 |
| GET | `/api/dashboard/org/{org_id}/relations` | path | 关系明细 | `org_detail -> RelationMapper` | 否 | 否 | 是 | 未实测 |
| GET | `/api/dashboard/org/{org_id}/timeline` | `limit?` | 情报时间线 | org_detail router | 否 | 否 | 是 | 未实测 |

### Collection / Mission / Agent

| Method | URL | Request | Response | 调用链 | Stream | LLM | SQL | 响应时间 |
|---|---|---|---|---|---|---|---|---|
| POST | `/api/collection/start` | `StartCollectionRequest` | `StartCollectionResponse` | router -> 内存任务 -> 后台线程 | 否 | 否 | 部分 | 未实测 |
| GET | `/api/collection/status/{task_id}` | path | `TaskStatusResponse` | router -> 内存任务字典 | 否 | 否 | 否 | 未实测 |
| GET | `/api/collection/recent` | `limit?` | 最近任务 + agent stats | router | 否 | 否 | 部分 | 未实测 |
| GET | `/api/collection/presets` | 无 | 预设关键词 | router -> data file | 否 | 否 | 否 | 未实测 |
| POST | `/api/missions` | query params | mission 对象 | router -> queue / mission runner | 否 | 否 | 是 | 未实测 |
| GET | `/api/missions/{mission_id}` | path | mission 状态 | router | 否 | 否 | 是 | 未实测 |
| POST | `/api/agent/run` | 无 | `AgentTriggerResponse` | router -> `run_agent_cycle()` | 否 | 否 | 是 | 未实测 |
| GET | `/api/agent/status` | 无 | agent 状态 | router -> DB + file | 否 | 否 | 是 | 未实测 |
| GET | `/api/agent/logs` | `limit`, `module?` | `agent_logs` | router -> `Memory` | 否 | 否 | 是 | 未实测 |

### Utility / Content / Ops

| Method | URL | Request | Response | 调用链 | Stream | LLM | SQL | 响应时间 |
|---|---|---|---|---|---|---|---|---|
| POST | `/api/bookmarks` | body | 收藏结果 | router -> ORM | 否 | 否 | 是 | 未实测 |
| GET | `/api/bookmarks` | query | 收藏列表 | router -> ORM | 否 | 否 | 是 | 未实测 |
| DELETE | `/api/bookmarks/{bookmark_id}` | path | 删除结果 | router -> ORM | 否 | 否 | 是 | 未实测 |
| POST | `/api/tasks` | body | 任务创建结果 | router -> ORM | 否 | 否 | 是 | 未实测 |
| GET | `/api/tasks` | `limit?` | 任务列表 | router -> ORM | 否 | 否 | 是 | 未实测 |
| PATCH | `/api/tasks/{task_id}` | body | 更新结果 | router -> ORM | 否 | 否 | 是 | 未实测 |
| DELETE | `/api/tasks/{task_id}` | path | 删除结果 | router -> ORM | 否 | 否 | 是 | 未实测 |
| POST | `/api/feedback` | body | 反馈写入结果 | router -> ORM | 否 | 否 | 是 | 未实测 |
| GET | `/api/feedback/stats` | 无 | 反馈统计 | router -> ORM | 否 | 否 | 是 | 未实测 |
| GET | `/api/export/html` | query | HTML 导出 | router | 否 | 否 | 可能 | 未实测 |
| GET | `/api/export/pdf` | query | PDF 文件 | router | 否 | 否 | 可能 | 未实测 |
| POST | `/api/analyze-url` | `{url}` | URL 分析结果 | router -> scraper + optional LLM | 否 | 是 | 否 | 未实测 |
| GET | `/api/health` | 无 | 健康状态 | router | 否 | 否 | 否 | 未实测 |
| GET | `/api/health/sources` | 无 | 来源健康 | router | 否 | 否 | 是 | 未实测 |
| GET | `/api/health/sources/{source_id}` | path | 单来源健康 | router | 否 | 否 | 是 | 未实测 |
| GET | `/api/configs/keys` | 无 | API key 状态 | router | 否 | 否 | 是 | 未实测 |
| GET | `/api/diagnostics/request/{request_id}` | path | trace 日志 | router -> `RequestTrace` | 否 | 否 | 是 | 未实测 |

## 第五部分 Execution Flow

### 1. Chat 主链路
```text
用户发送消息
↓
ChatArea.handleSend()
↓
sendChatStream()
↓
POST /api/chat/stream
↓
chat._prepare_chat_request()
↓
写入 Conversation / Message / RequestTrace
↓
Brain.think_stream()
```

### 2. Brain 内部分支
```text
Brain.think_stream()
├─ A. QueryParser 命中
│  ↓
│  直接 SQL / ORM
│  ↓
│  token 流式返回
│
├─ B. AgentOrchestrator 命中
│  ↓
│  IntentAgent
│  ↓
│  DataAgent
│  ↓
│  (complexity=multi_step ? AnalysisAgent : skip)
│  ↓
│  ReportAgent 或直接答
│  ↓
│  token 流式返回
│
├─ C. BrainPlanner 命中
│  ↓
│  QueryPlanner / TruthEngine / ExecutiveReporter
│  ↓
│  生成 executive report
│  ↓
│  token 流式返回
│
└─ D. LLM Tool Calling
   ↓
   DeepSeek chat/completions + tools
   ↓
   tool_call
   ↓
   _execute_tool_call()
   ↓
   继续调用 LLM
   ↓
   token 流式返回
```

### 3. Chat 收尾链路
```text
SSE chunk 返回前端
↓
ChatArea.onEvent(content/tool_call/done)
↓
前端累计 streamingContent
↓
done 事件
↓
addMessage(assistant)
↓
后端 _finalize_delivery()
↓
写回 Message / RequestTrace
```

### 4. CollectionPanel 执行流
```text
用户点击开始采集
↓
POST /api/collection/start
↓
_collection_tasks[task_id] 写入内存
↓
BackgroundTasks -> _execute_collection()
↓
NewsAPI / RSS / Webpage
↓
写 intelligence_items
↓
前端轮询 /status/{task_id}
```

### 5. Mission / Worker 执行流
```text
用户 / 系统 创建 Mission
↓
POST /api/missions
↓
enqueue_collection_mission()
↓
Redis RQ queue
↓
workers/collector.py
↓
run_mission()
↓
写 missions / intelligence_items / request traces / notifications
```

### 6. 自动 Agent 执行流
```text
Worker 每完成 N 个任务
↓
run_agent_cycle(force=False)
↓
Perception.run_all()
↓
Planner.create_plans()
↓
SafetyGuard.filter_plans()
↓
ActionExecutor.execute()
↓
Memory.log() / Memory.create_task()
↓
可能创建 Mission / 通知消息
```

## 第六部分 Code Dependency Report

### 1. Chat 调用树
```text
ChatArea.tsx
↓
frontend/src/services/api.ts::sendChatStream()
↓
FastAPI /api/chat/stream
↓
backend/routers/chat.py::_stream_chat_response()
↓
backend/services/brain.py::Brain.think_stream()
├─ QueryParser
├─ AgentOrchestrator
│  ├─ IntentAgent
│  ├─ DataAgent
│  ├─ AnalysisAgent
│  └─ ReportAgent
├─ BrainPlanner / TruthEngine
└─ LLM Tool Calling
   ├─ query_database
   ├─ query_intelligence
   ├─ query_graph
   ├─ query_investors
   ├─ match_investors
   └─ ...
↓
SQLAlchemy / SQL / external APIs
↓
SSE chunk
↓
ChatArea 渲染
```

### 2. Dashboard 调用树
```text
Dashboard.tsx
↓
fetch('/api/dashboard/*')
↓
dashboard.py
↓
OrganizationProfile / LeaderCandidate / FundingRound / Investor / RelationEdge
↓
SQLAlchemy
↓
JSON response
```

### 3. Org Detail 调用树
```text
OrgDetailPage.tsx
├─ GET /api/dashboard/org/{orgId}
├─ GET /api/dashboard/org/{orgId}/relations
└─ GET /api/dashboard/org/{orgId}/timeline
↓
org_detail.py
├─ OrganizationProfile
├─ RelationMapper
└─ IntelligenceItem
↓
SQLAlchemy
↓
JSON response
```

### 4. 自动 Agent 调用树
```text
/api/agent/run
↓
agent.loop.run_agent_cycle()
↓
Perception
↓
Planner
↓
SafetyGuard
↓
ActionExecutor
├─ create Mission
├─ mark api error
└─ notify user
↓
Memory(agent_logs / agent_tasks)
```

## 第七部分 Bug Risk Report

### 1. 重复代码
- 评分查询逻辑重复：
  - `query_parser.py`
  - `data_agent.py`
  - `orchestrator.py`
- 投资关系查询逻辑重复：
  - `query_parser.py`
  - `data_agent.py`
  - `org_detail.py` / `relation_mapper.py`
  - `dashboard.py`
- LLM 调用逻辑重复：
  - `brain.py`
  - `llm_client.py`
  - `auto_extractor.py`
  - `llm_contact_extractor.py`
  - 多个 scripts / crawlers

### 2. 循环依赖风险
- `backend/agent/*` 通过 `sys.path.insert` 和跨层 import 互相耦合，容易形成隐式循环依赖。
- `routers/collection.py` 同时尝试 `backend.services.*` 和 `services.*` 双路径 import，说明 import 边界本身不稳。

### 3. 多入口
- 聊天主脑有：
  - `think()`
  - `Brain.think()`
  - `Brain.think_stream()`
  - `AgentOrchestrator.process()`
  - `QueryParser.parse()`
- 采集主流程有：
  - `/api/collection/start`
  - `/api/missions`
  - 自动 Agent 创建 Mission

### 4. Dead Code / 半成品
- `workers/collector.py` 中 `scan_rss_feed()` / `extract_page()` 仍是 `pass`
- 多个 scripts / services 中有大量 `pass`
- 旧文档、旧架构说明与现状明显漂移

### 5. Unused API / UI 不一致风险
- `ApiKeyManager.tsx` 和 `AgentAlerts.tsx` 使用相对路径 `/api/...`
- 大量其他前端组件硬编码 `http://localhost:8000/api/...`
- 这说明前端 API 接入方式并不统一，环境切换时容易“有的接口通、有的不通”

### 6. Unused Prompt / Prompt 冲突
- 同类职责存在多个系统提示词：
  - `brain.py::SYSTEM_PROMPT`
  - `llm_client.py::SYSTEM_PROMPT`
  - `IntentAgent/AnalysisAgent/ReportAgent` 各自 prompt
- 很多 prompt 风格互相冲突：
  - 一边要求“禁止长报告”
  - 一边 `ReportAgent` 明确生成长报告模板

### 7. 重复 LLM 调用
- 同一查询在不同路径下可能触发多次 LLM：
  - Agent intent 识别
  - analysis
  - report
  - brain tool continuation
  - planner report
- 若入口判断不稳定，成本和延迟都容易膨胀

### 8. 重复 SQL
- 同一机构模糊匹配在多个模块中各写一套 `ilike`
- 同一 relation lookup 在多个模块中重写
- 缺乏 repository 或 query service 统一复用

### 9. 重复 Stream
- 只有一个对外 `/chat/stream`，但 `brain.py` 内部存在多套 token 生成路径
- 同一用户问题不同阶段会经历：
  - parser 直流
  - orchestrator 直流
  - planner 报告流
  - raw LLM 流

### 10. 潜在 Race Condition
- `CollectionPanel` 的 `_collection_tasks` 是进程内字典，只对单进程安全，多 worker / 重启后不安全
- `QueryParser._CONVERSATION_LANG_PREF` 是进程内全局字典，多实例部署会丢语言状态
- 前端聊天虽已加 `useRef` 锁，但后端并无请求幂等层

### 11. Potential Memory Leak / Resource Leak
- `DataAgent` 长持有 `SessionLocal()`，依赖 `__del__` 关闭，不够可靠
- 多个 service/crawler 维护 `httpx.AsyncClient`，未见统一生命周期管理
- `BaseAgent.context` 在进程内累积，虽有截断，但仍是隐式状态

### 12. Potential Infinite Loop / Runaway Flow
- 自动 Agent 与 Worker 互相触发：
  - Worker 完成任务 -> 触发 Agent
  - Agent 创建 Mission -> Worker 执行
- 有 `cooldown` 和 `safety`，但系统仍存在“自动化链条回路”的设计风险

## 第八部分 Architecture Debt Report

说明：
- 下面不是优点总结。
- 下面只列真正的问题。

### P0. `brain.py` 是 God Object
- 文件体量极大，已经变成系统级单点。
- 它同时负责：
  - 对话入口
  - 规则路由
  - planner
  - tool calling
  - LLM 调用
  - stream 协议
  - profile memory
  - graph / investor / ontology / funding 等多域业务
- 结果：
  - 可测试性差
  - 修改风险高
  - 任意一个分支变更都可能影响整条链路

### P0. 系统存在多套并行架构，没有真正收敛
- 对话型 `agents/*`
- 自动感知型 `agent/*`
- `QueryParser`
- `BrainPlanner`
- `Brain + TOOLS`
- 这些不是层次分明的组合，而是并行叠加。
- 这违反了最基本的“单一主路径”原则。

### P0. 执行体系分裂
- `collection.py` 走：
  - 内存任务字典
  - BackgroundTasks
- `missions` 走：
  - Redis / RQ / Worker
- 自动 Agent 又自己创建 `Mission`
- 这意味着系统至少有 3 套任务模型：
  - CollectionTask
  - Mission / JobRun
  - agent_tasks
- 这是非常典型的架构债。

### P0. 认证和授权几乎不存在
- 当前不只是“不完善”，而是几乎没有。
- 对外风险：
  - 任意人可触发 `/api/agent/run`
  - 任意人可调用看板写接口
  - 任意人可删会话、改任务、做 manual update
- 这已经不是未来债务，而是现时风险。

### P1. 代码真实架构与文档架构长期漂移
- 旧文档写的是 `PostgreSQL + Redis + RQ`
- 当前默认配置是 `SQLite`
- docker-compose 还是 `postgres + redis`
- 前端实际大量依赖本地直连 `localhost:8000`
- 这说明“部署口径”和“运行口径”已经分裂

### P1. 前端 API 接入方式不统一
- 一部分用 `API_BASE`
- 一部分用相对路径 `/api`
- 一部分直接硬编码 `http://localhost:8000/api`
- 这会导致：
  - 本地可用，部署即裂
  - Vite proxy 生效范围不一致
  - 反向代理 / Vercel / Docker 环境容易失真

### P1. Migration 体系不干净
- 仓库依赖里有 `alembic`
- 但核心 schema 兼容逻辑在 `init_db()` 里手写 `ALTER TABLE`
- 这说明：
  - migration truth source 不唯一
  - 无法稳定回滚
  - 环境间 schema 一致性难保证

### P1. Prompt 管理完全失控
- Prompt 分散在多文件、多脚本、多角色里。
- 没有：
  - 版本管理
  - 统一注册中心
  - 冲突检测
  - 评估基线
- 对未来最大问题不是“写 prompt 麻烦”，而是：
  - 你无法知道哪个 prompt 正在生效

### P1. RAG 名义存在，实质缺席
- 系统可以回答很多问题，但不是因为有严谨 RAG 层。
- 主要靠：
  - SQL 模糊匹配
  - 规则解析
  - 硬编码补丁
- 一旦问题复杂化、规模扩大、同名实体增多，这种方式扩展性会迅速恶化。

### P1. 日志与可观测性碎片化
- 没有统一 logger strategy
- 没有统一 request correlation
- 没有 metrics
- 没有 tracing
- `request_traces` 只覆盖一部分链路
- `agent_logs` 又是另一套

### P2. 违反单一职责与 Clean Architecture
- `router` 太厚
- `brain.py` 太厚
- `dashboard.py` 太厚
- 查询、业务、展示适配、fallback、stream 协议混杂
- 这直接违背了：
  - SOLID 中的 SRP
  - Clean Architecture 的边界隔离

### P2. DDD 边界不清楚
- `Organization`, `Intelligence`, `Mission`, `Task`, `Relation`, `Investor` 等本该是不同 domain
- 但当前实现被混在同一个 service / router / brain 大杂烩里
- 没有明确 domain service / repository / application service 分层

### P2. CQRS 没落地
- 看板查询和写入操作混在同一个大 router 中
- manual update / review / overview / scores 都在 `dashboard.py`
- 读写路径和模型没有明确区分

### P2. Event Driven 只有半套
- 系统确实有 worker、queue、notification、agent loop
- 但它不是清晰的事件驱动架构，只是“任务完成后顺便触发别的逻辑”
- 缺少：
  - 明确事件模型
  - 事件总线
  - 消费者边界
  - 幂等策略

### P2. 数据访问层复用不足
- 多个模块各自手写模糊查找和 ORM 组装
- 没有统一 query service / repository 层
- 结果：
  - 重复 SQL
  - bug 修一处漏三处

### P2. 无缓存层，规模放大会吃性能
- 当前很多请求直接打 SQLite
- `ilike`、全文模糊、统计查询都无缓存
- 如果数据规模继续扩大，看板和聊天都可能受影响

### P3. Docker / 部署 / CI 仍停留在演示态
- 没有 backend Dockerfile
- 没有 frontend Dockerfile
- 没有正式 compose app stack
- 没有 CI/CD
- 这说明项目更像“高强度本地开发环境”，还不是稳定可迁移工程产品

### P3. MCP 不存在，扩展协议层为空白
- 当前外部能力扩展只有：
  - 直接 HTTP
  - 直接工具函数
  - Redis worker
- 没有统一外部工具协议层，后续可插拔性有限

## 核心结论

这个项目的最大问题不是功能少，而是“功能已经很多，但主干架构没有收敛”。

最关键的三个债务是：
- `brain.py` 过度集中，已经成为系统单点
- 任务 / Agent / 采集存在多套并行执行体系
- 认证、配置、部署口径没有形成工程闭环

如果继续在现状上堆功能，未来最先出问题的不会是模型能力，而是：
- 可维护性
- 线上稳定性
- 环境一致性
- 迭代速度
