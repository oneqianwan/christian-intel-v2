# PHASE5_5_RBAC_ADMIN_IMPLEMENTATION_PLAN

## Title

Phase 5.5 RBAC + Admin Minimal Implementation Plan

## 1. Current State Summary

- 已有 `User.role` 字段。
- 当前角色包括 `super_admin`、`admin`、`analyst`、`viewer`。
- 当前 `role` 主要是存储字段和前端显示字段，不是完整后端权限边界。
- Auth / Watch / Alert / Chat 用户归属已经完成。
- 当前缺少 Admin / RBAC 的后端强制执行。
- 当前缺少 Admin 用户管理闭环。
- 当前缺少前端 `/admin` 最小管理入口。

## 2. Phase 5.5 Scope Lock

### A. 后端 RBAC 基线

- 新增 `require_role`
- 新增 `require_admin`
- 新增 `require_super_admin`
- 明确 role hierarchy
- 明确 `401 / 403` 行为
- 保持 `AUTH_V1_ENABLED=false` 或 legacy 模式兼容
- 不影响 Watch / Alert / Chat ownership

### B. 高风险接口收口

- 至少纳入评估和处理：
  - `/api/agent/run`
  - `/configs/keys`
  - dashboard 写接口
  - 其他运营型 / 配置型 / 执行型接口
- 处理要求：
  - 高风险写接口 `admin-only`
  - 超级敏感接口 `super_admin-only`
  - 普通 `viewer / analyst` 不可调用
  - 未登录用户不可调用

### C. legacy 身份残留清理

- 至少处理：
  - `feedback.py` 不再信任 `x-session-id` / `session-1` 作为真实身份
  - `bookmarks.py` 不再写入固定 `"default"` 用户
  - 如果必须保留 legacy 模式，必须明确隔离在 `AUTH_V1_ENABLED=false` 或 feature flag 下
  - authenticated mode 下必须使用 `current_user`

### D. Admin 用户管理 API

- 最小 API 范围：
  - `GET /api/admin/users`
  - `GET /api/admin/users/{user_id}`
  - `PATCH /api/admin/users/{user_id}/role`
  - `PATCH /api/admin/users/{user_id}/status`
  - `POST /api/admin/users/{user_id}/sessions/revoke`
- 必须考虑：
  - 只有 `super_admin / admin` 可以进入用户管理
  - 修改角色至少需要 `super_admin`，或者明确 `admin` 能否改 `analyst/viewer`
  - 禁止普通 `admin` 把自己升为 `super_admin`
  - 禁止 `admin` 修改 `super_admin`
  - 禁止禁用最后一个 active `super_admin`
  - 禁止用户误禁用自己，除非明确允许并安全处理
  - `status` 只能使用系统已有合法状态
  - session revoke 不能破坏当前请求稳定性

### E. 前端 Admin 最小入口

- 最小范围：
  - `/admin` 路由
  - `AdminGuard` 接入 App 路由
  - `AdminLayout`
  - `UsersPage`
  - 用户列表
  - 用户详情或基础操作入口
  - `role/status` 展示
  - 修改 `role/status` 的最小 UI
  - revoke sessions 按钮
  - 普通用户看不到 Admin 入口
  - 普通用户强行访问 `/admin` 显示无权限或重定向

### F. 测试与静态校验

#### 后端测试

- `super_admin` 可访问 admin API
- `admin` 权限行为符合矩阵
- `analyst/viewer` 调用 admin API 返回 `403`
- 未登录调用 admin API 返回 `401`
- 普通用户不能改自己为 `super_admin`
- 不能禁用最后一个 `super_admin`
- 不能越权修改 `super_admin`
- revoke sessions 生效
- 高风险接口 `admin-only`
- `feedback/bookmarks` authenticated mode 不再使用 legacy 身份

#### 前端测试

- `super_admin / admin` 可看到 Admin 入口
- `analyst / viewer` 看不到 Admin 入口
- 未登录访问 `/admin` 被拦截
- 普通用户访问 `/admin` 显示无权限
- `UsersPage` 能加载用户列表
- `role/status` 操作调用正确 API
- `403` 时显示无权限，不显示误导性普通失败

#### 静态校验

- 搜索 `x-session-id / session-1 / default user` 残留
- 搜索 admin API 是否有 `require_admin / require_super_admin`
- 搜索高风险接口是否有权限依赖

## 3. Suggested Implementation Order

### Phase 5.5A: 后端 RBAC 依赖与角色矩阵

- 输出：
  - `require_role / require_admin / require_super_admin`
  - backend RBAC tests
  - 不接入大量业务接口，只建立基线

### Phase 5.5B: Admin 用户管理 API

- 输出：
  - `/api/admin/users` APIs
  - 用户列表 / 详情 / 修改角色 / 修改状态 / revoke sessions
  - admin user management tests

### Phase 5.5C: 高风险接口 RBAC 收口 + legacy 身份清理

- 输出：
  - `agent / configs / dashboard` 写接口权限保护
  - `feedback / bookmarks` 身份修复
  - 高风险接口 tests
  - legacy compatibility tests

### Phase 5.5D: 前端 Admin 路由与 UsersPage

- 输出：
  - `/admin`
  - `AdminGuard` 真正接入 App
  - `AdminLayout`
  - `UsersPage`
  - `role/status/revoke sessions` UI
  - frontend admin tests

### Phase 5.5E: 浏览器 UAT + 最终硬化审计

- 输出：
  - `super_admin` 浏览器 UAT
  - `viewer/analyst` 拒绝 UAT
  - `logout/relogin` UAT
  - final audit report

## 4. Permission Matrix Draft

### super_admin

- 全部 admin 能力
- 修改角色
- 禁用/启用用户
- revoke 任意用户 sessions
- 管理 `configs / keys`
- 运行 `agent / 后台运营任务`

### admin

- 查看用户列表
- 查看用户详情
- 可管理 `analyst/viewer`
- 不可修改 `super_admin`
- 不可创建 `super_admin`
- 不可禁用 `super_admin`
- 建议：可 revoke `analyst/viewer` sessions，但不可 revoke `super_admin` sessions

### analyst

- 可使用普通分析功能
- 可使用 Chat / Watch / Alert 自己的数据
- 不可访问 admin API
- 不可修改配置
- 不可运行高风险后台任务

### viewer

- 只读
- 可使用自己的 Chat / Watch / Alert，或按现有产品定义限制
- 不可访问 admin API
- 不可写配置
- 不可运行 agent

## 5. Risk Points And Guard Rules

- 最后一个 active `super_admin` 保护
- self-demotion 保护
- self-disable 保护
- `admin` 修改 `super_admin` 保护
- role enum 校验
- status enum 校验
- session revoke 边界
- feature flag 关闭时 legacy 行为
- authenticated mode 不信任前端传 `role`
- 前端隐藏按钮不能代替后端权限
- 所有 admin API 后端必须 `403` 拦截

## 6. Required Test Commands

### 基础回归

- `cd frontend && npm run check:auth-ui`
- `cd frontend && npm run test:auth`
- `cd frontend && npm run check:chat-user-auth`
- `cd frontend && npm run test:chat-user-auth`
- `cd frontend && npm run check:watch-alert-contract`
- `cd frontend && npm run check:watchlist-ui`
- `cd frontend && npm run check:alerts-ui`
- `cd frontend && npm run check:watch-alert-auth`
- `cd frontend && npm run check:watch-alert-user-auth`
- `cd frontend && npm run test:watch-alert-user-auth`
- `cd frontend && npm run build`

### 后端 Auth 基线

- `cd backend && python -m pytest -q tests/test_create_admin.py tests/test_auth_models.py tests/test_auth_migration.py tests/test_auth_service.py tests/test_auth_api.py tests/test_auth_account_lifecycle.py`

### 后端 Chat/Watch Ownership 基线

- `cd backend && python scripts/verify_chat_user_ownership.py`
- `cd backend && python -m pytest -q tests/test_chat_user_ownership.py tests/test_chat_stream_ownership.py tests/test_chat_owner_migration.py`

### Phase 5.5 新增测试建议

- `cd backend && python -m pytest -q tests/test_admin_rbac.py`
- `cd backend && python -m pytest -q tests/test_admin_user_management.py`
- `cd backend && python -m pytest -q tests/test_high_risk_admin_protection.py`
- `cd frontend && vitest run src/auth/__tests__ src/pages/__tests__/Admin*.test.tsx src/components/__tests__/Admin*.test.tsx`

## 7. Non-Goals

- Phase 5.5 不做：
  - 多租户组织权限
  - 复杂审计日志系统
  - 付费订阅权限
  - 细粒度资源级 ACL
  - OAuth / SSO
  - 邀请系统
  - 复杂 Admin Dashboard
  - 数据可视化后台
  - Brain 性能优化
  - crawler 调度系统重构

## 8. Final Recommendation

- RecommendedNextStep=Phase 5.5A backend RBAC baseline
- READY_FOR_PHASE5_5A=true
- READY_FOR_CODE_CHANGES=false until user approves
