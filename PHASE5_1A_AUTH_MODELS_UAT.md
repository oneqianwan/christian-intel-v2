# PHASE 5.1A：User、AuthSession 数据模型与安全迁移基础（UAT）

项目目录：`C:\Users\baiwan\christian-intel-v2`  
分支：`phase5/auth-rbac-admin-v1`  
基线提交：`08774d7b071e2e9e13a35cb1d87c91df3a76ec7a`

## 0. 执行边界声明

- 本阶段仅新增数据模型、迁移脚本与测试；未新增任何认证 API、未修改任何 Router/Service、未修改前端。
- 未恢复 `session-1`；本阶段也未改动现有 `x-session-id` 行为。
- 原始 `session_token` 不入库、不记录日志、不以任何形式返回给前端 JavaScript（本阶段不生成 token，仅为未来预留 `token_hash` 字段）。

## 1. 基线与工作树

- Branch=phase5/auth-rbac-admin-v1
- HEAD=08774d7b071e2e9e13a35cb1d87c91df3a76ec7a
- TrackedWorkingTree=Clean（变更前）

说明：按要求“在项目外保存当前完整状态”时，运行环境对 `C:\Users\baiwan\phase5_1a_status_before.txt` 的写入路径有限制，因此改为保存至：

- `C:\Users\baiwan\.trae\builtin\work\phase5_1a_status_before.txt`

## 2. 数据库机制审计（真实代码结论）

### 2.1 SQLAlchemy Base 的唯一定义

- Base 定义位置： [database.py](file:///C:/Users/baiwan/christian-intel-v2/backend/models/database.py#L630-L633)
- 结论：项目仅使用这一处 `Base = declarative_base()`，本阶段未创建第二套 Base。

### 2.2 模型如何注册进 metadata

- 现有模式：各模型模块通过 `from models.database import Base` 绑定到同一 metadata（例如 [watch_alert.py](file:///C:/Users/baiwan/christian-intel-v2/backend/models/watch_alert.py#L4-L8)）。
- 本阶段新增 auth 模型也遵循同样模式： [auth.py](file:///C:/Users/baiwan/christian-intel-v2/backend/models/auth.py)。

### 2.3 init_db 是否调用 create_all

- `init_db()` 会调用 `Base.metadata.create_all(bind=engine)`（[database.py](file:///C:/Users/baiwan/christian-intel-v2/backend/models/database.py#L1275-L1324)）。
- 但本阶段迁移脚本不会调用 `init_db()`，避免触发 `_ensure_schema_compatibility()` 对既有表做 ALTER/补索引。

### 2.4 项目是否使用 Alembic

- 未发现 `alembic.ini` 或 `alembic/` 目录（结论：未使用 Alembic）。

### 2.5 当前 DATABASE_URL 配置方式

- Settings 默认：`sqlite:///backend/cio_intelligence.db`（[config.py](file:///C:/Users/baiwan/christian-intel-v2/backend/config.py#L96-L99)）。
- `SettingsConfigDict(env_file=backend/.env)` + `load_dotenv(..., override=True)`（[config.py](file:///C:/Users/baiwan/christian-intel-v2/backend/config.py#L9-L11)、[config.py](file:///C:/Users/baiwan/christian-intel-v2/backend/config.py#L138-L139)）。

### 2.6 时间字段规范

- 既有模型普遍使用 `datetime.utcnow`（例如 [database.py](file:///C:/Users/baiwan/christian-intel-v2/backend/models/database.py#L640-L642)、[watch_alert.py](file:///C:/Users/baiwan/christian-intel-v2/backend/models/watch_alert.py#L37-L39)）。
- 本阶段新增模型同样使用 `datetime.utcnow`。

### 2.7 命名、索引与 CheckConstraint 风格

- 风格参考既有 Watch/Alert：`ck_*`（CheckConstraint）、`ix_*`（Index）、`ux_*`（UniqueConstraint）命名（[watch_alert.py](file:///C:/Users/baiwan/christian-intel-v2/backend/models/watch_alert.py#L10-L24)）。
- 本阶段新增 users/auth_sessions 也遵循同样命名规则（[auth.py](file:///C:/Users/baiwan/christian-intel-v2/backend/models/auth.py#L10-L47)）。

### 2.8 SQLite 外键是否启用

- 现有 SQLite connect 事件设置了 `PRAGMA busy_timeout=1000`，未显式设置 `PRAGMA foreign_keys=ON`（[database.py](file:///C:/Users/baiwan/christian-intel-v2/backend/models/database.py#L498-L538)）。
- 结论：SQLite 外键强制性不保证开启（本阶段不改变既有行为；外键存在于 schema，但 SQLite 运行时是否强制依赖后续统一策略）。

## 3. User 模型（users）

文件： [auth.py](file:///C:/Users/baiwan/christian-intel-v2/backend/models/auth.py)

字段（均满足约束要求）：

- `id`：String UUID，PK（内部主键，不作为凭证）
- `public_id`：String UUID，非空，唯一（用于管理后台展示/外部标识，不作为凭证）
- `email`：String(320)，非空；含 `email = trim(email)` 约束防止首尾空格
- `email_normalized`：String(320)，非空，唯一；含 `email_normalized = lower(trim(email_normalized))` 约束；用于未来登录查询唯一键
- `password_hash`：非空（可容纳 Argon2id/bcrypt 字符串；本阶段不实现哈希服务）
- `display_name`：非空（默认 `"User"`；不具备认证作用）
- `role`：非空，默认 `viewer`；CheckConstraint 限定 `super_admin|admin|analyst|viewer`
- `status`：非空，默认 `active`；CheckConstraint 限定 `active|disabled|pending`
- `email_verified_at` / `last_login_at`：可空
- `created_at` / `updated_at`：非空 UTC
- `deleted_at`：可空（软删除字段，首期不实现删除 API）

索引/约束：

- `ux_users_public_id`
- `ux_users_email_normalized`
- `ix_users_email_normalized`
- `ck_users_role`、`ck_users_status`、`ck_users_email_trimmed`、`ck_users_email_normalized`

邮箱复用规则（首期冻结）：

- 软删除用户的 email/email_normalized **不自动复用**（因为 unique 约束仍会阻止复用；除非未来明确迁移策略放开）。

## 4. AuthSession 模型（auth_sessions）

文件： [auth.py](file:///C:/Users/baiwan/christian-intel-v2/backend/models/auth.py)

字段：

- `id`：String UUID，PK（内部主键，不作为 cookie）
- `public_id`：String UUID，非空，唯一（用于管理后台展示/撤销/审计，不作为认证凭证）
- `user_id`：FK -> `users.id`，非空，索引（未来鉴权时将从 session 查 user，再检查 user.status）
- `token_hash`：String(64)，非空，唯一（仅保存 hash；原始 token 不入库）
- `status`：非空，默认 `active`；CheckConstraint 限定 `active|revoked|expired`
- `created_at`：非空
- `last_seen_at`：可空
- `expires_at`：非空
- `revoked_at`：可空

public_id 与 token_hash 的区别（冻结）：

- `public_id`：用于管理/审计/撤销展示，不作为认证凭证。
- `token_hash`：未来 cookie 中保存的高熵随机 `session_token` 的 hash；数据库只存 hash，绝不存 raw token。

禁止字段确认：

- schema 与测试均确认不存在 `raw_token/session_token/cookie_token` 等字段（见测试用例）。

## 5. ORM 关系

实现：

- `User.auth_sessions`
- `AuthSession.user`

验证：

- 在 `test_auth_models.py` 中完成双向关系查询验证（User -> Sessions 与 Session -> User）。

## 6. Feature Flags（默认关闭）

文件： [config.py](file:///C:/Users/baiwan/christian-intel-v2/backend/config.py)

新增（默认 false）：

- `AUTH_V1_ENABLED=false`
- `AUTH_COOKIE_REQUIRED=false`

本阶段严格不读取这些 Flag，不影响任何现有 Router/Service 行为。

## 7. 迁移实现（无 Alembic）

脚本： [migrate_auth_v1.py](file:///C:/Users/baiwan/christian-intel-v2/backend/scripts/migrate_auth_v1.py)

能力：

- `--database <path-or-url>`：必须提供；支持 SQLite 路径或 SQLAlchemy URL
- `--dry-run`：不写 DB，仅输出当前表清单
- `--apply`：只创建 `users` 和 `auth_sessions` 两张表（使用 `Base.metadata.create_all(..., tables=[...])`，不会修改既有表）
- `--verify`：校验
  - 表存在
  - 必需列存在
  - unique 约束存在
  - 外键存在
  - CheckConstraint 行为可被触发（插入非法 role/status 会失败）
- 幂等：重复执行 `--apply --verify` 不报 “table exists”
- 防误操作：拒绝对默认 `backend/cio_intelligence.db` 执行

事务与数据写入约束：

- `--verify` 在单独事务中执行插入/非法插入校验，并在结束时整体 rollback，确保不会写入任何默认用户或默认 session。

## 8. 测试（必须场景与结果）

### 8.1 test_auth_models.py（模型约束）

文件： [test_auth_models.py](file:///C:/Users/baiwan/christian-intel-v2/backend/tests/test_auth_models.py)

覆盖点（节选）：

- public_id 唯一
- email_normalized 唯一（case-insensitive 依赖 normalized）
- password_hash 必填
- role/status CheckConstraint
- token_hash 唯一
- 关系查询与禁用 raw token 字段

结果：

- PASS（12 cases）

### 8.2 test_auth_migration.py（迁移与兼容）

文件： [test_auth_migration.py](file:///C:/Users/baiwan/christian-intel-v2/backend/tests/test_auth_migration.py)

场景：

- 空库：apply + verify
- 既有库（含 conversations + watch/alert 表）：additive upgrade + 幂等重复执行
- 拒绝无 `--database`

结果：

- PASS（3 cases）

## 9. Phase 4 回归测试（必须 6 组）

执行：

- `tests/test_alert_engine.py`
- `tests/test_alerts_api.py`
- `tests/test_watch_runner.py`
- `tests/test_watch_scheduler.py`
- `tests/test_watch_targets_api.py`
- `tests/test_watch_signals_api.py`

结果：

- PASS（98 tests）

## 10. 运行行为未改变（证据）

- 未修改 `backend/main.py`、未修改任何 `backend/routers/*` 与 `backend/services/*`。
- 新增 Feature Flag 默认关闭，且本阶段任何运行路径不读取。
- 不新增 Cookie、不新增登录要求、不引入新的 401。

## 11. 实际修改文件清单

- `backend/models/auth.py`
- `backend/config.py`
- `backend/scripts/migrate_auth_v1.py`
- `backend/tests/test_auth_models.py`
- `backend/tests/test_auth_migration.py`
- `PHASE5_1A_AUTH_MODELS_UAT.md`

## 12. 已知限制

- SQLite 外键强制性是否开启取决于连接 PRAGMA（当前主工程 connect 事件未设置 `foreign_keys=ON`）；本阶段不改变现有行为，后续 Phase 5.1B/5.2 需要统一策略。
- 本阶段不实现登录/登出/鉴权依赖，Auth 表仅为后续阶段提供基础。

## 13. 回滚方案

- 运行期回滚：保持 `AUTH_V1_ENABLED=false`、`AUTH_COOKIE_REQUIRED=false`（默认即为 false），运行行为不变。
- 数据层回滚：本阶段创建的 `users/auth_sessions` 表可以保留不启用；生产环境不要求 drop 表。

