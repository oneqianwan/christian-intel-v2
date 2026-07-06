import fs from 'node:fs'
import path from 'node:path'
import { execSync } from 'node:child_process'

const frontendDir = process.cwd()
const repoRoot = path.resolve(frontendDir, '..')

function assert(condition, message) {
  if (!condition) {
    throw new Error(message)
  }
}

function read(relativePath) {
  return fs.readFileSync(path.join(frontendDir, relativePath), 'utf8')
}

function exists(relativePath) {
  return fs.existsSync(path.join(frontendDir, relativePath))
}

function grep(relativePath, pattern, message) {
  const content = read(relativePath)
  assert(pattern.test(content), message)
}

function grepNot(relativePath, pattern, message) {
  const content = read(relativePath)
  assert(!pattern.test(content), message)
}

const requiredFiles = [
  'src/auth/AuthProvider.tsx',
  'src/auth/useAuth.ts',
  'src/pages/LoginPage.tsx',
  'src/pages/SecuritySettingsPage.tsx',
  'src/auth/AuthGuard.tsx',
  'src/auth/AdminGuard.tsx',
  'src/api/auth.ts',
  'src/types/auth.ts',
]

for (const file of requiredFiles) {
  assert(exists(file), `Missing required file: ${file}`)
}

grep('src/App.tsx', /path="\/login"/, 'Missing /login route')
grep('src/App.tsx', /path="\/settings\/security"/, 'Missing /settings/security route')
grep('src/api/auth.ts', /credentials:\s*'include'/, 'Auth API must use credentials include')
grep('src/main.tsx', /<AuthProvider>/, 'App must mount AuthProvider')
grep('src/components/Sidebar.tsx', /UserMenu/, 'Sidebar must include UserMenu')

const authSourceFiles = [
  'src/api/auth.ts',
  'src/auth/AuthProvider.tsx',
  'src/auth/AuthGuard.tsx',
  'src/auth/AdminGuard.tsx',
  'src/auth/useAuth.ts',
  'src/components/UserMenu.tsx',
  'src/pages/LoginPage.tsx',
  'src/pages/SecuritySettingsPage.tsx',
]

const bannedSessionFallbackPattern = new RegExp(`session${'-'}1`)

for (const file of authSourceFiles) {
  grepNot(file, bannedSessionFallbackPattern, `Forbidden session fallback found in ${file}`)
  grepNot(file, /x-session-id/i, `Forbidden x-session-id usage found in ${file}`)
  grepNot(file, /localStorage/i, `Forbidden localStorage usage found in ${file}`)
  grepNot(file, /sessionStorage/i, `Forbidden sessionStorage usage found in ${file}`)
  grepNot(file, /\buser_id\b/, `Forbidden user_id auth payload found in ${file}`)
  grepNot(file, /password_hash|token_hash|session_token/i, `Sensitive auth field found in ${file}`)
}

grepNot('src/pages/LoginPage.tsx', /register|注册入口|忘记密码入口/, 'Public registration or password reset entry must not exist')
grepNot('src/pages/LoginPage.tsx', /admin\/admin|default password/i, 'Hardcoded default credentials found in LoginPage')

grep('.env.example', /VITE_AUTH_V1_ENABLED=false/, 'VITE_AUTH_V1_ENABLED must default to false')
grep('.env.example', /VITE_AUTH_REQUIRED=false/, 'VITE_AUTH_REQUIRED must default to false')

const diffOutput = execSync('git diff --name-only', {
  cwd: repoRoot,
  encoding: 'utf8',
}).trim()

const changedFiles = diffOutput ? diffOutput.split(/\r?\n/).filter(Boolean) : []
const forbiddenDiffPrefixes = [
  'backend/',
  'frontend/src/api/watchAlerts.ts',
  'frontend/src/components/NotificationBell.tsx',
  'frontend/src/components/WatchButton.tsx',
  'frontend/src/components/SignalList.tsx',
  'frontend/src/pages/WatchlistPage.tsx',
  'frontend/src/pages/AlertsPage.tsx',
]

for (const file of changedFiles) {
  assert(!forbiddenDiffPrefixes.some((prefix) => file === prefix || file.startsWith(prefix)), `Forbidden changed file detected: ${file}`)
}

console.log('AUTH_UI_CHECK=PASS')
