import fs from 'node:fs'
import path from 'node:path'
import process from 'node:process'
import { execSync } from 'node:child_process'

const frontendRoot = process.cwd()
const repoRoot = path.resolve(frontendRoot, '..')

function read(relativePath) {
  return fs.readFileSync(path.join(frontendRoot, relativePath), 'utf8')
}

function exists(relativePath) {
  return fs.existsSync(path.join(frontendRoot, relativePath))
}

function assertMatch(condition, message) {
  if (!condition) {
    throw new Error(message)
  }
}

function grep(source, pattern, message) {
  assertMatch(pattern.test(source), message)
}

function grepNot(source, pattern, message) {
  assertMatch(!pattern.test(source), message)
}

try {
  const requiredFiles = [
    'src/App.tsx',
    'src/auth/AdminGuard.tsx',
    'src/components/AdminLayout.tsx',
    'src/components/UserMenu.tsx',
    'src/api/admin.ts',
    'src/pages/AdminUsersPage.tsx',
    'src/auth/__tests__/AdminGuard.test.tsx',
    'src/api/__tests__/adminApi.test.ts',
    'src/components/__tests__/UserMenu.admin.test.tsx',
    'src/pages/__tests__/AdminUsersPage.test.tsx',
  ]

  for (const file of requiredFiles) {
    assertMatch(exists(file), `Missing required file: ${file}`)
  }

  const appSource = read('src/App.tsx')
  const adminGuardSource = read('src/auth/AdminGuard.tsx')
  const userMenuSource = read('src/components/UserMenu.tsx')
  const adminApiSource = read('src/api/admin.ts')
  const adminLayoutSource = read('src/components/AdminLayout.tsx')
  const adminPageSource = read('src/pages/AdminUsersPage.tsx')
  const packageJson = read('package.json')

  grep(appSource, /path="\/admin"/, 'Missing /admin route')
  grep(appSource, /path="\/admin\/users"/, 'Missing /admin/users route')
  grep(appSource, /<AdminGuard>/, 'Admin routes must be wrapped by AdminGuard')
  grep(appSource, /<AdminLayout>/, 'Admin routes must use AdminLayout')
  grep(appSource, /<AdminUsersPage \/>/, 'Admin routes must render AdminUsersPage')

  grep(adminGuardSource, /ALLOWED_ADMIN_ROLES/, 'AdminGuard must keep explicit admin role allow-list')
  grep(adminGuardSource, /status !== 'authenticated' \|\| !user/, 'AdminGuard must block unauthenticated access')
  grep(adminGuardSource, /403 无权限访问/, 'AdminGuard must provide explicit forbidden UI')

  grep(adminLayoutSource, /data-testid="admin-layout-scroll-container"/, 'AdminLayout must expose a dedicated scroll container')
  grep(adminLayoutSource, /overflowY:\s*'auto'/, 'AdminLayout scroll container must support vertical scrolling')
  grep(adminLayoutSource, /minHeight:\s*0/, 'AdminLayout scroll container must reset minHeight to avoid clipping')
  grep(adminLayoutSource, /overflow:\s*'hidden'/, 'AdminLayout root must prevent body-level overflow leakage')

  grep(userMenuSource, /ADMIN_ROLES/, 'UserMenu must keep explicit admin role allow-list')
  grep(userMenuSource, /navigate\('\/admin'\)/, 'UserMenu must navigate to /admin')
  grep(userMenuSource, /管理后台/, 'UserMenu must expose admin entry label')

  grep(adminApiSource, /credentials:\s*'include'/, 'Admin API client must use credentials include')
  grep(adminApiSource, /\/admin\/users/, 'Admin API client must target /admin/users')
  grep(adminApiSource, /updateAdminUserRole/, 'Admin API client must expose role update function')
  grep(adminApiSource, /updateAdminUserStatus/, 'Admin API client must expose status update function')
  grep(adminApiSource, /revokeAdminUserSessions/, 'Admin API client must expose revoke sessions function')
  grepNot(adminApiSource, /\bx-session-id\b/i, 'Admin API client must not use x-session-id')
  grepNot(adminApiSource, /\buser_id\b/, 'Admin API client must not send user_id fields')
  grepNot(adminApiSource, /\bpassword_hash\b|\btoken\b/i, 'Admin API client must not depend on sensitive fields')

  grep(adminPageSource, /listAdminUsers/, 'AdminUsersPage must load users list')
  grep(adminPageSource, /updateAdminUserRole/, 'AdminUsersPage must support role updates')
  grep(adminPageSource, /updateAdminUserStatus/, 'AdminUsersPage must support status updates')
  grep(adminPageSource, /revokeAdminUserSessions/, 'AdminUsersPage must support session revoke')
  grep(adminPageSource, /无权限访问管理后台/, 'AdminUsersPage must show explicit forbidden message')
  grep(adminPageSource, /登录状态已失效|需要登录/, 'AdminUsersPage must handle unauthenticated state')
  grep(adminPageSource, /data-testid="admin-users-table-scroll"/, 'AdminUsersPage must expose a table scroll wrapper')
  grep(adminPageSource, /minHeight:\s*'100%'/, 'AdminUsersPage must stretch within the scroll container')
  grepNot(adminPageSource, /password_hash|token/i, 'AdminUsersPage must not render sensitive fields')

  assertMatch(packageJson.includes('check:admin-ui'), 'package.json must expose check:admin-ui')
  assertMatch(packageJson.includes('test:admin-ui'), 'package.json must expose test:admin-ui')

  const diffOutput = execSync('git diff --name-only', { cwd: repoRoot, encoding: 'utf8' }).trim()
  const changedFiles = diffOutput ? diffOutput.split(/\r?\n/).filter(Boolean) : []
  const forbiddenBackendChanges = changedFiles.filter((filePath) => filePath.startsWith('backend/'))
  assertMatch(forbiddenBackendChanges.length === 0, `backend must not be modified: ${forbiddenBackendChanges.join(', ')}`)

  console.log('ADMIN_UI_CHECK=PASS')
} catch (error) {
  console.error('ADMIN_UI_CHECK=FAIL')
  console.error(error instanceof Error ? error.message : String(error))
  process.exitCode = 1
}
