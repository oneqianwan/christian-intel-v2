# PHASE4_3A_WATCH_RUN_UAT

## 1. 执行上下文

- Worktree 路径：`C:\Users\baiwan\christian-intel-v2-phase4`
- 分支：`phase4/watch-alert-v1`
- Phase 4.2 提交：`e9aa871`
- 当前基线：`feat: add watchlist api`

## 2. 实际修改文件

### 修改文件

- `backend/routers/watch_targets.py`
- `backend/schemas/watch_alert.py`

### 新增文件

- `backend/services/watch_runner.py`
- `backend/services/watch_snapshot_builder.py`
- `backend/services/watch_change_detector.py`
- `backend/services/signal_service.py`
- `backend/tests/test_watch_runner.py`
- `backend/tests/test_watch_signals_api.py`
- `PHASE4_3A_WATCH_RUN_UAT.md`

### 未修改但复用的关键文件

- `backend/config.py`
- `backend/models/database.py`
- `backend/models/watch_alert.py`
- `backend/services/watch_target_service.py`

## 3. 本阶段 API 结果

### 3.1 手动运行监控

- 方法：`POST /api/watch-targets/{id}/run`
- Feature Flag：受 `WATCH_ALERT_V1_ENABLED` 守卫
- 身份边界：复用 `get_current_user_id()`，仅按当前用户查询目标
- 所有权校验：非本人目标返回 `404 WATCH_TARGET_NOT_FOUND`
- 禁用目标：`status=disabled` 返回 `409 WATCH_TARGET_DISABLED`
- 并发保护：同一目标已存在 `running` 状态返回 `409 WATCH_RUN_ALREADY_RUNNING`
- 实体缺失：创建失败 `WatchRun`，返回 `404 WATCH_TARGET_ENTITY_NOT_FOUND`
- 未知异常：写入失败态 `WatchRun` 后返回 `WATCH_RUN_FAILED`
- `frequency=manual`：允许手动运行

成功返回示例：

```json
{
  "run_id": "uuid",
  "watch_target_id": "uuid",
  "status": "success",
  "items_found": 0,
  "signals_created": 0,
  "started_at": "2026-07-05T00:00:00",
  "finished_at": "2026-07-05T00:00:01"
}
```

### 3.2 查询 Signals

- 方法：`GET /api/watch-targets/{id}/signals`
- 查询参数：
  - `signal_type`
  - `severity`
  - `page`
  - `page_size`
- 默认排序：`detected_at DESC, created_at DESC`
- 分页约束：`page >= 1`，`1 <= page_size <= 100`
- 所有权边界：只能读取当前用户拥有的 `WatchTarget`
- 返回隔离：不会泄漏其他用户信号数据

## 4. Snapshot 最终结构

Snapshot 保存在最近一次成功 `WatchRun.metadata_json` 中，不新增独立 Snapshot 表。

最终结构：

```json
{
  "snapshot_version": 1,
  "entity_id": "victory-philippines",
  "entity_type": "organization",
  "captured_at": "2026-07-05T00:00:00.000000",
  "fields": {
    "name": "Victory Philippines",
    "leader_name": "Steve Murrell",
    "official_website": "https://victory.org.ph/mission",
    "email": null,
    "phone": null,
    "people_score": 64,
    "digital_score": 28,
    "intel_score": 65,
    "composite_score": 157
  },
  "intelligence_ids": [],
  "news_urls": [],
  "video_urls": [],
  "relation_keys": [],
  "run_summary": {
    "items_found": 0,
    "signals_created": 0,
    "baseline_created": true
  }
}
```

规范化结果：

- 字段顺序稳定：`fields` 固定为 `name -> leader_name -> official_website -> email -> phone -> people_score -> digital_score -> intel_score -> composite_score`
- 空字符串归一为 `null`
- URL 去空格、转小写 scheme/host、去掉尾部无意义 `/`
- 数字统一为 `int/float/null`
- 列表统一去重并排序
- 不保存 ORM 对象
- 不保存 Prompt、Token、内部堆栈

## 5. 数据读取来源

V1 仅读取现有数据库，不触发大型 Crawler，不调用 LLM。

读取来源：

- `organization_profiles`
  - 读取名称、领导人、官网、邮箱、电话、评分字段
- `knowledge_entities`
  - 作为 `organization` 回退存在性校验
  - 作为 `knowledge_entity` 主体来源
- `intelligence_items`
  - 按实体名称匹配，提取 `intelligence_ids`、`news_urls`、`video_urls`
- `relation_edges`
  - 为目标实体生成稳定的 `relation_keys`

实体解析策略：

- `entity_type=organization`
  - 先查 `OrganizationProfile.id`
  - 同时查 `KnowledgeEntity.id` 且 `entity_type='organization'`
  - 两者都不存在时视为实体缺失
- `entity_type=knowledge_entity`
  - 直接查 `KnowledgeEntity.id`

## 6. Change Detection 规则

首次运行：

- 无历史成功 Snapshot 时仅保存 baseline
- 不把当前全部数据视为变化
- `signals_created=0`

后续仅检测以下变化：

- `leadership_change`
  - 比较 `leader_name`
  - 仅当旧值与新值不同且不同时为空时生成
- `contact_change`
  - 比较 `email`、`phone`、`official_website`
  - 每个字段独立生成一条 Signal
- `score_change`
  - 比较 `people_score`、`digital_score`、`intel_score`
  - 基础分数变更时逐字段生成 Signal
  - `composite_score` 仅在三项基础分数都未变化时才补充检测，避免重复信号
- `new_intelligence`
  - 当前 Snapshot 出现新的 intelligence ID
  - 已排除新闻和视频类条目，避免与 `new_news/new_video` 重复
- `new_news`
  - 当前 Snapshot 出现新的新闻 URL
- `new_video`
  - 当前 Snapshot 出现新的视频 URL
- `relation_change`
  - 当前 Snapshot 出现新的 `relation_key`
- `website_change`
  - 仅在前后 Snapshot 同时存在可靠 `website_hash` 且值不同才生成
  - 当前 V1 Snapshot 未写入 `website_hash`，因此默认跳过，不制造假信号

## 7. Signal 规则

每条 Signal 均包含：

- `watch_target_id`
- `entity_id`
- `signal_type`
- `title`
- `summary`
- `severity`
- `evidence_id`
- `source_url`
- `old_value_json`
- `new_value_json`
- `detected_at`
- `dedup_key`
- `metadata_json`

严重级别：

- `leadership_change = high`
- `score_change`
  - 下降：`high`
  - 上升或空值参与比较：`medium`
- `contact_change = medium`
- `relation_change = medium`
- `new_news = low`
- `new_video = low`
- `new_intelligence = low`
- `website_change = medium`

`source_url` 规则：

- 若变化本身携带真实 `http/https` URL，则直接使用该 URL
- 否则回退为当前 Snapshot 中的 `official_website`
- 若两者都不是有效 `http/https`，则保存为 `null`

`old_value_json/new_value_json` 结构：

```json
{
  "value": 10,
  "field": "people_score"
}
```

## 8. Signal dedup_key 规则

确定性生成规则：

- 字段变化类：
  - `watch_target_id|signal_type|field_name|normalized_new_value`
- 集合新增类：
  - `watch_target_id|signal_type|source_url_or_item_id`

当前实现映射：

- `leadership_change` / `contact_change` / `score_change` / `relation_change` / `website_change`
  - `watch_target_id|signal_type|field_name|normalized_new_value`
- `new_intelligence`
  - `watch_target_id|new_intelligence|intelligence_id`
- `new_news`
  - `watch_target_id|new_news|news_url`
- `new_video`
  - `watch_target_id|new_video|video_url`

冲突处理：

- 依赖数据库唯一约束去重
- 唯一约束冲突视为重复 Signal
- 不导致整次 WatchRun 失败
- 不重复计入 `signals_created`

## 9. WatchRun 状态流转

运行开始：

- 创建 `WatchRun`
- `status=running`
- 写入 `started_at`

成功结束：

- `status=success`
- 写入 `finished_at`
- 写入 `items_found`
- 写入 `signals_created`
- `alerts_created=0`
- `metadata_json=当前 snapshot + run_summary`

失败结束：

- `status=failed`
- 写入 `finished_at`
- 写入 `error_code`
- 写入 `error_message`

同步更新 `WatchTarget`：

- 成功：
  - `last_checked_at=finished_at`
  - `last_success_at=finished_at`
  - `consecutive_failures=0`
- 失败：
  - `last_checked_at=finished_at`
  - `last_error_at=finished_at`
  - `consecutive_failures += 1`

事务与一致性结果：

- 失败不会遗留 `running` 状态
- `WatchRun` 失败态和 `WatchTarget` 时间字段会被落库
- Signal 去重不会把整次运行打成失败
- 未改动 Database Engine / Session / NullPool / PRAGMA

## 10. 30 项测试结果

- 1 Feature Flag 关闭时 run 返回 503：`PASS`
- 2 未登录返回 401：`PASS`
- 3 不能运行其他用户的 Watch Target：`PASS`
- 4 disabled 目标不能运行：`PASS`
- 5 首次运行成功创建 baseline：`PASS`
- 6 首次运行 `signals_created=0`：`PASS`
- 7 第二次数据无变化，不生成 Signal：`PASS`
- 8 `leader_name` 变化生成 `leadership_change`：`PASS`
- 9 `email` 变化生成 `contact_change`：`PASS`
- 10 `official_website` 变化生成 `contact_change`：`PASS`
- 11 `people_score` 下降生成 `high score_change`：`PASS`
- 12 `digital_score` 上升生成 `medium score_change`：`PASS`
- 13 新 `intelligence` 生成 `new_intelligence`：`PASS`
- 14 新 `news URL` 生成 `new_news`：`PASS`
- 15 新 `video URL` 生成 `new_video`：`PASS`
- 16 新 `relation key` 生成 `relation_change`：`PASS`
- 17 相同变化不会重复生成 Signal：`PASS`
- 18 同一目标已有 `running` 时返回 409：`PASS`
- 19 实体不存在时 `WatchRun=failed`：`PASS`
- 20 失败后不遗留 `running` 状态：`PASS`
- 21 成功后 `WatchTarget` 时间与失败计数正确：`PASS`
- 22 失败后 `consecutive_failures` 增加：`PASS`
- 23 Signals API 只返回当前用户数据：`PASS`
- 24 `signal_type` 筛选正确：`PASS`
- 25 `severity` 筛选正确：`PASS`
- 26 Signals 分页正确：`PASS`
- 27 `source_url` 为空或真实 `http/https` URL：`PASS`
- 28 Signal `old/new JSON` 正确：`PASS`
- 29 删除 Watch Target 不影响历史 Signal：`PASS`
- 30 现有 Watchlist API、Insight、Chat、Database 回归通过：`PASS`

补充覆盖：

- `frequency=manual` 的 Watch Target 可手动运行：`PASS`

测试命令：

```powershell
python -m pytest backend/tests/test_watch_runner.py -v
python -m pytest backend/tests/test_watch_signals_api.py -v
python -m pytest backend/tests/test_watch_targets_api.py -v
python -m pytest backend/tests/test_watch_alert_models.py -v
```

结果：

- `backend/tests/test_watch_runner.py`: `27 passed`
- `backend/tests/test_watch_signals_api.py`: `4 passed`
- `backend/tests/test_watch_targets_api.py`: `25 passed`
- `backend/tests/test_watch_alert_models.py`: `19 passed`

## 11. 回归结果

额外 import smoke：

```powershell
python -c "import sys, importlib; sys.path.insert(0, r'C:\Users\baiwan\christian-intel-v2-phase4\backend'); mods=['config','models.database','routers.chat','services.insight_models','services.insight_engine','services.pipeline_orchestrator']; [importlib.import_module(m) for m in mods]; print('IMPORT_SMOKE_OK')"
```

结果：

- `IMPORT_SMOKE_OK`

结论：

- `config` 导入正常
- `models.database` 导入正常
- `routers.chat` 导入正常
- `services.insight_models` 导入正常
- `services.insight_engine` 导入正常
- `services.pipeline_orchestrator` 导入正常
- Watchlist API 回归正常
- Watch / Alert 数据模型回归正常

## 12. Git 边界检查

执行：

```powershell
git status --short
git diff --stat
git diff --name-only
```

结果：

- `git status --short`

```text
 M backend/routers/watch_targets.py
 M backend/schemas/watch_alert.py
?? backend/services/signal_service.py
?? backend/services/watch_change_detector.py
?? backend/services/watch_runner.py
?? backend/services/watch_snapshot_builder.py
?? backend/tests/test_watch_runner.py
?? backend/tests/test_watch_signals_api.py
```

- `git diff --stat`

```text
 backend/routers/watch_targets.py | 72 ++++++++++++++++++++++++++++++++++++++++
 backend/schemas/watch_alert.py   | 48 +++++++++++++++++++++++++++
 2 files changed, 120 insertions(+)
```

- `git diff --name-only`

```text
backend/routers/watch_targets.py
backend/schemas/watch_alert.py
```

边界判断：

- 未出现 `brain.py`
- 未出现 `pipeline_orchestrator.py`
- 未出现 `insight_*`
- 未出现 `frontend/*`
- 未出现 `crawler/*`
- 未出现 `workflow_executor.py`
- 未出现 `answer_composer.py`
- 当前 tracked 修改与 untracked 新增均落在 Phase 4.3A 允许范围内
- 未发现 `__pycache__`
- 未发现测试残留 `.db`
- 未发现 `.pytest_cache`

## 13. 回滚方法

本阶段尚未提交，可直接回滚工作树改动：

- 删除新增文件：
  - `backend/services/watch_runner.py`
  - `backend/services/watch_snapshot_builder.py`
  - `backend/services/watch_change_detector.py`
  - `backend/services/signal_service.py`
  - `backend/tests/test_watch_runner.py`
  - `backend/tests/test_watch_signals_api.py`
  - `PHASE4_3A_WATCH_RUN_UAT.md`
- 撤销修改文件：
  - `backend/routers/watch_targets.py`
  - `backend/schemas/watch_alert.py`

说明：

- 本阶段未提交代码
- 本阶段未新增数据库表或字段
- 本阶段未改动 Engine / Session / NullPool / PRAGMA
- 本阶段未改动 Brain / Pipeline / Insight / Chat / Crawler / Frontend
