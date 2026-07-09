import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  AdminApiError,
  listAdminUsers,
  revokeAdminUserSessions,
  updateAdminUserRole,
  updateAdminUserStatus,
  type AdminUser,
} from '../../api/admin'
import { useAuth } from '../../auth/useAuth'
import { AdminUsersPage } from '../AdminUsersPage'

vi.mock('../../auth/useAuth', () => ({
  useAuth: vi.fn(),
}))

vi.mock('../../api/admin', async () => {
  const actual = await vi.importActual<typeof import('../../api/admin')>('../../api/admin')
  return {
    ...actual,
    listAdminUsers: vi.fn(),
    updateAdminUserRole: vi.fn(),
    updateAdminUserStatus: vi.fn(),
    revokeAdminUserSessions: vi.fn(),
  }
})

const mockedUseAuth = vi.mocked(useAuth)
const mockedListAdminUsers = vi.mocked(listAdminUsers)
const mockedUpdateAdminUserRole = vi.mocked(updateAdminUserRole)
const mockedUpdateAdminUserStatus = vi.mocked(updateAdminUserStatus)
const mockedRevokeAdminUserSessions = vi.mocked(revokeAdminUserSessions)

function createUseAuthValue(overrides: Partial<ReturnType<typeof useAuth>> = {}) {
  return {
    user: {
      public_id: 'current-user-public-id',
      email: 'admin@example.com',
      display_name: 'Admin User',
      role: 'admin' as const,
      status: 'active' as const,
    },
    status: 'authenticated' as const,
    error: null,
    login: vi.fn(),
    logout: vi.fn(),
    refreshUser: vi.fn(),
    changePassword: vi.fn(),
    logoutAll: vi.fn(),
    clearError: vi.fn(),
    ...overrides,
  }
}

const sampleUsers: AdminUser[] = [
  {
    public_id: 'super-public-id',
    email: 'super@example.com',
    display_name: 'Super',
    role: 'super_admin',
    status: 'active',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    last_login_at: '2026-01-02T00:00:00Z',
  },
  {
    public_id: 'analyst-public-id',
    email: 'analyst@example.com',
    display_name: 'Analyst',
    role: 'analyst',
    status: 'pending',
    created_at: '2026-01-03T00:00:00Z',
    updated_at: '2026-01-03T00:00:00Z',
    last_login_at: null,
  },
]

describe('AdminUsersPage', () => {
  beforeEach(() => {
    mockedUseAuth.mockReset()
    mockedListAdminUsers.mockReset()
    mockedUpdateAdminUserRole.mockReset()
    mockedUpdateAdminUserStatus.mockReset()
    mockedRevokeAdminUserSessions.mockReset()
    vi.restoreAllMocks()
  })

  it('未登录时显示需要登录，且不请求 admin users API', () => {
    mockedUseAuth.mockReturnValue(
      createUseAuthValue({
        user: null,
        status: 'unauthenticated',
      }),
    )

    render(<AdminUsersPage />)

    expect(screen.getByText('需要登录')).toBeInTheDocument()
    expect(mockedListAdminUsers).not.toHaveBeenCalled()
  })

  it.each(['analyst', 'viewer'] as const)('%s 访问页面显示无权限且不加载列表', (role) => {
    mockedUseAuth.mockReturnValue(
      createUseAuthValue({
        user: {
          public_id: 'public-member-alpha',
          email: `${role}@example.com`,
          display_name: role,
          role,
          status: 'active',
        },
      }),
    )

    render(<AdminUsersPage />)

    expect(screen.getByText('403 无权限访问')).toBeInTheDocument()
    expect(mockedListAdminUsers).not.toHaveBeenCalled()
  })

  it('admin 可以加载用户列表，且页面不展示 password_hash 或 token', async () => {
    mockedUseAuth.mockReturnValue(createUseAuthValue())
    mockedListAdminUsers.mockResolvedValue({
      items: [
        {
          ...sampleUsers[0],
          password_hash: 'should-not-render',
          token: 'should-not-render',
        } as never,
        sampleUsers[1],
      ],
      total: 2,
      limit: 100,
      offset: 0,
    })

    render(<AdminUsersPage />)

    expect(await screen.findByText('super@example.com')).toBeInTheDocument()
    expect(screen.getByText('analyst@example.com')).toBeInTheDocument()
    expect(screen.queryByText('should-not-render')).not.toBeInTheDocument()
  })

  it('页面外层与表格区域保留可滚动访问能力，不会因为固定高度直接截断', async () => {
    mockedUseAuth.mockReturnValue(createUseAuthValue())
    mockedListAdminUsers.mockResolvedValue({
      items: [
        ...sampleUsers,
        {
          public_id: 'viewer-public-id',
          email: 'viewer@example.com',
          display_name: 'Viewer',
          role: 'viewer',
          status: 'active',
          created_at: '2026-01-04T00:00:00Z',
          updated_at: '2026-01-04T00:00:00Z',
          last_login_at: null,
        },
        {
          public_id: 'admin-public-id',
          email: 'admin2@example.com',
          display_name: 'Admin Two',
          role: 'admin',
          status: 'active',
          created_at: '2026-01-05T00:00:00Z',
          updated_at: '2026-01-05T00:00:00Z',
          last_login_at: null,
        },
      ],
      total: 4,
      limit: 100,
      offset: 0,
    })

    render(<AdminUsersPage />)

    expect(await screen.findByText('viewer@example.com')).toBeInTheDocument()
    expect(screen.getByText('admin2@example.com')).toBeInTheDocument()
    expect(screen.getByTestId('admin-users-page')).toHaveStyle({
      minHeight: '100%',
    })
    expect(screen.getByTestId('admin-users-table-scroll')).toHaveStyle({
      overflowX: 'auto',
      overflowY: 'visible',
    })
  })

  it('super_admin 可以看到 role 修改控件并更新角色', async () => {
    mockedUseAuth.mockReturnValue(
      createUseAuthValue({
        user: {
          public_id: 'current-user-public-id',
          email: 'super@example.com',
          display_name: 'Super',
          role: 'super_admin',
          status: 'active',
        },
      }),
    )
    mockedListAdminUsers.mockResolvedValue({
      items: sampleUsers,
      total: 2,
      limit: 100,
      offset: 0,
    })
    mockedUpdateAdminUserRole.mockResolvedValue({
      ...sampleUsers[1],
      role: 'viewer',
    })

    render(<AdminUsersPage />)

    const roleSelect = await screen.findByLabelText('修改 analyst@example.com 角色')
    fireEvent.change(roleSelect, { target: { value: 'viewer' } })

    await waitFor(() => expect(mockedUpdateAdminUserRole).toHaveBeenCalledWith('analyst-public-id', 'viewer'))
    expect(await screen.findByRole('status')).toHaveTextContent('已更新 analyst@example.com 的角色。')
  })

  it('admin 看不到 role 修改控件，且不能对 super_admin/admin 执行 status 操作', async () => {
    mockedUseAuth.mockReturnValue(createUseAuthValue())
    mockedListAdminUsers.mockResolvedValue({
      items: sampleUsers,
      total: 2,
      limit: 100,
      offset: 0,
    })

    render(<AdminUsersPage />)

    expect(await screen.findByText('super@example.com')).toBeInTheDocument()
    expect(screen.queryByLabelText('修改 analyst@example.com 角色')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('修改 super@example.com 状态')).not.toBeInTheDocument()
    expect(screen.getByLabelText('修改 analyst@example.com 状态')).toBeInTheDocument()
  })

  it('admin 可以修改 analyst/viewer 状态', async () => {
    mockedUseAuth.mockReturnValue(createUseAuthValue())
    mockedListAdminUsers.mockResolvedValue({
      items: sampleUsers,
      total: 2,
      limit: 100,
      offset: 0,
    })
    mockedUpdateAdminUserStatus.mockResolvedValue({
      ...sampleUsers[1],
      status: 'active',
    })

    render(<AdminUsersPage />)

    const statusSelect = await screen.findByLabelText('修改 analyst@example.com 状态')
    fireEvent.change(statusSelect, { target: { value: 'active' } })

    await waitFor(() => expect(mockedUpdateAdminUserStatus).toHaveBeenCalledWith('analyst-public-id', 'active'))
  })

  it('revoke sessions 调用正确 API，并显示成功提示', async () => {
    mockedUseAuth.mockReturnValue(createUseAuthValue())
    mockedListAdminUsers
      .mockResolvedValueOnce({
        items: sampleUsers,
        total: 2,
        limit: 100,
        offset: 0,
      })
      .mockResolvedValueOnce({
        items: sampleUsers,
        total: 2,
        limit: 100,
        offset: 0,
      })
    mockedRevokeAdminUserSessions.mockResolvedValue({
      success: true,
      revoked_count: 3,
    })
    vi.spyOn(window, 'confirm').mockReturnValue(true)

    render(<AdminUsersPage />)

    const revokeButtons = await screen.findAllByRole('button', { name: 'Revoke Sessions' })
    fireEvent.click(revokeButtons[1])

    await waitFor(() => expect(mockedRevokeAdminUserSessions).toHaveBeenCalledWith('analyst-public-id'))
    expect(await screen.findByRole('status')).toHaveTextContent('已撤销 analyst@example.com 的 3 个会话。')
  })

  it('401 / 403 / 409/422 / 网络错误分别显示正确语义', async () => {
    mockedUseAuth.mockReturnValue(createUseAuthValue())
    mockedListAdminUsers
      .mockRejectedValueOnce(
        new AdminApiError({
          status: 401,
          errorCode: 'AUTH_REQUIRED',
          message: 'Auth required',
        }),
      )
      .mockRejectedValueOnce(
        new AdminApiError({
          status: 403,
          errorCode: 'ROLE_FORBIDDEN',
          message: 'Insufficient permissions',
        }),
      )
      .mockResolvedValue({
        items: sampleUsers,
        total: 2,
        limit: 100,
        offset: 0,
      })

    render(<AdminUsersPage />)
    expect(await screen.findByText('需要登录')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '刷新列表' }))
    expect(await screen.findByText('403 无权限访问')).toBeInTheDocument()

    mockedUpdateAdminUserStatus.mockRejectedValue(
      new AdminApiError({
        status: 409,
        errorCode: 'LAST_SUPER_ADMIN_PROTECTED',
        message: 'Cannot disable the last active super admin',
      }),
    )

    fireEvent.click(screen.getByRole('button', { name: '刷新列表' }))
    const statusSelect = await screen.findByLabelText('修改 analyst@example.com 状态')
    fireEvent.change(statusSelect, { target: { value: 'active' } })
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Cannot disable the last active super admin'))

    mockedUpdateAdminUserStatus.mockReset()
    mockedUpdateAdminUserStatus.mockRejectedValue(
      new AdminApiError({
        status: 0,
        errorCode: 'NETWORK_ERROR',
        message: 'Network request failed',
        isNetworkError: true,
      }),
    )
    fireEvent.change(statusSelect, { target: { value: 'disabled' } })
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('网络异常，请稍后重试。'))
  })

  it('logout 或 user switch 后会按新角色重新判断并清理页面状态', async () => {
    const authState = createUseAuthValue()
    mockedUseAuth.mockReturnValue(authState)
    mockedListAdminUsers.mockResolvedValue({
      items: sampleUsers,
      total: 2,
      limit: 100,
      offset: 0,
    })

    const { rerender } = render(<AdminUsersPage />)

    expect(await screen.findByText('super@example.com')).toBeInTheDocument()

    mockedUseAuth.mockReturnValue(
      createUseAuthValue({
        user: null,
        status: 'unauthenticated',
      }),
    )
    rerender(<AdminUsersPage />)

    expect(await screen.findByText('需要登录')).toBeInTheDocument()
    expect(screen.queryByText('super@example.com')).not.toBeInTheDocument()

    mockedUseAuth.mockReturnValue(
      createUseAuthValue({
        user: {
          public_id: 'public-viewer-1',
          email: 'viewer@example.com',
          display_name: 'Viewer',
          role: 'viewer',
          status: 'active',
        },
      }),
    )
    rerender(<AdminUsersPage />)

    expect(await screen.findByText('403 无权限访问')).toBeInTheDocument()
    expect(screen.queryByText('super@example.com')).not.toBeInTheDocument()
  })
})
