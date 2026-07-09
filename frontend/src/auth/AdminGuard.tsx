import type { ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { AuthLoadingScreen } from '../components/AuthLoadingScreen'
import { useAuth } from './useAuth'
import { isAuthUiEnabled } from './flags'

type AdminGuardProps = {
  children: ReactNode
}

const ALLOWED_ADMIN_ROLES = new Set(['super_admin', 'admin'])

export function AdminGuard({ children }: AdminGuardProps) {
  const location = useLocation()
  const { user, status, refreshUser, error } = useAuth()

  if (!isAuthUiEnabled() || status === 'disabled') {
    return <Navigate to="/" replace />
  }

  if (status === 'loading') {
    return <AuthLoadingScreen title="正在校验管理员权限" description="请稍候，系统正在确认当前账号角色。" />
  }

  if (status === 'error') {
    return (
      <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '24px' }}>
        <div data-testid="admin-guard-error" style={{ maxWidth: '460px', width: '100%', background: '#fff', border: '1px solid #e2e8f0', borderRadius: '18px', padding: '28px' }}>
          <h1 style={{ marginTop: 0, marginBottom: '10px', fontSize: '22px', color: '#0f172a' }}>无法校验管理员权限</h1>
          <p style={{ marginTop: 0, marginBottom: '18px', color: '#475569', lineHeight: 1.7 }}>
            {error?.message || '权限服务暂时不可用，请稍后重试。'}
          </p>
          <button
            type="button"
            onClick={() => void refreshUser()}
            style={{
              border: 'none',
              borderRadius: '10px',
              padding: '10px 16px',
              background: '#4f46e5',
              color: '#fff',
              cursor: 'pointer',
              fontWeight: 600,
            }}
          >
            重试
          </button>
        </div>
      </div>
    )
  }

  if (status !== 'authenticated' || !user) {
    return (
      <Navigate
        to="/login"
        replace
        state={{
          from: `${location.pathname}${location.search}${location.hash}`,
        }}
      />
    )
  }

  if (!ALLOWED_ADMIN_ROLES.has(user.role)) {
    return (
      <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#f8fafc', padding: '24px' }}>
        <div data-testid="admin-guard-forbidden" style={{ maxWidth: '480px', width: '100%', background: '#fff', border: '1px solid #e2e8f0', borderRadius: '18px', padding: '28px' }}>
          <h1 style={{ marginTop: 0, marginBottom: '10px', fontSize: '22px', color: '#0f172a' }}>403 无权限访问</h1>
          <p style={{ marginTop: 0, marginBottom: 0, color: '#475569', lineHeight: 1.7 }}>
            当前页面需要管理员角色。前端 Guard 仅用于界面控制，最终权限边界仍由后端 RBAC 决定。
          </p>
        </div>
      </div>
    )
  }

  return <>{children}</>
}
