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
  const banned = /\bsession-1\b|\buser-1\b|\btest-user\b|\bdefault-user\b/i
  const matches = []

  for (const filePath of walkFiles(searchRoot)) {
    if (!allowExtensions.has(path.extname(filePath))) continue
    const source = fs.readFileSync(filePath, 'utf8')
    if (banned.test(source)) {
      matches.push(path.relative(repoRoot, filePath))
    }
  }

  assertMatch(matches.length === 0, `Banned default identity found in: ${matches.join(', ')}`)
}

try {
  const envExample = read('.env.example')
  const packageJson = read('package.json')
  const identitySource = read('src/features/chat/identity.ts')
  const apiSource = read('src/services/api.ts')
  const chatAreaSource = read('src/components/ChatArea.tsx')
  const sidebarSource = read('src/components/Sidebar.tsx')
  const authFlagsSource = read('src/auth/flags.ts')

  assertMatch(envExample.includes('VITE_CHAT_USER_OWNERSHIP_ENABLED=false'), 'VITE_CHAT_USER_OWNERSHIP_ENABLED must default to false')
  assertMatch(envExample.includes('VITE_AUTH_REQUIRED=false'), 'VITE_AUTH_REQUIRED must default to false')

  assertMatch(identitySource.includes("'legacy'"), 'Chat identity helper must support legacy mode')
  assertMatch(identitySource.includes("'authenticated-user'"), 'Chat identity helper must support authenticated-user mode')
  assertMatch(identitySource.includes("'invalid'"), 'Chat identity helper must support invalid mode')
  assertMatch(
    identitySource.includes("import.meta.env.VITE_CHAT_USER_OWNERSHIP_ENABLED === 'true'"),
    'Chat identity helper must read VITE_CHAT_USER_OWNERSHIP_ENABLED',
  )

  assertMatch(
    apiSource.includes("if (identityMode === 'authenticated-user')") &&
      apiSource.includes("requestInit.credentials = 'include'"),
    'Authenticated chat mode must use credentials include',
  )
  assertMatch(
    apiSource.includes("if (identityMode === 'invalid')") &&
      apiSource.includes('CHAT_IDENTITY_INVALID'),
    'Invalid chat identity must fail safe before calling fetch',
  )
  grepNot(apiSource, /x-session-id|X-Session-Id/, 'Chat API client must not send x-session-id headers')
  grepNot(apiSource, /\buser_id\b/, 'Chat API client must not send user_id')
  grepNot(apiSource, /\bowner_user_id\b/, 'Chat API client must not send owner_user_id')
  grepNot(apiSource, /\bpublic_id\b/, 'Chat API client must not use public_id as an auth parameter')
  assertMatch(
    !/document\.cookie|cookieStore|session_token|token_hash|localStorage\.setItem\(.+token/i.test(apiSource + chatAreaSource),
    'Chat frontend must not read cookies or persist tokens',
  )

  assertMatch(
    chatAreaSource.includes('AbortController') &&
      chatAreaSource.includes('abortControllerRef') &&
      chatAreaSource.includes('controller.signal'),
    'Chat stream must use AbortController and pass AbortSignal',
  )
  assertMatch(
    chatAreaSource.includes('authenticatedMode') &&
      chatAreaSource.includes("auth.status !== 'authenticated'") &&
      chatAreaSource.includes("navigate('/login'"),
    'ChatArea must block unauthenticated actions in authenticated-user mode',
  )
  assertMatch(
    sidebarSource.includes('getChatIdentityMode') &&
      sidebarSource.includes("chatIdentityMode === 'authenticated-user'") &&
      sidebarSource.includes("status !== 'authenticated'"),
    'Sidebar must gate chat conversation list and new chat actions in authenticated-user mode',
  )
  assertMatch(authFlagsSource.includes('VITE_AUTH_REQUIRED'), 'Auth flags must remain configurable')
  assertMatch(packageJson.includes('check:chat-user-auth'), 'package.json must expose check:chat-user-auth')
  assertMatch(packageJson.includes('test:chat-user-auth'), 'package.json must expose test:chat-user-auth')

  scanForBannedIdentity(path.join(repoRoot, 'frontend', 'src'))
  scanForBannedIdentity(path.join(repoRoot, 'frontend', 'scripts'))

  const diffOutput = execSync('git diff --name-only', { cwd: repoRoot, encoding: 'utf8' }).trim()
  const changedFiles = diffOutput ? diffOutput.split(/\r?\n/).filter(Boolean) : []

  const forbiddenBackendChanges = changedFiles.filter((filePath) => filePath.startsWith('backend/'))
  assertMatch(forbiddenBackendChanges.length === 0, `backend must not be modified: ${forbiddenBackendChanges.join(', ')}`)

  const forbiddenWatchAlertChanges = changedFiles.filter(
    (filePath) =>
      filePath === 'frontend/src/api/watchAlerts.ts' ||
      filePath === 'frontend/src/features/watchAlerts/identity.ts' ||
      filePath === 'frontend/src/components/WatchButton.tsx' ||
      filePath === 'frontend/src/pages/WatchlistPage.tsx' ||
      filePath === 'frontend/src/pages/AlertsPage.tsx',
  )
  assertMatch(forbiddenWatchAlertChanges.length === 0, `Watch/Alert business files must not be modified: ${forbiddenWatchAlertChanges.join(', ')}`)

  console.log('CHAT_USER_AUTH_UI_CHECK=PASS')
} catch (error) {
  console.error('CHAT_USER_AUTH_UI_CHECK=FAIL')
  console.error(error instanceof Error ? error.message : String(error))
  process.exitCode = 1
}
