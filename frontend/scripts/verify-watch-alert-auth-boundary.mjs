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
  const bellPath = path.join(srcRoot, 'components', 'NotificationBell.tsx')
  const watchButtonPath = path.join(srcRoot, 'components', 'WatchButton.tsx')
  const watchlistPath = path.join(srcRoot, 'pages', 'WatchlistPage.tsx')
  const alertsPath = path.join(srcRoot, 'pages', 'AlertsPage.tsx')

  const apiSource = read(apiPath)
  const bellSource = read(bellPath)
  const watchButtonSource = read(watchButtonPath)
  const watchlistSource = read(watchlistPath)
  const alertsSource = read(alertsPath)

  assertMatch(!/\buser_id\b/.test(apiSource), 'Watch/Alert API client must not send or mention user_id')
  assertMatch(
    !/\buser_id\b/.test(bellSource + watchButtonSource + watchlistSource + alertsSource),
    'Watch/Alert UI must not send or mention user_id',
  )

  assertMatch(apiSource.includes('export function hasWatchAlertSession'), 'API must expose hasWatchAlertSession()')
  assertMatch(!/DEFAULT_SESSION_ID/.test(apiSource), 'Watch/Alert API client must not define a default session id')
  assertMatch(
    /const sessionId = getStoredSessionId\(\)[\s\S]*if \(!sessionId\)[\s\S]*throw createAuthRequiredError\(\)/.test(
      apiSource,
    ),
    'API client must reject unauthenticated requests without falling back',
  )
  assertOrder(apiSource, 'const sessionId = getStoredSessionId()', 'if (!sessionId)', "headers.set('x-session-id'", 'fetch(')
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

  assertMatch(bellSource.includes('hasWatchAlertSession'), 'NotificationBell must check auth presence')
  assertMatch(
    bellSource.includes("if (!hasWatchAlertSession())") && bellSource.includes('setAuthExpired(true)'),
    'NotificationBell must stop polling and show auth-expired state when unauthenticated',
  )
  const unauthIndex = bellSource.indexOf("if (!hasWatchAlertSession())")
  const awaitUnreadIndex = bellSource.indexOf('await getUnreadAlertCount()')
  assertMatch(
    unauthIndex >= 0 && awaitUnreadIndex >= 0 && unauthIndex < awaitUnreadIndex,
    'NotificationBell must check auth presence before calling getUnreadAlertCount()',
  )
  assertMatch(
    bellSource.includes('status === 401') && bellSource.includes('setAuthExpired(true)'),
    'NotificationBell must stop polling after receiving 401',
  )
  assertMatch(bellSource.includes('clearTimer'), 'NotificationBell must cleanup polling timer')

  const status = execSync('git status --short', { cwd: repoRoot, encoding: 'utf8' })
  const modified = status
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => line.slice(3))
  const backendTouched = modified.some((filePath) => filePath.startsWith('backend/'))
  assertMatch(!backendTouched, 'Backend files must not be modified for this fix')

  console.log('WATCH_ALERT_AUTH_BOUNDARY_CHECK=PASS')
} catch (error) {
  console.error('WATCH_ALERT_AUTH_BOUNDARY_CHECK=FAIL')
  console.error(error instanceof Error ? error.message : String(error))
  process.exitCode = 1
}
