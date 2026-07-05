import fs from 'node:fs'
import path from 'node:path'
import process from 'node:process'

const root = process.cwd()
const apiPath = path.join(root, 'src', 'api', 'watchAlerts.ts')
const typesPath = path.join(root, 'src', 'types', 'watchAlerts.ts')
const envExamplePath = path.join(root, '.env.example')
const watchTargetsRouterPath = path.join(root, '..', 'backend', 'routers', 'watch_targets.py')
const alertsRouterPath = path.join(root, '..', 'backend', 'routers', 'alerts.py')
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

const apiSource = read(apiPath)
const typesSource = read(typesPath)
const envExample = read(envExamplePath)
const watchTargetsRouter = read(watchTargetsRouterPath)
const alertsRouter = read(alertsRouterPath)
const schemaSource = read(schemasPath)

const endpointChecks = [
  ['createWatchTarget', 'POST', '/api/watch-targets'],
  ['listWatchTargets', 'GET', '/api/watch-targets'],
  ['updateWatchTarget', 'PATCH', '/api/watch-targets/${encodeURIComponent(String(watchTargetId))}'],
  ['deleteWatchTarget', 'DELETE', '/api/watch-targets/${encodeURIComponent(String(watchTargetId))}'],
  ['runWatchTarget', 'POST', '/api/watch-targets/${encodeURIComponent(String(watchTargetId))}/run'],
  ['listWatchTargetSignals', 'GET', '/api/watch-targets/${encodeURIComponent(String(watchTargetId))}/signals'],
  ['listAlerts', 'GET', '/api/alerts'],
  ['getUnreadAlertCount', 'GET', '/api/alerts/unread-count'],
  ['markAlertRead', 'PATCH', '/api/alerts/${encodeURIComponent(String(alertId))}/read'],
  ['dismissAlert', 'PATCH', '/api/alerts/${encodeURIComponent(String(alertId))}/dismiss'],
  ['markAllAlertsRead', 'POST', '/api/alerts/read-all'],
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
assertMatch(!/\buser_id\b/.test(typesSource), 'Types must not include user_id')
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
assertMatch(
  apiSource.includes("import.meta.env.VITE_WATCH_ALERT_UI_ENABLED === 'true'"),
  'Feature flag must default to false and only enable on strict true',
)
assertMatch(
  envExample.includes('VITE_WATCH_ALERT_UI_ENABLED=false'),
  '.env.example must default VITE_WATCH_ALERT_UI_ENABLED to false',
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

console.log('WATCH_ALERT_CONTRACT_CHECK=PASS')
