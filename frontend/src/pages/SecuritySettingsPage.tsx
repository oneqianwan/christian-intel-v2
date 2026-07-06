import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AuthApiError } from '../api/auth'
import { useAuth } from '../auth/useAuth'

const MIN_PASSWORD_LENGTH = 12
const MAX_PASSWORD_LENGTH = 128

function mapSecurityError(error: unknown) {
  if (error instanceof AuthApiError) {
    if (error.isNetworkError) {
      return '后端不可用，请稍后重试。'
    }

    switch (error.errorCode) {
      case 'CURRENT_PASSWORD_INVALID':
        return '当前密码错误。'
      case 'PASSWORD_CONFIRMATION_MISMATCH':
        return '两次输入的新密码不一致。'
      case 'PASSWORD_TOO_SHORT':
        return `新密码至少 ${MIN_PASSWORD_LENGTH} 个字符。`
      case 'PASSWORD_TOO_LONG':
        return `新密码不能超过 ${MAX_PASSWORD_LENGTH} 个字符。`
      case 'PASSWORD_UNCHANGED':
        return '新密码不能与当前密码相同。'
      case 'PASSWORD_WHITESPACE_ONLY':
        return '新密码不能全部为空白字符。'
      case 'AUTH_DISABLED':
        return '认证功能未启用。'
      default:
        return '操作失败，请稍后重试。'
    }
  }

  return '操作失败，请稍后重试。'
}

export function SecuritySettingsPage() {
  const navigate = useNavigate()
  const { user, changePassword, logoutAll } = useAuth()
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [formError, setFormError] = useState<string | null>(null)
  const [formSuccess, setFormSuccess] = useState<string | null>(null)
  const [changingPassword, setChangingPassword] = useState(false)
  const [loggingOutAll, setLoggingOutAll] = useState(false)

  const resetPasswordFields = () => {
    setCurrentPassword('')
    setNewPassword('')
    setConfirmPassword('')
  }

  const handleChangePassword = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (changingPassword) {
      return
    }

    setFormError(null)
    setFormSuccess(null)

    if (newPassword.length < MIN_PASSWORD_LENGTH) {
      setFormError(`新密码至少 ${MIN_PASSWORD_LENGTH} 个字符。`)
      return
    }
    if (newPassword.length > MAX_PASSWORD_LENGTH) {
      setFormError(`新密码不能超过 ${MAX_PASSWORD_LENGTH} 个字符。`)
      return
    }
    if (newPassword !== confirmPassword) {
      setFormError('两次输入的新密码不一致。')
      return
    }
    if (currentPassword === newPassword) {
      setFormError('新密码不能与当前密码相同。')
      return
    }

    setChangingPassword(true)
    try {
      await changePassword({
        current_password: currentPassword,
        new_password: newPassword,
        confirm_password: confirmPassword,
      })
      resetPasswordFields()
      navigate('/login', {
        replace: true,
        state: {
          message: '密码已修改，请重新登录。',
        },
      })
    } catch (error) {
      setFormError(mapSecurityError(error))
    } finally {
      setChangingPassword(false)
    }
  }

  const handleLogoutAll = async () => {
    if (loggingOutAll) {
      return
    }

    const confirmed = window.confirm('确认退出所有设备吗？当前设备也会立即失效，需要重新登录。')
    if (!confirmed) {
      return
    }

    setFormError(null)
    setFormSuccess(null)
    setLoggingOutAll(true)
    try {
      const response = await logoutAll()
      setFormSuccess(`已退出所有设备，撤销 ${response.revoked_count} 个会话。`)
      navigate('/login', {
        replace: true,
        state: {
          message: `已退出所有设备，撤销 ${response.revoked_count} 个会话。`,
        },
      })
    } catch (error) {
      setFormError(mapSecurityError(error))
    } finally {
      setLoggingOutAll(false)
    }
  }

  return (
    <div style={{ minHeight: '100vh', background: '#f8fafc', padding: '24px' }}>
      <div style={{ maxWidth: '820px', margin: '0 auto', display: 'grid', gap: '20px' }}>
        <div style={{ background: '#fff', border: '1px solid #e2e8f0', borderRadius: '18px', padding: '24px' }}>
          <h1 style={{ marginTop: 0, marginBottom: '10px', fontSize: '28px', color: '#0f172a' }}>安全设置</h1>
          <p style={{ marginTop: 0, marginBottom: 0, color: '#475569', lineHeight: 1.7 }}>
            修改密码和退出全部设备后，当前登录状态都会失效，需要重新登录。
          </p>
        </div>

        <div style={{ background: '#fff', border: '1px solid #e2e8f0', borderRadius: '18px', padding: '24px' }}>
          <h2 style={{ marginTop: 0, marginBottom: '14px', fontSize: '20px', color: '#0f172a' }}>当前账号</h2>
          <div style={{ display: 'grid', gap: '10px', color: '#334155' }}>
            <div><strong>名称：</strong>{user?.display_name || '-'}</div>
            <div><strong>邮箱：</strong>{user?.email || '-'}</div>
            <div><strong>角色：</strong>{user?.role || '-'}</div>
            <div><strong>状态：</strong>{user?.status || '-'}</div>
          </div>
        </div>

        <div style={{ background: '#fff', border: '1px solid #e2e8f0', borderRadius: '18px', padding: '24px' }}>
          <h2 style={{ marginTop: 0, marginBottom: '14px', fontSize: '20px', color: '#0f172a' }}>修改密码</h2>

          {formError ? (
            <div role="alert" style={{ marginBottom: '16px', borderRadius: '12px', background: '#fef2f2', border: '1px solid #fecaca', color: '#991b1b', padding: '12px 14px' }}>
              {formError}
            </div>
          ) : null}
          {formSuccess ? (
            <div style={{ marginBottom: '16px', borderRadius: '12px', background: '#ecfdf5', border: '1px solid #86efac', color: '#166534', padding: '12px 14px' }}>
              {formSuccess}
            </div>
          ) : null}

          <form onSubmit={handleChangePassword} style={{ display: 'grid', gap: '16px' }}>
            <label style={{ display: 'grid', gap: '8px' }}>
              <span style={{ fontSize: '14px', fontWeight: 600, color: '#1e293b' }}>当前密码</span>
              <input
                type="password"
                autoComplete="current-password"
                value={currentPassword}
                onChange={(event) => setCurrentPassword(event.target.value)}
                style={{ borderRadius: '12px', border: '1px solid #cbd5e1', padding: '12px 14px', fontSize: '14px' }}
              />
            </label>
            <label style={{ display: 'grid', gap: '8px' }}>
              <span style={{ fontSize: '14px', fontWeight: 600, color: '#1e293b' }}>新密码</span>
              <input
                type="password"
                autoComplete="new-password"
                value={newPassword}
                onChange={(event) => setNewPassword(event.target.value)}
                style={{ borderRadius: '12px', border: '1px solid #cbd5e1', padding: '12px 14px', fontSize: '14px' }}
              />
            </label>
            <label style={{ display: 'grid', gap: '8px' }}>
              <span style={{ fontSize: '14px', fontWeight: 600, color: '#1e293b' }}>确认新密码</span>
              <input
                type="password"
                autoComplete="new-password"
                value={confirmPassword}
                onChange={(event) => setConfirmPassword(event.target.value)}
                style={{ borderRadius: '12px', border: '1px solid #cbd5e1', padding: '12px 14px', fontSize: '14px' }}
              />
            </label>
            <button
              type="submit"
              disabled={changingPassword}
              style={{
                border: 'none',
                borderRadius: '12px',
                padding: '12px 16px',
                background: changingPassword ? '#c7d2fe' : '#4f46e5',
                color: '#fff',
                cursor: changingPassword ? 'not-allowed' : 'pointer',
                fontWeight: 700,
              }}
            >
              {changingPassword ? '提交中...' : '修改密码'}
            </button>
          </form>
        </div>

        <div style={{ background: '#fff', border: '1px solid #e2e8f0', borderRadius: '18px', padding: '24px' }}>
          <h2 style={{ marginTop: 0, marginBottom: '12px', fontSize: '20px', color: '#0f172a' }}>退出全部设备</h2>
          <p style={{ marginTop: 0, marginBottom: '16px', color: '#475569', lineHeight: 1.7 }}>
            这会撤销当前账号的所有有效会话，包括本设备。完成后需要重新登录。
          </p>
          <button
            type="button"
            onClick={() => void handleLogoutAll()}
            disabled={loggingOutAll}
            style={{
              border: '1px solid #fecaca',
              borderRadius: '12px',
              padding: '12px 16px',
              background: loggingOutAll ? '#fff1f2' : '#fff',
              color: '#b91c1c',
              cursor: loggingOutAll ? 'not-allowed' : 'pointer',
              fontWeight: 700,
            }}
          >
            {loggingOutAll ? '处理中...' : '退出所有设备'}
          </button>
        </div>
      </div>
    </div>
  )
}
