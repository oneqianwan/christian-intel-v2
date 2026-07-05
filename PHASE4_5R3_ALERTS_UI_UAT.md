# Phase 4.5R3 Alerts UI UAT

## Scope
- Stage: Phase 4.5R3
- Branch: `phase4/watch-alert-ui-rebuild-final`
- Baseline commits:
  - `R1=9bd4021`
  - `R2=f52476d`

## Actual Modified Files
- `frontend/src/components/NotificationBell.tsx`
- `frontend/src/pages/AlertsPage.tsx`
- `frontend/scripts/verify-alerts-ui.mjs`
- `frontend/src/App.tsx`
- `frontend/src/components/Sidebar.tsx`
- `frontend/src/api/watchAlerts.ts`
- `frontend/package.json`
- `frontend/scripts/verify-watchlist-ui.mjs`
- `PHASE4_5R3_ALERTS_UI_UAT.md`

## NotificationBell Placement
- Placed in `Sidebar` watch/alerts navigation area.
- No second global layout or router was introduced.

## Feature Flag Behavior
- Guard source: `isWatchAlertUiEnabled()`
- Flag rule: only `import.meta.env.VITE_WATCH_ALERT_UI_ENABLED === 'true'` enables R3 UI.
- When disabled:
  - `NotificationBell` returns `null`
  - Alerts nav entry is hidden
  - `/alerts` redirects away instead of rendering full Alerts UI
  - unread-count polling does not start
  - existing Watchlist flow remains intact

## Unread Count Initial Load
- Trigger conditions:
  - feature flag enabled
  - component mounted
  - session header available through existing API client path
- API used: `getUnreadAlertCount()`
- Contract used: `GET /api/alerts/unread-count`
- `user_id` is not sent.

## Polling
- Interval: `60000 ms`
- Retry on `503`: `120000 ms`
- Lifecycle:
  - recursive `setTimeout`
  - request lock via `inFlightRef`
  - page hidden => skip scheduling
  - `visibilitychange` and `focus` resume refresh safely
  - cleanup on unmount clears timer and listeners
  - `401` sets auth-expired state and stops further polling

## AlertsPage
- Route: `/alerts`
- Functions:
  - list alerts
  - filter by `status`, `severity`, `watch_target_id`
  - paginate by `page`, `page_size`
  - refresh current result set
  - mark single alert read
  - dismiss single alert
  - mark all unread alerts as read
  - empty/error/loading states
  - responsive card layout

## Single-Alert Read Logic
- API: `markAlertRead(id)`
- Request button disabled while pending
- Success path:
  - refreshes current list
  - dispatches unread refresh event
- Failure path:
  - keeps button state recoverable
  - maps error via `WatchAlertApiError`

## Single-Alert Dismiss Logic
- API: `dismissAlert(id)`
- Request button disabled while pending
- Success path:
  - refreshes current list
  - dispatches unread refresh event
- Failure path:
  - keeps state unchanged
  - shows mapped error message

## Mark-All-Read Logic
- API: `markAllAlertsRead()`
- Enabled only when current result contains unread alerts
- Success path:
  - reloads current page
  - dispatches unread refresh event
  - displays returned `updated_count`
- `updated_count=0` is handled without front-end fabrication.

## Unread Count Synchronization
- Mechanism: `dispatchWatchAlertUnreadRefresh()`
- Triggers:
  - single read success
  - single dismiss success
  - mark-all-read success

## URL Safety
- Links rendered only for `http://` or `https://`
- External links include `target="_blank"` and `rel="noopener noreferrer"`
- No `dangerouslySetInnerHTML`
- Invalid or null URL renders as plain fallback content

## Filters and Pagination
- Supported filters:
  - `status`
  - `severity`
  - `watch_target_id`
  - `page`
  - `page_size`
- Filter changes reset to page 1.
- Refresh keeps active filter state.
- Empty page after mutation falls back by reloading current page data path.

## API Integration Result
- Backend env used:
  - `WATCH_ALERT_V1_ENABLED=true`
  - `WATCH_ALERT_NOTIFICATIONS_ENABLED=true`
- Frontend env used:
  - `VITE_WATCH_ALERT_UI_ENABLED=true`
- Test session header: `x-session-id: session-1`
- Seeded test data:
  - 1 organization
  - 1 watch target
  - 3 alerts
- Verified live flow:
  1. unread-count initially loaded to `3`
  2. click bell navigated to `/alerts`
  3. unread filter loaded 3 unread items
  4. mark one read => unread-count `2`
  5. dismiss one unread => unread-count `1`
  6. mark all read => unread-count `0`
  7. refresh `/alerts` remained accessible and state stayed correct

## Regression Result
- `npm run check:watch-alert-contract` => `WATCH_ALERT_CONTRACT_CHECK=PASS`
- `npm run check:watchlist-ui` => `WATCHLIST_UI_CHECK=PASS`
- `npm run check:alerts-ui` => `ALERTS_UI_CHECK=PASS`

## Build Result
- `npm run build` => PASS
- TypeScript build passed
- Vite production build passed
- Note: Vite emitted a chunk-size warning only; build still succeeded.

## 60-Point Acceptance
1. PASS - Flag off hides NotificationBell by component guard.
2. PASS - Flag off hides Alerts nav by Sidebar guard.
3. PASS - Flag off avoids unread-count request by bell early return.
4. PASS - Flag off avoids polling by bell scheduling guard.
5. PASS - Flag on shows bell in Sidebar.
6. PASS - `0` unread hides numeric badge and keeps aria text.
7. PASS - live verified unread count `3`.
8. PASS - `99+` formatting implemented in bell badge logic.
9. PASS - live verified bell click navigates to `/alerts`.
10. PASS - bell click only navigates; no read-all call wired.
11. PASS - live verified initial unread-count load.
12. PASS - fetch failure path keeps bell rendered.
13. PASS - polling interval is `60000 ms`.
14. PASS - unmount cleanup removes timer and listeners.
15. PASS - hidden page skips scheduling via `document.visibilityState`.
16. PASS - request lock prevents overlapping fetches.
17. PASS - `401` sets stop state and ends polling.
18. PASS - `503` retry backs off to `120000 ms` without toast storm.
19. PASS - live verified AlertsPage load.
20. PASS - live verified status filter `Unread`.
21. PASS - severity filter implemented and verified by code path.
22. PASS - pagination controls and server params implemented.
23. PASS - live verified empty state after mark-all on unread filter.
24. PASS - loading state rendered during initial fetch and actions.
25. PASS - error block renders message plus retry action.
26. PASS - live verified single mark-read success.
27. PASS - live verified unread-count updated from `3` to `2`.
28. PASS - live verified single dismiss success.
29. PASS - live verified dismissed status in API result.
30. PASS - live verified dismissing unread reduced count to `1`.
31. PASS - live verified mark-all-read success.
32. PASS - front end parses backend `updated_count`.
33. PASS - live verified unread-count became `0`.
34. PASS - action buttons disabled while request is pending.
35. PASS - `401` message mapped to relogin text.
36. PASS - `404` message mapped to not-found text.
37. PASS - `409` message mapped to conflict text.
38. PASS - `422` message mapped to invalid-request text.
39. PASS - `503` message mapped to feature-disabled text.
40. PASS - `source_url` only renders as link after protocol check.
41. PASS - non-http/https values do not render as active links.
42. PASS - external links include `noopener noreferrer`.
43. PASS - no `dangerouslySetInnerHTML` used.
44. PASS - null dates render `—`.
45. PASS - invalid dates fall back to `—`, never `Invalid Date`.
46. PASS - status and severity always include text labels.
47. PASS - responsive card layout used for list rows.
48. PASS - buttons/selects expose labels and keyboard access.
49. PASS - Watchlist page not modified.
50. PASS - WatchButton not modified.
51. PASS - SignalList not modified.
52. PASS - Organization Detail behavior preserved.
53. PASS - Chat routing preserved; no router replacement introduced.
54. PASS - Dashboard routes preserved.
55. PASS - live verified `/alerts` remains valid after refresh.
56. PASS - R1 contract regression check passed.
57. PASS - R2 watchlist regression check passed.
58. PASS - R3 alerts UI check passed.
59. PASS - build passed.
60. PASS - no backend files modified.

## Git Boundary Check
- Required forbidden areas remain untouched:
  - `backend/*`
  - `frontend/src/pages/WatchlistPage.tsx`
  - `frontend/src/components/WatchButton.tsx`
  - `frontend/src/components/SignalList.tsx`
- Boundary note:
  - `frontend/scripts/verify-watchlist-ui.mjs` was minimally adjusted so R2 regression checks continue to validate R2 core files without falsely blocking R3-allowed App/Sidebar wiring.

## Known Limitations
- `frontend/src/api/watchAlerts.ts` contains pre-existing mojibake in some legacy Chinese fallback strings; this stage did not broaden scope to re-encode them.
- `99+` badge behavior was validated from implementation/script evidence, not by seeding 100+ live unread alerts.
- Refresh validation focused on `/alerts` direct reload and post-mutation persistence, not on every filter permutation.

## Rollback
1. Revert this stage's modified files from the user's local Git client.
2. Restore branch state to commit `f52476d` if a full R3 rollback is needed.
3. Re-run:
   - `npm run check:watch-alert-contract`
   - `npm run check:watchlist-ui`
   - `npm run check:alerts-ui`
   - `npm run build`
