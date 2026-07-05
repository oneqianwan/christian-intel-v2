# PHASE4_2_WATCHLIST_API_UAT

## 1. 执行上下文

- Worktree 路径：`C:\Users\baiwan\christian-intel-v2-phase4`
- 分支：`phase4/watch-alert-v1`
- Phase 4.1 提交：`4ccf403`
- 当前基线：`feat: add watch alert data models`

## 2. 实际修改文件

### 修改文件

- `backend/main.py`

### 新增文件

- `backend/routers/watch_targets.py`
- `backend/services/watch_target_service.py`
- `backend/schemas/watch_alert.py`
- `backend/tests/test_watch_targets_api.py`
- `PHASE4_2_WATCHLIST_API_UAT.md`

### 未修改但复用的关键文件

- `backend/config.py`
- `backend/models/database.py`
- `backend/models/watch_alert.py`

## 3. Router 注册方式

- 注册文件：`backend/main.py`
- 注册方式：沿用现有 `app.include_router(...)` 模式
- 实际注册：
  - 在 router import 列表中加入 `watch_targets`
  - 添加 `app.include_router(watch_targets.router, prefix="/api", tags=["watch_targets"])`

说明：

- 当前项目确实通过 `backend/main.py` 集中注册 Router
- 本阶段只做了最小注册改动

## 4. 用户身份获取方式

- 依赖函数：`get_current_user_id()`
- 定义位置：`backend/routers/watch_targets.py`
- 运行时身份来源：
  - 请求头 `x-session-id`
- 未获取身份时：
  - `401`
  - `detail.error_code=AUTH_REQUIRED`

测试方式：

- API 测试通过 FastAPI `dependency_overrides` 注入测试用户
- 未登录场景通过 override 返回 `401`

说明：

- 未从 body 接受 `user_id`
- 未从 query 参数接受 `user_id`
- 所有查询、更新、删除都以当前用户边界执行

## 5. Feature Flag 行为

- Flag：`WATCH_ALERT_V1_ENABLED`
- 默认值：`false`
- 读取方式：复用 `config.settings.feature_flag("WATCH_ALERT_V1_ENABLED")`
- 守卫位置：`require_watch_alert_enabled()`

关闭时行为：

- 返回 `503 Service Unavailable`
- `detail.error_code=WATCH_ALERT_V1_DISABLED`
- 不执行数据库写入

开启时行为：

- API 正常执行

## 6. 四个 API 契约

## 6.1 创建关注

- 方法：`POST /api/watch-targets`
- 请求体：

```json
{
  "entity_id": "victory-philippines",
  "entity_type": "organization",
  "frequency": "daily"
}
```

- 允许值：
  - `entity_type`: `organization | knowledge_entity`
  - `frequency`: `daily | weekly | manual`
- 默认值：
  - `status=active`
  - `frequency=daily`
- 成功返回：
  - `201 Created`
  - `WatchTargetResponse`
- 失败返回：
  - `401 AUTH_REQUIRED`
  - `404 WATCH_TARGET_ENTITY_NOT_FOUND`
  - `409 WATCH_TARGET_EXISTS`
  - `503 WATCH_ALERT_V1_DISABLED`
  - `422` 请求体校验失败

## 6.2 获取关注列表

- 方法：`GET /api/watch-targets`
- 查询参数：
  - `status`
  - `entity_type`
  - `page`
  - `page_size`
- 默认值：
  - `page=1`
  - `page_size=20`
- 约束：
  - `page >= 1`
  - `1 <= page_size <= 100`
  - 默认排除 `deleted_at IS NOT NULL`
  - 默认按 `created_at DESC`
- 成功返回：

```json
{
  "items": [],
  "page": 1,
  "page_size": 20,
  "total": 0
}
```

- 失败返回：
  - `401 AUTH_REQUIRED`
  - `503 WATCH_ALERT_V1_DISABLED`
  - `422` 查询参数校验失败

## 6.3 修改关注

- 方法：`PATCH /api/watch-targets/{id}`
- 允许修改字段：
  - `status`
  - `frequency`
- 不允许客户端修改：
  - `user_id`
  - `entity_id`
  - `entity_type`
  - `last_checked_at`
  - `next_check_at`
  - `consecutive_failures`
  - `created_at`
  - `deleted_at`
- 成功返回：
  - `200 OK`
  - `WatchTargetResponse`
- 失败返回：
  - `401 AUTH_REQUIRED`
  - `404 WATCH_TARGET_NOT_FOUND`
  - `503 WATCH_ALERT_V1_DISABLED`
  - `422` 非法 `status/frequency` 或额外字段

## 6.4 删除关注

- 方法：`DELETE /api/watch-targets/{id}`
- 删除方式：
  - 软删除
  - `deleted_at=当前时间`
  - `status=disabled`
- 成功返回：
  - `204 No Content`
- 失败返回：
  - `401 AUTH_REQUIRED`
  - `404 WATCH_TARGET_NOT_FOUND`
  - `503 WATCH_ALERT_V1_DISABLED`

## 7. Schema 结果

已实现：

- `WatchTargetCreate`
- `WatchTargetUpdate`
- `WatchTargetResponse`
- `WatchTargetListResponse`
- `ApiErrorResponse`

响应包含：

- `id`
- `entity_id`
- `entity_type`
- `status`
- `frequency`
- `last_checked_at`
- `next_check_at`
- `last_success_at`
- `consecutive_failures`
- `created_at`
- `updated_at`

响应不包含：

- `user_id`
- `deleted_at`
- 内部异常堆栈
- Session 信息

## 8. Service Layer 方法

文件：`backend/services/watch_target_service.py`

已实现：

- `create_watch_target()`
- `list_watch_targets()`
- `update_watch_target()`
- `soft_delete_watch_target()`
- `get_owned_watch_target()`

实现约束：

- Router 不直接堆 SQL
- 所有查询都带当前 `user_id`
- 更新和删除都验证所有权
- 唯一约束冲突转换为 `409 WATCH_TARGET_EXISTS`
- 未知数据库异常不吞掉

## 9. 实体验证与多态引用

当前方案：

- 使用 `entity_id + entity_type` 多态引用
- 不重构 `knowledge_entities`
- 不重构 `organization_profiles`

当前存在性验证：

- `entity_type=organization`
  - 先查 `organization_profiles.id`
  - 若未命中，再查 `knowledge_entities.id` 且 `entity_type='organization'`
- `entity_type=knowledge_entity`
  - 查 `knowledge_entities.id`

说明：

- 这是 V1 下的最小安全验证
- 未引入统一实体抽象重构

## 10. 多用户隔离结果

- 创建、列表、修改、删除均以当前用户为边界
- 同一用户重复关注同一实体：
  - `409 WATCH_TARGET_EXISTS`
- 不同用户关注同一实体：
  - 允许
- 修改他人记录：
  - `404 WATCH_TARGET_NOT_FOUND`
- API 不暴露其他用户记录是否存在

## 11. 软删除结果

- 删除接口执行软删除，不做物理删除
- 删除后：
  - `deleted_at` 被写入
  - `status=disabled`
  - 列表默认不再返回
- 软删除后：
  - 同一用户可重新关注同一实体
- 不影响：
  - `knowledge_entities`
  - `organization_profiles`
  - `watch_runs`
  - `signals`
  - `alerts`

## 12. 25 项测试结果

- 1 Feature Flag 关闭时返回 503：`PASS`
- 2 未登录返回 401：`PASS`
- 3 用户成功关注机构：`PASS`
- 4 默认 `status=active`：`PASS`
- 5 默认 `frequency=daily`：`PASS`
- 6 同一用户重复关注返回 409：`PASS`
- 7 不同用户可以关注同一机构：`PASS`
- 8 用户只能查看自己的 Watchlist：`PASS`
- 9 `status` 筛选正确：`PASS`
- 10 `entity_type` 筛选正确：`PASS`
- 11 分页正确：`PASS`
- 12 `page_size > 100` 被拒绝：`PASS`
- 13 用户可暂停关注：`PASS`
- 14 用户可恢复 `active`：`PASS`
- 15 用户可修改 `frequency`：`PASS`
- 16 非法 `status` 返回 `422`：`PASS`
- 17 非法 `frequency` 返回 `422`：`PASS`
- 18 用户不能修改其他用户记录：`PASS`
- 19 `DELETE` 执行软删除：`PASS`
- 20 软删除后列表不再返回：`PASS`
- 21 软删除后允许重新关注：`PASS`
- 22 删除 WatchTarget 不影响机构表：`PASS`
- 23 不返回 `user_id` 和 `deleted_at`：`PASS`
- 24 API 路由正确注册：`PASS`
- 25 现有 Insight、Database、Chat import 回归通过：`PASS`

测试命令：

```powershell
python -m pytest backend/tests/test_watch_targets_api.py -v
python -m pytest backend/tests/test_watch_alert_models.py -v
```

结果：

- `backend/tests/test_watch_targets_api.py`: `25 passed`
- `backend/tests/test_watch_alert_models.py`: `19 passed`

## 13. 回归测试结果

额外 import smoke：

```powershell
python -c "import sys, importlib; sys.path.insert(0, r'C:\Users\baiwan\christian-intel-v2-phase4\backend'); mods=['config','models.database','routers.chat','services.insight_models','services.insight_engine','services.pipeline_orchestrator']; [importlib.import_module(m) for m in mods]; print('IMPORT_SMOKE_OK')"
```

结果：

- `IMPORT_SMOKE_OK`

回归结论：

- `config` 导入正常
- `models.database` 导入正常
- `routers.chat` 导入正常
- `services.insight_models` 导入正常
- `services.insight_engine` 导入正常
- `services.pipeline_orchestrator` 导入正常

## 14. Git 边界检查

执行：

```powershell
git status --short
git diff --stat
git diff --name-only
```

结果：

- `git status --short`

```text
 M backend/main.py
?? backend/routers/watch_targets.py
?? backend/schemas/
?? backend/services/watch_target_service.py
?? backend/tests/test_watch_targets_api.py
```

- `git diff --stat`

```text
 backend/main.py | 2 ++
 1 file changed, 2 insertions(+)
```

- `git diff --name-only`

```text
backend/main.py
```

边界判断：

- 未出现 `brain.py`
- 未出现 `pipeline_orchestrator.py`
- 未出现 `insight_engine.py`
- 未出现 `crawler`
- 未出现 `frontend`
- 允许范围内唯一 tracked 修改是 `backend/main.py`
- 允许范围内存在 4 个新增业务文件和 1 个新增 UAT 文档

## 15. 回滚方式

本阶段未提交代码，可直接回滚工作树：

- 删除新增文件：
  - `backend/routers/watch_targets.py`
  - `backend/services/watch_target_service.py`
  - `backend/schemas/watch_alert.py`
  - `backend/tests/test_watch_targets_api.py`
  - `PHASE4_2_WATCHLIST_API_UAT.md`
- 撤销最小修改：
  - `backend/main.py`

说明：

- 本阶段未修改数据库 Engine / Session / NullPool
- 本阶段未修改 Insight / Brain / Crawler / Frontend
- 本阶段未提交代码，等待你验收后再决定是否创建 Phase 4.2 commit
