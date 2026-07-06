# Phase 5.3B Watch / Alert Frontend Auth UAT

## Scope

- Branch: `phase5/auth-rbac-admin-v1`
- Baseline Commit: `7a1c18d65f724b96f505b48b4e488dffd1051910`
- Phase Goal: migrate Watch / Alert frontend to authenticated Cookie mode behind a dedicated feature flag, while preserving Phase 4 legacy-session rollback mode.
- Backend Changes: none
- Chat Migration: not included in this phase
- Global Auth Requirement: `VITE_AUTH_REQUIRED` remains `false`

## Frontend Architecture Audit

### Audit Files Read

- `frontend/src/api/watchAlerts.ts`
- `frontend/src/components/WatchButton.tsx`
- `frontend/src/components/NotificationBell.tsx`
- `frontend/src/components/SignalList.tsx`
- `frontend/src/pages/WatchlistPage.tsx`
- `frontend/src/pages/AlertsPage.tsx`
- `frontend/src/App.tsx`
- `frontend/src/main.tsx`
- `frontend/src/services/api.ts`
- `frontend/src/auth/*`
- `frontend/src/components/Sidebar.tsx`
- `frontend/src/stores/*`
- `frontend/src/types/*`
- `frontend/scripts/*`
- `frontend/package.json`
- `frontend/.env.example`
- `backend/routers/watch_targets.py`
- `backend/routers/alerts.py`
- `backend/dependencies/watch_alert_auth.py`
- `backend/config.py`
- `backend/models/schemas.py`
- `backend/models/watch_alert.py`

### Original x-session-id Usage

- Generation / storage location: `frontend/src/api/watchAlerts.ts` read `window.localStorage['x-session-id']`.
- Request injection point: shared `request()` helper in `frontend/src/api/watchAlerts.ts` automatically attached `x-session-id`.
- Legacy UI dependencies:
  - `WatchButton` loaded watch state through `listWatchTargets()`.
  - `WatchlistPage` loaded watch list through `listWatchTargets()`.
  - `SignalList` loaded signals through `listWatchTargetSignals()`.
  - `AlertsPage` loaded alerts through `listAlerts()` and mutations through `markAlertRead()` / `dismissAlert()` / `markAllAlertsRead()`.
  - `NotificationBell` polled unread count through `getUnreadAlertCount()` and Phase 4 session presence.

### API Base URL And Error Contract

- Frontend Watch / Alert API now builds URLs through `buildApiUrl()` and keeps the existing `VITE_API_BASE_URL` behavior.
- Backend ownership flag defaults:
  - Frontend: `VITE_WATCH_ALERT_USER_OWNERSHIP_ENABLED=false`
  - Backend: `WATCH_ALERT_USER_OWNERSHIP_ENABLED=false`
- Backend ownership mode contract:
  - When backend ownership flag is `true`, `backend/dependencies/watch_alert_auth.py` resolves user identity from authenticated Cookie session and ignores `x-session-id`.
  - Error envelope remains FastAPI-style `{"detail": {"error_code": "...", "message": "..."}}`.
- Frontend error parsing remains centralized in `parseApiError()` and maps `401 / 403 / 404 / 409 / 422 / 429 / 503` to user-safe messages.

## Identity Mode

### Feature Flag Matrix

- `disabled`
  - `VITE_WATCH_ALERT_UI_ENABLED=false`
  - Watch / Alert UI hidden, no data requests
- `legacy-session`
  - `VITE_WATCH_ALERT_UI_ENABLED=true`
  - `VITE_WATCH_ALERT_USER_OWNERSHIP_ENABLED=false`
  - Preserves Phase 4 `x-session-id` flow
- `authenticated-user`
  - `VITE_WATCH_ALERT_UI_ENABLED=true`
  - `VITE_WATCH_ALERT_USER_OWNERSHIP_ENABLED=true`
  - `VITE_AUTH_V1_ENABLED=true`
  - Uses browser-managed Cookie auth with `credentials: "include"`
- `invalid`
  - ownership flag `true`, Auth UI flag `false`
  - Fail-safe: no Watch / Alert requests, no legacy fallback, no anonymous identity creation

### Abstraction

- Added `frontend/src/features/watchAlerts/identity.ts`
- Exposes:
  - `getWatchAlertIdentityMode()`
  - `isWatchAlertUiEnabled()`
  - `isAuthenticatedOwnershipEnabled()`
  - `getWatchAlertInvalidConfigMessage()`
- All Watch / Alert API and UI entry points now reuse this shared mode instead of duplicating flag checks.

## Frontend Changes

### API Client

- `frontend/src/api/watchAlerts.ts`
  - Added `buildWatchAlertRequestOptions()`
  - `authenticated-user` mode:
    - sets `credentials: "include"`
    - deletes `x-session-id` / `X-Session-Id`
    - does not read Cookie values
    - does not send `user_id`, `owner_user_id`, or `public_id`
  - `legacy-session` mode:
    - preserves stored `x-session-id`
  - `invalid` mode:
    - throws `WATCH_ALERT_IDENTITY_INVALID`
  - Supports `AbortSignal` across Watch / Alert GET / POST / PATCH / DELETE requests
  - Preserves 204-safe parsing and network error wrapping

### WatchButton

- `frontend/src/components/WatchButton.tsx`
  - Uses `useAuth()` and shared identity mode
  - Authenticated mode:
    - blocks pre-auth requests
    - shows login CTA for unauthenticated users
    - redirects to `/login` with source route preserved
    - never creates legacy identity
  - Adds request cancellation and sequence guards
  - Handles `401` by refreshing auth state and clearing local watch state
  - Handles `409` by re-syncing current watch state
  - Prevents duplicate clicks during in-flight actions

### Watchlist / Signals

- `frontend/src/pages/WatchlistPage.tsx`
  - authenticated mode guarded by `AuthGuard` through `App.tsx`
  - does not request before auth recovery completes
  - clears page state when auth becomes unauthenticated
  - aborts stale requests on page/filter/user changes
- `frontend/src/components/SignalList.tsx`
  - uses Cookie mode in authenticated-user mode
  - blocks pre-auth requests
  - aborts stale requests and protects against target-switch overwrite
  - never filters by `session_id` client-side

### Alerts / NotificationBell

- `frontend/src/pages/AlertsPage.tsx`
  - authenticated mode guarded by `AuthGuard` through `App.tsx`
  - uses Cookie auth for list and mutation actions
  - does not send `x-session-id`, `user_id`, or `owner_user_id`
  - refreshes unread badge state after read / dismiss / mark-all-read
  - clears user-scoped state on `401`
- `frontend/src/components/NotificationBell.tsx`
  - only polls in authenticated-user mode when `status === "authenticated"`
  - uses `credentials: "include"` through API client
  - clears timers and aborts in-flight polling on unmount / logout / auth loss
  - avoids duplicate polling in StrictMode with in-flight guard
  - stops repeating on `401`
  - added backoff for `429` / `503`

### Routes / Sidebar

- `frontend/src/App.tsx`
  - `/watchlist` and `/alerts` now use conditional `AuthGuard` only in `authenticated-user` mode
  - does not enable global auth requirement
- `frontend/src/components/Sidebar.tsx`
  - Watchlist / Alerts navigation now routes through shared login-aware navigation
  - preserves return target when redirecting to `/login`

## Privacy And State Isolation

- Cookie is managed by the browser; frontend does not read Cookie values.
- Frontend does not store session token / Cookie token in `localStorage` or `sessionStorage`.
- Authenticated mode does not trust:
  - `x-session-id`
  - `user_id`
  - `owner_user_id`
  - `public_id` as authentication material
- Logout / auth loss cleanup covers:
  - Watchlist page state
  - Alerts page state
  - Signal list state
  - unread count
  - WatchButton local watch state
  - NotificationBell timer and in-flight poll
- Does not clear:
  - Chat data
  - Dashboard data
  - legacy session storage value

## Automated Verification

### Static Checks

- `npm run check:watch-alert-contract` -> PASS
- `npm run check:watchlist-ui` -> PASS
- `npm run check:alerts-ui` -> PASS
- `npm run check:watch-alert-auth` -> PASS
- `npm run check:watch-alert-user-auth` -> PASS
- `npm run check:auth-ui` -> PASS

### Tests

- `npm run test:auth` -> PASS
  - Result: 35 passed, 0 failed
- `npm run test:watch-alert-user-auth` -> PASS
  - Result: 22 passed, 0 failed

### Build

- `npm run build` -> PASS
- Notes:
  - Vite emitted a bundle size warning only
  - No TypeScript or build errors remain

## Phase 4 Legacy Regression

- Legacy-session path preserved in `frontend/src/api/watchAlerts.ts`
- Static verification confirms:
  - legacy `x-session-id` logic still exists
  - new mode removes `x-session-id`
  - invalid config does not silently downgrade to legacy mode

## Auth Regression

- `npm run test:auth` still passes after Watch / Alert migration
- `npm run check:auth-ui` still passes
- `VITE_AUTH_REQUIRED` remains `false`
- Chat is not migrated in this phase

## Local Browser UAT

- Status: `LIMITED`
- Reason:
  - This run completed static checks, unit tests, and production build.
  - Browser automation against a temporary backend, test admin bootstrap, and header inspection was not completed in this run.
- Required Phase 5.3C follow-up:
  - dual-user browser isolation validation
  - legacy data migration verification
- Important:
  - Do not mark production-ready default-on for authenticated Watch / Alert mode before Phase 5.3C browser validation is completed.

## Known Limits

- Manual browser UAT for single-user Cookie headers is still pending / limited in this run.
- Dual-user browser isolation is explicitly deferred to Phase 5.3C.
- No automatic migration or claim of legacy anonymous Watch data is performed.

## Rollback

- Frontend rollback: set `VITE_WATCH_ALERT_USER_OWNERSHIP_ENABLED=false`
- Backend rollback: set `WATCH_ALERT_USER_OWNERSHIP_ENABLED=false`
- Rollback preserves:
  - legacy `x-session-id` mode
  - owner columns and migrated data
  - existing legacy session storage
  - Chat behavior

## Required Release Notes

- New flag defaults to `false`
- Authenticated mode does not trust `x-session-id`
- Cookie is browser-managed and not read by frontend code
- No automatic migration of legacy anonymous Watch data
- Legacy mode remains available for rollback
- `VITE_AUTH_REQUIRED` remains `false`
- Chat is not migrated yet
- Phase 5.3C must complete browser multi-user validation before enabling the new mode by default
