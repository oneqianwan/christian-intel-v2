# PHASE5_4A_CHAT_USER_OWNERSHIP_UAT

## Baseline

- Branch: `phase5/auth-rbac-admin-v1`
- Baseline Commit: `4c395987bbf1a4bce2d238ecce119216c55a97bf`
- Phase Scope: backend-only Chat / Conversation ownership boundary
- Frontend Status: unchanged in this phase
- Watch/Alert Status: Phase 5.3 completed previously, not modified in this phase

## Architecture Audit Result

### Required Audit Facts

1. Chat related real tables: `conversations`, `messages`, `request_traces`, `user_profiles`
2. Conversation real model name: `Conversation`
3. Message real model name: `Message`
4. Current Conversation id type: `String`
5. Current Message to Conversation relation: `Message.conversation_id -> Conversation.id` by string foreign-key-like linkage in application queries
6. Current `/api/chat/simple` real entry: `backend/routers/chat.py` -> `chat_simple()`
7. Current `/api/chat/stream` real entry: `backend/routers/chat.py` -> `chat_stream()`
8. Current Conversation list API: `GET /api/conversations`
9. Current Conversation detail API: `GET /api/conversations/{conversation_id}` (added in this phase because the backend previously had no dedicated detail route)
10. Current Conversation delete API: `DELETE /api/conversations/{conversation_id}`
11. Current Message persistence location: `messages` table via `backend/routers/chat.py`
12. Current Chat history read path: `_load_history()` in `backend/routers/chat.py`, then `db.query(Message).filter(Message.conversation_id == conversation_id).order_by(Message.created_at.asc())`
13. Current Chat history shared across users before this phase: yes, effectively global by `conversation_id` only
14. Current frontend conversation list backend API: `GET /api/conversations`
15. Current session/user identity artifacts found during audit: backend historically accepted `x-session-id` in some legacy paths; frontend Chat flow does not use `x-session-id` for formal auth and stores chat state in Zustand memory, not localStorage-based chat ownership
16. Current `/chat/simple` and `/chat/stream` still use different answer-generation paths: yes, `think()` vs `Brain.think_stream()`
17. Current SSE auth failure safety before this phase: unsafe; stream could reach `StreamingResponse(200)` before ownership/auth rejection
18. Current test coverage before this phase: no dedicated formal-user chat ownership suite
19. Current database migration mechanism: startup schema compatibility path in `backend/models/database.py` using `init_db()` + `_ensure_schema_compatibility()` + idempotent `ALTER TABLE` / `CREATE INDEX IF NOT EXISTS`
20. Current legacy anonymous chat identification: by anonymous/global conversation records with `owner_user_id IS NULL`; no formal user binding

### Frontend Call Chain Audit

- `frontend/src/components/ChatArea.tsx` uses streaming chat
- `frontend/src/services/api.ts` / stores use:
  - `GET /api/conversations`
  - `POST /api/conversations`
  - `GET /api/conversations/{id}/messages`
  - `POST /api/chat/stream`
- Frontend does not currently call `/api/chat/simple`
- Frontend was intentionally not modified in Phase 5.4A

## Design Summary

### Feature Flag

- Added backend feature flag: `CHAT_USER_OWNERSHIP_ENABLED`
- Default value: `false`
- Rollback method: set `CHAT_USER_OWNERSHIP_ENABLED=false`

### Data Model

- `Conversation` now includes nullable `owner_user_id -> users.id`
- New ownership index: `conversations(owner_user_id, updated_at)`
- Message model unchanged for ownership fielding
- New message query index: `messages(conversation_id, created_at)`
- `owner_user_id` is nullable for legacy compatibility
- New-mode conversations must write non-null `owner_user_id`
- API responses do not expose `owner_user_id`

### Message Ownership Choice

- Final choice: do not add `Message.owner_user_id`
- Ownership is enforced through `conversation_id -> Conversation.owner_user_id`
- This matches the existing real query shape and avoids unnecessary schema duplication
- Message reads and writes first validate the target conversation under owner scope

### Auth Boundary

- New mode uses Phase 5.1 formal auth dependency only
- Cookie is resolved by existing auth dependency, not by custom cookie parsing
- Client-supplied `user_id`, `owner_user_id`, `public_id`, `email`, `x-session-id` are not trusted for formal identity
- `x-session-id` cannot override logged-in user ownership
- Auth disabled while chat ownership enabled fails safely with `503 AUTH_DISABLED`

## Implemented Backend Changes

- `backend/config.py`
  - added `CHAT_USER_OWNERSHIP_ENABLED=false`
- `backend/models/database.py`
  - added `Conversation.owner_user_id`
  - added ownership/message indexes
  - extended startup schema compatibility migration
- `backend/dependencies/chat_auth.py`
  - added chat-specific current-user resolution wrapper
- `backend/services/chat_ownership.py`
  - added shared ownership filtering / 401 / 404 logic
- `backend/routers/conversations.py`
  - create/list/detail/update/pin/delete/messages now owner-scoped in new mode
- `backend/routers/chat.py`
  - simple and stream share ownership pre-check path
  - stream auth/ownership failure now occurs before `StreamingResponse`
  - new-mode stream persists owned conversation/messages
  - old-mode stream remains legacy behavior
- `backend/services/brain.py`
  - blocked unsafe fallback to most recent `UserProfile` when chat ownership mode is enabled
- `backend/scripts/migrate_legacy_chat_owner.py`
  - added explicit legacy ownership migration CLI
- `backend/scripts/verify_chat_user_ownership.py`
  - added static security/architecture verification script
- `backend/tests/chat_ownership_testkit.py`
  - added shared runtime fixture helpers
- `backend/tests/test_chat_user_ownership.py`
  - added feature flag / simple / ownership / legacy hidden / auth lifecycle tests
- `backend/tests/test_chat_stream_ownership.py`
  - added SSE ownership coverage
- `backend/tests/test_chat_owner_migration.py`
  - added migration CLI coverage

## Feature Flag Behavior

### Flag = false

- Chat remains legacy-compatible
- Login is not required
- `/api/chat/simple` remains available without auth
- `/api/chat/stream` remains available without auth
- Legacy stream behavior remains non-persistent
- Legacy `owner_user_id IS NULL` data remains visible through old flow
- Frontend current behavior is not broken

### Flag = true

- Chat / Conversation API requires formal authenticated user
- Identity source is HttpOnly auth cookie only
- Unauthenticated access returns `401 AUTH_REQUIRED`
- Auth disabled returns `503 AUTH_DISABLED`
- New conversations persist `owner_user_id=current_user.id`
- Conversation list/detail/update/delete/messages are owner-filtered
- Cross-user access returns `404 CONVERSATION_NOT_FOUND`
- Legacy `owner_user_id IS NULL` conversations are hidden by default
- No automatic claiming of legacy anonymous conversations

## Ownership Behavior

### Conversation Ownership

- Create conversation writes `owner_user_id=current_user.id`
- List/detail/update/pin/delete/messages are filtered by `owner_user_id`
- Cross-user access returns `404`, not `403`
- NULL-owner legacy conversations are excluded in new mode

### Message Ownership

- Message persistence remains in `messages`
- Message writes occur only after conversation ownership validation
- Message reads require conversation ownership validation first
- No direct client-controlled ownership field exists in message writes

### Simple Path

- `/api/chat/simple` now uses formal current user in new mode
- New conversation writes owner
- Existing conversation requires owner match
- Cross-user `conversation_id` returns `404`
- Spoofed `x-session-id` / `owner_user_id` / `user_id` / `public_id` do not affect ownership

### Stream Path

- `/api/chat/stream` now performs auth/ownership validation before establishing SSE response
- New-mode stream creates owned conversation and persists owned user/assistant messages
- Cross-user `conversation_id` returns `404` before stream begins
- Old-mode stream remains legacy-compatible and non-persistent

### SSE Auth Failure Behavior

- Verified: unauthenticated stream returns `401`
- Verified: cross-user stream returns `404`
- Verified: rejection happens before establishing `200 text/event-stream`
- Verified: no cross-user conversation content is leaked in failure path

## Database Migration

- Migration mechanism reused existing project startup schema compatibility process
- Empty DB initialization succeeds
- Existing DB incremental upgrade succeeds
- `owner_user_id` remains nullable
- Existing conversations/messages are preserved
- Index creation is idempotent
- Repeated startup does not duplicate columns
- SQLite change was implemented using the project's existing additive schema upgrade style

## Legacy Migration CLI

### CLI Contract

- File: `backend/scripts/migrate_legacy_chat_owner.py`
- Required args:
  - `--database`
  - `--email`
  - `--legacy-conversation-id`
  - exactly one of `--dry-run` or `--apply`
- Default safety posture: dry-run unless `--apply` is explicitly requested

### CLI Rules Enforced

- Requires explicit database path / URL
- Refuses to create users
- Requires existing active target user
- Only migrates explicitly specified legacy conversation id
- Only updates `owner_user_id IS NULL` conversations
- Does not overwrite conversations already owned by another user
- Does not modify `AuthSession`
- Message ownership remains conversation-linked
- Reports `matched`, `updated`, `skipped`, `conflicts`

### CLI UAT Summary

- Dry-run: passed, no writes
- Apply: passed, owner updated
- Apply again: passed, idempotent
- Missing user: fails safely
- Disabled user: fails safely
- Missing conversation: safe zero-match success

## Automated Validation

### Static Security Check

- Command: `python backend/scripts/verify_chat_user_ownership.py`
- Result: `CHAT_USER_OWNERSHIP_CHECK=PASS`

### Chat Ownership Tests

- `backend/tests/test_chat_user_ownership.py`: `9 passed`
- `backend/tests/test_chat_stream_ownership.py`: `4 passed`
- `backend/tests/test_chat_owner_migration.py`: `7 passed`
- Chat ownership focused total: `20 passed, 0 failed`

### Auth Regression

- Auth regression batch executed
- Result: `45 passed`
- Includes auth models, auth service, auth API, create_admin, auth lifecycle

### Watch/Alert Regression

- Static watch/alert verification executed
- Result: `PASS`
- Watch/Alert regression batch executed
- Result: `59 passed`
- Confirms Watch/Alert was not modified by this phase

## Backend UAT Evidence

### Runtime Configuration

- `AUTH_V1_ENABLED=true`
- `AUTH_COOKIE_REQUIRED=false`
- `AUTH_COOKIE_SECURE=false`
- `CHAT_USER_OWNERSHIP_ENABLED=true`
- `AUTH_CORS_ALLOW_ORIGINS=http://127.0.0.1:5174`

### UAT Results

- Login:
  - User A: `200`
  - User B: `200`
- Simple:
  - User A create/send: `200`
  - created conversation id: `99cd5369-0918-4c1c-9455-3f11665ccde0`
- Stream:
  - User B create/send: `200`
  - created conversation id: `f656a5ec-f448-4481-94ad-5f0f6196b1a3`
- List isolation:
  - User A list ids: `["99cd5369-0918-4c1c-9455-3f11665ccde0"]`
  - User B list ids: `["f656a5ec-f448-4481-94ad-5f0f6196b1a3"]`
- Cross-user isolation:
  - A get B: `404`
  - B get A: `404`
  - A simple to B conversation: `404`
  - B stream to A conversation: `404`
- Legacy NULL owner hidden:
  - A list contains legacy: `false`
  - A detail legacy status: `404`
  - unauth + spoof header status: `401`
- Spoofed `x-session-id`:
  - A list with spoofed header: `200`
  - returned ids still only A-owned conversation
- Auth lifecycle:
  - logout-all endpoint: `200`
  - old cookie after logout-all: `401 SESSION_REVOKED`
  - change-password endpoint: `200`
  - old cookie after password change: `401 SESSION_REVOKED`
- Legacy migration CLI:
  - dry-run return code: `0`
  - apply return code: `0`
  - apply-again return code: `0`
  - missing-user return code: `1`
  - disabled-user return code: `1`
  - missing-conversation return code: `0`

## Security Conclusions

- New mode does not auto-claim legacy anonymous Chat
- New mode does not trust `x-session-id`
- Legacy `owner_user_id IS NULL` conversations are hidden by default
- Feature flag defaults to `false`
- Frontend has not yet been migrated to formal Chat auth UX
- Phase 5.4B should not be enabled in production by default before frontend integration
- Brain large-object architecture was not refactored
- This phase only adds backend identity boundary and isolation
- `VITE_AUTH_REQUIRED` remains default `false`

## Known Limitations

- Frontend Chat still uses pre-migration behavior and is not yet wired to formal login UX
- Legacy NULL-owner conversations are intentionally hidden, not auto-claimed
- Message ownership remains conversation-linked, not denormalized onto message rows
- Brain answer-generation architecture remains split between simple and stream; only ownership boundary was unified

## Rollback Plan

- Set `CHAT_USER_OWNERSHIP_ENABLED=false`
- Result:
  - Chat returns to legacy mode
  - `owner_user_id` column remains in schema
  - no conversations/messages are deleted
  - no new/old conversations are auto-merged
  - Watch/Alert remains unaffected

## Actual Files Modified

- `backend/config.py`
- `backend/models/database.py`
- `backend/routers/chat.py`
- `backend/routers/conversations.py`
- `backend/services/brain.py`
- `backend/dependencies/chat_auth.py`
- `backend/services/chat_ownership.py`
- `backend/scripts/migrate_legacy_chat_owner.py`
- `backend/scripts/verify_chat_user_ownership.py`
- `backend/tests/chat_ownership_testkit.py`
- `backend/tests/test_chat_user_ownership.py`
- `backend/tests/test_chat_stream_ownership.py`
- `backend/tests/test_chat_owner_migration.py`
- `PHASE5_4A_CHAT_USER_OWNERSHIP_UAT.md`

## Temporary File Cleanup

- Temporary DBs, backup folders, transient UAT JSON/script artifacts, and probe DBs created during Phase 5.4A must be removed before external commit
- Final git boundary check must show:
  - no frontend changes
  - no Watch/Alert code changes
  - no temp DB files
  - no `_db_backups`
  - no cookie / response dump / log artifacts
