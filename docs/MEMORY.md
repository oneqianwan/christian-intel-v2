# 项目记忆 — Christian Intel (FaithMate)

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
