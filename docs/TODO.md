# 待办清单 — Christian Intel

## P0：数据资产（最高优先级）
- [ ] People自动化提取（当前进行中）
  - [x] V3第一阶段完成（PQS/DOC/Gap Workbench）
  - [x] 摸清HTML存储位置（当前：未存HTML原文，pages_crawled仅索引）
  - [x] 从Leadership页面HTML提取People（T1批量已跑通）
  - [x] Validator校验 + 分级入库（入候选表：approved/pending）
  - [x] T1 People批量提取（50家）已完成，等待审核结果
  - [x] 从已有文本字段提取People（about_text/description，T1=100家）
  - [x] 批量回写已approved候选到正式表（T1 People覆盖提升至 55/300）
- [x] pending候选人工审核与回写/驳回（27条已审核完毕，T1 People提升至61/300）
  - [x] 轻量级HTTP抓取验证（T1=50家，LLM提取成功=0，需继续优化）
  - [ ] People覆盖率 10.3% → 30%+
- [x] Week 1 文本字段补齐批处理（about_text → mission/programs/contact/description）
- [ ] About覆盖率 49.0% → 80%
- [ ] Mission覆盖率 31.0% → 70%
- [ ] Contact覆盖率 19.0%/20.7% → 60%
- [ ] Round 2 后续策略调整：补充新文本来源，而不是重复跑已耗尽的 T1 目标池
- [x] 美国T1首轮补源：`wikipedia_url` 从 `0/61` 提升到 `17/61`
- [x] 美国T1二轮补源：处理 Wikimedia `JSONDecodeError` / 限流兜底，`wikipedia_url` 提升到 `42/61`
- [x] 基于新增 `wikipedia_url` 重跑美国 T1 About/Mission 补齐
- [x] 美国 T1 Mission 三轮补齐：从 Wikipedia 全文补 Mission，验证边际已接近上限
- [ ] KnowledgeEntity增强：沉淀 `url/leader/contact_email` 等可反向映射字段
- [ ] 文本清洗规则加固（过滤 parked domain / Access Denied / 年份误识别电话）
- [ ] 若进入下一阶段，再考虑从官网 About/Mission/Beliefs 正文补美国 Mission
- [x] T1 `organization_type` 批量推断（300/300）
- [ ] `organization_type` 二级细分标签体系（Church / Denomination / Ministry / Media 等再细化）

## P1：Brain优化
- [x] brain.py纳入Git版本控制（已纳入升级前基线）
- [ ] brain.py职责拆分（意图识别/参数推断/工具调度/格式化/补采）
- [x] Week 3 Planner复杂分析模式（country_deep / competitor / investment）
- [x] Agent多模块体系搭建（MVP：Intent/Data/Analysis/Report + Orchestrator）
- [ ] 分析类查询改造为真正多Agent执行链（Planner / Research / Ranking / Reporter）
- [ ] 竞争格局分析接入结构化机构库排序，而不是仅依赖情报库命中
- [ ] think_stream 接入 Multi-Agent 流式输出链路

## P2：Dashboard完善
- [x] PQS质量评分
- [x] Gap Workbench在线补录
- [x] 智能推荐
- [x] 产品首页升级（Overview API + Overview 默认首页）
- [ ] 4个评分体系（Profile/People/Digital/Intel）
- [ ] 国家维度统计面板接入前端（country-stats drilldown）
- [ ] Quality Distribution 可视化（分段柱状图）
- [x] 投资人首页截图/演示流整理（Investor deck + 5张截图 + Dashboard 预览验证）
- [x] People 质量包装（Dashboard Overview 改为展示质量而非单纯数量）
- [ ] 将 `docs/INVESTOR_DECK.md` 扩展为正式 pitch deck / 讲解脚本
- [ ] 投资者接触清单与外联脚本

## P3：History Layer
- [x] 机构字段变化记录（FieldChangeHistory + history API）
- [ ] 版本Diff
- [ ] 历史趋势
- [x] 批处理脚本接入 History Layer（People批量提取/字段补齐）
- [x] 深采更新链路接入 History Layer

## P4：Content + Relation Layer
- [ ] Content Layer（新闻/博客/Podcast）
- [x] RSS Step 3：白名单重构（活跃源收缩至 6 个，停用 12 个）
- [x] RSS Step 3：`rss_collector.py` 接入 Christian 去噪规则
- [x] RSS Step 3：RSS 国家归因增强（`country` 从内容提取，未知保留 `None`）
- [x] RSS Step 3：复跑验证通过（净新增 `0`，Christian相关度 `52.0%`，国家归因 `100.0%`）
- [ ] RSS Step 4：精炼 `RNS/TGC` filtered 规则，继续压缩泛社会/政治噪音
- [ ] RSS Step 4：清理数据库内停用且重复的 `RSSSource` 记录，减少 URL 规范化冲突
- [ ] RSS Step 4：评估接入自动化调度，形成每日稳定采集链路
- [ ] Content Layer 下一层：在 RSS 稳定后扩展到 newsletter / blog / podcast
- [x] Relation Layer MVP（基于 Investor / Investment / FundingRound 构建投资关系图谱 + relations API）
- [x] 统一 RelationEdge / Graph schema 设计（投资、合作、并购共用）
- [x] Relation Layer 二期A：Investment -> RelationEdge 迁移 + co_invested 推断
- [x] Relation Layer 二期A：新闻关系抽取脚本落地与首轮验证
- [x] 发达国家基督教科技投资全景图谱（`developed_markets_graph.json`）
- [x] 美国投资网络专题页（`US_CHRISTIAN_TECH_INVESTMENT_REPORT.md`）
- [ ] 美国投资网络可视化（基于发达国家图谱输出）
- [ ] Relation Layer 二期B：提升 Christian 相关新闻命中率，过滤泛财经/政策噪音
- [ ] Relation Layer 二期C：从 IntelligenceItem 抽取合作/并购/联盟关系形成新增边

## P5：基础设施
- [x] 建立 docs/ 防失忆文档系统 + 架构地图生成
- [x] Git仓库清理（核心模块入版本控制 + 升级前基线提交）
- [x] 投资者 Executive Summary 初版（`docs/INVESTOR_DECK.md`）
- [ ] 自动化调度（Scheduler/Worker）
- [ ] Postgres迁移（远期）
- [ ] 将升级前 tag / backup branch 推送到远端（可选双保险）

## 技术债务
- [ ] SQLite方言兼容已修复，但长期需迁移
- [ ] `history_recorder` 在批量事务中需统一传递同一 DB session，避免 SQLite `database is locked`
- [ ] Contact 轻量抓取黑名单扩展（过滤 `sentry-next.wixpress.com` 等监控/埋点邮箱）
- [ ] Contact 来源扩展：`pages_crawled` URL 索引不足，需要更深页面抓取或正文落库
- [ ] Multi-Agent 报告生成增加更强的数值约束，进一步压缩 LLM 自由发挥空间
- [x] Relation Layer 国家字段编码清洗（`KnowledgeEntity.country` 10 条脏值已转英文标准值）
- [ ] Relation Layer 新闻源白名单/黑名单治理（避免 GlobeNewswire / 泛财经标题污染抽取）
- [ ] Wikipedia 批量补源增加 `User-Agent`、异常响应重试与 JSON 解析兜底
- [x] Wikipedia 批量补源增加 `User-Agent`、异常响应重试与 JSON 解析兜底
- [ ] Wikipedia 摘要抽取对 Mission 命中率偏低，需扩展为全文/官网正文提取

## 下一阶段
- [ ] 以现有 Demo 材料启动投资者接触，而不是继续同批深采
- [ ] 巴西/印度/印尼 T1 补源策略重设计：当前无可直接从 T2 升级的现成候选
- [x] 五国并行数据补齐 Week 1 首轮执行（美国/英国/韩国/新加坡/澳大利亚）
- [ ] 美国 People 下一轮：改用官网 leadership/team/staff 页面，而不是继续依赖 Wikipedia
- [ ] 英国 T1 扩容：先重建英国 T2 候选池，再谈升级
- [ ] 韩国 Mission 下一轮：改用官网正文或韩文来源，不再只靠 Wikipedia 摘要
- [ ] 新加坡收口：补齐剩余 1 家 `Archdiocese`
- [ ] 澳大利亚 People 下一轮：补 leadership 页面来源或候选池，而不是只跑 Wikipedia
