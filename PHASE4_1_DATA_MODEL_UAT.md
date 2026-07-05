# PHASE4_1_DATA_MODEL_UAT

## 1. 执行上下文

- Worktree 路径：`C:\Users\baiwan\christian-intel-v2-phase4`
- 分支：`phase4/watch-alert-v1`
- 基线 Commit：`9bc640bc1511468b5290612757a90903f07d7d0b`

## 2. 现有规范确认

- `Base` 定义位置：`backend/models/database.py`
- `Base` 定义方式：`Base = declarative_base()`
- 主键风格：现有核心业务表以 `String` 主键为主，`JobRun.id` 为 `String`
- 时间字段规范：统一使用 `DateTime` + `default=datetime.utcnow`，更新时间字段使用 `onupdate=datetime.utcnow`
- JSON 字段规范：直接使用 SQLAlchemy `JSON`
- 模型注册方式：通过 `backend/models/database.py` 的模块 import 进入 `Base.metadata`，最终由 `Base.metadata.create_all(bind=engine)` 建表
- Session / Engine：沿用 `backend/models/database.py` 中现有 `engine`、`SessionLocal`、`get_db()`，未创建第二套 Base / Engine / Session
- SQLite 建表方式：沿用 `Base.metadata.create_all()`；未改 `NullPool`、`Session`、PRAGMA 或 `_ensure_schema_compatibility()`
- 当前测试数据库创建与清理：测试中使用独立 SQLite 文件 `backend/data/watch_alert_phase41_test.db`，每次测试前重建，测试结束后删除

## 3. 实际修改文件

### 修改文件

- `backend/config.py`
- `backend/models/database.py`

### 新增文件

- `backend/models/watch_alert.py`
- `backend/tests/test_watch_alert_models.py`
- `PHASE4_1_DATA_MODEL_UAT.md`

### 未修改文件

- `backend/models/__init__.py`

## 4. Feature Flag

- 新增：`WATCH_ALERT_V1_ENABLED`
- 默认值：`False`
- 接入位置：`backend/config.py`
- 本阶段行为：仅定义，不接入任何运行逻辑
- 验证结果：`PASS`

## 5. 五张表最终字段

## 5.1 `watch_targets`

- `id`
- `user_id`
- `entity_id`
- `entity_type`
- `status`
- `frequency`
- `last_checked_at`
- `next_check_at`
- `last_success_at`
- `last_error_at`
- `consecutive_failures`
- `created_at`
- `updated_at`
- `deleted_at`

说明：

- 主键类型：`String`
- 多态实体引用：`entity_id + entity_type`
- 不强制外键到 `knowledge_entities` 或 `organization_profiles`
- 软删除：`deleted_at`

## 5.2 `watch_runs`

- `id`
- `watch_target_id`
- `job_run_id`
- `status`
- `started_at`
- `finished_at`
- `items_found`
- `signals_created`
- `alerts_created`
- `error_code`
- `error_message`
- `metadata_json`
- `created_at`

说明：

- `job_run_id` 类型与现有 `JobRun.id` 一致，均为 `String`
- 为兼容现有图谱，当前只保存同类型引用，不直接外键到 `job_runs`

## 5.3 `signals`

- `id`
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
- `created_at`

## 5.4 `alert_rules`

- `id`
- `user_id`
- `signal_type`
- `minimum_severity`
- `is_enabled`
- `configuration_json`
- `created_at`
- `updated_at`

## 5.5 `alerts`

- `id`
- `user_id`
- `watch_target_id`
- `signal_id`
- `title`
- `summary`
- `severity`
- `status`
- `source_url`
- `created_at`
- `read_at`
- `dismissed_at`

## 6. Check Constraints

### `watch_targets`

- `ck_watch_targets_status`
- `ck_watch_targets_frequency`

### `watch_runs`

- `ck_watch_runs_status`

### `signals`

- `ck_signals_signal_type`
- `ck_signals_severity`

### `alert_rules`

- `ck_alert_rules_signal_type`
- `ck_alert_rules_minimum_severity`

### `alerts`

- `ck_alerts_status`
- `ck_alerts_severity`

## 7. Partial Unique Indexes

- `ux_watch_targets_user_entity_type_active`
  - SQL: `CREATE UNIQUE INDEX ux_watch_targets_user_entity_type_active ON watch_targets (user_id, entity_id, entity_type) WHERE deleted_at IS NULL`
- `ux_alert_rules_user_signal_type`
  - SQL: `CREATE UNIQUE INDEX ux_alert_rules_user_signal_type ON alert_rules (user_id, signal_type) WHERE user_id IS NOT NULL`
- `ux_alert_rules_default_signal_type`
  - SQL: `CREATE UNIQUE INDEX ux_alert_rules_default_signal_type ON alert_rules (signal_type) WHERE user_id IS NULL`

## 8. 普通索引与唯一约束

### 普通索引

- `ix_watch_targets_entity_id`
- `ix_watch_targets_status_next_check_at`
- `ix_watch_targets_user_id`
- `ix_watch_runs_watch_target_id`
- `ix_watch_runs_status`
- `ix_watch_runs_started_at`
- `ix_signals_watch_target_id`
- `ix_signals_entity_id_detected_at`
- `ix_signals_signal_type_severity`
- `ix_alert_rules_is_enabled`
- `ix_alert_rules_signal_type`
- `ix_alerts_user_id_status_created_at`
- `ix_alerts_watch_target_id`
- `ix_alerts_signal_id`
- `ix_alerts_severity`

### 唯一约束

- `ux_signals_dedup_key`
- `uix_alerts_signal_id_user_id`
- 以及 3 个 partial unique indexes

## 9. 外键关系

- `watch_runs.watch_target_id -> watch_targets.id`
- `signals.watch_target_id -> watch_targets.id`
- `alerts.watch_target_id -> watch_targets.id`
- `alerts.signal_id -> signals.id`

关系设计：

- `WatchTarget 1:N WatchRun`
- `WatchTarget 1:N Signal`
- `WatchTarget 1:N Alert`
- `Signal 1:N Alert`

兼容性说明：

- 未新增 `User` ORM 模型
- 未重构 `knowledge_entities`
- 未重构 `organization_profiles`
- 未建立到实体主表的硬外键，避免破坏现有机构数据

## 10. 多态实体引用方案

- 方案：`WatchTarget.entity_id + WatchTarget.entity_type`
- 原因：当前项目同时存在 `knowledge_entities` 与 `organization_profiles`
- 结果：Watch / Alert 模型只记录目标实体标识，不强行统一实体表

## 11. 测试数据库位置

- 测试数据库路径：`backend/data/watch_alert_phase41_test.db`
- 使用方式：仅测试时创建
- 当前状态：已在测试和 schema 导出后删除，未污染工作树

## 12. SQLite 实际建表 SQL

```sql
-- alert_rules
CREATE TABLE alert_rules (
	id VARCHAR NOT NULL,
	user_id VARCHAR,
	signal_type VARCHAR NOT NULL,
	minimum_severity VARCHAR NOT NULL,
	is_enabled BOOLEAN NOT NULL,
	configuration_json JSON,
	created_at DATETIME,
	updated_at DATETIME,
	PRIMARY KEY (id),
	CONSTRAINT ck_alert_rules_signal_type CHECK (signal_type IN ('new_intelligence', 'website_change', 'new_news', 'new_video', 'leadership_change', 'contact_change', 'score_change', 'relation_change')),
	CONSTRAINT ck_alert_rules_minimum_severity CHECK (minimum_severity IN ('low', 'medium', 'high', 'critical'))
);

-- alerts
CREATE TABLE alerts (
	id VARCHAR NOT NULL,
	user_id VARCHAR NOT NULL,
	watch_target_id VARCHAR NOT NULL,
	signal_id VARCHAR NOT NULL,
	title VARCHAR NOT NULL,
	summary TEXT,
	severity VARCHAR NOT NULL,
	status VARCHAR NOT NULL,
	source_url VARCHAR,
	created_at DATETIME,
	read_at DATETIME,
	dismissed_at DATETIME,
	PRIMARY KEY (id),
	CONSTRAINT ck_alerts_status CHECK (status IN ('unread', 'read', 'dismissed')),
	CONSTRAINT ck_alerts_severity CHECK (severity IN ('low', 'medium', 'high', 'critical')),
	CONSTRAINT uix_alerts_signal_id_user_id UNIQUE (signal_id, user_id),
	FOREIGN KEY(watch_target_id) REFERENCES watch_targets (id),
	FOREIGN KEY(signal_id) REFERENCES signals (id)
);

-- signals
CREATE TABLE signals (
	id VARCHAR NOT NULL,
	watch_target_id VARCHAR NOT NULL,
	entity_id VARCHAR NOT NULL,
	signal_type VARCHAR NOT NULL,
	title VARCHAR NOT NULL,
	summary TEXT,
	severity VARCHAR NOT NULL,
	evidence_id VARCHAR,
	source_url VARCHAR,
	old_value_json JSON,
	new_value_json JSON,
	detected_at DATETIME NOT NULL,
	dedup_key VARCHAR NOT NULL,
	metadata_json JSON,
	created_at DATETIME,
	PRIMARY KEY (id),
	CONSTRAINT ck_signals_signal_type CHECK (signal_type IN ('new_intelligence', 'website_change', 'new_news', 'new_video', 'leadership_change', 'contact_change', 'score_change', 'relation_change')),
	CONSTRAINT ck_signals_severity CHECK (severity IN ('low', 'medium', 'high', 'critical')),
	FOREIGN KEY(watch_target_id) REFERENCES watch_targets (id)
);

-- watch_runs
CREATE TABLE watch_runs (
	id VARCHAR NOT NULL,
	watch_target_id VARCHAR NOT NULL,
	job_run_id VARCHAR,
	status VARCHAR NOT NULL,
	started_at DATETIME,
	finished_at DATETIME,
	items_found INTEGER NOT NULL,
	signals_created INTEGER NOT NULL,
	alerts_created INTEGER NOT NULL,
	error_code VARCHAR,
	error_message TEXT,
	metadata_json JSON,
	created_at DATETIME,
	PRIMARY KEY (id),
	CONSTRAINT ck_watch_runs_status CHECK (status IN ('pending', 'running', 'success', 'failed', 'skipped')),
	FOREIGN KEY(watch_target_id) REFERENCES watch_targets (id)
);

-- watch_targets
CREATE TABLE watch_targets (
	id VARCHAR NOT NULL,
	user_id VARCHAR NOT NULL,
	entity_id VARCHAR NOT NULL,
	entity_type VARCHAR NOT NULL,
	status VARCHAR NOT NULL,
	frequency VARCHAR NOT NULL,
	last_checked_at DATETIME,
	next_check_at DATETIME,
	last_success_at DATETIME,
	last_error_at DATETIME,
	consecutive_failures INTEGER NOT NULL,
	created_at DATETIME,
	updated_at DATETIME,
	deleted_at DATETIME,
	PRIMARY KEY (id),
	CONSTRAINT ck_watch_targets_status CHECK (status IN ('active', 'paused', 'disabled')),
	CONSTRAINT ck_watch_targets_frequency CHECK (frequency IN ('daily', 'weekly', 'manual'))
);
```

## 13. 13 项测试结果

- Test 1 建表：`PASS`
- Test 2 WatchTarget 活跃唯一约束：`PASS`
- Test 3 软删除后重新关注：`PASS`
- Test 4 多用户隔离：`PASS`
- Test 5 Signal 去重：`PASS`
- Test 6 Alert 去重：`PASS`
- Test 7 AlertRule 用户规则唯一：`PASS`
- Test 8 AlertRule 系统默认唯一：`PASS`
- Test 9 非法状态拒绝：`PASS`
- Test 10 内部关系：`PASS`
- Test 11 机构安全：`PASS`
- Test 12 Feature Flag：`PASS`
- Test 13 现有系统回归导入：`PASS`

测试命令：

```powershell
python -m pytest backend/tests/test_watch_alert_models.py -v
```

结果摘要：

- `19 passed`
- 总耗时约 `4.95s`

说明：

- Test 9 使用参数化拆成 7 条断言，因此 pytest 收集到 19 条用例

## 14. 现有系统回归结果

已验证以下导入与建表动作可正常执行：

- `config` import
- `models.database` import
- `Base.metadata.create_all()`
- `services.insight_models` import
- `services.insight_engine` import
- `services.pipeline_orchestrator` import

结果：

- 无循环导入
- 无 Watch / Alert 相关副作用
- `WATCH_ALERT_V1_ENABLED` 默认关闭

## 15. Feature Flag 默认值

- `WATCH_ALERT_V1_ENABLED=false`

## 16. 回滚方式

本阶段未提交代码，回滚方式仅针对工作树改动：

- 删除新增文件：
  - `backend/models/watch_alert.py`
  - `backend/tests/test_watch_alert_models.py`
  - `PHASE4_1_DATA_MODEL_UAT.md`
- 撤销最小修改文件中的本阶段增量：
  - `backend/config.py`
  - `backend/models/database.py`

说明：

- 当前未执行 commit
- 当前未修改正式数据库
- 当前未保留测试数据库文件

## 17. Git diff 文件清单

当前允许范围内的业务文件：

- `backend/config.py`
- `backend/models/database.py`
- `backend/models/watch_alert.py`
- `backend/tests/test_watch_alert_models.py`
- `PHASE4_1_DATA_MODEL_UAT.md`

未出现越界业务文件修改。

## 18. 验收结论

- DataModels：`PASS`
- Constraints：`PASS`
- PartialIndexes：`PASS`
- DatabaseCreation：`PASS`
- Regression：`PASS`
- BoundaryCheck：`PASS`
- `WATCH_ALERT_V1_ENABLED=false`
- `READY_FOR_PHASE4_2=true`
