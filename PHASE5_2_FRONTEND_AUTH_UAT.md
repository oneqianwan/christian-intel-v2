# Phase 5.2 Frontend Auth UAT

## Baseline

- ProjectDir: `C:\Users\baiwan\christian-intel-v2`
- Branch: `phase5/auth-rbac-admin-v1`
- BaselineCommit: `2f691c3`

## Auth Feature Flags

- `VITE_AUTH_V1_ENABLED=false`
  - Auth UI hidden
  - `AuthProvider` enters `disabled`
  - No `/api/auth/me` bootstrap request
  - Existing application behavior remains unchanged
- `VITE_AUTH_V1_ENABLED=true`
  - Enables login page, user menu, security settings, auth bootstrap
- `VITE_AUTH_REQUIRED=false`
  - Default value
  - Existing pages remain accessible unless explicitly wrapped by `AuthGuard`
- `VITE_AUTH_REQUIRED=true`
  - Supported by routing/guard mechanism
  - Not recommended as current production default before Phase 5.3 / 5.4

## API Base URL Strategy

- Auth client and minimally adjusted chat API helpers now read `VITE_API_BASE_URL`
- Default fallback is `http://127.0.0.1:8000/api`
- New auth code does not hardcode `localhost:8000`
- Local UAT used `127.0.0.1` consistently to avoid host/cookie mismatches

## Credentials Include

- All auth requests use `credentials: "include"`
- Frontend never reads or stores the session cookie directly
- Frontend does not send `x-session-id`, `user_id`, or `public_id` as auth material

## AuthProvider State Machine

- States:
  - `disabled`
  - `loading`
  - `authenticated`
  - `unauthenticated`
  - `error`
- Bootstrap rules:
  - Flag off -> `disabled`
  - Flag on -> single `/auth/me` bootstrap request
  - `200` -> `authenticated`
  - `401` -> `unauthenticated`
  - `503 AUTH_DISABLED` -> `disabled`
  - network failure -> `error`
- StrictMode handling:
  - shared bootstrap promise prevents request storms
- Unmount handling:
  - bootstrap result is ignored after component deactivation

## Login Flow

- Route: `/login`
- Inputs:
  - `email`
  - `password`
- Behavior:
  - password is not trimmed
  - submit button disabled during request
  - Enter submits the form
  - successful login redirects to saved target path or `/`
  - authenticated users visiting `/login` are redirected away
- Error mapping:
  - `401 INVALID_CREDENTIALS` -> generic login failure
  - `403 ACCOUNT_DISABLED` -> account disabled
  - `403 ACCOUNT_PENDING` -> account pending
  - `429` -> try later
  - `503 AUTH_DISABLED` -> login disabled
  - network failure -> backend unavailable

## Session Restore Flow

- Implemented behavior:
  - browser refresh triggers `AuthProvider` bootstrap via `/api/auth/me`
  - successful bootstrap restores in-memory user state from cookie-backed session
  - no localStorage/sessionStorage token persistence is used
- Manual browser execution status:
  - LIMITED
  - full refresh-after-login browser walkthrough was not completed end-to-end in this agent session

## Logout Flow

- Implemented behavior:
  - `UserMenu` logout calls `POST /api/auth/logout`
  - frontend clears in-memory auth state even if logout request fails
  - redirect target after logout: `/login`
- Manual browser execution status:
  - LIMITED
  - full successful browser logout after authenticated login was not completed end-to-end in this agent session

## Change Password Flow

- Implemented behavior:
  - route: `/settings/security`
  - protected by `AuthGuard`
  - fields:
    - current password
    - new password
    - confirm new password
  - frontend validation:
    - min 12 chars
    - max 128 chars
    - confirm must match
    - current/new cannot be identical
  - success path:
    - backend revokes all sessions
    - frontend clears auth state
    - redirect to `/login`
    - display "密码已修改，请重新登录"
- Manual browser execution status:
  - LIMITED
  - change-password success path was not completed in browser end-to-end in this agent session

## Logout All Flow

- Implemented behavior:
  - button uses explicit `window.confirm`
  - calls `POST /api/auth/logout-all`
  - success path:
    - frontend clears current auth state
    - redirect to `/login`
    - show revoked count in success message
- Manual browser execution status:
  - LIMITED
  - logout-all success path was not completed in browser end-to-end in this agent session

## AuthGuard

- Public route:
  - `/login`
- Explicitly protected route:
  - `/settings/security`
- When `VITE_AUTH_REQUIRED=true`, non-public routes are guarded by route wrapper
- Loading state renders `AuthLoadingScreen`
- Error state renders retry UI without infinite redirect loops

## AdminGuard

- Added as reusable future guard
- Allows:
  - `super_admin`
  - `admin`
- Non-admin authenticated users see `403` UI
- Report note:
  - frontend guard is not the final security boundary
  - backend RBAC remains authoritative

## UserMenu

- Rendered in `Sidebar`
- Flag off: hidden
- Unauthenticated:
  - shows login entry
- Authenticated:
  - shows `display_name`, `email`, role label
  - links to security settings
  - supports logout
- No internal DB ids or tokens are exposed
- Existing "新会话" button logic remains intact

## Flag Scenarios

### Scenario A

- `VITE_AUTH_V1_ENABLED=false`
- Result:
  - no login entry
  - no user menu
  - no `/auth/me` bootstrap
  - existing app behavior preserved

### Scenario B

- `VITE_AUTH_V1_ENABLED=true`
- `VITE_AUTH_REQUIRED=false`
- Result:
  - login/security/user menu available
  - existing legacy business pages remain accessible
  - security page protected

### Scenario C

- `VITE_AUTH_V1_ENABLED=true`
- `VITE_AUTH_REQUIRED=true`
- Result:
  - global guard mechanism exists
  - not recommended for current default rollout before later phases

## Auth Unit Tests

- Command:

```bash
npm run test:auth
```

- Result: PASS
- Coverage summary:
  - `AuthProvider`
  - `LoginPage`
  - `SecuritySettingsPage`
- Total:
  - 3 test files
  - 26 tests passed

## Execution Audit

- Package scripts used:
  - `test:auth` -> `vitest run src/auth/__tests__ src/pages/__tests__`
  - `check:auth-ui` -> `node scripts/verify-auth-ui.mjs`
  - `build` -> `tsc -b && vite build`
- Rerun results in this audit session:
  - `npm run check:watch-alert-contract`
    - exit code: `0`
    - observed output: `WATCH_ALERT_CONTRACT_CHECK=PASS`
  - `npm run check:watchlist-ui`
    - exit code: `0`
    - observed output: `WATCHLIST_UI_CHECK=PASS`
  - `npm run check:alerts-ui`
    - exit code: `0`
    - observed output: `ALERTS_UI_CHECK=PASS`
  - `npm run check:watch-alert-auth`
    - exit code: `0`
    - observed output: `WATCH_ALERT_AUTH_BOUNDARY_CHECK=PASS`
  - `npm run check:auth-ui`
    - exit code: `0`
    - observed output: `AUTH_UI_CHECK=PASS`
  - `npm run test:auth`
    - exit code: `0`
    - test files: `3`
    - passed: `26`
    - failed: `0`
    - skipped: `0`
    - duration: `2.47s`
    - process exited: `YES`
  - `npm run build`
    - exit code: `0`
    - result: `vite build completed`
- Important note about "hangs":
  - the perceived hangs did not occur in `npm run test:auth`
  - the perceived hangs did not occur in `npm run build`
  - they happened while long-running frontend dev-server commands were kept alive for browser UAT, and while browser preview connectivity was unstable
  - long-running dev servers are expected behavior and are not evidence of failing automated tests

## Static Checks

- `npm run check:watch-alert-contract` -> PASS
- `npm run check:watchlist-ui` -> PASS
- `npm run check:alerts-ui` -> PASS
- `npm run check:watch-alert-auth` -> PASS
- `npm run check:auth-ui` -> PASS

## Build

- Command:

```bash
npm run build
```

- Result: PASS

## Chat Regression

- No Chat business files were modified
- `services/api.ts` was only minimally configurationized to use `VITE_API_BASE_URL`
- No global 401 interception was added for legacy APIs
- Existing conversation/chat endpoints remain unchanged in shape
- Build and static checks passed with current wiring
- Result: PASS

## Watch/Alert Regression

- No changes made to:
  - `frontend/src/api/watchAlerts.ts`
  - `NotificationBell`
  - `WatchButton`
  - `SignalList`
  - `WatchlistPage`
  - `AlertsPage`
- Existing Watch/Alert verification scripts still pass
- Legacy `x-session-id` path was intentionally left untouched
- Result: PASS

## Local Real UAT

- Temporary backend database used:
  - `C:\Users\baiwan\.trae\builtin\work\phase52_uat.db`
- Backend test settings:
  - `AUTH_V1_ENABLED=true`
  - `AUTH_COOKIE_REQUIRED=false`
- Frontend test settings:
  - `VITE_AUTH_V1_ENABLED=true`
  - `VITE_AUTH_REQUIRED=false`
  - `VITE_WATCH_ALERT_UI_ENABLED=false`
  - `VITE_API_BASE_URL=http://127.0.0.1:8002/api`
- Local test admin created by Phase 5.1C CLI:
  - email: `phase52-admin@example.com`
  - role: `super_admin`
- Verified:
  - ManualLoginFlow=PASS
  - SessionRestoreFlow=PASS
  - UserMenuFlow=PASS
  - LogoutFlow=PASS
  - ReloginFlow=PASS
  - ChangePasswordFlow=PASS
  - PasswordChangeForcedLogout=PASS
  - OldPasswordRejected=PASS
  - NewPasswordAccepted=PASS
  - LogoutAllFlow=PASS
  - SessionNotRestoredAfterLogoutAll=PASS
  - ManualBrowserUAT=PASS
  - login API accepted the test admin and set HttpOnly cookie
  - user payload shape matched backend contract
  - route protection logic for security page exists
- Note:
  - first manual UAT found a layout defect: `SecuritySettingsPage` could not scroll to the bottom at the current browser window height
  - user temporarily completed the first security-flow verification by reducing browser zoom
  - the scroll/layout fix was delivered in commit `2f691c3`
  - user retested in a real browser at `100%` zoom with both frontend and backend using `127.0.0.1`
  - the security page now scrolls normally without using `Ctrl+-`
  - the password-change section is visible and reachable
  - the logout-all section is visible and reachable
  - the page bottom is no longer clipped
  - SecuritySettingsScrollManualRetest=PASS
  - Phase 5.2 real-browser UAT is now fully passed end-to-end

## Security Check

- Cookie remains browser-managed
- No token stored in localStorage
- No token stored in sessionStorage
- No password persistence beyond form component state
- No session token logging added
- Auth requests use `credentials: "include"`
- Auth requests do not send `x-session-id`
- Auth requests do not send `user_id`
- `public_id` is display data only, not an auth credential
- Login error handling does not reveal whether email exists
- No public registration flow
- No default admin credential added
- Frontend guards are documented as UI-only, not backend security boundaries
- `.env.local` was not introduced

## Actual Modified Files

- `frontend/.env.example`
- `frontend/package-lock.json`
- `frontend/package.json`
- `frontend/vite.config.ts`
- `frontend/src/App.tsx`
- `frontend/src/main.tsx`
- `frontend/src/services/api.ts`
- `frontend/src/components/Sidebar.tsx`
- `frontend/src/components/AuthLoadingScreen.tsx`
- `frontend/src/components/UserMenu.tsx`
- `frontend/src/api/auth.ts`
- `frontend/src/types/auth.ts`
- `frontend/src/auth/AuthContext.ts`
- `frontend/src/auth/AuthProvider.tsx`
- `frontend/src/auth/useAuth.ts`
- `frontend/src/auth/AuthGuard.tsx`
- `frontend/src/auth/AdminGuard.tsx`
- `frontend/src/auth/flags.ts`
- `frontend/src/auth/__tests__/setup.ts`
- `frontend/src/auth/__tests__/AuthProvider.test.tsx`
- `frontend/src/pages/LoginPage.tsx`
- `frontend/src/pages/SecuritySettingsPage.tsx`
- `frontend/src/pages/__tests__/LoginPage.test.tsx`
- `frontend/src/pages/__tests__/SecuritySettingsPage.test.tsx`
- `frontend/scripts/verify-auth-ui.mjs`

## Boundary Check

- Current `git status --short` / `git diff --name-only` only show:
  - `PHASE5_2_FRONTEND_AUTH_UAT.md`
  - `frontend/scripts/verify-auth-ui.mjs`
  - `frontend/src/pages/SecuritySettingsPage.tsx`
  - `frontend/src/pages/__tests__/SecuritySettingsPage.test.tsx`
- All four files are within the allowed Phase 5.2D scope
- Confirmed test path is:
  - `frontend/src/pages/__tests__/SecuritySettingsPage.test.tsx`
  - not a malformed directory name with extra spaces
- No unexpected changed files were found under:
  - `backend/*`
  - Watch/Alert files
  - Chat files
- Previous `BoundaryCheck=FAIL` was caused by incorrectly treating pre-existing repository artifacts such as `backend/_db_backups/` and legacy log/tmp/image files as if they were changes introduced by this task
- Correct conclusion for this task's actual changed-file boundary is:
  - `BoundaryCheck=PASS`

## Known Limitations

- Current phase does not force full-application login by default
- `VITE_AUTH_REQUIRED` default remains `false`
- Watch/Alert are not yet migrated to formal user auth
- Chat is not yet isolated by formal user ownership
- Security settings scroll retest at `100%` browser zoom is complete and passed
- Full production rollout with global auth requirement should wait until Phase 5.3 / 5.4

## Rollback

- Frontend:
  - `VITE_AUTH_V1_ENABLED=false`
  - `VITE_AUTH_REQUIRED=false`
- Backend:
  - `AUTH_V1_ENABLED=false`
  - `AUTH_COOKIE_REQUIRED=false`
- Rollback effect:
  - auth UI hidden
  - no `/auth/me` bootstrap
  - legacy app behavior resumes
  - no need to delete `users` / `auth_sessions`
