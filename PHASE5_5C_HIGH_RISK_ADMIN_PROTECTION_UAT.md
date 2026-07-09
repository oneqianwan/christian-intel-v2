# Phase 5.5C High-Risk Admin Protection UAT

## Baseline
- BaselineCommit=`2e61659`
- Branch=`phase5/auth-rbac-admin-v1`
- Scope=`High-risk backend RBAC hardening + legacy identity cleanup only`
- OutOfScope=`frontend admin page`, `Chat / Watch / Alert business logic changes`, `Brain`, `large refactor`

## Audit Summary

### Audited High-Risk Interfaces
- `POST /api/agent/run`
- `GET /api/agent/status`
- `GET /api/agent/logs`
- `GET /api/configs/keys`
- `POST /api/dashboard/manual-update`
- `POST /api/dashboard/inline-entry`
- `POST /api/dashboard/inline-entry/bulk`
- `POST /api/dashboard/people-candidates/review`
- `POST /api/dashboard/quick-people-entry`
- `POST /api/feedback`
- `GET /api/feedback/stats`
- `POST /api/bookmarks`
- `GET /api/bookmarks`
- `DELETE /api/bookmarks/{bookmark_id}`

### Legacy Identity Residue Audited
- `feedback.py` trusted `x-session-id`
- `feedback.py` fell back to `session-1`
- `bookmarks.py` wrote fixed `default` user
- `bookmarks.py` list/delete paths were not user-scoped

### Additional Interfaces Audited But Deferred
- `backend/routers/tasks.py`
- `backend/routers/collection.py`
- `backend/routers/missions.py`

Reason:
These files contain write or execution-like behavior, but this phase was intentionally constrained to the explicit high-risk surfaces requested by the user: `agent`, `configs`, `dashboard`, `feedback`, `bookmarks`. Expanding scope here would increase blast radius and risk breaking unrelated flows. They should be revisited in a dedicated follow-up audit.

## Protection Decisions

### Admin-Only
- `agent` router is protected with `require_admin`
- `GET /api/agent/status` remains admin-only because it exposes operational state and API readiness
- `GET /api/agent/logs` remains admin-only because it exposes backend operational logs
- Dashboard write endpoints are protected with `require_admin`
- `GET /api/feedback/stats` is protected with `require_admin`

### Super-Admin-Only
- `GET /api/configs/keys` is protected with `require_super_admin`

Reason:
Even though it is a read endpoint, it exposes provider-key/config-health surface that can reveal sensitive operational state.

### Authenticated Current User
- `POST /api/feedback` uses authenticated `current_user` when `AUTH_V1_ENABLED=true`
- Bookmarks create/list/delete use authenticated `current_user` when `AUTH_V1_ENABLED=true`

### Legacy-Only
- `POST /api/feedback` keeps legacy `x-session-id` and `session-1` behavior only when `AUTH_V1_ENABLED=false`
- Bookmarks keep legacy `default` user behavior only when `AUTH_V1_ENABLED=false`

## Feedback Fix
- Added `get_current_user_if_auth_enabled` helper in `backend/dependencies/auth.py`
- When `AUTH_V1_ENABLED=true`, `POST /api/feedback` resolves identity from session user only
- In auth mode, `x-session-id` is ignored as an identity source
- In auth mode, `session-1` fallback is disabled
- In auth mode, unauthenticated requests return `401`
- Feedback rows now persist `user_id` from authenticated `current_user`
- `user_feedbacks.user_id` additive schema/index support was added in `backend/models/database.py`
- When `AUTH_V1_ENABLED=false`, previous legacy behavior is preserved and isolated

## Bookmarks Fix
- Bookmarks now derive effective user through `get_current_user_if_auth_enabled`
- When `AUTH_V1_ENABLED=true`, bookmarks bind to `current_user.id`
- In auth mode, bookmarks no longer write fixed `default`
- In auth mode, list/create/delete scope only to the effective current user
- In auth mode, unauthenticated bookmark operations return `401`
- When `AUTH_V1_ENABLED=false`, legacy `default` behavior remains intact for backward compatibility

## AUTH_V1 Behavior

### AUTH_V1_ENABLED=true
- Missing or invalid session returns `401`
- Role insufficiency returns `403`
- `feedback` ignores forged `x-session-id`
- `feedback` does not fall back to `session-1`
- `bookmarks` do not write `default`
- `bookmarks` are isolated per authenticated user

### AUTH_V1_ENABLED=false
- Admin APIs fail closed through existing auth guard semantics
- Legacy feedback behavior remains available
- Legacy bookmarks `default` behavior remains available
- Auth-mode logic does not fall back to legacy when auth is enabled

## Error Semantics
- `401` = unauthenticated, missing session, invalid session
- `403` = authenticated but insufficient role
- `404` = target resource not found
- `422` = request validation failure, preserved by FastAPI/Pydantic defaults

## Regression Notes
- Dashboard GET endpoints were not blanket-locked
- Existing read behavior was preserved for audited read-only dashboard coverage endpoint
- This avoids accidental frontend breakage from over-restricting all GET routes

## Test Results
- `cd backend && python scripts/verify_admin_rbac.py` -> `PASS`
- `cd backend && python -m pytest -q tests/test_admin_rbac.py` -> `18 passed`
- `cd backend && python scripts/verify_admin_user_management.py` -> `PASS`
- `cd backend && python -m pytest -q tests/test_admin_user_management.py` -> `25 passed`
- `cd backend && python -m pytest -q tests/test_create_admin.py tests/test_auth_models.py tests/test_auth_migration.py tests/test_auth_service.py tests/test_auth_api.py tests/test_auth_account_lifecycle.py` -> `48 passed`
- `cd backend && python scripts/verify_high_risk_admin_protection.py` -> `PASS`
- `cd backend && python -m pytest -q tests/test_high_risk_admin_protection.py` -> `16 passed`
- `cd backend && python -m pytest -q tests/test_legacy_identity_cleanup.py` -> `8 passed`
- `cd backend && python scripts/verify_chat_user_ownership.py` -> `PASS`
- `cd backend && python -m pytest -q tests/test_chat_user_ownership.py` -> `9 passed`
- `cd backend && python -m pytest -q tests/test_chat_stream_ownership.py` -> `4 passed`
- `cd backend && python -m pytest -q tests/test_chat_owner_migration.py` -> `7 passed`
- `cd backend && python -m pytest -q tests/test_watch_alert_owner_migration.py tests/test_watch_alert_user_ownership.py tests/test_watch_alert_models.py tests/test_watch_retry.py tests/test_watch_scheduler.py tests/test_watch_runner.py tests/test_watch_signals_api.py tests/test_watch_targets_api.py tests/test_alert_engine.py tests/test_alerts_api.py` -> `153 passed`

## Files Changed
- `backend/dependencies/auth.py`
- `backend/models/database.py`
- `backend/routers/agent.py`
- `backend/routers/bookmarks.py`
- `backend/routers/configs.py`
- `backend/routers/dashboard.py`
- `backend/routers/feedback.py`
- `backend/scripts/verify_high_risk_admin_protection.py`
- `backend/tests/test_high_risk_admin_protection.py`
- `backend/tests/test_legacy_identity_cleanup.py`
- `PHASE5_5C_HIGH_RISK_ADMIN_PROTECTION_UAT.md`

## Not Done
- Frontend Admin page not implemented; reserved for Phase 5.5D
- Complex audit logging not implemented
- Multi-tenant ACL not implemented
- Brain performance optimization not implemented
- Deferred follow-up audit for `tasks.py`, `collection.py`, `missions.py`

## Risk Conclusion
- Result=`PASS`
- Security gain is high on the explicitly audited surfaces
- Blast radius is controlled because Chat / Watch / Alert business logic was not modified
- Main residual risk is deferred operational/write surfaces outside this narrowed 5.5C scope
- Ordinary dashboard reads were intentionally preserved to avoid accidental feature breakage

## Next Step
- RecommendedNextStep=`Phase 5.5D frontend admin route and users page`
