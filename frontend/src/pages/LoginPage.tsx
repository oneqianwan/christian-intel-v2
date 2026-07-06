import { useMemo, useState } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { AuthApiError } from '../api/auth'
import { AuthLoadingScreen } from '../components/AuthLoadingScreen'
import { isAuthUiEnabled } from '../auth/flags'
import { useAuth } from '../auth/useAuth'

type LocationState = {
  from?: string
  message?: string
}

function mapLoginError(error: unknown) {
  if (error instanceof AuthApiError) {
    if (error.isNetworkError) {
      return '后端不可用，请稍后重试。'
    }

    if (error.status === 401 && error.errorCode === 'INVALID_CREDENTIALS') {
      return '邮箱或密码错误。'
    }

    if (error.status === 403 && error.errorCode === 'ACCOUNT_DISABLED') {
      return '账号已禁用，请联系管理员。'
    }

    if (error.status === 403 && error.errorCode === 'ACCOUNT_PENDING') {
      return '账号待启用，请联系管理员。'
    }

    if (error.status === 429) {
      return '尝试过多，请稍后重试。'
    }

    if (error.status === 503 && error.errorCode === 'AUTH_DISABLED') {
      return '登录功能暂未启用。'
    }

    return '登录失败，请稍后重试。'
  }

  return '登录失败，请稍后重试。'
}

function getRedirectTarget(candidate: unknown) {
  if (typeof candidate !== 'string') {
    return '/'
  }
  if (!candidate.startsWith('/')) {
    return '/'
  }
  return candidate
}

export function LoginPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const locationState = (location.state || {}) as LocationState
  const { login, status } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const redirectTarget = useMemo(() => getRedirectTarget(locationState.from), [locationState.from])
  const noticeMessage = typeof locationState.message === 'string' ? locationState.message : null
  const authEnabled = isAuthUiEnabled()
  const canSubmit = email.trim().length > 0 && password.length > 0 && !submitting

  if (!authEnabled || status === 'disabled') {
    return (
      <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '24px', background: '#f8fafc' }}>
        <div style={{ width: '100%', maxWidth: '440px', background: '#fff', border: '1px solid #e2e8f0', borderRadius: '18px', padding: '28px' }}>
          <h1 style={{ marginTop: 0, marginBottom: '10px', fontSize: '24px', color: '#0f172a' }}>登录未启用</h1>
          <p style={{ marginTop: 0, marginBottom: 0, color: '#475569', lineHeight: 1.7 }}>
            当前环境已关闭正式 Auth UI。请保持 `VITE_AUTH_V1_ENABLED=false` 的兼容模式，或在测试环境开启后再访问本页面。
          </p>
        </div>
      </div>
    )
  }

  if (status === 'loading') {
    return <AuthLoadingScreen title="正在检查当前会话" description="请稍候，系统会自动恢复已登录状态。" />
  }

  if (status === 'authenticated') {
    return <Navigate to={redirectTarget} replace />
  }

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!canSubmit) {
      return
    }

    setSubmitting(true)
    setErrorMessage(null)

    try {
      await login({
        email: email.trim(),
        password,
      })
      navigate(redirectTarget, { replace: true })
    } catch (error) {
      setErrorMessage(mapLoginError(error))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '24px',
        background: 'linear-gradient(180deg, #f8fafc 0%, #eef2ff 100%)',
      }}
    >
      <div
        style={{
          width: '100%',
          maxWidth: '460px',
          background: '#fff',
          border: '1px solid #e2e8f0',
          borderRadius: '20px',
          padding: '30px',
          boxShadow: '0 18px 45px rgba(15, 23, 42, 0.08)',
        }}
      >
        <h1 style={{ marginTop: 0, marginBottom: '10px', fontSize: '28px', color: '#0f172a' }}>账号登录</h1>
        <p style={{ marginTop: 0, marginBottom: '20px', color: '#475569', lineHeight: 1.7 }}>
          使用已创建的管理员或用户账号登录。当前不提供公共注册和找回密码入口。
        </p>

        {noticeMessage ? (
          <div style={{ marginBottom: '16px', borderRadius: '12px', background: '#ecfdf5', border: '1px solid #86efac', color: '#166534', padding: '12px 14px' }}>
            {noticeMessage}
          </div>
        ) : null}

        {errorMessage ? (
          <div role="alert" style={{ marginBottom: '16px', borderRadius: '12px', background: '#fef2f2', border: '1px solid #fecaca', color: '#991b1b', padding: '12px 14px' }}>
            {errorMessage}
          </div>
        ) : null}

        <form onSubmit={handleSubmit} style={{ display: 'grid', gap: '16px' }}>
          <label style={{ display: 'grid', gap: '8px' }}>
            <span style={{ fontSize: '14px', fontWeight: 600, color: '#1e293b' }}>邮箱</span>
            <input
              type="email"
              inputMode="email"
              autoComplete="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="you@example.com"
              style={{
                width: '100%',
                borderRadius: '12px',
                border: '1px solid #cbd5e1',
                padding: '12px 14px',
                fontSize: '14px',
                boxSizing: 'border-box',
              }}
            />
          </label>

          <label style={{ display: 'grid', gap: '8px' }}>
            <span style={{ fontSize: '14px', fontWeight: 600, color: '#1e293b' }}>密码</span>
            <input
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder="请输入密码"
              style={{
                width: '100%',
                borderRadius: '12px',
                border: '1px solid #cbd5e1',
                padding: '12px 14px',
                fontSize: '14px',
                boxSizing: 'border-box',
              }}
            />
          </label>

          <button
            type="submit"
            disabled={!canSubmit}
            style={{
              border: 'none',
              borderRadius: '12px',
              padding: '12px 16px',
              background: canSubmit ? '#4f46e5' : '#c7d2fe',
              color: '#fff',
              cursor: canSubmit ? 'pointer' : 'not-allowed',
              fontWeight: 700,
              fontSize: '14px',
            }}
          >
            {submitting ? '登录中...' : '登录'}
          </button>
        </form>

        <div style={{ marginTop: '18px', color: '#64748b', fontSize: '13px', lineHeight: 1.7 }}>
          注册与忘记密码功能暂未开放，请联系管理员处理账号问题。
        </div>
      </div>
    </div>
  )
}
