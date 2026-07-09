# Phase 5.5D Frontend Admin Users UAT

## Baseline
- BaselineCommit=`77c3e9a`
- Branch=`phase5/auth-rbac-admin-v1`
- Scope=`Frontend admin route + AdminGuard wiring + AdminLayout + UsersPage only`
- BackendChanged=`NO`
- ManualBrowserUAT=`LIMITED`

## Files Changed
- `frontend/package.json`
- `frontend/scripts/verify-admin-ui.mjs`
- `frontend/src/App.tsx`
- `frontend/src/api/admin.ts`
- `frontend/src/auth/AdminGuard.tsx`
- `frontend/src/auth/__tests__/AdminGuard.test.tsx`
- `frontend/src/components/AdminLayout.tsx`
- `frontend/src/components/UserMenu.tsx`
- `frontend/src/components/__tests__/UserMenu.admin.test.tsx`
- `frontend/src/pages/AdminUsersPage.tsx`
- `frontend/src/pages/__tests__/AdminUsersPage.test.tsx`
- `frontend/src/api/__tests__/adminApi.test.ts`
- `PHASE5_5D_FRONTEND_ADMIN_USERS_UAT.md`

## Admin Route
- Added `/admin`
- Added `/admin/users`
- Both routes are wrapped by `AdminGuard`
- Both routes render `AdminLayout + AdminUsersPage`
- Existing Chat / Watch / Alert routes remain unchanged

## AdminGuard Behavior
- `loading` shows admin permission loading state
- `unauthenticated` redirects to `/login`
- `analyst/viewer` render explicit `403 无权限访问`
- `admin/super_admin` can enter admin routes
- Guard remains UX-only; backend RBAC is still the final authority

## UsersPage Features
- Loads admin user list from `GET /api/admin/users`
- Displays `email`, `display_name`, `role`, `status`, `public_id`, `created_at`, `last_login_at`
- Supports refresh
- Shows loading state
- Shows empty state
- Shows explicit unauthenticated state
- Shows explicit forbidden state for `403`
- Shows normal network error state without collapsing all failures into one message
- `super_admin` can change role
- `admin` cannot change role in UI
- `admin` can only change `analyst/viewer` status in UI
- `super_admin/admin` can revoke sessions within backend permission boundaries
- Success feedback is preserved after revoke refresh
- Sensitive fields like `password_hash` and `token` are not rendered

## Role Matrix

### super_admin
- Can see Admin entry
- Can access `/admin`
- Can load user list
- Can update role
- Can update status
- Can revoke sessions
- Self-demotion / protected-target rules still defer to backend error semantics

### admin
- Can see Admin entry
- Can access `/admin`
- Can load user list
- Cannot update role
- Can update status only for `analyst/viewer`
- Cannot manage `super_admin/admin` status in UI
- Can revoke sessions only for `analyst/viewer`

### analyst
- Cannot see Admin entry
- Cannot access `/admin`
- Frontend shows explicit forbidden state if route is forced

### viewer
- Cannot see Admin entry
- Cannot access `/admin`
- Frontend shows explicit forbidden state if route is forced

## API Client Behavior
- Added dedicated frontend admin client in `frontend/src/api/admin.ts`
- Exposes:
  - `listAdminUsers`
  - `getAdminUser`
  - `updateAdminUserRole`
  - `updateAdminUserStatus`
  - `revokeAdminUserSessions`
- All requests use `credentials: 'include'`
- Uses `public_id` as route key
- Does not send `user_id`, role spoofing data, `x-session-id`, or localStorage identity
- Preserves `401 / 403 / 409 / 422 / network error` distinction through `AdminApiError`

## Error Handling Semantics
- `401` -> show login/session-expired guidance
- `403` -> show `无权限访问管理后台` or `无权限执行该管理操作`
- `409 / 422 / 400` -> show backend message directly
- Network error -> show `网络异常，请稍后重试。`
- No generic misleading red error replaces permission errors

## Navigation Behavior
- `UserMenu` now exposes `管理后台` only for `super_admin/admin`
- `analyst/viewer/unauthenticated` do not see the Admin entry
- Existing `SecuritySettings` and logout entries remain intact

## Test Results
- `cd frontend && npm run check:admin-ui` -> `PASS`
- `cd frontend && npm run test:admin-ui` -> `24 passed`
- `cd frontend && npm run check:auth-ui` -> `PASS`
- `cd frontend && npm run test:auth` -> `50 passed`
- `cd frontend && npm run check:chat-user-auth` -> `PASS`
- `cd frontend && npm run test:chat-user-auth` -> `13 passed`
- `cd frontend && npm run check:watch-alert-contract` -> `PASS`
- `cd frontend && npm run check:watchlist-ui` -> `PASS`
- `cd frontend && npm run check:alerts-ui` -> `PASS`
- `cd frontend && npm run check:watch-alert-auth` -> `PASS`
- `cd frontend && npm run check:watch-alert-user-auth` -> `PASS`
- `cd frontend && npm run test:watch-alert-user-auth` -> `23 passed`
- `cd frontend && npm run build` -> `PASS`

## Browser UAT
- ManualBrowserUAT=`LIMITED`
- No browser PASS is claimed in this phase
- Recommended manual checks:
  - super_admin login -> Admin entry visible
  - admin login -> Admin entry visible but role update hidden
  - analyst/viewer login -> Admin entry hidden
  - forced `/admin` access for analyst/viewer -> explicit forbidden UI
  - revoke/status/role flows reflect backend RBAC message correctly
  - logout/relogin updates admin visibility correctly

## Not Done
- Complex Admin Dashboard not implemented
- Multi-tenant support not implemented
- Audit logging system not implemented
- Brain performance optimization not implemented

## Risk Conclusion
- Result=`PASS`
- Blast radius is controlled because only frontend routing/menu/admin UI files changed
- Backend was intentionally untouched
- Main residual risk is manual browser verification still pending

## Next Step
- RecommendedNextStep=`Phase 5.5E browser UAT and final hardening audit`
