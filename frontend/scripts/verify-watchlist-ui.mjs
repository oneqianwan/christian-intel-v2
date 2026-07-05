import fs from 'node:fs'
import path from 'node:path'
import { execSync } from 'node:child_process'

const root = process.cwd()
const repoRoot = path.resolve(root, '..')

function read(relativePath) {
  return fs.readFileSync(path.join(repoRoot, relativePath), 'utf8')
}

function assertMatch(condition, message) {
  if (!condition) {
    throw new Error(message)
  }
}

const watchButtonSource = read('frontend/src/components/WatchButton.tsx')
const signalListSource = read('frontend/src/components/SignalList.tsx')
const watchlistPageSource = read('frontend/src/pages/WatchlistPage.tsx')
const appSource = read('frontend/src/App.tsx')
const sidebarSource = read('frontend/src/components/Sidebar.tsx')
const orgDetailSource = read('frontend/src/pages/OrgDetailPage.tsx')
const packageSource = read('frontend/package.json')

assertMatch(
  /export function WatchButton\(\{ entityId, entityType \}: WatchButtonProps\)/.test(watchButtonSource),
  'WatchButton must receive real entityId/entityType props',
)
assertMatch(
  /<WatchButton entityId=\{org\.id\} entityType="organization"/.test(orgDetailSource),
  'Organization detail must pass org.id and organization entityType to WatchButton',
)
assertMatch(!/\buser_id\b/.test(watchButtonSource + signalListSource + watchlistPageSource), 'UI files must not use user_id')
assertMatch(!/Victory Philippines/i.test(watchButtonSource + signalListSource + watchlistPageSource), 'UI files must not hardcode Victory Philippines')
assertMatch(appSource.includes('path="/watchlist"'), 'Watchlist route must exist')
assertMatch(
  watchButtonSource.includes('isWatchAlertUiEnabled()') &&
    watchlistPageSource.includes('isWatchAlertUiEnabled()') &&
    sidebarSource.includes('isWatchAlertUiEnabled()') &&
    orgDetailSource.includes('isWatchAlertUiEnabled()'),
  'Feature flag guard must exist in watch UI entry points',
)
assertMatch(
  watchButtonSource.includes('createWatchTarget') &&
    watchButtonSource.includes('updateWatchTarget') &&
    watchButtonSource.includes('runWatchTarget') &&
    watchButtonSource.includes('deleteWatchTarget'),
  'WatchButton must wire Watch/Pause/Resume/Run Now/Remove actions to API client',
)
assertMatch(
  watchlistPageSource.includes('updateWatchTarget') &&
    watchlistPageSource.includes('runWatchTarget') &&
    watchlistPageSource.includes('deleteWatchTarget'),
  'WatchlistPage must wire actions to API client',
)
assertMatch(signalListSource.includes('listWatchTargetSignals'), 'SignalList must use real signals API client')
assertMatch(
  /\/\^https\?:\\\/\\\/i\.test\(value\)/.test(signalListSource) || signalListSource.includes('/^https?:\\/\\//i.test(value)'),
  'SignalList must validate source_url with http/https check',
)
assertMatch(
  signalListSource.includes('rel="noopener noreferrer"') && signalListSource.includes('target="_blank"'),
  'SignalList external links must be safe',
)
assertMatch(
  !/NotificationBell|AlertsPage/.test(watchButtonSource + signalListSource + watchlistPageSource + appSource + sidebarSource + orgDetailSource),
  'R2 files must not reference NotificationBell or AlertsPage',
)
assertMatch(!/dangerouslySetInnerHTML/.test(watchButtonSource + signalListSource + watchlistPageSource), 'UI must not use dangerouslySetInnerHTML')
assertMatch(packageSource.includes('check:watchlist-ui'), 'package.json must expose check:watchlist-ui')

const gitStatus = execSync('git status --short', { cwd: repoRoot, encoding: 'utf8' })
const statusLines = gitStatus
  .split(/\r?\n/)
  .map((line) => line.trim())
  .filter(Boolean)

const disallowed = statusLines.filter((line) => {
  const filePath = line.slice(3)
  if (filePath.startsWith('backend/')) return true
  if (filePath.includes('NotificationBell')) return true
  if (filePath.includes('AlertsPage')) return true
  return false
})
assertMatch(disallowed.length === 0, `Disallowed modified files detected: ${disallowed.join(', ')}`)

console.log('WATCHLIST_UI_CHECK=PASS')
