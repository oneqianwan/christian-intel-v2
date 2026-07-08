# PHASE5_4B_CHAT_FRONTEND_AUTH_UAT

## Baseline

- Branch: `phase5/auth-rbac-admin-v1`
- Baseline Commit: `1bed492157733677c9983024b7b797f86d050d24`
- Scope: Frontend Chat / Conversation 正式登录身份接入与状态清理（Phase 5.4B）+ Phase 5.4B-2 Hotfix
- Constraints honored:
  - Backend: 未修改
  - Watch/Alert：未修改所有权/鉴权/业务逻辑；仅修复 UI 侧登出/切换导致的 AbortError 误报红字
  - 不开启全站强制登录（`VITE_AUTH_REQUIRED` 仍默认 false）
  - 不重构 Brain

## Frontend Architecture Audit (真实文件审计)

### 1) Chat API Client 在哪里

- Chat/Conversation API client 入口： [api.ts](file:///C:/Users/baiwan/christian-intel-v2/frontend/src/services/api.ts)

### 2) `/api/chat/simple` 调用方式

- Phase 5.4B 前：前端未调用 `/api/chat/simple`（仅有 stream）。
- Phase 5.4B 实现后：新增 `sendChatSimple()`（未接入 UI，供后续或回滚时使用）。[api.ts](file:///C:/Users/baiwan/christian-intel-v2/frontend/src/services/api.ts)

### 3) `/api/chat/stream` 调用方式

- `fetch + ReadableStream.getReader()` 流式读取，按 `data:` / `event:` 解析。[api.ts](file:///C:/Users/baiwan/christian-intel-v2/frontend/src/services/api.ts)
- UI 侧分发处理：按 `thinking/tool_call/content/done/error` 等事件更新 UI。[ChatArea.tsx](file:///C:/Users/baiwan/christian-intel-v2/frontend/src/components/ChatArea.tsx)

### 4) Conversation 列表接口调用方式

- `GET /api/conversations`：`fetchConversations()`。[api.ts](file:///C:/Users/baiwan/christian-intel-v2/frontend/src/services/api.ts)
- Sidebar 初始化/登录态变化时加载列表。[Sidebar.tsx](file:///C:/Users/baiwan/christian-intel-v2/frontend/src/components/Sidebar.tsx)

### 5) Conversation 详情接口调用方式

- UI 目前不直接调用 `/api/conversations/:id`；后端存在该接口用于完整契约。[conversations.py](file:///C:/Users/baiwan/christian-intel-v2/backend/routers/conversations.py)
- 前端 API client 已补齐 `fetchConversation()` 以覆盖契约与后续用例。[api.ts](file:///C:/Users/baiwan/christian-intel-v2/frontend/src/services/api.ts)

### 6) Conversation 删除接口调用方式

- Sidebar 删除入口：`deleteConversation()` -> `DELETE /api/conversations/:id`。[Sidebar.tsx](file:///C:/Users/baiwan/christian-intel-v2/frontend/src/components/Sidebar.tsx)

### 7) 新会话按钮逻辑

- Sidebar “+ 新会话”：
  - legacy：直接创建
  - authenticated-user：未登录跳登录；已登录创建并写入 store。[Sidebar.tsx](file:///C:/Users/baiwan/christian-intel-v2/frontend/src/components/Sidebar.tsx)

### 8) 会话列表加载逻辑

- legacy：页面挂载即加载
- authenticated-user：仅 `status === authenticated` 时加载，未登录/loading 时不请求并清空列表。[Sidebar.tsx](file:///C:/Users/baiwan/christian-intel-v2/frontend/src/components/Sidebar.tsx)

### 9) Chat 历史加载逻辑

- `fetchMessages(currentId)`：首次加载与 2 秒轮询同步；在 authenticated-user 下要求 `status === authenticated` 才运行；401/404 会触发清理。[ChatArea.tsx](file:///C:/Users/baiwan/christian-intel-v2/frontend/src/components/ChatArea.tsx)

### 10) SSE/stream 实现方式

- 使用 `fetch + ReadableStream`，不是 EventSource。[api.ts](file:///C:/Users/baiwan/christian-intel-v2/frontend/src/services/api.ts)

### 11) API Base URL 与 Vite proxy 关系

- API base：`VITE_API_BASE_URL`（默认 `http://127.0.0.1:8000/api`）。[api.ts](file:///C:/Users/baiwan/christian-intel-v2/frontend/src/services/api.ts)

### 12) 是否硬编码 127.0.0.1:8000 或 localhost

- ChatArea 原本存在 `http://localhost:8000/api/...` 多处调用；Phase 5.4B 已将 ChatArea 内相关调用改为 `buildApiUrl(...)`，避免混用 host 导致 CORS/调试困扰。[ChatArea.tsx](file:///C:/Users/baiwan/christian-intel-v2/frontend/src/components/ChatArea.tsx)

### 13) 是否发送 x-session-id

- Chat/Conversation 主链路：不发送 `x-session-id`。[api.ts](file:///C:/Users/baiwan/christian-intel-v2/frontend/src/services/api.ts)
- Watch/Alert 仍保留 legacy-session 的 `x-session-id` 行为，且 authenticated-user 会主动删除该 header（本阶段未改 Watch/Alert 业务文件）。[watchAlerts.ts](file:///C:/Users/baiwan/christian-intel-v2/frontend/src/api/watchAlerts.ts)

### 14) 是否从 localStorage/sessionStorage 读取 Chat 身份

- Chat/Conversation：不读取 localStorage/sessionStorage 身份，不存 token。

### 15) Chat 状态存储位置

- Conversation：Zustand store。[conversationStore.ts](file:///C:/Users/baiwan/christian-intel-v2/frontend/src/stores/conversationStore.ts)
- Messages：Zustand store。[messageStore.ts](file:///C:/Users/baiwan/christian-intel-v2/frontend/src/stores/messageStore.ts)
- in-flight stream：ChatArea 内 `AbortController` + refs/state。[ChatArea.tsx](file:///C:/Users/baiwan/christian-intel-v2/frontend/src/components/ChatArea.tsx)

### 16) logout 后是否清理 Chat 状态

- Phase 5.4B：已实现。AuthProvider 在 authenticated-user 模式下，检测 `user.public_id` 变化（login/logout/logout-all/change-password/user switch）时调用 `clearChatState()`：清空 store + abort in-flight stream。[AuthProvider.tsx](file:///C:/Users/baiwan/christian-intel-v2/frontend/src/auth/AuthProvider.tsx)、[cleanup.ts](file:///C:/Users/baiwan/christian-intel-v2/frontend/src/features/chat/cleanup.ts)

### 17) AuthProvider 能否触发身份变化

- 能：login / logout / logoutAll / changePassword / refreshUser 均会更新 `AuthContext`。[AuthProvider.tsx](file:///C:/Users/baiwan/christian-intel-v2/frontend/src/auth/AuthProvider.tsx)

### 18) 错误提示机制

- ChatArea 使用内置卡片（renderFeedbackCard）/ streamingContent 文本提示；Sidebar 在创建失败时 `alert` 并记录 console error。[ChatArea.tsx](file:///C:/Users/baiwan/christian-intel-v2/frontend/src/components/ChatArea.tsx)、[Sidebar.tsx](file:///C:/Users/baiwan/christian-intel-v2/frontend/src/components/Sidebar.tsx)

### 19) Chat 自动轮询/自动请求位置

- `fetchMessages()` 每 2 秒轮询同步当前会话消息；authenticated-user 未登录/loading 时不轮询。[ChatArea.tsx](file:///C:/Users/baiwan/christian-intel-v2/frontend/src/components/ChatArea.tsx)

### 20) 前端测试框架与已有 Chat 测试

- 测试框架：Vitest + React Testing Library（项目既有）。[package.json](file:///C:/Users/baiwan/christian-intel-v2/frontend/package.json)
- Phase 5.4B 新增：
  - identity tests：[identity.test.ts](file:///C:/Users/baiwan/christian-intel-v2/frontend/src/features/chat/__tests__/identity.test.ts)
  - chat api client tests：[chatAuth.test.ts](file:///C:/Users/baiwan/christian-intel-v2/frontend/src/api/__tests__/chatAuth.test.ts)
  - chat UI gating tests：[ChatArea.auth.test.tsx](file:///C:/Users/baiwan/christian-intel-v2/frontend/src/components/__tests__/ChatArea.auth.test.tsx)
  - chat state cleanup tests：[chatAuthState.test.ts](file:///C:/Users/baiwan/christian-intel-v2/frontend/src/stores/__tests__/chatAuthState.test.ts)

## Backend Contract Audit (真实契约核对)

- 后端 Chat ownership 开关依赖 Cookie Auth（当 `CHAT_USER_OWNERSHIP_ENABLED=true` 时）。[chat_auth.py](file:///C:/Users/baiwan/christian-intel-v2/backend/dependencies/chat_auth.py)
- Conversations API 全链路已按 owner scope 限制（Phase 5.4A 已完成，本阶段不修改后端）。[conversations.py](file:///C:/Users/baiwan/christian-intel-v2/backend/routers/conversations.py)

## Frontend Feature Flag

- 新增 `VITE_CHAT_USER_OWNERSHIP_ENABLED=false`（默认必须为 false）。[.env.example](file:///C:/Users/baiwan/christian-intel-v2/frontend/.env.example)

### 身份模式统一封装

- 新增统一 identity module： [identity.ts](file:///C:/Users/baiwan/christian-intel-v2/frontend/src/features/chat/identity.ts)
- 模式矩阵：
  - `VITE_CHAT_USER_OWNERSHIP_ENABLED=false` -> `legacy`
  - `VITE_CHAT_USER_OWNERSHIP_ENABLED=true` 且 `VITE_AUTH_V1_ENABLED=true` -> `authenticated-user`
  - `VITE_CHAT_USER_OWNERSHIP_ENABLED=true` 且 `VITE_AUTH_V1_ENABLED=false` -> `invalid`（安全失败，不请求 Chat/Conversation）

## API Client 迁移（Cookie / credentials include）

- authenticated-user 模式：
  - 所有 Chat/Conversation 请求 `credentials: 'include'`
  - 不发送 `x-session-id`
  - 不发送 `user_id/owner_user_id/public_id/email` 作为认证参数
  - invalid 模式不发请求，直接 503 fail-safe
- legacy 模式：
  - 保持旧行为（不强制 `credentials: include`），不要求登录

实现位置：[api.ts](file:///C:/Users/baiwan/christian-intel-v2/frontend/src/services/api.ts)

## Chat UI 行为与状态清理

### 未登录 / Auth loading / invalid

- authenticated-user + unauthenticated：ChatArea 显示“需要登录”卡片与“去登录”按钮；Sidebar 不请求 list。[ChatArea.tsx](file:///C:/Users/baiwan/christian-intel-v2/frontend/src/components/ChatArea.tsx)、[Sidebar.tsx](file:///C:/Users/baiwan/christian-intel-v2/frontend/src/components/Sidebar.tsx)
- authenticated-user + loading：ChatArea 显示“检查登录状态中”，不请求 Chat API。[ChatArea.tsx](file:///C:/Users/baiwan/christian-intel-v2/frontend/src/components/ChatArea.tsx)
- invalid：ChatArea 显示“配置错误”，不请求 Chat API。[ChatArea.tsx](file:///C:/Users/baiwan/christian-intel-v2/frontend/src/components/ChatArea.tsx)

### 401/404/503 处理

- API client 统一抛出 `ChatApiError`（status/code），stream 在 `response.ok` 前终止，不进入 token loop。[api.ts](file:///C:/Users/baiwan/christian-intel-v2/frontend/src/services/api.ts)
- 401：触发 `auth.refreshUser()` 并引导重新登录；同时由 AuthProvider 清理 chat store（cookie revoked / logout-all / change-password）。[AuthProvider.tsx](file:///C:/Users/baiwan/christian-intel-v2/frontend/src/auth/AuthProvider.tsx)
- 404：清理 `activeConversationId`（`setCurrentId(null)`），显示会话不存在提示。[ChatArea.tsx](file:///C:/Users/baiwan/christian-intel-v2/frontend/src/components/ChatArea.tsx)
- 503：显示 Chat 功能不可用，不降级匿名模式。

### 状态清理与 stream abort

- 新增 Chat cleanup module（store reset + abort handler registry）：[cleanup.ts](file:///C:/Users/baiwan/christian-intel-v2/frontend/src/features/chat/cleanup.ts)
- AuthProvider 在 authenticated-user 模式下监听 `user.public_id` 变化并 `clearChatState()`：[AuthProvider.tsx](file:///C:/Users/baiwan/christian-intel-v2/frontend/src/auth/AuthProvider.tsx)
- ChatArea 注册 abort handler，确保 logout/user switch 时中断 in-flight stream，且不会写入下一用户 UI。[ChatArea.tsx](file:///C:/Users/baiwan/christian-intel-v2/frontend/src/components/ChatArea.tsx)

## 自动化验证（本阶段要求）

### 静态检查

- `npm run check:chat-user-auth` -> `CHAT_USER_AUTH_UI_CHECK=PASS`
- `npm run check:auth-ui` -> `AUTH_UI_CHECK=PASS`
- `npm run check:watch-alert-contract` -> `WATCH_ALERT_CONTRACT_CHECK=PASS`
- `npm run check:watchlist-ui` -> `WATCHLIST_UI_CHECK=PASS`
- `npm run check:alerts-ui` -> `ALERTS_UI_CHECK=PASS`
- `npm run check:watch-alert-auth` -> `WATCH_ALERT_AUTH_BOUNDARY_CHECK=PASS`
- `npm run check:watch-alert-user-auth` -> `WATCH_ALERT_USER_AUTH_UI_CHECK=PASS`

### 单元/组件测试

- `npm run test:chat-user-auth` -> 13 passed, 0 failed
- `npm run test:auth` -> 35 passed, 0 failed
- `npm run test:watch-alert-user-auth` -> 22 passed, 0 failed

### Build

- `npm run build` -> PASS

## 浏览器 UAT

### Phase 5.4B 用户真实浏览器 UAT（用户已完成）

- 未登录首页正常打开：PASS
- 未登录 Chat 显示需要登录：PASS
- 未登录不能直接使用 Chat / Conversation：PASS
- 左下角显示“登录”：PASS
- 点击“去登录”后登录成功：PASS
- 登录后回到 Chat 页面：PASS
- 左下角显示 Chat UAT Admin：PASS
- Chat 输入框恢复可用：PASS
- 登录后发送消息成功：PASS
- 同一会话内继续发送第二条消息成功：PASS
- 第二条消息收到 OK 回复：PASS
- 刷新页面后聊天内容仍在：PASS
- 刷新后无红色错误：PASS
- 退出登录后回到登录页面：PASS
- 同一用户重新登录后，之前聊天记录仍在：PASS

### Phase 5.4B-2 发现问题

- 现象：同一用户退出登录后再次登录，页面会短暂出现红色提示“操作失败，请稍后重试”；刷新页面后消失
- 影响：属于真实 UX 缺陷，Phase 5.4C 前必须修复

### Phase 5.4B-2 Root Cause（真实根因）

- 根因：Sidebar 的 Alerts 通知入口组件 NotificationBell 在登出/切换身份时会 `abort()` 正在进行的 unread-count 轮询请求；该请求抛出 `AbortError`（DOMException），未被组件 catch 过滤，落入兜底文案分支显示“操作失败，请稍后重试”
- 证据：
  - 兜底文案位置：[NotificationBell.tsx](file:///C:/Users/baiwan/christian-intel-v2/frontend/src/components/NotificationBell.tsx)
  - abort 发生位置：[NotificationBell.tsx](file:///C:/Users/baiwan/christian-intel-v2/frontend/src/components/NotificationBell.tsx)
  - AbortError 未过滤导致兜底文案：[NotificationBell.tsx](file:///C:/Users/baiwan/christian-intel-v2/frontend/src/components/NotificationBell.tsx)

### Phase 5.4B-2 Fix（不掩盖真实错误的最小修复）

- 修复：NotificationBell 在 catch 中识别 `AbortError` 并直接 return，不写入 `inlineMessage`
- 结果：登出/重登（或身份切换）触发的“预期 abort”不再显示通用红字；非 abort 的真实错误（401/429/503/网络错误）仍会按原逻辑显示

### Phase 5.4B-2 自动化回归（均 Exit Code 0）

- `npm run check:chat-user-auth` -> `CHAT_USER_AUTH_UI_CHECK=PASS`
- `npm run test:chat-user-auth` -> 13 passed, 0 failed
- `npm run check:auth-ui` -> `AUTH_UI_CHECK=PASS`
- `npm run test:auth` -> 35 passed, 0 failed
- `npm run check:watch-alert-contract` -> `WATCH_ALERT_CONTRACT_CHECK=PASS`
- `npm run check:watchlist-ui` -> `WATCHLIST_UI_CHECK=PASS`
- `npm run check:alerts-ui` -> `ALERTS_UI_CHECK=PASS`
- `npm run check:watch-alert-auth` -> `WATCH_ALERT_AUTH_BOUNDARY_CHECK=PASS`
- `npm run check:watch-alert-user-auth` -> `WATCH_ALERT_USER_AUTH_UI_CHECK=PASS`
- `npm run test:watch-alert-user-auth` -> 23 passed, 0 failed
- `npm run build` -> PASS

### Phase 5.4B-2 浏览器复测

- 用户真实浏览器复测时间：`2026-07-08`
- ManualBrowserRetest=PASS
- LogoutReloginRedErrorManualRetest=PASS
- RedErrorAfterLogoutRelogin=PASS
- SameUserConversationRestore=PASS
- ChatSendStillWorks=PASS
- BrainReplyWorks=PASS
- 真实复测结果：
  - 重新登录后红色“操作失败，请稍后重试”已消失
  - 发送 Chat 消息正常
  - Brain 可以正常回复
  - F5 刷新后当前聊天仍在
  - 退出登录后再次登录，左侧历史会话仍在
  - 点进历史会话后，消息内容仍在
  - 数据库核验：`conversations=1`、`messages=2`
- 性能观察：
  - Chat / Brain response time felt slow, but functional and not blocking Phase 5.4B.
- 临时文件清理：
  - `phase5_chat_uat.db deleted`
  - `_db_backups deleted`
- Phase 5.4B browser UAT final status: `PASS`

## 回滚方案

- 前端回滚：`VITE_CHAT_USER_OWNERSHIP_ENABLED=false`
- 后端回滚（Phase 5.4A 已实现）：`CHAT_USER_OWNERSHIP_ENABLED=false`
- 回滚不删除字段、不删除新旧会话、不自动合并新旧数据

## 实际修改文件

- `frontend/.env.example`
- `frontend/package.json`
- `frontend/scripts/verify-chat-user-auth.mjs`
- `frontend/scripts/verify-alerts-ui.mjs`
- `frontend/scripts/verify-watch-alert-user-auth.mjs`
- `frontend/src/auth/AuthProvider.tsx`
- `frontend/src/components/ChatArea.tsx`
- `frontend/src/components/Sidebar.tsx`
- `frontend/src/services/api.ts`
- `frontend/src/stores/conversationStore.ts`
- `frontend/src/stores/messageStore.ts`
- `frontend/src/features/chat/identity.ts`
- `frontend/src/features/chat/cleanup.ts`
- `frontend/src/features/chat/__tests__/identity.test.ts`
- `frontend/src/api/__tests__/chatAuth.test.ts`
- `frontend/src/components/__tests__/ChatArea.auth.test.tsx`
- `frontend/src/stores/__tests__/chatAuthState.test.ts`
- `frontend/src/components/NotificationBell.tsx`
- `frontend/src/components/__tests__/NotificationBell.auth.test.tsx`
