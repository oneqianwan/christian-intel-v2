import fs from 'node:fs'
import path from 'node:path'
import process from 'node:process'

const root = process.cwd()
const apiPath = path.join(root, 'src', 'api', 'watchAlerts.ts')
const typesPath = path.join(root, 'src', 'types', 'watchAlerts.ts')
const identityPath = path.join(root, 'src', 'features', 'watchAlerts', 'identity.ts')
const envExamplePath = path.join(root, '.env.example')
const watchTargetsRouterPath = path.join(root, '..', 'backend', 'routers', 'watch_targets.py')
const alertsRouterPath = path.join(root, '..', 'backend', 'routers', 'alerts.py')
const dependencyPath = path.join(root, '..', 'backend', 'dependencies', 'watch_alert_auth.py')
const schemasPath = path.join(root, '..', 'backend', 'schemas', 'watch_alert.py')

function read(filePath) {
  return fs.readFileSync(filePath, 'utf8')
}

function assertMatch(condition, message) {
  if (!condition) {
    throw new Error(message)
  }
}

function hasRegex(source, pattern) {
  return pattern.test(source)
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
      matches.push(path.relative(root, filePath))
    }
  }

  assertMatch(matches.length === 0, `Banned default identity found in: ${matches.join(', ')}`)
}

const apiSource = read(apiPath)
const typesSource = read(typesPath)
const identitySource = read(identityPath)
const envExample = read(envExamplePath)
const watchTargetsRouter = read(watchTargetsRouterPath)
const alertsRouter = read(alertsRouterPath)
const watchAlertDependency = read(dependencyPath)
const schemaSource = read(schemasPath)

const endpointChecks = [
  ['createWatchTarget', 'POST', '/watch-targets'],
  ['listWatchTargets', 'GET', '/watch-targets'],
  ['updateWatchTarget', 'PATCH', '/watch-targets/${encodeURIComponent(String(watchTargetId))}'],
  ['deleteWatchTarget', 'DELETE', '/watch-targets/${encodeURIComponent(String(watchTargetId))}'],
  ['runWatchTarget', 'POST', '/watch-targets/${encodeURIComponent(String(watchTargetId))}/run'],
  ['listWatchTargetSignals', 'GET', '/watch-targets/${encodeURIComponent(String(watchTargetId))}/signals'],
  ['listAlerts', 'GET', '/alerts'],
  ['getUnreadAlertCount', 'GET', '/alerts/unread-count'],
  ['markAlertRead', 'PATCH', '/alerts/${encodeURIComponent(String(alertId))}/read'],
  ['dismissAlert', 'PATCH', '/alerts/${encodeURIComponent(String(alertId))}/dismiss'],
  ['markAllAlertsRead', 'POST', '/alerts/read-all'],
]

for (const [functionName, method, endpoint] of endpointChecks) {
  assertMatch(
    apiSource.includes(`export async function ${functionName}`),
    `Missing API method ${functionName}`,
  )
  assertMatch(apiSource.includes(`method: '${method}'`), `Missing HTTP method ${method} for ${functionName}`)
  assertMatch(apiSource.includes(endpoint), `Missing endpoint ${endpoint} for ${functionName}`)
}

assertMatch(!/\buser_id\b/.test(apiSource), 'API client must not send or mention user_id')
assertMatch(!/\bowner_user_id\b/.test(apiSource), 'API client must not send or mention owner_user_id')
assertMatch(!/\buser_id\b/.test(typesSource), 'Types must not include user_id')
assertMatch(!/\bowner_user_id\b/.test(typesSource), 'Types must not include owner_user_id')
assertMatch(
  apiSource.includes("if (response.status === 204 || !parseJson)"),
  'Request helper must handle 204 without response.json()',
)
assertMatch(
  /deleteWatchTarget[\s\S]*parseJson: false/.test(apiSource),
  'deleteWatchTarget must disable JSON parsing for 204 responses',
)
assertMatch(
  apiSource.includes("return response.unread_count"),
  'Unread count client must parse unread_count',
)
assertMatch(
  apiSource.includes("return response.updated_count"),
  'Read-all client must parse updated_count',
)
scanForBannedIdentity(path.join(root, 'src'))
scanForBannedIdentity(path.join(root, 'scripts'))
assertMatch(
  identitySource.includes('export type WatchAlertIdentityMode'),
  'Identity module must expose WatchAlertIdentityMode',
)
assertMatch(
  identitySource.includes("'legacy-session'") &&
    identitySource.includes("'authenticated-user'") &&
    identitySource.includes("'invalid'"),
  'Identity module must cover disabled/legacy-session/authenticated-user/invalid modes',
)
assertMatch(
  apiSource.includes('buildWatchAlertRequestOptions'),
  'API client must centralize watch/alert request authentication logic',
)
assertMatch(
  apiSource.includes("credentials: 'include'"),
  'Authenticated watch/alert requests must support credentials: include',
)
assertMatch(
  apiSource.includes("headers.set('x-session-id', sessionId)"),
  'Legacy watch/alert mode must still set x-session-id',
)
assertMatch(
  apiSource.includes("if (identityMode === 'authenticated-user')") &&
    apiSource.includes("headers.delete('x-session-id')"),
  'Authenticated mode must actively remove x-session-id headers',
)
assertMatch(
  apiSource.indexOf("if (identityMode === 'authenticated-user')") <
    apiSource.indexOf('const sessionId = getStoredSessionId()'),
  'Authenticated requests must not depend on legacy session storage reads',
)
assertMatch(
  identitySource.includes("import.meta.env.VITE_WATCH_ALERT_UI_ENABLED === 'true'"),
  'Identity module must read VITE_WATCH_ALERT_UI_ENABLED',
)
assertMatch(
  identitySource.includes("import.meta.env.VITE_WATCH_ALERT_USER_OWNERSHIP_ENABLED === 'true'"),
  'Identity module must read VITE_WATCH_ALERT_USER_OWNERSHIP_ENABLED',
)
assertMatch(
  envExample.includes('VITE_WATCH_ALERT_UI_ENABLED=false'),
  '.env.example must default VITE_WATCH_ALERT_UI_ENABLED to false',
)
assertMatch(
  envExample.includes('VITE_WATCH_ALERT_USER_OWNERSHIP_ENABLED=false'),
  '.env.example must default VITE_WATCH_ALERT_USER_OWNERSHIP_ENABLED to false',
)
assertMatch(
  /interface PaginatedResponse<T>[\s\S]*items: T\[][\s\S]*page: number[\s\S]*page_size: number[\s\S]*total: number/.test(typesSource),
  'PaginatedResponse must include items, page, page_size, total',
)
assertMatch(
  /interface WatchSignal[\s\S]*source_url: string \| null/.test(typesSource),
  'WatchSignal.source_url must allow null',
)
assertMatch(
  /interface WatchAlert[\s\S]*source_url: string \| null/.test(typesSource),
  'WatchAlert.source_url must allow null',
)
assertMatch(
  /interface WatchSignal[\s\S]*old_value_json: JsonValue[\s\S]*new_value_json: JsonValue/.test(typesSource),
  'WatchSignal must use old_value_json/new_value_json field names',
)
assertMatch(
  /interface WatchAlert[\s\S]*signal_id: string/.test(typesSource),
  'WatchAlert.signal_id must match backend string contract',
)
assertMatch(
  schemaSource.includes('old_value_json') && schemaSource.includes('new_value_json'),
  'Backend schema must expose old_value_json/new_value_json',
)
assertMatch(
  schemaSource.includes('class AlertUnreadCountResponse') && schemaSource.includes('unread_count: int'),
  'Backend schema must expose unread_count',
)
assertMatch(
  schemaSource.includes('class AlertReadAllResponse') && schemaSource.includes('updated_count: int'),
  'Backend schema must expose updated_count',
)
assertMatch(
  hasRegex(watchTargetsRouter, /@router\.post\(\s*""/s),
  'Watch targets router must expose POST /watch-targets',
)
assertMatch(
  hasRegex(watchTargetsRouter, /@router\.get\("\/\\?\{watch_target_id\}\/signals"/),
  'Watch targets router must expose GET /watch-targets/{watch_target_id}/signals',
)
assertMatch(
  hasRegex(alertsRouter, /@router\.get\("\/unread-count"/),
  'Alerts router must expose GET /alerts/unread-count',
)
assertMatch(
  hasRegex(alertsRouter, /@router\.post\("\/read-all"/),
  'Alerts router must expose POST /alerts/read-all',
)
assertMatch(
  watchAlertDependency.includes('x_session_id') &&
    watchAlertDependency.includes('watch_alert_user_ownership_enabled') &&
    watchAlertDependency.includes('resolve_user_for_request'),
  'Backend dependency must support both legacy x-session-id and authenticated ownership modes',
)

console.log('WATCH_ALERT_CONTRACT_CHECK=PASS')
