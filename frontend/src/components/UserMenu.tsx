import { useMemo, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/useAuth'
import { isAuthUiEnabled } from '../auth/flags'

const ROLE_LABELS: Record<string, string> = {
  super_admin: '超级管理员',
  admin: '管理员',
  analyst: '分析员',
  viewer: '只读用户',
}

function cardStyle() {
  return {
    borderTop: '1px solid #e5e7eb',
    padding: '14px 16px 16px',
    background: '#fff',
  } as const
}

export function UserMenu() {
  const navigate = useNavigate()
  const location = useLocation()
  const { user, status, logout } = useAuth()
  const [busy, setBusy] = useState(false)

  const roleLabel = useMemo(() => {
    if (!user) {
      return ''
    }
    return ROLE_LABELS[user.role] || user.role
  }, [user])

  if (!isAuthUiEnabled() || status === 'disabled') {
    return null
  }

  const handleLoginClick = () => {
    navigate('/login', {
      state: {
        from: `${location.pathname}${location.search}${location.hash}`,
      },
    })
  }

  const handleLogout = async () => {
    setBusy(true)
    try {
      await logout()
    } finally {
      setBusy(false)
      navigate('/login', {
        replace: true,
        state: {
          message: '已退出登录。',
        },
      })
    }
  }

  if (status === 'loading') {
    return (
      <div style={cardStyle()}>
        <div style={{ fontSize: '12px', color: '#64748b' }}>正在恢复登录状态...</div>
      </div>
    )
  }

  if (!user || status !== 'authenticated') {
    return (
      <div style={cardStyle()}>
        <div style={{ fontSize: '12px', color: '#64748b', marginBottom: '10px' }}>正式登录功能已启用</div>
        <button
          type="button"
          onClick={handleLoginClick}
          style={{
            width: '100%',
            border: '1px solid #cbd5e1',
            borderRadius: '10px',
            padding: '10px 14px',
            background: '#fff',
            color: '#0f172a',
            cursor: 'pointer',
            fontWeight: 600,
          }}
        >
          登录
        </button>
      </div>
    )
  }

  return (
    <div style={cardStyle()}>
      <details>
        <summary
          style={{
            listStyle: 'none',
            cursor: 'pointer',
            display: 'flex',
            flexDirection: 'column',
            gap: '4px',
            outline: 'none',
          }}
        >
          <span style={{ fontSize: '14px', fontWeight: 700, color: '#0f172a' }}>{user.display_name}</span>
          <span style={{ fontSize: '12px', color: '#475569', wordBreak: 'break-word' }}>{user.email}</span>
          <span style={{ fontSize: '12px', color: '#6366f1', fontWeight: 600 }}>{roleLabel}</span>
        </summary>
        <div style={{ display: 'grid', gap: '10px', marginTop: '12px' }}>
          <button
            type="button"
            onClick={() => navigate('/settings/security')}
            style={{
              width: '100%',
              border: '1px solid #cbd5e1',
              borderRadius: '10px',
              padding: '10px 14px',
              background: '#fff',
              color: '#0f172a',
              cursor: 'pointer',
              textAlign: 'left',
            }}
          >
            安全设置
          </button>
          <button
            type="button"
            onClick={() => void handleLogout()}
            disabled={busy}
            style={{
              width: '100%',
              border: '1px solid #fecaca',
              borderRadius: '10px',
              padding: '10px 14px',
              background: busy ? '#fff1f2' : '#fff',
              color: '#b91c1c',
              cursor: busy ? 'not-allowed' : 'pointer',
              textAlign: 'left',
            }}
          >
            {busy ? '退出中...' : '退出登录'}
          </button>
        </div>
      </details>
    </div>
  )
}
