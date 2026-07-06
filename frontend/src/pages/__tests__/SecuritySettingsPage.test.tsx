import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AuthApiError } from '../../api/auth'
import { SecuritySettingsPage } from '../SecuritySettingsPage'
import { useAuth } from '../../auth/useAuth'

vi.mock('../../auth/useAuth', () => ({
  useAuth: vi.fn(),
}))

const mockedUseAuth = vi.mocked(useAuth)

function createUseAuthValue(overrides: Partial<ReturnType<typeof useAuth>> = {}) {
  return {
    user: {
      public_id: 'public-auth-demo',
      email: 'user@example.com',
      display_name: 'Demo User',
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

function renderSecurityPage(authValue = createUseAuthValue()) {
  mockedUseAuth.mockReturnValue(authValue)
  return render(
    <MemoryRouter initialEntries={['/settings/security']}>
      <Routes>
        <Route path="/settings/security" element={<SecuritySettingsPage />} />
        <Route path="/login" element={<div>login route</div>} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('SecuritySettingsPage', () => {
  beforeEach(() => {
    mockedUseAuth.mockReset()
    vi.restoreAllMocks()
  })

  it('显示当前用户信息', () => {
    renderSecurityPage()

    expect(screen.getByText('Demo User')).toBeInTheDocument()
    expect(screen.getByText('user@example.com')).toBeInTheDocument()
    expect(screen.getByText('admin')).toBeInTheDocument()
  })

  it('短密码和确认不一致会在前端被拒绝', async () => {
    const changePassword = vi.fn()
    renderSecurityPage(createUseAuthValue({ changePassword }))

    fireEvent.change(screen.getByLabelText('当前密码'), { target: { value: 'OldPassword123!' } })
    fireEvent.change(screen.getByLabelText('新密码'), { target: { value: 'short' } })
    fireEvent.change(screen.getByLabelText('确认新密码'), { target: { value: 'short' } })
    fireEvent.click(screen.getByRole('button', { name: '修改密码' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('新密码至少 12 个字符。')
    expect(changePassword).not.toHaveBeenCalled()

    fireEvent.change(screen.getByLabelText('新密码'), { target: { value: 'UpdatedPassword123!' } })
    fireEvent.change(screen.getByLabelText('确认新密码'), { target: { value: 'UpdatedPassword1234!' } })
    fireEvent.click(screen.getByRole('button', { name: '修改密码' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('两次输入的新密码不一致。')
    expect(changePassword).not.toHaveBeenCalled()
  })

  it('修改密码请求期间禁用提交，并在成功后跳转登录', async () => {
    let resolveChangePassword: (() => void) | undefined
    const changePassword = vi.fn().mockImplementation(
      () =>
        new Promise<void>((resolve) => {
          resolveChangePassword = resolve
        }),
    )

    renderSecurityPage(createUseAuthValue({ changePassword }))

    fireEvent.change(screen.getByLabelText('当前密码'), { target: { value: 'OldPassword123!' } })
    fireEvent.change(screen.getByLabelText('新密码'), { target: { value: 'UpdatedPassword123!' } })
    fireEvent.change(screen.getByLabelText('确认新密码'), { target: { value: 'UpdatedPassword123!' } })
    fireEvent.click(screen.getByRole('button', { name: '修改密码' }))

    expect(screen.getByRole('button', { name: '提交中...' })).toBeDisabled()
    expect(changePassword).toHaveBeenCalledWith({
      current_password: 'OldPassword123!',
      new_password: 'UpdatedPassword123!',
      confirm_password: 'UpdatedPassword123!',
    })

    resolveChangePassword?.()
    await waitFor(() => expect(screen.getByText('login route')).toBeInTheDocument())
  })

  it('当前密码错误会显示后端映射消息', async () => {
    const changePassword = vi.fn().mockRejectedValue(
      new AuthApiError({
        status: 401,
        errorCode: 'CURRENT_PASSWORD_INVALID',
        message: 'Invalid credentials',
      }),
    )

    renderSecurityPage(createUseAuthValue({ changePassword }))

    fireEvent.change(screen.getByLabelText('当前密码'), { target: { value: 'wrong' } })
    fireEvent.change(screen.getByLabelText('新密码'), { target: { value: 'UpdatedPassword123!' } })
    fireEvent.change(screen.getByLabelText('确认新密码'), { target: { value: 'UpdatedPassword123!' } })
    fireEvent.click(screen.getByRole('button', { name: '修改密码' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('当前密码错误。')
  })

  it('logout-all 需要确认，取消时不发请求', () => {
    const logoutAll = vi.fn()
    vi.spyOn(window, 'confirm').mockReturnValue(false)

    renderSecurityPage(createUseAuthValue({ logoutAll }))

    fireEvent.click(screen.getByRole('button', { name: '退出所有设备' }))

    expect(logoutAll).not.toHaveBeenCalled()
  })

  it('logout-all 成功后跳转登录，且不发送 user_id', async () => {
    const logoutAll = vi.fn().mockResolvedValue({
      success: true,
      revoked_count: 4,
    })
    vi.spyOn(window, 'confirm').mockReturnValue(true)

    renderSecurityPage(createUseAuthValue({ logoutAll }))

    fireEvent.click(screen.getByRole('button', { name: '退出所有设备' }))

    expect(logoutAll).toHaveBeenCalledWith()
    await waitFor(() => expect(screen.getByText('login route')).toBeInTheDocument())
  })
})
