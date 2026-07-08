import fs from 'node:fs'
import path from 'node:path'
import process from 'node:process'
import { execSync } from 'node:child_process'

const frontendRoot = process.cwd()
const repoRoot = path.resolve(frontendRoot, '..')

function read(relativePath) {
  return fs.readFileSync(path.join(frontendRoot, relativePath), 'utf8')
}

function assertMatch(condition, message) {
  if (!condition) {
    throw new Error(message)
  }
}

function grepNot(source, pattern, message) {
  assertMatch(!pattern.test(source), message)
}

try {
  const bannedSessionFallbackPattern = new RegExp(`\\bsession${'-'}1\\b`, 'i')
  const envExample = read('.env.example')
  const packageJson = read('package.json')
  const appSource = read('src/App.tsx')
  const identitySource = read('src/features/watchAlerts/identity.ts')
  const apiSource = read('src/api/watchAlerts.ts')
  const bellSource = read('src/components/NotificationBell.tsx')
  const watchButtonSource = read('src/components/WatchButton.tsx')
  const watchlistSource = read('src/pages/WatchlistPage.tsx')
  const alertsSource = read('src/pages/AlertsPage.tsx')
  const signalListSource = read('src/components/SignalList.tsx')
  const sidebarSource = read('src/components/Sidebar.tsx')

  assertMatch(
    envExample.includes('VITE_WATCH_ALERT_USER_OWNERSHIP_ENABLED=false'),
    'VITE_WATCH_ALERT_USER_OWNERSHIP_ENABLED must default to false',
  )
  assertMatch(envExample.includes('VITE_WATCH_ALERT_UI_ENABLED=false'), 'VITE_WATCH_ALERT_UI_ENABLED must default to false')
  assertMatch(envExample.includes('VITE_AUTH_REQUIRED=false'), 'VITE_AUTH_REQUIRED must default to false')

  assertMatch(identitySource.includes("return 'disabled'"), 'Identity helper must support disabled mode')
  assertMatch(identitySource.includes("return 'legacy-session'"), 'Identity helper must support legacy-session mode')
  assertMatch(
    identitySource.includes("return 'authenticated-user'"),
    'Identity helper must support authenticated-user mode',
  )
  assertMatch(identitySource.includes("return 'invalid'"), 'Identity helper must support invalid mode')
  assertMatch(
    identitySource.includes("import.meta.env.VITE_WATCH_ALERT_USER_OWNERSHIP_ENABLED === 'true'"),
    'Identity helper must read VITE_WATCH_ALERT_USER_OWNERSHIP_ENABLED',
  )

  assertMatch(
    apiSource.includes("if (identityMode === 'authenticated-user')") &&
      apiSource.includes("credentials: 'include'"),
    'Authenticated mode must use credentials include',
  )
  assertMatch(
    apiSource.includes("headers.delete('x-session-id')") &&
      apiSource.includes("headers.delete('X-Session-Id')"),
    'Authenticated mode must actively remove legacy session headers',
  )
  assertMatch(
    apiSource.includes("if (identityMode !== 'legacy-session')") &&
      apiSource.includes('const sessionId = getStoredSessionId()'),
    'Legacy session storage reads must remain isolated behind legacy-session mode',
  )
  assertMatch(
    apiSource.includes("headers.set('x-session-id', sessionId)"),
    'Legacy mode must still preserve x-session-id behavior',
  )
  assertMatch(
    !/Cookie['"]\s*:|document\.cookie|cookieStore|session_token|token_hash/i.test(apiSource + watchButtonSource + bellSource + watchlistSource + alertsSource + signalListSource),
    'Frontend must not read cookies or persist session tokens',
  )
  grepNot(apiSource, /\buser_id\b/, 'API client must not send or mention user_id')
  grepNot(apiSource, /\bowner_user_id\b/, 'API client must not send or mention owner_user_id')
  grepNot(apiSource, /\bpublic_id\b/, 'API client must not use public_id as an auth parameter')
  grepNot(apiSource, bannedSessionFallbackPattern, 'API client must not reintroduce the legacy default session fallback')

  assertMatch(
    appSource.includes('wrapWatchAlertRoute') &&
      appSource.includes('path="/watchlist"') &&
      appSource.includes('path="/alerts"') &&
      appSource.includes('<AuthGuard requireEnabled>'),
    'Watchlist and Alerts routes must be guarded by AuthGuard in authenticated-user mode',
  )
  assertMatch(
    sidebarSource.includes('navigateToWatchAlertRoute') &&
      sidebarSource.includes("from: path"),
    'Sidebar Watch/Alert navigation must preserve login redirect target',
  )
  assertMatch(
    watchButtonSource.includes('redirectToLogin') &&
      watchButtonSource.includes("status !== 'authenticated'") &&
      watchButtonSource.includes("status === 'loading' ? 'Checking login...' : '登录后关注'"),
    'WatchButton must require login in authenticated-user mode',
  )
  assertMatch(
    watchlistSource.includes("if (authenticatedMode && status !== 'authenticated')") &&
      watchlistSource.includes('controllerRef.current?.abort()'),
    'WatchlistPage must block pre-auth requests and abort stale requests',
  )
  assertMatch(
    alertsSource.includes("if (authenticatedMode && status !== 'authenticated')") &&
      alertsSource.includes('listControllerRef.current?.abort()') &&
      alertsSource.includes('dispatchWatchAlertUnreadRefresh()'),
    'AlertsPage must block pre-auth requests and refresh unread state after mutations',
  )
  assertMatch(
    signalListSource.includes("if (authenticatedMode && status !== 'authenticated')") &&
      signalListSource.includes('requestSequenceRef') &&
      signalListSource.includes('controllerRef'),
    'SignalList must wait for authenticated user state and cancel stale requests',
  )
  assertMatch(
    bellSource.includes('const canPoll') &&
      bellSource.includes("status === 'authenticated'") &&
      bellSource.includes('setUnreadCount(0)') &&
      bellSource.includes('setAuthExpired(true)'),
    'NotificationBell must only poll while authenticated and clear unread state on logout/401',
  )
  assertMatch(
    bellSource.includes('await getUnreadAlertCount({ signal: controller.signal })'),
    'NotificationBell must pass AbortSignal to polling requests',
  )
  assertMatch(packageJson.includes('check:watch-alert-user-auth'), 'package.json must expose check:watch-alert-user-auth')
  assertMatch(packageJson.includes('test:watch-alert-user-auth'), 'package.json must expose test:watch-alert-user-auth')

  const diffOutput = execSync('git diff --name-only', { cwd: repoRoot, encoding: 'utf8' }).trim()
  const changedFiles = diffOutput ? diffOutput.split(/\r?\n/).filter(Boolean) : []
  const allowedBackendChanges = new Set([
    'backend/scripts/migrate_legacy_watch_alert_owner.py',
    'backend/tests/test_watch_alert_owner_migration.py',
  ])
  const forbiddenBackendChanges = changedFiles.filter(
    (filePath) => filePath.startsWith('backend/') && !allowedBackendChanges.has(filePath),
  )
  assertMatch(forbiddenBackendChanges.length === 0, `backend must not be modified: ${forbiddenBackendChanges.join(', ')}`)

  console.log('WATCH_ALERT_USER_AUTH_UI_CHECK=PASS')
} catch (error) {
  console.error('WATCH_ALERT_USER_AUTH_UI_CHECK=FAIL')
  console.error(error instanceof Error ? error.message : String(error))
  process.exitCode = 1
}
