# 项目记忆 — Christian Intel (FaithMate)

## Content Layer Step 3：RSS白名单重构 + 去噪规则（2026-06-30）
- 已完成 RSS 白名单重构：`18` 个源收缩为 `6` 个活跃源、`12` 个停用源
- 当前活跃白名单：
- 1. `今日基督教 (Christianity Today)`
- 2. `基督邮报 (Christian Post)`
- 3. `宗教新闻通讯社 (RNS)` `needs_filter`
- 4. `Barna Group`
- 5. `世界福音联盟 (WEA)`
- 6. `福音联盟 (TGC)` `needs_filter`
- 已在 `backend/services/rss_collector.py` 接入 Christian 相关性过滤：
- 1. `CHRISTIAN_KEYWORDS` 正向信号词
- 2. `NON_CHRISTIAN_SIGNALS` 泛社会/政治噪音词
- 3. `is_christian_relevant()` 写入前过滤
- 已在 `backend/services/rss_collector.py` 接入国家归因增强：
- 1. 新增 `COUNTRY_KEYWORDS`
- 2. 新增 `extract_country_from_text()`
- 3. RSS 条目 `country` 改为“命中则写国家，未知则 `None`”，不再硬编码“全球”
- 已修复 RSS URL 规范化时的唯一约束风险：若规范化 URL 与现存 `RSSSource.rss_url` 冲突，则跳过更新，避免 SQLite `UNIQUE constraint failed`
- 复跑验证结果：
- 1. 白名单后活跃源数量：`6`
- 2. 重新采集净新增数量：`0`
- 3. Christian 相关度（最近 50 条样本）：`26/50 = 52.0%`
- 4. 当日国家归因比例：`61/61 = 100.0%`
- 结论：RSS 内容质量已从“必须重做来源白名单”阶段，进入“可继续精炼 filtered 源规则”的阶段；下一步重点应放在 `RNS/TGC` 二次过滤和历史重复源清理，而不是盲目扩源

## Multi-Agent 架构拆分（2026-06-30）
- 已新增 `backend/agents/` 目录，落地 `AgentOrchestrator + IntentAgent + DataAgent + AnalysisAgent + ReportAgent + BaseAgent`
- `services.llm_client.call_llm()` 已升级为双模式兼容：保留旧 `prompt` 用法，同时支持新 Agent 的 `messages` 调用
- `services/brain.py` 已接入 Multi-Agent 前置路径：优先走 orchestrator，失败后自动 fallback 到 legacy Brain 逻辑
- 已修复 Multi-Agent 首轮测试暴露的两个问题：
- 1. IntentAgent 返回中文国家名/非标准关键词导致数据库查询 miss，现已加入标准化归一
- 2. `ai_maturity_score = 0` 被误显示为 `N/A`，导致报告口径偏差，现已修复为保留真实 0 分
- 编译验证：`agents/*.py`、`services/brain.py`、`services/llm_client.py` 全部 `py_compile` 通过
- 功能验证：查询“菲律宾有哪些AI教会？”时，Multi-Agent 能识别 `country_analysis`，成功查到 10 家机构并生成最终报告；`Brain.think()` 也已走通 Multi-Agent 路径

## P4 Relation Layer MVP（2026-06-30）
- 已新增 `backend/scripts/build_relation_graph.py`，从 `Investor / Investment / FundingRound / KnowledgeEntity` 构建投资关系图谱
- 真实 schema 与蓝图草案存在偏差：`FundingRound` 当前使用 `entity_id` 关联 `KnowledgeEntity`，并不存在 `organization_id`
- 图谱构建结果：`16` 条机构-投资方关系、`7` 个有投资的机构/实体、`7` 对共同投资关系、`11` 个投资方节点
- 图谱文件已写入 `backend/data/relation_graph.json`
- 已在 `backend/routers/dashboard.py` 增加 3 个 API：
- 1. `/api/dashboard/relations/network-overview`
- 2. `/api/dashboard/relations/investor/{investor_id}`
- 3. `/api/dashboard/relations/{org_id}`
- API 验证已通过：`network-overview` 返回 `67` 个投资方、`12` 个融资轮次、`16` 条投资边；`investor/23` 可正确返回 Greylock Partners 的投资组合
- 当前 Relation Layer 中枢以 `KnowledgeEntity` 为主，因为如 `Gloo` 等融资实体尚未映射进 `OrganizationProfile`
- 发现一项数据质量问题：部分国家字段存在历史编码脏值，在关系 API 中会显示为乱码，后续需做统一清洗

## Relation Layer 二期A（2026-06-30）
- 已在 `backend/models/database.py` 新增 `RelationEdge` 统一关系表，用于同时容纳投资关系、共同投资关系、新闻关系
- `RelationEdge` 采用 `(source_id, target_id, relation_type, source_item)` 唯一约束，而非仅 `source-target-type`，避免同一投资方对同一实体的多轮投资被错误折叠
- 已新增 `backend/scripts/migrate_investments_to_edges.py` 并执行迁移：
- 1. `16` 条 `invested_in`
- 2. `8` 条 `co_invested`
- 3. 当前 `RelationEdge` 总数 `24`
- 已新增 `backend/scripts/extract_relations_from_news.py` 并执行新闻关系抽取
- Step 1 侦察结果显示：关系关键词命中的 `IntelligenceItem` 共 `19` 条，但混有大量泛财经/政策新闻与 `ARDA_Denomination` 噪音
- 实际抽取时经去噪后待处理新闻 `7` 条，最终新增关系 `0` 条；说明当前新闻样本尚不足以形成可映射的 Christian 关系边
- 已完成 `KnowledgeEntity.country` 清洗：将 `10` 条非 ASCII 国家值统一映射为英文标准值，清洗后剩余非 ASCII 国家值为 `0`

## 投资者 Demo 材料（2026-06-30）
- 已新增 `docs/INVESTOR_DECK.md`，完成 5 分钟投资者 Executive Summary 初版
- 前端 `npm run build` 已通过，`npm run preview -- --host 127.0.0.1 --port 4173` 可正常打开 Dashboard
- 已保存 5 张演示截图到 `docs/screenshots/`：
- 1. `01-overview-home.png`
- 2. `02-coverage-progress.png`
- 3. `03-priority-gaps.png`
- 4. `04-brain-chat-philippines-ai-churches.png`
- 5. `05-relation-network-overview.png`
- 说明：Brain 问答截图通过真实前端交互完成，需先点击 `+ 新会话` 后才会渲染输入框

## 数据资产深度提升 Round 2（2026-06-30）
- 已执行 Round 2 三个补齐动作，并补充 history 记录写入
- Mission Round 2：目标池为 `0`，当前筛选条件下不存在“有 description、无 mission、且无 about_text”的 T1 机构
- About Round 2：目标池为 `0`，当前不存在“有 wikipedia_url 但 description 为空”的 T1 机构
- Contact Round 2：首批 `100` 家中仅 `35` 家能解析出 contact/about/donate URL；本轮实际新增邮箱 `0`，跳过 `29` 家、请求失败 `6` 家
- Round 2 结束后 T1 覆盖率无变化：About `140/300 (46.7%)`、Mission `108/300 (36.0%)`、Contact `60/300 (20.0%)`
- 结论：当前瓶颈已从“脚本未跑”转为“目标池枯竭 + 源页面无有效邮箱/无可补文本”，后续应优先做新来源注入或更强页面内容落库，而不是重复跑同一筛选条件

## 发达国家基督教科技投资全景（2026-06-30）
- 已完成发达国家 T1 情报侦察：共覆盖 `143` 家 T1 机构，发达国家整体 `People` 覆盖 `18.9%`、`Contact` 覆盖 `21.0%`、`AI` 覆盖 `60.8%`
- 美国是核心主战场：`61` 家 T1，`AI` 覆盖 `91.8%`、`Deep` 覆盖 `86.9%`、`Mission` 覆盖 `70.5%`，但 `People` 仅 `27.9%`、`Contact` 仅 `31.1%`
- 美国定向补充 Step 1 结果：当前美国 T1 的 `wikipedia_url` 为 `0/61`，因此 `Wikipedia -> About/Mission` 路径本轮无可执行目标
- 美国定向补充 Step 2 结果：`KnowledgeEntity` 当前主要只有融资 seed 元数据（`data.seed_origin`），无结构化 `leader/email/url` 信号，反向映射 `People/Contact` 命中 `0`
- 已生成 `backend/data/developed_markets_graph.json`
- 图谱统计：
- 1. 覆盖国家 `9`
- 2. 机构节点 `150`
- 3. 投资方节点 `11`
- 4. 投资关系边 `16`
- 投资边全部集中在美国 FaithTech / Christian media 节点：`YouVersion / Life.Church`、`Gloo`、`BibleProject`、`Subsplash`、`Tithe.ly`、`Pushpay`、`RightNow Media`
- 结论：发达国家全景已经可以进入“美国优先”的定向运营，但下一步的核心不是继续跑 Wikipedia，而是先补美国 T1 的 `wikipedia_url` / `KnowledgeEntity` 正文信号

## 美国投资专题页 + wikipedia_url 补源（2026-06-30）
- 已新增 `backend/scripts/generate_us_investment_report.py`，并生成 [US_CHRISTIAN_TECH_INVESTMENT_REPORT.md](file:///c:/Users/baiwan/christian-intel-v2/docs/US_CHRISTIAN_TECH_INVESTMENT_REPORT.md)
- 专题页当前基于 `developed_markets_graph.json` 输出美国投资市场概况、重点案例与投资方 Portfolio
- 报告统计：美国投资方节点 `11`、美国投资关系边 `16`
- `wikipedia_url` 批量补源首次执行全部失败，根因是 Wikimedia API 返回 `403 Please set a user-agent`
- 加入合规 `User-Agent` 后重跑成功：美国 T1 `wikipedia_url` 从 `0/61` 提升至 `17/61 (27.9%)`
- 本轮成功样本包括：`Christianity Today`、`Cru`、`Biola University`、`USCCB`、`Southern Baptist Convention`、`Salvation Army`
- 仍有 `44` 家失败，其中大量为 `JSONDecodeError`，说明后续还需处理 Wikimedia 的限流/异常返回兜底
- 结论：美国 `Wikipedia -> About/Mission` 路径已从“完全封死”变为“可继续扩张”，下一步应直接重跑美国 T1 About/Mission 补齐

## 美国 wikipedia 二轮修复 + About/Mission 重跑（2026-06-30）
- 已对剩余 `44` 家美国 T1 机构执行修复版 `wikipedia_url` 补源：加入名称清洗、`User-Agent`、`0.5s` 限流与 JSON 解析兜底
- 二轮结果：新增 `25` 家，累计 `wikipedia_url` 从 `17/61` 提升到 `42/61 (68.9%)`
- 成功补源的代表机构包括：`Presbyterian Church in America`、`Presbyterian Church (U.S.A.)`、`Orthodox Presbyterian Church`、`Reformed Church in America`、`Pillar of Fire`
- 已基于新增 `wikipedia_url` 重跑美国 T1 `About/Mission` 补齐，并接入 `record_change`
- 重跑结果：待补机构 `14` 家，但净增 `About=0`、`Mission=0`
- 拆分后发现：`4` 家仍缺 `About`，`13` 家仍缺 `Mission`
- 说明当前瓶颈已从“没有 Wikipedia URL”转为“Wikipedia extract 本身不含足够可回写文本，特别是不含明确 Mission Statement”
- 当前美国 T1 终态：
- 1. `wikipedia_url`: `42/61 (68.9%)`
- 2. `About`: `55/61 (90.2%)`
- 3. `Mission`: `43/61 (70.5%)`

## 美国 T1 Mission 最终轮（2026-06-30）
- 已执行美国 T1 Mission 最终轮：对 `13` 家“有 `wikipedia_url` 但 `mission_statement` 仍为空”的机构改用 Wikipedia 全文抽取，而非摘要
- 脚本已接入 `record_change()`，确保 Mission 回写进入 History Layer
- 最终结果：`Mission补充 = 0`，`无使命宣言 = 13`
- 美国 T1 Mission 终态保持 `43/61 (70.5%)`
- 全球 T1 Mission 终态保持 `108/300 (36.0%)`
- 结论：美国这一批机构的 Wikipedia 页面虽可补 `About`/背景文本，但对“明确使命宣言”字段的边际价值已接近耗尽

## Demo 材料终态（2026-06-30）
- 已具备面向投资者的完整 Demo 材料包：
- 1. `docs/INVESTOR_DECK.md`：5 分钟 Executive Summary
- 2. `docs/US_CHRISTIAN_TECH_INVESTMENT_REPORT.md`：美国投资专题报告
- 3. `docs/screenshots/`：Dashboard / Coverage / Priority Gaps / Brain / Relation 5 张截图
- 4. `backend/data/developed_markets_graph.json`：发达国家投资图谱
- 5. `backend/data/relation_graph.json`：关系层投资图谱
- 6. Dashboard + Brain 多步分析 + Relation Layer 已可演示
- 当前判断：产品已达到“可对外讲述价值、可支持投资者 5 分钟理解”的阶段，下一步主任务应从深采转向投资者接触与 Demo 演示

## 数据打磨：三个关键修复（2026-06-30）
- 修复 1：已完成 `organization_type` 批量推断，T1 覆盖从 `0/300` 提升到 `300/300 (100.0%)`
- 本轮 `organization_type` 未触发 LLM，全部由规则命中完成；当前类型分布：
- 1. `Church: 233`
- 2. `Diocese: 16`
- 3. `Mission Agency: 13`
- 4. `Union: 9`
- 5. `Denomination: 7`
- 其余长尾包括 `Cathedral / Association / Other / University / Trust / Seminary / Ministry / Fellowship / Council/Network / Bible Society / Alliance`
- 修复 2：已完成巴西/印度/印尼 T1 侦察
- 1. `Brazil: T1=6, T2=6, Total=12, Deep=5/6`
- 2. `India: T1=40, T2=78, Total=118, Deep=27/40`
- 3. `Indonesia: T1=5, T2=23, Total=57, Deep=5/5`
- 在“`T2 + 有website + 有deep profile`”这一升级口径下，三国当前候选数均为 `0`
- 结论：地理覆盖短板暂时不是“可直接升 T1 的现成候选不够”，而是需要新一轮定向补源或重新定义 T1 升级规则
- 修复 3：已完成 `frontend/src/components/Dashboard.tsx` 的 People 质量包装
- Dashboard Overview 现在不再只强调 `20.3%` 的数量覆盖，而是同时展示：
- 1. `100%` 有 Title
- 2. `74%` 有 Bio URL
- 3. `95%` Top10 置信度
- 前端 `npm run build` 已通过，说明当前 Demo 更适合投资者叙事：People 是“高质量但仍待扩容”，而不是“纯数量不足”

## 五国并行数据补齐：30天路线图 Week 1（2026-06-30）
- 已按顺序执行 5 个国家任务，结果显示：本轮真正拿到确定增量的是新加坡；美国 / 英国 / 韩国 / 澳大利亚主要暴露的是源数据不足或升级口径限制
- 任务 1：美国 People 补齐
- 1. 目标池：`20` 家（美国 T1、无 People、有官网）
- 2. 结果：`People补充 = 0`
- 3. 终态：美国 T1 People `17/61 (27.9%)`
- 4. 结论：Wikipedia 领导人提取与已批准 `LeaderCandidate` 对美国这批对象未产生新增
- 任务 2：英国 T2 -> T1 升级
- 1. 目标池：`0` 家（同时满足 `website + deep profile` 的英国 T2 候选为 0）
- 2. 结果：`升级 = 0`
- 3. 终态：英国 T1 仍为 `22`
- 4. 结论：英国问题不是“升不升”，而是“候选池本身为空”
- 任务 3：韩国 Mission 补齐
- 1. 原始脚本曾误写入 `3` 条“未找到 Mission”的说明文本
- 2. 已立即清理这 `3` 条脏值，并删除对应 `History` 记录
- 3. 真实结果：`Mission补充 = 0`
- 4. 终态：韩国 T1 Mission `1/14 (7.1%)`
- 5. 结论：韩国需要更强的原文来源，而不是继续依赖当前 Wikipedia 摘要链路
- 任务 4：新加坡 About/Mission 补齐
- 1. T1 总数：`4`
- 2. 结果：`About +2`, `Mission +2`
- 3. 当前状态：
-    - `Barker Road Methodist Church`: About=Yes, Mission=Yes
-    - `New Creation Church`: About=Yes, Mission=Yes
-    - `Telok Ayer Chinese Methodist Church`: About=Yes, Mission=Yes
-    - `Archdiocese`: About=No, Mission=No
- 4. 结论：新加坡是本轮 ROI 最高的国家，样本小、补齐路径短、可快速接近完整
- 任务 5：澳大利亚 People 补齐
- 1. 目标池：`7` 家（澳洲 T1 无 People）
- 2. 结果：`People补充 = 0`
- 3. 终态：澳洲 T1 People `2/9 (22.2%)`
- 4. 结论：澳洲当前同样缺高信号来源，Wikipedia 提取未命中可用负责人
- Week 1 总判断：
- 1. 这轮证明“分国家、分字段、分来源”是对的，但不同国家的有效链路差异极大
- 2. 新加坡适合继续做“快速补齐样板”
- 3. 美国 / 澳大利亚的 People 需要更强的人员页面来源
- 4. 韩国 Mission 需要官网正文或更可靠的语言源
- 5. 英国若要扩 T1，需先重建候选池而不是直接升级

## 升级前回退基线（2026-06-30）
- 已建立 Agent 升级前的三重回退基线：Git 基线 + SQLite 物理备份 + 项目 Zip 快照
- Git 基线提交：`e480fc6`（`backup: baseline before agent upgrade`）
- Git 标签：`pre-agent-upgrade-20260630-2005`
- Git 备份分支：`backup/pre-agent-upgrade-20260630-2005`
- 数据库快照：`backups/pre-agent-upgrade-20260630-200319/cio_intelligence.db`
- 项目快照：`backups/pre-agent-upgrade-20260630-200319/project-code-snapshot.zip`
- 当前仓库状态：基线提交后工作区已清空，可作为后续 Agent 升级的安全起点

## 30天计划完成状态（2026-06-30）

### 已完成工作
- Week 1: P0数据资产补齐（Mission +34, Programs +88, Description +6）
- Week 2: Dashboard产品化（Overview首页 + 覆盖率进度条 + Priority Gaps）
- Week 3: Brain多步分析增强（Country Deep / Competitor / Investment 三种模式）
- Week 4: History Layer激活（18条记录）+ pending审核清零

### 当前T1覆盖率
| 字段 | 覆盖 | 目标 | 状态 |
|------|------|------|------|
| Website | 85.0% | 95% | 🟡 |
| Deep Profile | 81.3% | 85% | 🟡 |
| AI Score | 58.3% | — | 🟢 |
| About | 46.7% | 80% | 🔴 |
| Programs | 39.7% | 50% | 🔴 |
| Mission | 36.0% | 70% | 🔴 |
| People | 20.3% | 30% | 🔴 |
| Contact | 20.0% | 60% | 🔴 |

### 已建立的能力
- Dashboard产品首页 ✅
- Brain多步分析 ✅
- History Layer变更追踪 ✅
- People候选审核工作流 ✅
- Profile Quality Score ✅
- Gap Workbench在线补录 ✅

## 项目定位
全球基督教行业情报平台 = Bloomberg + Crunchbase + LinkedIn + Perplexity 融合体

## 当前数据状态（最后更新：2026-06-30）
### T1（300家）
| 字段 | 覆盖数 | 覆盖率 |
|------|--------|--------|
| Website | 255 | 85.0% |
| People | 61 | 20.3% |
| Deep Profile | 244 | 81.3% |
| About | 140 | 46.7% |
| Mission | 108 | 36.0% |
| Email | 60 | 20.0% |
| AI Score | 175 | 58.3% |
| Has Leadership Page | 70 | 23.3% |

### T2/T3状态：待补充

## 上次完成的工作
- V3第一阶段5个工作已完成（PQS/DOC/Gap Workbench/批量补录/智能推荐）
- 3个关键Bug已修复（参数兼容/实体漂移/宏观查询退化）
- Brain回答链路基本稳定（12条测试0条误触发Executive Report）
- 建立 docs/ 防失忆文档系统（MEMORY/DECISIONS/TODO/ARCHITECTURE）
- People提取摸底完成：pages_crawled 仅存页面索引（type+url），未落库存储HTML原文
- T1 People批量提取已完成（50家，入候选表）：通过校验3、自动通过2、待审核1、拒绝1，People覆盖总数=34
- People提取策略调整：从已有文本字段（about_text/description）提取（T1=100家），通过校验37、拒绝2、候选自动通过3、待审核2，全局People覆盖仍为34
- 批量回写已approved候选到正式表：回写23家，T1 People覆盖提升至 55/300（18.3%），全局People覆盖=55
- Week 1 P0字段补齐已执行：基于 `about_text` 批量补齐 Mission/Programs/Contact/Description，Mission +34、Programs +88、Email +3、Phone +23、Description +6
- Week 1 字段清洗已执行：清除 description 脏数据 7 条、phone_public 误识别 9 条、mission_statement 脏数据 7 条；清洗后 About=46.7%、Mission=28.7%、Email=19.0%
- Dashboard 产品化首页已完成：新增 `/api/dashboard/overview` 与 `/api/dashboard/country-stats`，前端升级为 `Overview + Operations` 双 Tab，默认首页展示行业全景与优先缺口
- Week 3 Planner增强已完成：在 `brain_planner.py` 增加 `COUNTRY_DEEP / COMPETITOR / INVESTMENT` 三类复杂分析模板与计划构建器，并在 `brain.py` 的 `think()` 入口新增分析类查询自动路由
- Week 4 History Layer 最小可行版已完成：新增 `FieldChangeHistory` 模型、`history_recorder.py` 服务、`/api/dashboard/history/summary` 与 `/api/dashboard/history/{org_id}` API，当前已记录 18 条变更
- pending People 候选已完成首轮审核：27 条中通过 7 条、拒绝 20 条、`pending` 清零，T1 People 覆盖提升至 61/300（20.3%）
- 30天收尾完成：批处理脚本已接入 History Layer，终盘统计已确认 T1 People=61、Mission=108、Programs=119、History=47
- 30天收尾补齐二轮已完成：Mission 二次提取净增 22 家（T1=108/300, 36.0%），Contact 轻量抓取净增 3 家（清洗后 T1=60/300, 20.0%），History 记录累计提升至 47 条

## 当前正在进行
- 轻量级HTTP抓取验证已完成（T1=50家）：多数无法获取页面，LLM提取成功=0（需进一步优化路径/策略）
- Week 2 Dashboard 产品化：已完成首页结构升级，下一步进入国家维度/质量分布可视化增强
- Week 3 Brain升级：下一步将复杂分析模式从模板驱动升级为真正的多Agent协同执行
- Week 4 History Layer：Dashboard主路径、批处理脚本、深采更新链路均已接入，下一步转向 History 趋势与版本 Diff 展示
- Agent 升级前回退基线已完成：当前可安全进入下一轮 Agent 升级与架构演进
- Brain 多Agent拆分 MVP 已完成：下一步将继续细化为 Research / Ranking / Reporter 等更深层专职链路，并补齐流式输出接入
- P4 Relation Layer MVP 已完成：下一步可进入统一 `RelationEdge` 模型设计，以及新闻关系抽取补图
- Relation Layer 二期A 已完成：下一步应进入新闻源质量治理和更高命中率的关系抽取策略，而不是继续扩大低质量标题匹配
- 投资者 Demo 材料已可交付：下一步可将 `INVESTOR_DECK.md` 扩展为正式 pitch deck 或演示脚本
- Round 2 数据补齐已验证：下一步不应继续重复同批 T1 目标，而应改为扩充新的文本来源和 contact 页面抓取深度
- 发达国家全景图谱已生成：下一步应围绕美国做 `wikipedia_url` 补源、`KnowledgeEntity` 正文增强和美国投资网络专题展示
- 美国投资专题页已生成，且 `wikipedia_url` 已从 `0` 补到 `17`：下一步可直接执行美国 T1 的 About/Mission 二次提取
- 美国 `wikipedia_url` 二轮补源已完成并提升到 `68.9%`：下一步应从 Wikipedia 全文、官网 About 页或 KnowledgeEntity 正文增强继续补 `Mission`
- 最终轮 Mission 已验证边际接近见顶：下一步不应再继续深采同一批美国 T1，而应进入投资者接触、Demo 演示与反馈收集
- 数据打磨关键项已完成三项：下一步可以把“机构类型完整、People质量可讲、美国投资专题已成形”作为对外沟通主叙事
- 五国 Week 1 已完成首轮试跑：下一步应改成“按国家选择最有效的数据源”，而不是用同一套 Wikipedia 策略横推所有国家
- RSS Step 3 已完成：下一步应优先精炼 `RNS/TGC` 的过滤规则、清理停用重复源，并评估是否接入自动调度，而不是直接再次扩大 RSS 源数量

## 技术栈
- Backend: Python/FastAPI/SQLAlchemy/SQLite
- Frontend: React/TypeScript/Tailwind
- Brain: 多工具协同（意图识别→直答→Planner→交付净化）
- Crawler: 结构化深采 + fail-fast

## 关键约束
- 用户不是基督教徒，菲律宾无基督教资源
- 目标是找投资者/收购方，不是SaaS订阅
- 策略：停止横向加功能，纵向做数据
- `brain.py` 是核心编排器，虽已纳入 Git 基线，但仍属于高风险“上帝模块”

## 风险项
1. brain.py职责过重（上帝模块），需拆分
2. 当前回退基线已在本地建立，如需跨设备/远端双保险，仍应补推 tag/backup branch
3. People覆盖率20.3%仍是最大缺口
4. Pages_crawled只存URL索引，不存HTML内容
5. People提取依赖Leadership页面原文HTML，但当前数据层缺少HTML落库/文件化存储机制
6. `about_text` 含 parked domain / Access Denied / 无关页面内容，已导致 Mission/Description/Phone 出现误提取风险
7. 当前复杂分析模式已可识别并执行，但 `query_database` 主要基于情报库而非机构库，竞争/投资分析的结构化排序能力仍有限
8. Contact 轻量抓取仍会命中监控/埋点邮箱（如 `@sentry-next.wixpress.com`），后续需把这类域名纳入黑名单
9. Multi-Agent 目前只接入 `think()` 主入口，`think_stream()` 仍主要沿用 legacy 路径
10. Relation Layer 目前以投资关系为主，合作/并购/联盟关系尚未从 `IntelligenceItem` 中抽取
11. 当前新闻关系抽取命中的 `IntelligenceItem` 噪音较高，需要优先过滤泛财经来源与非 Christian 相关标题
12. `pages_crawled` 中可直接命中的 contact/about/donate URL 仍然偏少，Contact 覆盖提升已接近现有索引数据的上限
13. 美国 T1 虽然数据成熟度高，但 `wikipedia_url` 仍为 `0`，阻断了稳定网络环境下的低成本补文案路径
14. `KnowledgeEntity` 当前更多承担融资种子实体角色，尚未沉淀 People/Contact 可复用字段，限制了反向映射补洞能力
15. Wikimedia API 需要显式 `User-Agent`，否则批量补源会被 `403` 拒绝
16. 美国 T1 的 `wikipedia_url` 已提升到 `27.9%`，但仍有大量长名称宗派机构因异常响应或搜索质量问题未命中
17. 美国 T1 的 `wikipedia_url` 二轮已提升到 `68.9%`，但 Wikipedia 摘要对 `Mission` 字段的提取价值有限，后续需引入全文或官网正文
18. 美国 T1 Mission 最终轮验证后未再提升，说明当前低成本公开文本对该字段的可提取价值已接近上限
19. `organization_type` 虽然已达 100%，但当前是规则推断结果，后续如需高精度行业分类仍应补二级标签体系
20. 五国 Week 1 证明：国家差异远大于字段差异，后续补齐策略必须从“统一脚本”转向“国家定制链路”
