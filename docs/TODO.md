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
- [ ] 文本清洗规则加固（过滤 parked domain / Access Denied / 年份误识别电话）

## P1：Brain优化
- [ ] brain.py纳入Git版本控制
- [ ] brain.py职责拆分（意图识别/参数推断/工具调度/格式化/补采）
- [x] Week 3 Planner复杂分析模式（country_deep / competitor / investment）
- [ ] Agent多模块体系搭建
- [ ] 分析类查询改造为真正多Agent执行链（Planner / Research / Ranking / Reporter）
- [ ] 竞争格局分析接入结构化机构库排序，而不是仅依赖情报库命中

## P2：Dashboard完善
- [x] PQS质量评分
- [x] Gap Workbench在线补录
- [x] 智能推荐
- [x] 产品首页升级（Overview API + Overview 默认首页）
- [ ] 4个评分体系（Profile/People/Digital/Intel）
- [ ] 国家维度统计面板接入前端（country-stats drilldown）
- [ ] Quality Distribution 可视化（分段柱状图）
- [ ] 投资人首页截图/演示流整理

## P3：History Layer
- [x] 机构字段变化记录（FieldChangeHistory + history API）
- [ ] 版本Diff
- [ ] 历史趋势
- [x] 批处理脚本接入 History Layer（People批量提取/字段补齐）
- [x] 深采更新链路接入 History Layer

## P4：Content + Relation Layer
- [ ] Content Layer（新闻/博客/Podcast）
- [ ] Relation Layer（合作/资金/会议）

## P5：基础设施
- [x] 建立 docs/ 防失忆文档系统 + 架构地图生成
- [ ] Git仓库清理（核心模块入版本控制）
- [ ] 自动化调度（Scheduler/Worker）
- [ ] Postgres迁移（远期）

## 技术债务
- [ ] brain.py未入Git
- [ ] Git仓库dirty状态清理
- [ ] SQLite方言兼容已修复，但长期需迁移
- [ ] `history_recorder` 在批量事务中需统一传递同一 DB session，避免 SQLite `database is locked`
- [ ] Contact 轻量抓取黑名单扩展（过滤 `sentry-next.wixpress.com` 等监控/埋点邮箱）
