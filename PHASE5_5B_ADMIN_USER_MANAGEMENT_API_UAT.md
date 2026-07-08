# PHASE5_5B_ADMIN_USER_MANAGEMENT_API_UAT

## Baseline

- Branch: `phase5/auth-rbac-admin-v1`
- Baseline Commit: `680a094c40982f7379ba790d16719f9f08e17921`
- Phase Scope: backend-only Admin user management API
- Frontend Status: unchanged in this phase
- Chat / Watch / Alert / Brain Status: unchanged in this phase

## Modified Files

- `backend/main.py`
- `backend/models/schemas.py`
- `backend/routers/admin.py`
- `backend/scripts/verify_admin_user_management.py`
- `backend/tests/test_admin_user_management.py`
- `PHASE5_5B_ADMIN_USER_MANAGEMENT_API_UAT.md`

## Added Admin API

- `GET /api/admin/users`
  - list users
  - supports `limit` / `offset`
  - supports optional `role` / `status` / `email` filtering
- `GET /api/admin/users/{user_id}`
  - returns a single user by `public_id`
- `PATCH /api/admin/users/{user_id}/role`
  - updates user role
  - super_admin only
- `PATCH /api/admin/users/{user_id}/status`
  - updates user status
  - admin or super_admin with target-role protections
- `POST /api/admin/users/{user_id}/sessions/revoke`
  - revokes all target user sessions
  - admin or super_admin with target-role protections

## Response Safety

- User responses include:
  - `public_id`
  - `email`
  - `display_name`
  - `role`
  - `status`
  - `email_verified_at`
  - `last_login_at`
  - `created_at`
  - `updated_at`
- User responses do not include:
  - `password_hash`
  - `password_salt`
  - session token
  - raw cookie
  - reset token
  - API key
  - stack trace

## Permission Matrix

### List / Detail

- `super_admin`: allowed
- `admin`: allowed
- `analyst`: `403 ROLE_FORBIDDEN`
- `viewer`: `403 ROLE_FORBIDDEN`
- unauthenticated: `401 AUTH_REQUIRED`
- invalid session: existing auth path returns `401`

### Role Update

- `super_admin`: allowed for `admin` / `analyst` / `viewer`
- `super_admin`: forbidden to change own role
- `super_admin`: forbidden to demote the last active super_admin
- `admin`: forbidden
- `analyst` / `viewer`: forbidden

### Status Update

- `super_admin`: allowed for `admin` / `analyst` / `viewer`
- `super_admin`: allowed for another `super_admin`, but not if it disables the last active super_admin
- `super_admin`: forbidden to change own status
- `admin`: allowed for `analyst` / `viewer`
- `admin`: forbidden for `admin` / `super_admin`
- `analyst` / `viewer`: forbidden

### Session Revoke

- `super_admin`: allowed for any non-self target
- `admin`: allowed for `analyst` / `viewer`
- `admin`: forbidden for `admin` / `super_admin`
- `analyst` / `viewer`: forbidden
- self revoke through admin API: forbidden
- self session management remains on existing `/api/auth/logout-all`

## Role Update Rules

- Valid roles:
  - `super_admin`
  - `admin`
  - `analyst`
  - `viewer`
- Request body is validated through typed schema
- Unknown role returns `422`
- Backend does not trust header/body spoofed current role
- Authorization uses backend authenticated `current_user.role` only

## Status Update Rules

- Valid statuses come from existing `User.status` implementation:
  - `active`
  - `disabled`
  - `pending`
- Request body is validated through typed schema
- Unknown status returns `422`
- Self status mutation is rejected with `403`
- Disabling the last active super_admin is rejected with `403`

## Session Revoke Rules

- Uses existing `revoke_all_user_sessions()` from `backend/services/auth_service.py`
- Returns `success` and `revoked_count` only
- Does not return token or token hash
- Revoked target session can no longer access protected endpoints
- Admin API revoke is intentionally blocked for self target to avoid current-request ambiguity

## Error Semantics

- Unauthenticated / missing cookie: `401 AUTH_REQUIRED`
- Invalid session: `401 INVALID_SESSION`
- Revoked session: `401 SESSION_REVOKED`
- Permission denied: `403 ROLE_FORBIDDEN`
- Self-demotion denied: `403 SELF_DEMOTION_FORBIDDEN`
- Self-disable denied: `403 SELF_DISABLE_FORBIDDEN`
- Self session revoke denied: `403 SELF_SESSION_REVOKE_FORBIDDEN`
- Last active super_admin protected: `403 LAST_SUPER_ADMIN_PROTECTED`
- Missing target user: `404 USER_NOT_FOUND`
- Invalid role / status payload: `422`
- `AUTH_V1_ENABLED=false`: `503 AUTH_DISABLED`

## AUTH_V1 Compatibility

### `AUTH_V1_ENABLED=true`

- Admin API is active
- Authorization uses backend authenticated user from session cookie
- `require_admin` and `require_super_admin` are reused directly

### `AUTH_V1_ENABLED=false`

- Admin API fails closed through existing auth gate
- Result: `503 AUTH_DISABLED`
- No anonymous fallback is introduced

## Automated Validation

### Phase 5.5A RBAC Baseline

- Command: `cd backend && python scripts/verify_admin_rbac.py`
- Result: `ADMIN_RBAC_CHECK=PASS`
- Command: `cd backend && python -m pytest -q tests/test_admin_rbac.py`
- Result: `18 passed`

### Existing Auth Regression

- Command:
  - `cd backend && python -m pytest -q tests/test_create_admin.py tests/test_auth_models.py tests/test_auth_migration.py tests/test_auth_service.py tests/test_auth_api.py tests/test_auth_account_lifecycle.py`
- Result: `48 passed`
- Confirms login / create_admin / change-password / logout-all remain intact

### Phase 5.5B Static Verification

- Command: `cd backend && python scripts/verify_admin_user_management.py`
- Result: `ADMIN_USER_MANAGEMENT_CHECK=PASS`

### Phase 5.5B API Tests

- Command: `cd backend && python -m pytest -q tests/test_admin_user_management.py`
- Result: `25 passed`
- Verified:
  - super_admin list users pass
  - admin list users pass
  - analyst/viewer denied
  - unauthenticated denied
  - detail by `public_id`
  - missing user `404`
  - super_admin role update pass
  - admin role update denied
  - self-demotion denied
  - unknown role denied
  - super_admin/admin status matrix enforced
  - self-disable denied
  - session revoke works
  - revoked session loses access
  - password hash not returned
  - header/body spoofing ignored
  - `AUTH_V1_ENABLED=false` fails closed

### Chat Ownership Regression

- Command: `cd backend && python scripts/verify_chat_user_ownership.py`
- Result: `CHAT_USER_OWNERSHIP_CHECK=PASS`
- Command:
  - `cd backend && python -m pytest -q tests/test_chat_user_ownership.py tests/test_chat_stream_ownership.py tests/test_chat_owner_migration.py`
- Result: `20 passed`
- Confirms Phase 5.4 ownership baseline remains intact

### Frontend

- Not run
- Reason: no frontend code or shared frontend contract changes in this phase

## Security Boundary

- Do not trust `x-user-id`
- Do not trust `x-session-id`
- Do not trust `x-role`
- Do not trust request body current role
- Do not trust frontend user object
- Do not trust email as path identifier
- Use `public_id` for admin user path lookups
- Use backend authenticated `current_user.role` only

## Non-Goals Confirmed

- Frontend Admin page not implemented; deferred to Phase 5.5D
- High-risk interface lockdown not implemented; deferred to Phase 5.5C
- `agent/configs/dashboard` not modified
- Chat business logic not modified
- Watch/Alert business logic not modified
- Brain not modified

## Risk Conclusion

- Admin user management API baseline is ready for backend use
- Role/status/session controls are explicit and deny by default outside the permitted matrix
- Invalid enum values are rejected at request validation time with `422`
- Protection rules use `403` and keep behavior deterministic
- High-risk interface enforcement remains a separate next phase

## Final Conclusion

- Phase 5.5B result: PASS
- RecommendedNextStep=Phase 5.5C high-risk admin protection and legacy identity cleanup
- READY_FOR_PHASE5_5C=false
