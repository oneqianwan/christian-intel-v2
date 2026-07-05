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

const notificationBellPath = 'frontend/src/components/NotificationBell.tsx'
const alertsPagePath = 'frontend/src/pages/AlertsPage.tsx'
const appPath = 'frontend/src/App.tsx'
const sidebarPath = 'frontend/src/components/Sidebar.tsx'
const apiPath = 'frontend/src/api/watchAlerts.ts'
const packagePath = 'frontend/package.json'

assertMatch(fs.existsSync(path.join(repoRoot, notificationBellPath)), 'NotificationBell file must exist')
assertMatch(fs.existsSync(path.join(repoRoot, alertsPagePath)), 'AlertsPage file must exist')

const bellSource = read(notificationBellPath)
const alertsPageSource = read(alertsPagePath)
const appSource = read(appPath)
const sidebarSource = read(sidebarPath)
const apiSource = read(apiPath)
const packageSource = read(packagePath)

assertMatch(appSource.includes('path="/alerts"'), 'Alerts route must exist in App.tsx')
assertMatch(sidebarSource.includes('Alerts') && sidebarSource.includes("navigate('/alerts')"), 'Alerts nav entry must exist')
assertMatch(
  bellSource.includes('isWatchAlertUiEnabled()') &&
    alertsPageSource.includes('isWatchAlertUiEnabled()') &&
    sidebarSource.includes('isWatchAlertUiEnabled()'),
  'Feature flag guard must exist in alerts entry points',
)
assertMatch(
  bellSource.includes('if (!enabled) {') && bellSource.includes('return null'),
  'NotificationBell must not render when feature flag is disabled',
)
assertMatch(
  bellSource.includes('if (!enabled) {') && bellSource.includes('return') && bellSource.includes('useEffect'),
  'NotificationBell must not poll when feature flag is disabled',
)
assertMatch(bellSource.includes('getUnreadAlertCount'), 'NotificationBell must use getUnreadAlertCount')
assertMatch(alertsPageSource.includes('listAlerts'), 'AlertsPage must use listAlerts')
assertMatch(alertsPageSource.includes('markAlertRead'), 'AlertsPage must use markAlertRead')
assertMatch(alertsPageSource.includes('dismissAlert'), 'AlertsPage must use dismissAlert')
assertMatch(alertsPageSource.includes('markAllAlertsRead'), 'AlertsPage must use markAllAlertsRead')
assertMatch(!/\buser_id\b/.test(bellSource + alertsPageSource), 'Alerts UI must not use user_id')
assertMatch(!/items\.length\s*[<>!=]=?\s*\d+\s*\?\s*['"`]99/.test(bellSource), 'Unread badge must not be hardcoded')
assertMatch(!/setUnreadCount\(\s*\d+\s*\)/.test(bellSource), 'Unread count must not be hardcoded')
assertMatch(!bellSource.includes('markAllAlertsRead'), 'Clicking NotificationBell must not trigger read-all')
assertMatch(
  /\/\^https\?:\\\/\\\/i\.test\(value\)/.test(alertsPageSource) || alertsPageSource.includes('/^https?:\\/\\//i.test(value)'),
  'AlertsPage must validate source_url with http/https check',
)
assertMatch(
  alertsPageSource.includes('rel="noopener noreferrer"') && alertsPageSource.includes('target="_blank"'),
  'AlertsPage external links must be safe',
)
assertMatch(!/dangerouslySetInnerHTML/.test(bellSource + alertsPageSource), 'Alerts UI must not use dangerouslySetInnerHTML')
assertMatch(
  bellSource.includes('clearTimeout') || bellSource.includes('clearTimer()'),
  'NotificationBell polling must have cleanup logic',
)
assertMatch(
  bellSource.includes('inFlightRef.current'),
  'NotificationBell must guard against concurrent unread-count requests',
)
assertMatch(
  bellSource.includes('status === 401') && bellSource.includes('setAuthExpired(true)'),
  'NotificationBell must stop or avoid continued polling after 401',
)
assertMatch(
  sidebarSource.includes('showWatchlistNav') && sidebarSource.includes('Alerts'),
  'Sidebar must hide alerts navigation when the feature flag is disabled',
)
assertMatch(
  !/createBrowserRouter|RouterProvider|MemoryRouter|HashRouter/.test(appSource + sidebarSource + alertsPageSource + bellSource),
  'R3 must not introduce a new Router',
)
assertMatch(
  !/"redux"|"@reduxjs\/toolkit"|"recoil"|"jotai"|"mobx"|"valtio"/.test(packageSource),
  'R3 must not introduce a new state management dependency',
)
assertMatch(packageSource.includes('check:alerts-ui'), 'package.json must expose check:alerts-ui')
assertMatch(apiSource.includes('WATCH_ALERT_UNREAD_REFRESH_EVENT'), 'API client must expose unread refresh event helper')

const gitStatus = execSync('git status --short', { cwd: repoRoot, encoding: 'utf8' })
const statusLines = gitStatus
  .split(/\r?\n/)
  .map((line) => line.trim())
  .filter(Boolean)

const disallowed = statusLines.filter((line) => {
  const filePath = line.slice(3)
  if (filePath.startsWith('backend/')) return true
  if (filePath === 'frontend/src/pages/WatchlistPage.tsx') return true
  if (filePath === 'frontend/src/components/WatchButton.tsx') return true
  if (filePath === 'frontend/src/components/SignalList.tsx') return true
  if (filePath.includes('Chat')) return true
  if (filePath.includes('Dashboard')) return true
  if (filePath.includes('Insight')) return true
  return false
})
assertMatch(disallowed.length === 0, `Disallowed modified files detected: ${disallowed.join(', ')}`)

console.log('ALERTS_UI_CHECK=PASS')
