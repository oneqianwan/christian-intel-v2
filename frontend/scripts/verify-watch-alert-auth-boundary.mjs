import fs from 'node:fs'
import path from 'node:path'
import process from 'node:process'
import { execSync } from 'node:child_process'

const root = process.cwd()
const repoRoot = path.resolve(root, '..')
const frontendRoot = path.join(repoRoot, 'frontend')
const srcRoot = path.join(frontendRoot, 'src')
const scriptsRoot = path.join(frontendRoot, 'scripts')

function read(filePath) {
  return fs.readFileSync(filePath, 'utf8')
}

function assertMatch(condition, message) {
  if (!condition) {
    throw new Error(message)
  }
}

function walkFiles(dirPath) {
  const entries = fs.readdirSync(dirPath, { withFileTypes: true })
  const files = []
  for (const entry of entries) {
    const fullPath = path.join(dirPath, entry.name)
    if (entry.isDirectory()) {
      files.push(...walkFiles(fullPath))
      continue
    }
    files.push(fullPath)
  }
  return files
}

function scanForBannedIdentity(searchRoot) {
  const allowExtensions = new Set(['.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs', '.json'])
  const banned = /\bsession-1\b|\buser-1\b|\btest-user\b|\bdefault-user\b|\banonymous\b|\bguest\b/i
  const matches = []

  for (const filePath of walkFiles(searchRoot)) {
    if (!allowExtensions.has(path.extname(filePath))) continue
    const source = read(filePath)
    if (banned.test(source)) {
      matches.push(path.relative(repoRoot, filePath))
    }
  }

  assertMatch(matches.length === 0, `Banned default identity found in: ${matches.join(', ')}`)
}

function assertOrder(source, ...needles) {
  const indices = needles.map((needle) => source.indexOf(needle))
  assertMatch(indices.every((value) => value >= 0), `Missing expected sequence: ${needles.join(' -> ')}`)
  for (let idx = 1; idx < indices.length; idx += 1) {
    assertMatch(indices[idx - 1] < indices[idx], `Sequence order invalid: ${needles.join(' -> ')}`)
  }
}

try {
  scanForBannedIdentity(srcRoot)
  scanForBannedIdentity(scriptsRoot)

  const apiPath = path.join(srcRoot, 'api', 'watchAlerts.ts')
  const identityPath = path.join(srcRoot, 'features', 'watchAlerts', 'identity.ts')
  const bellPath = path.join(srcRoot, 'components', 'NotificationBell.tsx')
  const watchButtonPath = path.join(srcRoot, 'components', 'WatchButton.tsx')
  const watchlistPath = path.join(srcRoot, 'pages', 'WatchlistPage.tsx')
  const alertsPath = path.join(srcRoot, 'pages', 'AlertsPage.tsx')

  const apiSource = read(apiPath)
  const identitySource = read(identityPath)
  const bellSource = read(bellPath)
  const watchButtonSource = read(watchButtonPath)
  const watchlistSource = read(watchlistPath)
  const alertsSource = read(alertsPath)

  assertMatch(!/\buser_id\b/.test(apiSource), 'Watch/Alert API client must not send or mention user_id')
  assertMatch(
    !/\buser_id\b/.test(bellSource + watchButtonSource + watchlistSource + alertsSource),
    'Watch/Alert UI must not send or mention user_id',
  )

  assertMatch(identitySource.includes('getWatchAlertIdentityMode'), 'Identity mode helper must exist')
  assertMatch(
    identitySource.includes("'legacy-session'") &&
      identitySource.includes("'authenticated-user'") &&
      identitySource.includes("'invalid'"),
    'Identity mode helper must support legacy/authenticated/invalid modes',
  )
  assertMatch(apiSource.includes('export function hasWatchAlertSession'), 'API must expose hasWatchAlertSession()')
  assertMatch(!/DEFAULT_SESSION_ID/.test(apiSource), 'Watch/Alert API client must not define a default session id')
  assertMatch(
    /const sessionId = getStoredSessionId\(\)[\s\S]*if \(!sessionId\)[\s\S]*throw createAuthRequiredError\(\)/.test(
      apiSource,
    ),
    'API client must reject unauthenticated requests without falling back',
  )
  assertMatch(
    apiSource.includes("if (identityMode === 'authenticated-user')") &&
      apiSource.includes("credentials: 'include'") &&
      apiSource.includes("headers.delete('x-session-id')"),
    'Authenticated mode must use credentials include and remove legacy headers',
  )
  assertOrder(apiSource, 'const sessionId = getStoredSessionId()', 'if (!sessionId)', "headers.set('x-session-id'")
  assertMatch(!/headers\.set\(['"]x-session-id['"],\s*['"`]/.test(apiSource), 'x-session-id header must not be hardcoded')

  assertMatch(
    /export async function createWatchTarget[\s\S]*return request</.test(apiSource),
    'createWatchTarget must use shared request helper (unauthenticated calls should be blocked there)',
  )
  assertMatch(
    /export async function updateWatchTarget[\s\S]*return request</.test(apiSource),
    'updateWatchTarget must use shared request helper (unauthenticated calls should be blocked there)',
  )
  assertMatch(
    /export async function deleteWatchTarget[\s\S]*await request</.test(apiSource),
    'deleteWatchTarget must use shared request helper (unauthenticated calls should be blocked there)',
  )
  assertMatch(
    /export async function runWatchTarget[\s\S]*return request</.test(apiSource),
    'runWatchTarget must use shared request helper (unauthenticated calls should be blocked there)',
  )

  assertMatch(bellSource.includes('getWatchAlertIdentityMode'), 'NotificationBell must use identity mode helper')
  assertMatch(bellSource.includes('hasWatchAlertSession'), 'NotificationBell must check auth presence')
  assertMatch(
    bellSource.includes("status === 'authenticated'") && bellSource.includes('const canPoll'),
    'NotificationBell must only poll for authenticated users in authenticated mode',
  )
  assertMatch(
    bellSource.includes("if (!authenticatedMode && !hasWatchAlertSession())") && bellSource.includes('setAuthExpired(true)'),
    'NotificationBell must stop polling and show auth-expired state in legacy mode when unauthenticated',
  )
  assertMatch(
    bellSource.includes('await getUnreadAlertCount({ signal: controller.signal })'),
    'NotificationBell must pass AbortSignal to unread-count polling',
  )
  assertMatch(
    bellSource.includes('status === 401') && bellSource.includes('setAuthExpired(true)'),
    'NotificationBell must stop polling after receiving 401',
  )
  assertMatch(
    bellSource.includes('clearTimer') && bellSource.includes('controllerRef.current?.abort()'),
    'NotificationBell must cleanup timer and abort in-flight requests',
  )
  assertMatch(
    watchButtonSource.includes("status !== 'authenticated'") &&
      watchButtonSource.includes('redirectToLogin') &&
      watchButtonSource.includes('useAuth'),
    'WatchButton must redirect unauthenticated users in authenticated mode',
  )
  assertMatch(
    watchlistSource.includes("if (authenticatedMode && status !== 'authenticated')") &&
      alertsSource.includes("if (authenticatedMode && status !== 'authenticated')"),
    'Watchlist and Alerts pages must avoid data requests before authentication is ready',
  )

  const status = execSync('git status --short', { cwd: repoRoot, encoding: 'utf8' })
  const modified = status
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => line.slice(3))
  const allowedBackendChanges = new Set([
    'backend/scripts/migrate_legacy_watch_alert_owner.py',
    'backend/tests/test_watch_alert_owner_migration.py',
  ])
  const forbiddenBackendChanges = modified.filter(
    (filePath) => filePath.startsWith('backend/') && !allowedBackendChanges.has(filePath),
  )
  assertMatch(forbiddenBackendChanges.length === 0, `Backend files must not be modified for this fix: ${forbiddenBackendChanges.join(', ')}`)

  console.log('WATCH_ALERT_AUTH_BOUNDARY_CHECK=PASS')
} catch (error) {
  console.error('WATCH_ALERT_AUTH_BOUNDARY_CHECK=FAIL')
  console.error(error instanceof Error ? error.message : String(error))
  process.exitCode = 1
}
