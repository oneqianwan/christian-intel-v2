import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AdminGuard } from '../AdminGuard'
import { useAuth } from '../useAuth'

vi.mock('../useAuth', () => ({
  useAuth: vi.fn(),
}))

const mockedUseAuth = vi.mocked(useAuth)

function createUseAuthValue(overrides: Partial<ReturnType<typeof useAuth>> = {}) {
  return {
    user: {
      public_id: 'public-admin-1',
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

function renderGuard(authValue = createUseAuthValue()) {
  mockedUseAuth.mockReturnValue(authValue)
  return render(
    <MemoryRouter initialEntries={['/admin']}>
      <Routes>
        <Route
          path="/admin"
          element={
            <AdminGuard>
              <div>admin page</div>
            </AdminGuard>
          }
        />
        <Route path="/login" element={<div>login page</div>} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('AdminGuard', () => {
  beforeEach(() => {
    vi.stubEnv('VITE_AUTH_V1_ENABLED', 'true')
    mockedUseAuth.mockReset()
  })

  it('未登录时跳转到登录页且不渲染管理内容', async () => {
    renderGuard(
      createUseAuthValue({
        user: null,
        status: 'unauthenticated',
      }),
    )

    await waitFor(() => expect(screen.getByText('login page')).toBeInTheDocument())
    expect(screen.queryByText('admin page')).not.toBeInTheDocument()
  })

  it.each(['analyst', 'viewer'] as const)('%s 强行访问 /admin 显示 403 无权限', (role) => {
    renderGuard(
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

    expect(screen.getByTestId('admin-guard-forbidden')).toHaveTextContent('403 无权限访问')
    expect(screen.queryByText('admin page')).not.toBeInTheDocument()
  })

  it.each(['admin', 'super_admin'] as const)('%s 可以进入管理页面', (role) => {
    renderGuard(
      createUseAuthValue({
        user: {
          public_id: 'public-admin-1',
          email: `${role}@example.com`,
          display_name: role,
          role,
          status: 'active',
        },
      }),
    )

    expect(screen.getByText('admin page')).toBeInTheDocument()
  })
})
