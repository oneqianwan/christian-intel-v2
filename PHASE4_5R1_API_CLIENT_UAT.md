# PHASE4_5R1_API_CLIENT_UAT

## 实际修改文件

- `frontend/src/types/watchAlerts.ts`
- `frontend/src/api/watchAlerts.ts`
- `frontend/scripts/verify-watch-alert-contract.mjs`
- `frontend/package.json`
- `frontend/.env.example`

## 现有 API Client 复用方式

- 继续复用项目现有前端约定：原生 `fetch`
- 继续复用现有 API Base URL 模式：`VITE_API_BASE_URL || http://localhost:8000`
- 未引入 axios、全局 request SDK、状态管理或第二套路由
- 新增逻辑仅限 `frontend/src/api/watchAlerts.ts`

参考现有文件：

- `frontend/src/services/api.ts`
- `frontend/src/pages/OrgDetailPage.tsx`

## 认证 Header 复用方式

- 继续使用后端真实要求的 `x-session-id`
- 默认读取浏览器 `localStorage['x-session-id']`
- 未读取到时回落到现有开发环境默认值 `session-1`
- 未发送 `user_id`

## Feature Flag 实现

- 新增 `frontend/.env.example`
- 默认：
  - `VITE_WATCH_ALERT_UI_ENABLED=false`
- 实现：
  - `isWatchAlertUiEnabled() => import.meta.env.VITE_WATCH_ALERT_UI_ENABLED === 'true'`
- 未配置时默认为 `false`
- 只有严格字符串 `"true"` 才开启
- 本阶段未接入任何 UI

## TypeScript 类型

已实现并与后端真实契约对齐：

- `WatchTarget`
- `CreateWatchTargetRequest`
- `UpdateWatchTargetRequest`
- `WatchRunResult`
- `WatchSignal`
- `WatchAlert`
- `PaginatedResponse<T>`
- 查询参数类型
- `WatchAlertApiError`

关键对齐点：

- 所有主键与外键 ID 采用真实后端类型 `string`
- `WatchSignal` 保持真实字段名：
  - `old_value_json`
  - `new_value_json`
  - `metadata_json`
- `source_url` 允许 `null`
- 未包含 `user_id`

## 11 个 API Client 方法

Watch Targets:

- `createWatchTarget`
- `listWatchTargets`
- `updateWatchTarget`
- `deleteWatchTarget`
- `runWatchTarget`
- `listWatchTargetSignals`

Alerts:

- `listAlerts`
- `getUnreadAlertCount`
- `markAlertRead`
- `dismissAlert`
- `markAllAlertsRead`

## 后端真实契约核对结果

读取文件：

- `backend/routers/watch_targets.py`
- `backend/routers/alerts.py`
- `backend/schemas/watch_alert.py`

核对结果：

- 路径与 Method 已对齐
- 查询参数已对齐：
  - Watch Targets: `status`, `entity_type`, `page`, `page_size`
  - Signals: `signal_type`, `severity`, `page`, `page_size`
  - Alerts: `status`, `severity`, `watch_target_id`, `page`, `page_size`
- 错误结构已对齐：
  - FastAPI `detail`
  - `detail.error_code`
  - `detail.message`
- `DELETE /api/watch-targets/{id}` 为 `204 No Content`
- `GET /api/alerts/unread-count` 返回 `unread_count`
- `POST /api/alerts/read-all` 返回 `updated_count`

## 文档与真实后端的差异

以下早期说明与真实后端代码存在差异，本阶段前端已按真实后端实现：

1. ID 类型不是 `number`，而是 `string`
2. `WatchRunResponse` 当前真实返回不含 `alerts_created`
3. `WatchSignal` 使用真实字段名：
   - `old_value_json`
   - `new_value_json`
   不是 `old_value` / `new_value`
4. FastAPI 错误对象位于 `detail` 内，不是平铺返回
5. `WatchTargetCreate.frequency` 后端默认值由后端 schema 处理，前端可选传入

## 错误解析方式

- 统一抛出 `WatchAlertApiError`
- 支持解析：
  - `{ error_code, message }`
  - `{ detail: { error_code, message } }`
  - `{ detail: "..." }`
- 至少覆盖：
  - `401`
  - `404`
  - `409`
  - `422`
  - `503`
- 未将后端堆栈暴露给 UI
- 未吞掉错误

## 204 处理方式

- `deleteWatchTarget` 显式使用 `parseJson: false`
- request helper 遇到 `204` 时不会调用 `response.json()`
- 返回 `void`

## 契约检查结果

执行目录：`frontend`

命令：

```powershell
npm run check:watch-alert-contract
```

结果：

```text
WATCH_ALERT_CONTRACT_CHECK=PASS
```

## Build 结果

执行目录：`frontend`

命令：

```powershell
npm run build
```

结果：

- TypeScript 编译通过
- Vite 生产构建通过
- 仅存在既有 chunk size warning，无新增高优先级错误

## Git 边界检查

执行目录：仓库根目录

命令：

```powershell
git status --short
git diff --stat
git diff --name-only
```

结果：

- 仅出现允许范围内文件：
  - `frontend/src/types/watchAlerts.ts`
  - `frontend/src/api/watchAlerts.ts`
  - `frontend/scripts/verify-watch-alert-contract.mjs`
  - `frontend/package.json`
  - `frontend/.env.example`
  - `PHASE4_5R1_API_CLIENT_UAT.md`
- 无 `backend/*` 变更
- 无 `frontend/src/pages/*` 变更
- 无 `frontend/src/components/*` 变更
- 无 Router / 导航 / Dashboard / Chat / Organization Detail 改动

## 回滚方法

本阶段尚未提交。

如需回滚，仅恢复本阶段允许范围文件即可，不应触碰：

- `backend/*`
- `frontend/src/pages/*`
- `frontend/src/components/*`
- Router / 导航相关文件
