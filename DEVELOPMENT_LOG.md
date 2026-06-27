# 基督教情报系统 v2 — 开发需求执行清单 

## 项目定位 
基督教行业情报操作系统，面向信息决策者、资源连接者、合作操盘者。 

--- 

## 一、已完成的开发需求（Phase 1：基础内核） 

### 1. 基础设施 
- [x] Docker Compose (PostgreSQL 16 + Redis 7) 
- [x] FastAPI后端框架 
- [x] React 18 + TypeScript + Vite前端 
- [x] RQ (Redis Queue) Worker队列 
- [x] SQLAlchemy ORM + Alembic迁移 

### 2. 数据库模型（8张表 + 1张追踪表） 
- [x] conversations — 会话管理 
- [x] messages — 消息持久化 
- [x] knowledge_entities — 结构化知识 
- [x] sources — 采集来源种子 
- [x] pages — 抓取页面记录 
- [x] intelligence_items — 情报条目 
- [x] missions — 采集任务 
- [x] job_runs — 子任务执行记录 
- [x] request_traces — 全链路追踪 

### 3. 核心后端模块 
- [x] Chat Gateway — SSE流式响应 
- [x] Intent Router — 5意图分类（identity/knowledge_lookup/collection_request/collection_status/analysis_request） 
- [x] Knowledge Service — 知识库查询 
- [x] Collection Orchestrator — 采集计划编排 
- [x] Mission Runner — 任务执行调度 
- [x] Worker Engine — RQ后台Worker 
- [x] Delivery Composer — 结构化简报输出 
- [x] LLM Client — DeepSeek API接入 
- [x] Diagnostics API — 按request_id查全链路 
- [x] Scoring Service — 情报质量评分（5维度加权） 
- [x] Health Check — 来源健康度监控 
- [x] URL Analyzer — 社媒链接分析 

### 4. 采集渠道 
- [x] RSS扫描（feedparser） 
- [x] 页面抓取（httpx + BeautifulSoup） 
- [x] 深度抓取（子页面发现） 
- [x] YouTube API采集（google-api-python-client） 
- [x] URL粘贴分析（TikTok/YouTube/通用网页） 
- [x] Telegram Bot接口（预留，未启用采集） 

### 5. 前端模块 
- [x] 左右分栏布局（Sidebar + ChatArea） 
- [x] 会话管理（创建/列表/切换/删除） 
- [x] 流式消息渲染（SSE事件消费） 
- [x] 结构化情报卡片（摘要+来源+下一步） 
- [x] 消息状态隔离（assistant_message_id绑定） 
- [x] URL粘贴自动分析 
- [x] 欢迎引导界面 
- [x] 快捷模板按钮（已移除硬编码，保留框架） 

### 6. 数据覆盖 
- [x] 菲律宾：14来源，1084条情报 
- [x] 美国：9来源，142条情报 
- [x] 动态国家切换（detect_country） 

### 7. LLM约束体系 
- [x] 系统级约束（身份/数据边界/事实推断区分/安全红线） 
- [x] 任务级约束（knowledge_summary/collection_report/compare_analysis/url_analysis） 
- [x] 【事实】/【推断-置信度】标注 
- [x] 来源追溯格式 
- [x] 降级策略（LLM超时→模板） 

### 8. 验收测试 
- [x] 45次自动化测试（93.3%通过率→97.8%） 
- [x] 全功能端到端验收（知识问答/采集/对比/URL分析/健康度） 

--- 

## 二、已完成的开发需求（Phase 2：能力扩展） 

### 1. 多国家支持 
- [x] 菲律宾种子建设（B+C策略+AI辅助） 
- [x] 美国种子建设（6RSS + 4YouTube） 
- [x] 动态国家检测（chat级别） 
- [x] 来源按国家隔离（mission_runner过滤） 

### 2. 情报质量 
- [x] 5维度评分（时效性/影响力/独特性/完整性/行动导向） 
- [x] 基督教相关性过滤 
- [x] 常规内容惩罚（讲道/灵修/直播降分） 
- [x] 无关内容过滤（Taylor Swift等） 
- [x] TOP15高质量情报优先展示 

### 3. 对话采集执行 
- [x] 对话框输入触发采集（原按钮方式保留） 
- [x] 流式进度展示（mission_created/progress/delivery_emitted） 
- [x] 近30天情报返回（而非仅mission后新增） 

### 4. 对比分析 
- [x] 实体提取 
- [x] 双边情报对比 
- [x] 趋势判断（高置信推断） 

--- 

## 三、明确拒绝/后置的需求 

### 1. 关系图谱 
- 状态：⏸️ 后置 
- 原因：数据密度不足（需5国+/5000条+/50机构+） 
- 决策：不预留字段，不开放人工录入入口 
- 自动关系发现条件：覆盖≥5国，情报≥5000条，机构≥50个 

### 2. 浏览器插件 
- 状态：📋 开发计划 
- 原因：独立技术栈，维护成本高 
- 决策：第三阶段评估 

### 3. 语音播报 
- 状态：📋 开发计划 
- 原因：非核心路径 
- 决策：第二阶段末尾或第三阶段 

### 4. 社媒自动化采集（TikTok/FB/IG） 
- 状态：❌ 明确不做 
- 原因：反爬极强，封号风险高 
- 替代方案：URL粘贴分析（已上线） 

### 5. 人工关系录入 
- 状态：❌ 明确不做 
- 原因：数据污染风险 
- 替代方案：LLM动态处理 + 后期自动发现 

--- 

## 四、待办需求（第三阶段触发） 

### 触发条件 
- 覆盖国家 ≥ 5个 
- 情报条目 ≥ 5000条 
- 机构实体 ≥ 50个 

### 1. 商业情报层 
- FaithTech投融资事件采集 
- M&A交易追踪 
- 教会科技市场数据 
- LLM商业分析能力（找收购方/竞争格局/市场评估） 

### 2. 关系图谱 
- 实体消歧 
- 自动关系抽取 
- 跨国家机构关联 
- 图谱可视化 

### 3. 来源扩展 
- 更多国家种子建设 
- 官网子页面持续发现 
- RSSHub部署 

### 4. 定时任务 
- 来源健康度自动巡检（每6小时） 
- 告警日志写入 

### 5. 浏览器插件 
- Chrome Extension评估 
- 体验优化 

--- 

## 五、架构红线（始终遵守） 

- [x] 知识问答与采集严格分离 
- [x] 状态枚举全系统统一 
- [x] 消息绑定assistant_message_id，禁止全局回写 
- [x] 异常必须有错误码+用户说明+诊断字段 
- [x] 禁止人工录入关系图谱 
- [x] 禁止未闭环加复杂能力 
- [x] LLM只充当分析层，不充当采集执行层 
- [x] DeepSeek可替换设计 

--- 

## 六、版本信息 

- 当前版本：v0.2.0 
- 总文件数：60+ 
- 数据库表：9张 
- 后端模块：12个 
- 前端组件：4个核心 
- 覆盖国家：2个（菲律宾/美国） 
- 情报条目：1226条 
- 验收通过率：97.8% 

最后更新：2026-06-26 
