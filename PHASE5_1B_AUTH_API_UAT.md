# PHASE 5.1B UAT：Password Hashing + HttpOnly Cookie Session + Auth API

正式项目目录：`C:\Users\baiwan\christian-intel-v2`  
分支：`phase5/auth-rbac-admin-v1`  
基线提交：`3bbf087`

## 1. 目标与范围

本阶段实现：
- Argon2id 密码哈希与验证
- 高熵 Session Token 生成（HttpOnly Cookie 保存 raw token）
- 数据库仅保存 `token_hash`（SHA-256 hex）
- 统一 Auth Dependency（cookie → token_hash → AuthSession → User）
- Auth API：
  - `POST /api/auth/login`
  - `POST /api/auth/logout`
  - `GET /api/auth/me`
- CORS：显式 allow_origins + `allow_credentials=True`
- 登录速率限制（最小进程内实现）
- 认证相关测试 + Phase 4 回归测试

明确不做（保持现有行为不变）：
- 前端登录页面 / AuthProvider
- 公共注册、忘记密码、修改密码、管理员创建用户、RBAC 管理接口
- Chat、Watch、Alert 的现有认证/身份逻辑改造（仍按既有方式运行）
- x-session-id 移除与迁移

## 2. 安全架构冻结核对

- Cookie 保存 raw session token：YES
- 数据库仅保存 `token_hash`：YES
- `AuthSession.public_id` 不作为凭证：YES
- Cookie 不包含 user_id / db id / public_id：YES
- raw token 仅在登录成功时生成一次：YES
- raw token 不写入数据库/日志/错误/JSON：YES（仅写入 HttpOnly Cookie）
- Cookie 设置 `HttpOnly=true`：YES
- 前端 JS 未来不可读取凭证：YES（HttpOnly）
- 不恢复 `session-1`：YES
- 本阶段不改变 Watch/Alert 的 `x-session-id` 行为：YES

## 3. 密码哈希（Argon2id）

实现位置：
- `backend/services/auth_service.py`

接口：
- `hash_password(password: str) -> str`
- `verify_password(password_hash: str, password: str) -> bool`
- `needs_rehash(password_hash: str) -> bool`

算法与参数（生产默认）：
- Argon2id（argon2-cffi `PasswordHasher(type=Type.ID)`）
- `time_cost=3`
- `memory_cost=65536 KiB`
- `parallelism=4`
- `hash_len=32`
- `salt_len=16`

行为：
- 同一密码多次哈希结果不同（随机 salt）：已测试
- 错误密码返回 False；损坏 hash 安全失败：已测试
- 登录时若 `needs_rehash=True`，会安全升级哈希并持久化：已测试

## 4. Session Token

实现位置：
- `backend/services/auth_service.py`

生成与哈希：
- raw token：`secrets.token_urlsafe(48)`（至少 256-bit 熵）
- token_hash：`sha256(raw_token).hexdigest()`（固定 64 hex）

存储策略：
- Cookie：保存 raw token
- 数据库：仅保存 token_hash（用于查询）

## 5. Cookie 策略

Cookie 名称（默认）：
- `AUTH_COOKIE_NAME=cio_session`

登录成功设置 Cookie：
- `HttpOnly=true`
- `Secure=<AUTH_COOKIE_SECURE>`（本地默认 false；生产应设 true）
- `SameSite=<AUTH_COOKIE_SAMESITE>`（默认 lax）
- `Path=<AUTH_COOKIE_PATH>`（默认 `/`）
- `Max-Age=<AUTH_SESSION_TTL_SECONDS>`（默认 86400）

退出登录（Logout）：
- 若存在可解析 Session：标记 revoked，并写入 `revoked_at`
- 无论 Session 是否存在/是否有效：都安全删除 Cookie
- 重复 Logout：安全返回成功

## 6. Auth Dependency（统一鉴权）

实现位置：
- `backend/dependencies/auth.py`

核心流程：
- Feature Flag：`AUTH_V1_ENABLED=false` 时直接 503 `AUTH_DISABLED`
- 读取 HttpOnly Cookie raw token
  - 无 Cookie：401 `AUTH_REQUIRED`
  - 有 Cookie：hash → 按 `token_hash` 查询 `auth_sessions`
    - 不存在：401 `INVALID_SESSION`
    - revoked：401 `SESSION_REVOKED`
    - expired：401 `SESSION_EXPIRED`
  - 查询 User
    - deleted/disabled：403 `ACCOUNT_DISABLED`
    - pending：403 `ACCOUNT_PENDING`
  - 节流更新 `last_seen_at`（默认 300 秒）：已测试

## 7. Auth API

实现位置：
- `backend/routers/auth.py`

路由：
- `POST /api/auth/login`
  - Flag off：503 `AUTH_DISABLED`（不查询 Auth 表、不创建 Session、不设置 Cookie）
  - 成功：设置 HttpOnly Cookie；返回安全用户字段（不含 password_hash/token_hash/raw token）
  - 失败：
    - 401 `INVALID_CREDENTIALS`
    - 403 `ACCOUNT_DISABLED` / `ACCOUNT_PENDING`
    - 429 `LOGIN_RATE_LIMITED`（含 `Retry-After`）

- `POST /api/auth/logout`
  - Flag off：安全删除 Cookie，并返回 503 `AUTH_DISABLED`
  - Flag on：尝试撤销 Session（存在则 revoked），删除 Cookie，返回 `{ "success": true }`

- `GET /api/auth/me`
  - 必须使用统一依赖
  - 未登录：401
  - 已登录：返回当前用户安全字段

错误响应结构（与现有 Watch/Alert 统一）：
- `HTTPException(detail=ApiErrorResponse(...).model_dump())`
- FastAPI JSON 响应形态为：`{"detail": {"error_code": "...", "message": "..."}}`

## 8. Feature Flag 行为

默认：
- `AUTH_V1_ENABLED=false`
- `AUTH_COOKIE_REQUIRED=false`（迁移预留，本阶段不用于保护 Chat/Watch/Alert）

当 `AUTH_V1_ENABLED=false`：
- `/api/auth/login`：503 `AUTH_DISABLED`，不创建 Session、不设置 Cookie、不查询 Auth 表
- `/api/auth/me`：503 `AUTH_DISABLED`
- `/api/auth/logout`：安全清 Cookie + 503 `AUTH_DISABLED`
- 现有 API 行为保持不变

## 9. CORS（本地跨端口）

实现位置：
- `backend/main.py`

策略：
- `allow_credentials=True`
- `allow_origins` 使用显式列表（来自 `AUTH_CORS_ALLOW_ORIGINS`）
- 禁止 `allow_origins=["*"]` 与 `allow_credentials=True` 的组合（在 config 校验中拒绝）

默认允许（settings 默认值）包含：
- `http://127.0.0.1:4173`
- `http://localhost:4173`
- `http://127.0.0.1:5173`
- `http://localhost:5173`

## 10. 登录速率限制

实现位置：
- `backend/services/auth_service.py`

策略：
- 最小进程内实现（单实例有效）
- key：`normalize_email(email) + sha256(client_fingerprint)`  
  - 指纹当前使用 `request.client.host` 的 sha256 摘要
- 不持久化原始 IP，不把密码放入 key
- 超限：429 `LOGIN_RATE_LIMITED` + `Retry-After`
- 成功登录：清理失败计数

生产限制（已知限制）：
- 多进程/多实例需引入 Redis / 网关级限流才能全局生效

## 11. 测试与回归

Auth Service Tests：
- `backend/tests/test_auth_service.py`：PASS

Auth API Tests：
- `backend/tests/test_auth_api.py`：PASS
  - 覆盖：Flag off 503、登录 cookie 属性、敏感字段不泄露、unknown/wrong 同 401、disabled/pending、空/超大密码 422、rate limit 429、me 不接受 `x-session-id`、logout revoke + 清 cookie、expired/revoked/invalid session、needs_rehash 升级、last_seen 节流、CORS allow-origin/credentials 行为

Phase 4 回归（后端）：
- `tests/test_alert_engine.py`：PASS
- `tests/test_alerts_api.py`：PASS
- `tests/test_watch_runner.py`：PASS
- `tests/test_watch_scheduler.py`：PASS
- `tests/test_watch_targets_api.py`：PASS
- `tests/test_watch_signals_api.py`：PASS

## 12. 安全检查结论

- 数据库不保存 raw token：PASS（仅保存 sha256 token_hash）
- JSON 响应不包含 raw token/password_hash/token_hash：PASS（测试覆盖）
- Cookie 为 HttpOnly：PASS（测试覆盖）
- CORS 不使用 `*` + credentials：PASS（配置校验 + 代码实现）
- Auth API 不接受 `x-session-id` 作为凭证：PASS（测试覆盖）
- 无默认管理员、无默认密码：PASS（本阶段未实现）

## 13. 实际修改文件

- `backend/config.py`
- `backend/main.py`
- `backend/models/schemas.py`
- `backend/requirements.txt`
- `backend/services/auth_service.py`
- `backend/dependencies/__init__.py`
- `backend/dependencies/auth.py`
- `backend/routers/auth.py`
- `backend/tests/test_auth_service.py`
- `backend/tests/test_auth_api.py`
- `PHASE5_1B_AUTH_API_UAT.md`

## 14. 回滚方式

- 设置：
  - `AUTH_V1_ENABLED=false`
  - `AUTH_COOKIE_REQUIRED=false`
- 由于 Chat/Watch/Alert 尚未接入正式 Auth，关闭后原系统行为保持不变。

