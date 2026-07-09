import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useAuth } from '../../auth/useAuth'
import { UserMenu } from '../UserMenu'

vi.mock('../../auth/useAuth', () => ({
  useAuth: vi.fn(),
}))

const mockedUseAuth = vi.mocked(useAuth)

function createUseAuthValue(overrides: Partial<ReturnType<typeof useAuth>> = {}) {
  return {
    user: null,
    status: 'unauthenticated' as const,
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

function renderUserMenu(authValue: ReturnType<typeof createUseAuthValue>) {
  mockedUseAuth.mockReturnValue(authValue)
  return render(
    <MemoryRouter initialEntries={['/dashboard']}>
      <Routes>
        <Route path="/dashboard" element={<UserMenu />} />
        <Route path="/admin" element={<div>admin route</div>} />
        <Route path="/login" element={<div>login route</div>} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('UserMenu admin entry', () => {
  beforeEach(() => {
    vi.stubEnv('VITE_AUTH_V1_ENABLED', 'true')
    mockedUseAuth.mockReset()
  })

  it('未登录时不显示 Admin 入口', () => {
    renderUserMenu(createUseAuthValue())

    expect(screen.queryByRole('button', { name: '管理后台' })).not.toBeInTheDocument()
  })

  it.each(['analyst', 'viewer'] as const)('%s 看不到 Admin 入口', (role) => {
    renderUserMenu(
      createUseAuthValue({
        user: {
          public_id: 'public-member-alpha',
          email: `${role}@example.com`,
          display_name: role,
          role,
          status: 'active',
        },
        status: 'authenticated',
      }),
    )

    expect(screen.queryByRole('button', { name: '管理后台' })).not.toBeInTheDocument()
  })

  it.each(['admin', 'super_admin'] as const)('%s 可以看到并进入 Admin 入口', (role) => {
    renderUserMenu(
      createUseAuthValue({
        user: {
          public_id: 'public-admin-1',
          email: `${role}@example.com`,
          display_name: role,
          role,
          status: 'active',
        },
        status: 'authenticated',
      }),
    )

    fireEvent.click(screen.getByText(role))
    fireEvent.click(screen.getByRole('button', { name: '管理后台' }))
    expect(screen.getByText('admin route')).toBeInTheDocument()
  })
})
