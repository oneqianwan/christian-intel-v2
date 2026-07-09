import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import {
  AdminApiError,
  listAdminUsers,
  revokeAdminUserSessions,
  updateAdminUserRole,
  updateAdminUserStatus,
  type AdminUser,
} from '../api/admin'
import { useAuth } from '../auth/useAuth'
import type { UserRole, UserStatus } from '../types/auth'

const ROLE_LABELS: Record<UserRole, string> = {
  super_admin: '超级管理员',
  admin: '管理员',
  analyst: '分析员',
  viewer: '只读用户',
}

const STATUS_LABELS: Record<UserStatus, string> = {
  active: 'active',
  disabled: 'disabled',
  pending: 'pending',
}

type ViewState =
  | { kind: 'idle' }
  | { kind: 'loading' }
  | { kind: 'ready' }
  | { kind: 'empty' }
  | { kind: 'unauthenticated'; message: string }
  | { kind: 'forbidden'; message: string }
  | { kind: 'error'; message: string }

function formatDateTime(value?: string | null) {
  if (!value) {
    return '-'
  }

  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return value
  }

  return date.toLocaleString()
}

function getRoleLabel(role: UserRole) {
  return ROLE_LABELS[role] || role
}

function getStatusLabel(status: UserStatus) {
  return STATUS_LABELS[status] || status
}

function canManageAdminUiRole(currentRole?: UserRole | null) {
  return currentRole === 'super_admin'
}

function canManageStatus(currentRole: UserRole | null | undefined, currentUserId: string | null, row: AdminUser) {
  if (!currentRole || !currentUserId) {
    return false
  }

  if (row.public_id === currentUserId) {
    return false
  }

  if (currentRole === 'super_admin') {
    return true
  }

  if (currentRole === 'admin') {
    return row.role === 'analyst' || row.role === 'viewer'
  }

  return false
}

function canRevokeSessions(currentRole: UserRole | null | undefined, currentUserId: string | null, row: AdminUser) {
  if (!currentRole || !currentUserId) {
    return false
  }

  if (row.public_id === currentUserId) {
    return false
  }

  if (currentRole === 'super_admin') {
    return true
  }

  if (currentRole === 'admin') {
    return row.role === 'analyst' || row.role === 'viewer'
  }

  return false
}

function getMutationErrorMessage(error: unknown) {
  if (!(error instanceof AdminApiError)) {
    return error instanceof Error ? error.message : '操作失败，请稍后重试。'
  }

  if (error.status === 401) {
    return '登录状态已失效，请重新登录。'
  }

  if (error.status === 403) {
    const permissionCodes = new Set([
      'ROLE_FORBIDDEN',
      'AUTH_FORBIDDEN',
      'ADMIN_REQUIRED',
      'SUPER_ADMIN_REQUIRED',
      'HTTP_403',
    ])
    if (permissionCodes.has(error.errorCode)) {
      return '无权限执行该管理操作。'
    }
    return error.message || '无权限执行该管理操作。'
  }

  if (error.status === 409 || error.status === 422 || error.status === 400) {
    return error.message || '请求参数无效。'
  }

  if (error.isNetworkError || error.status === 0) {
    return '网络异常，请稍后重试。'
  }

  return error.message || '操作失败，请稍后重试。'
}

export function AdminUsersPage() {
  const { user, status } = useAuth()
  const [users, setUsers] = useState<AdminUser[]>([])
  const [viewState, setViewState] = useState<ViewState>({ kind: 'idle' })
  const [feedbackMessage, setFeedbackMessage] = useState<string | null>(null)
  const [feedbackTone, setFeedbackTone] = useState<'success' | 'error'>('success')
  const [busyKey, setBusyKey] = useState<string | null>(null)
  const requestSequenceRef = useRef(0)
  const currentRole = user?.role ?? null
  const currentUserId = user?.public_id ?? null
  const canEditRole = canManageAdminUiRole(currentRole)

  const clearDataIfNoAccess = useCallback(() => {
    setUsers([])
    setBusyKey(null)
  }, [])

  const loadUsers = useCallback(async () => {
    if (status !== 'authenticated' || !user) {
      clearDataIfNoAccess()
      setViewState({ kind: 'unauthenticated', message: '需要登录后才能访问管理后台。' })
      return
    }

    if (!(user.role === 'super_admin' || user.role === 'admin')) {
      clearDataIfNoAccess()
      setViewState({ kind: 'forbidden', message: '无权限访问管理后台。' })
      return
    }

    const sequence = requestSequenceRef.current + 1
    requestSequenceRef.current = sequence
    setViewState({ kind: 'loading' })
    setFeedbackMessage(null)

    try {
      const response = await listAdminUsers()
      if (requestSequenceRef.current !== sequence) {
        return
      }

      setUsers(response.items)
      setViewState(response.items.length > 0 ? { kind: 'ready' } : { kind: 'empty' })
    } catch (error) {
      if (requestSequenceRef.current !== sequence) {
        return
      }

      clearDataIfNoAccess()
      if (error instanceof AdminApiError) {
        if (error.status === 401) {
          setViewState({ kind: 'unauthenticated', message: '登录状态已失效，请重新登录后访问管理后台。' })
          return
        }
        if (error.status === 403) {
          setViewState({ kind: 'forbidden', message: '无权限访问管理后台。' })
          return
        }
        if (error.isNetworkError || error.status === 0) {
          setViewState({ kind: 'error', message: '网络异常，请稍后重试。' })
          return
        }
        setViewState({ kind: 'error', message: error.message || '加载用户列表失败。' })
        return
      }

      setViewState({ kind: 'error', message: error instanceof Error ? error.message : '加载用户列表失败。' })
    }
  }, [clearDataIfNoAccess, status, user])

  useEffect(() => {
    if (status !== 'authenticated' || !user) {
      clearDataIfNoAccess()
      setViewState({ kind: 'unauthenticated', message: '需要登录后才能访问管理后台。' })
      return
    }

    if (!(user.role === 'super_admin' || user.role === 'admin')) {
      clearDataIfNoAccess()
      setViewState({ kind: 'forbidden', message: '无权限访问管理后台。' })
      return
    }

    void loadUsers()
  }, [clearDataIfNoAccess, loadUsers, status, user?.public_id, user?.role])

  const summaryText = useMemo(() => {
    if (viewState.kind === 'ready' || viewState.kind === 'empty' || viewState.kind === 'loading') {
      return `共 ${users.length} 位用户`
    }
    return '等待权限校验'
  }, [users.length, viewState.kind])

  const runAction = useCallback(
    async (key: string, action: () => Promise<void>) => {
      setBusyKey(key)
      setFeedbackMessage(null)
      try {
        await action()
      } catch (error) {
        setFeedbackTone('error')
        setFeedbackMessage(getMutationErrorMessage(error))
      } finally {
        setBusyKey(null)
      }
    },
    [],
  )

  const handleRoleChange = useCallback(
    async (row: AdminUser, nextRole: UserRole) => {
      if (!canEditRole || row.role === nextRole || busyKey) {
        return
      }

      await runAction(`role:${row.public_id}`, async () => {
        const updated = await updateAdminUserRole(row.public_id, nextRole)
        setUsers((current) => current.map((item) => (item.public_id === row.public_id ? updated : item)))
        setFeedbackTone('success')
        setFeedbackMessage(`已更新 ${row.email} 的角色。`)
      })
    },
    [busyKey, canEditRole, runAction],
  )

  const handleStatusChange = useCallback(
    async (row: AdminUser, nextStatus: UserStatus) => {
      if (!canManageStatus(currentRole, currentUserId, row) || row.status === nextStatus || busyKey) {
        return
      }

      await runAction(`status:${row.public_id}`, async () => {
        const updated = await updateAdminUserStatus(row.public_id, nextStatus)
        setUsers((current) => current.map((item) => (item.public_id === row.public_id ? updated : item)))
        setFeedbackTone('success')
        setFeedbackMessage(`已更新 ${row.email} 的状态。`)
      })
    },
    [busyKey, currentRole, currentUserId, runAction],
  )

  const handleRevokeSessions = useCallback(
    async (row: AdminUser) => {
      if (!canRevokeSessions(currentRole, currentUserId, row) || busyKey) {
        return
      }

      const confirmed = window.confirm(`确认撤销 ${row.email} 的全部会话？`)
      if (!confirmed) {
        return
      }

      await runAction(`revoke:${row.public_id}`, async () => {
        const response = await revokeAdminUserSessions(row.public_id)
        await loadUsers()
        setFeedbackTone('success')
        setFeedbackMessage(`已撤销 ${row.email} 的 ${response.revoked_count} 个会话。`)
      })
    },
    [busyKey, currentRole, currentUserId, loadUsers, runAction],
  )

  const renderStateCard = () => {
    if (viewState.kind === 'loading') {
      return (
        <div style={stateCardStyle()}>
          <h2 style={stateTitleStyle()}>正在加载用户列表</h2>
          <p style={stateTextStyle()}>请稍候，系统正在从后端读取管理员可见的用户数据。</p>
        </div>
      )
    }

    if (viewState.kind === 'unauthenticated') {
      return (
        <div style={stateCardStyle()}>
          <h2 style={stateTitleStyle()}>需要登录</h2>
          <p style={stateTextStyle()}>{viewState.message}</p>
        </div>
      )
    }

    if (viewState.kind === 'forbidden') {
      return (
        <div style={stateCardStyle('#fff7ed', '#fed7aa')}>
          <h2 style={stateTitleStyle()}>403 无权限访问</h2>
          <p style={stateTextStyle()}>{viewState.message}</p>
        </div>
      )
    }

    if (viewState.kind === 'error') {
      return (
        <div style={stateCardStyle('#fef2f2', '#fecaca')}>
          <h2 style={stateTitleStyle()}>加载失败</h2>
          <p style={stateTextStyle()}>{viewState.message}</p>
        </div>
      )
    }

    if (viewState.kind === 'empty') {
      return (
        <div style={stateCardStyle()}>
          <h2 style={stateTitleStyle()}>暂无用户数据</h2>
          <p style={stateTextStyle()}>当前管理范围内没有可展示的用户记录。</p>
        </div>
      )
    }

    return null
  }

  return (
    <div data-testid="admin-users-page" style={{ display: 'grid', gap: '16px', minHeight: '100%' }}>
      <section
        style={{
          background: '#fff',
          border: '1px solid #e2e8f0',
          borderRadius: '18px',
          padding: '20px 22px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: '16px',
          flexWrap: 'wrap',
        }}
      >
        <div>
          <h2 style={{ margin: 0, fontSize: '20px' }}>Admin Users</h2>
          <p style={{ margin: '8px 0 0', color: '#475569' }}>
            {summaryText}，当前账号角色：{currentRole ? getRoleLabel(currentRole) : '-'}
          </p>
        </div>
        <button
          type="button"
          onClick={() => void loadUsers()}
          disabled={viewState.kind === 'loading' || status !== 'authenticated'}
          style={actionButtonStyle(viewState.kind === 'loading' || status !== 'authenticated')}
        >
          {viewState.kind === 'loading' ? '刷新中...' : '刷新列表'}
        </button>
      </section>

      {feedbackMessage ? (
        <div
          role="status"
          style={{
            borderRadius: '14px',
            padding: '14px 16px',
            border: `1px solid ${feedbackTone === 'success' ? '#bbf7d0' : '#fecaca'}`,
            background: feedbackTone === 'success' ? '#f0fdf4' : '#fef2f2',
            color: feedbackTone === 'success' ? '#166534' : '#b91c1c',
          }}
        >
          {feedbackMessage}
        </div>
      ) : null}

      {viewState.kind !== 'ready' ? (
        renderStateCard()
      ) : (
        <section
          style={{
            background: '#fff',
            border: '1px solid #e2e8f0',
            borderRadius: '18px',
            overflow: 'hidden',
          }}
        >
          <div
            data-testid="admin-users-table-scroll"
            style={{ overflowX: 'auto', overflowY: 'visible' }}
          >
            <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: '1040px' }}>
              <thead>
                <tr style={{ background: '#f8fafc', textAlign: 'left' }}>
                  <TableHead>Email</TableHead>
                  <TableHead>显示名称</TableHead>
                  <TableHead>Role</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Public ID</TableHead>
                  <TableHead>Created</TableHead>
                  <TableHead>Last Login</TableHead>
                  <TableHead>操作</TableHead>
                </tr>
              </thead>
              <tbody>
                {users.map((row) => {
                  const statusEditable = canManageStatus(currentRole, currentUserId, row)
                  const revokeEnabled = canRevokeSessions(currentRole, currentUserId, row)
                  const roleBusy = busyKey === `role:${row.public_id}`
                  const statusBusy = busyKey === `status:${row.public_id}`
                  const revokeBusy = busyKey === `revoke:${row.public_id}`

                  return (
                    <tr key={row.public_id} style={{ borderTop: '1px solid #e2e8f0' }}>
                      <TableCell>
                        <div style={{ fontWeight: 600 }}>{row.email}</div>
                      </TableCell>
                      <TableCell>{row.display_name || '-'}</TableCell>
                      <TableCell>
                        {canEditRole ? (
                          <select
                            aria-label={`修改 ${row.email} 角色`}
                            value={row.role}
                            disabled={row.public_id === currentUserId || roleBusy}
                            onChange={(event) => void handleRoleChange(row, event.target.value as UserRole)}
                            style={selectStyle(row.public_id === currentUserId || roleBusy)}
                          >
                            <option value="super_admin">super_admin</option>
                            <option value="admin">admin</option>
                            <option value="analyst">analyst</option>
                            <option value="viewer">viewer</option>
                          </select>
                        ) : (
                          <span>{getRoleLabel(row.role)}</span>
                        )}
                      </TableCell>
                      <TableCell>
                        {statusEditable ? (
                          <select
                            aria-label={`修改 ${row.email} 状态`}
                            value={row.status}
                            disabled={statusBusy}
                            onChange={(event) => void handleStatusChange(row, event.target.value as UserStatus)}
                            style={selectStyle(statusBusy)}
                          >
                            <option value="active">active</option>
                            <option value="disabled">disabled</option>
                            <option value="pending">pending</option>
                          </select>
                        ) : (
                          <span>{getStatusLabel(row.status)}</span>
                        )}
                      </TableCell>
                      <TableCell>{row.public_id}</TableCell>
                      <TableCell>{formatDateTime(row.created_at)}</TableCell>
                      <TableCell>{formatDateTime(row.last_login_at)}</TableCell>
                      <TableCell>
                        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                          <button
                            type="button"
                            onClick={() => void handleRevokeSessions(row)}
                            disabled={!revokeEnabled || revokeBusy}
                            style={secondaryButtonStyle(!revokeEnabled || revokeBusy)}
                          >
                            {revokeBusy ? '处理中...' : 'Revoke Sessions'}
                          </button>
                        </div>
                      </TableCell>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  )
}

function stateCardStyle(background = '#fff', borderColor = '#e2e8f0') {
  return {
    background,
    border: `1px solid ${borderColor}`,
    borderRadius: '18px',
    padding: '24px',
  } as const
}

function stateTitleStyle() {
  return {
    margin: 0,
    fontSize: '20px',
    color: '#0f172a',
  } as const
}

function stateTextStyle() {
  return {
    margin: '10px 0 0',
    color: '#475569',
    lineHeight: 1.7,
  } as const
}

function actionButtonStyle(disabled: boolean) {
  return {
    border: '1px solid #c7d2fe',
    borderRadius: '10px',
    padding: '10px 14px',
    background: disabled ? '#eef2ff' : '#4f46e5',
    color: disabled ? '#6366f1' : '#fff',
    cursor: disabled ? 'not-allowed' : 'pointer',
    fontWeight: 700,
  } as const
}

function secondaryButtonStyle(disabled: boolean) {
  return {
    border: '1px solid #cbd5e1',
    borderRadius: '10px',
    padding: '9px 12px',
    background: disabled ? '#f8fafc' : '#fff',
    color: disabled ? '#94a3b8' : '#0f172a',
    cursor: disabled ? 'not-allowed' : 'pointer',
    fontWeight: 600,
  } as const
}

function selectStyle(disabled: boolean) {
  return {
    width: '100%',
    minWidth: '132px',
    border: '1px solid #cbd5e1',
    borderRadius: '10px',
    padding: '9px 10px',
    background: disabled ? '#f8fafc' : '#fff',
    color: disabled ? '#94a3b8' : '#0f172a',
    cursor: disabled ? 'not-allowed' : 'pointer',
  } as const
}

function TableHead({ children }: { children: string }) {
  return (
    <th style={{ padding: '14px 16px', fontSize: '13px', color: '#475569', fontWeight: 700 }}>
      {children}
    </th>
  )
}

function TableCell({ children }: { children: ReactNode }) {
  return (
    <td style={{ padding: '16px', verticalAlign: 'top', color: '#0f172a' }}>
      {children}
    </td>
  )
}
