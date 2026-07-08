# PHASE5_5A_RBAC_BASELINE_UAT

## Baseline

- Branch: `phase5/auth-rbac-admin-v1`
- Baseline Commit: `020af7483fa0973a0cb9a135c26d8581c482c902`
- Phase Scope: backend RBAC permission baseline only
- Frontend Status: not modified in this phase
- Admin User Management API: not implemented in this phase
- High-Risk Interface Lockdown: not implemented in this phase

## Modified Files

- `backend/dependencies/auth.py`
- `backend/tests/test_admin_rbac.py`
- `backend/scripts/verify_admin_rbac.py`
- `PHASE5_5A_RBAC_BASELINE_UAT.md`

## RBAC Design

### Role Hierarchy

- Defined roles: `viewer`, `analyst`, `admin`, `super_admin`
- Hierarchy helper order: `viewer < analyst < admin < super_admin`
- Shared constants:
  - `ROLE_HIERARCHY = ("viewer", "analyst", "admin", "super_admin")`
  - `ROLE_RANK = {role: index ...}`
- Helper functions:
  - `normalize_role_value(role)`
  - `is_known_role(role)`
  - `role_at_least(role, minimum_role)`

### Hierarchy Decision

- `role_at_least()` is implemented as an explicit reusable helper for future admin API and high-risk interface rollout
- Unknown role, `None`, empty role, and invalid casing only pass after successful normalization to a known backend role
- Unknown role never defaults to allow
- This phase does not derive permissions from email, `public_id`, header values, body values, or any frontend user object

### `require_role(*allowed_roles)`

- Implemented in `backend/dependencies/auth.py`
- Depends on authenticated backend `current_user` resolved from session cookie
- Uses exact allow-list semantics, not minimum-role implicit expansion
- Behavior:
  - no session / missing cookie / invalid session / revoked session / expired session: existing auth path returns `401`
  - disabled user: existing auth path returns `403 ACCOUNT_DISABLED`
  - pending user: existing auth path returns `403 ACCOUNT_PENDING`
  - authenticated but role missing or unknown: `403 ROLE_FORBIDDEN`
  - authenticated but role not in allow-list: `403 ROLE_FORBIDDEN`
- Design choice for this phase:
  - `require_role("analyst")` allows only `analyst`
  - `require_role("viewer")` allows only `viewer`
  - higher roles are not implicitly allowed unless explicitly listed

### `require_admin`

- Implemented as `Depends(require_role("admin", "super_admin"))`
- Allows:
  - `admin`
  - `super_admin`
- Rejects:
  - `analyst`
  - `viewer`
  - unknown / missing roles

### `require_super_admin`

- Implemented as `Depends(require_role("super_admin"))`
- Allows:
  - `super_admin`
- Rejects:
  - `admin`
  - `analyst`
  - `viewer`
  - unknown / missing roles

## Error Semantics

- Authentication failure remains existing auth behavior:
  - missing cookie: `401 AUTH_REQUIRED`
  - invalid session: `401 INVALID_SESSION`
  - revoked session: `401 SESSION_REVOKED`
  - expired session: `401 SESSION_EXPIRED`
- User status unavailable remains existing auth behavior:
  - disabled: `403 ACCOUNT_DISABLED`
  - pending: `403 ACCOUNT_PENDING`
- Permission failure:
  - unknown role: `403 ROLE_FORBIDDEN`
  - disallowed role: `403 ROLE_FORBIDDEN`
- No RBAC path leaks session token, password hash, other user existence, or stack traces

## AUTH_V1 Behavior

### `AUTH_V1_ENABLED=true`

- RBAC helpers depend on authenticated session user
- Permission evaluation uses only backend `current_user.role`
- Header/body spoofing does not affect authorization

### `AUTH_V1_ENABLED=false`

- Existing auth dependency behavior remains unchanged
- RBAC helpers fail closed through existing auth gate with `503 AUTH_DISABLED`
- No fallback to anonymous or legacy identity is introduced
- This phase does not attach RBAC to production admin endpoints, so legacy business routes remain unaffected

## Security Boundary

- Do not trust `x-user-id`
- Do not trust `x-session-id`
- Do not trust request body `role`
- Do not trust frontend/localStorage role
- Do not trust frontend user object
- Trust only backend authenticated `current_user.role`
- Unknown role denies by default
- Auth failure returns `401`
- Permission failure returns `403`

## Automated Validation

### Static Verification

- Command: `cd backend && python scripts/verify_admin_rbac.py`
- Result: `ADMIN_RBAC_CHECK=PASS`

### RBAC Tests

- Command: `cd backend && python -m pytest -q tests/test_admin_rbac.py`
- Result: `18 passed`
- Coverage includes:
  - `super_admin` pass / reject cases
  - `admin` pass / reject cases
  - `analyst` / `viewer` deny cases
  - unauthenticated / invalid / revoked / expired session behavior
  - disabled user behavior
  - unknown role deny
  - header spoofing ignore
  - body spoofing ignore
  - exact-role semantics for `require_role("analyst")` and `require_role("viewer")`
  - `AUTH_V1_ENABLED=false` fail-closed behavior

### Existing Auth Regression

- Command:
  - `cd backend && python -m pytest -q tests/test_create_admin.py tests/test_auth_models.py tests/test_auth_migration.py tests/test_auth_service.py tests/test_auth_api.py tests/test_auth_account_lifecycle.py`
- Result: `48 passed`
- Confirms existing auth account creation, login, password change, logout-all, and related lifecycle flows still pass

### Chat Ownership Regression

- Command: `cd backend && python scripts/verify_chat_user_ownership.py`
- Result: `CHAT_USER_OWNERSHIP_CHECK=PASS`
- Command:
  - `cd backend && python -m pytest -q tests/test_chat_user_ownership.py tests/test_chat_stream_ownership.py tests/test_chat_owner_migration.py`
- Result: `20 passed`
- Confirms Phase 5.4 chat ownership baseline remains intact

### Frontend

- Command: not run
- Reason: no frontend changes in Phase 5.5A

## Non-Goals Confirmed

- Admin user management API not implemented; deferred to Phase 5.5B
- High-risk interface lockdown not implemented; deferred to Phase 5.5C
- Frontend admin route/page not implemented; deferred to Phase 5.5D
- Watch/Alert business logic not modified
- Chat business logic not modified in this phase

## Risk Conclusion

- RBAC baseline is reusable and minimal
- Exact allow-list semantics avoid accidental privilege expansion in Phase 5.5A
- Hierarchy helper exists for explicit future use, but is not auto-wired into `require_role`, reducing surprise and rollout risk
- Because production admin-only endpoints are not yet connected, this phase establishes primitives rather than full system enforcement
- Main follow-up work remains attaching these helpers to real admin APIs and high-risk routes in later phases

## Final Conclusion

- Phase 5.5A result: PASS
- RecommendedNextStep=Phase 5.5B Admin user management API
- READY_FOR_PHASE5_5B=false
