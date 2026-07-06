import type { ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { AuthLoadingScreen } from '../components/AuthLoadingScreen'
import { useAuth } from './useAuth'
import { isAuthUiEnabled, isAuthRequired } from './flags'

type AuthGuardProps = {
  children: ReactNode
  requireEnabled?: boolean
}

function AuthGuardError() {
  const { error, refreshUser, clearError } = useAuth()

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: '#f8fafc',
        padding: '24px',
      }}
    >
      <div
        style={{
          width: '100%',
          maxWidth: '460px',
          borderRadius: '18px',
          border: '1px solid #e2e8f0',
          background: '#fff',
          padding: '28px',
          boxShadow: '0 18px 45px rgba(15, 23, 42, 0.08)',
        }}
      >
        <h1 style={{ marginTop: 0, marginBottom: '10px', color: '#0f172a', fontSize: '22px' }}>无法恢复登录状态</h1>
        <p style={{ marginTop: 0, marginBottom: '18px', color: '#475569', lineHeight: 1.7 }}>
          {error?.message || '认证服务暂时不可用，请重试。'}
        </p>
        <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
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
          <button
            type="button"
            onClick={clearError}
            style={{
              border: '1px solid #cbd5e1',
              borderRadius: '10px',
              padding: '10px 16px',
              background: '#fff',
              color: '#334155',
              cursor: 'pointer',
              fontWeight: 600,
            }}
          >
            稍后再试
          </button>
        </div>
      </div>
    </div>
  )
}

export function AuthGuard({ children, requireEnabled = false }: AuthGuardProps) {
  const location = useLocation()
  const { status } = useAuth()
  const authEnabled = isAuthUiEnabled()
  const protectedByGlobalRequirement = authEnabled && isAuthRequired()
  const shouldProtect = requireEnabled || protectedByGlobalRequirement

  if (!shouldProtect) {
    return <>{children}</>
  }

  if (!authEnabled || status === 'disabled') {
    return <Navigate to="/" replace />
  }

  if (status === 'loading') {
    return <AuthLoadingScreen />
  }

  if (status === 'error') {
    return <AuthGuardError />
  }

  if (status === 'authenticated') {
    return <>{children}</>
  }

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
