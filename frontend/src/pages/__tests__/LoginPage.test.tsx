import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AuthApiError } from '../../api/auth'
import { LoginPage } from '../LoginPage'
import { useAuth } from '../../auth/useAuth'

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

function renderLoginPage(options?: {
  authValue?: ReturnType<typeof createUseAuthValue>
  initialEntries?: Array<string | { pathname: string; state?: Record<string, unknown> }>
}) {
  const authValue = options?.authValue || createUseAuthValue()
  mockedUseAuth.mockReturnValue(authValue)
  return render(
    <MemoryRouter initialEntries={options?.initialEntries || ['/login']}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/" element={<div>home page</div>} />
        <Route path="/dashboard" element={<div>dashboard page</div>} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('LoginPage', () => {
  beforeEach(() => {
    vi.stubEnv('VITE_AUTH_V1_ENABLED', 'true')
    vi.stubEnv('VITE_AUTH_REQUIRED', 'false')
    mockedUseAuth.mockReset()
  })

  it('渲染 Email 和 Password 字段，且不显示注册入口', () => {
    renderLoginPage()

    expect(screen.getByLabelText('邮箱')).toBeInTheDocument()
    expect(screen.getByLabelText('密码')).toBeInTheDocument()
    expect(screen.getByText('注册与忘记密码功能暂未开放，请联系管理员处理账号问题。')).toBeInTheDocument()
  })

  it('空字段不能提交，Enter 可提交且正确跳转', async () => {
    const user = userEvent.setup()
    const login = vi.fn().mockResolvedValue({
      public_id: 'public-auth-demo',
      email: 'user@example.com',
      display_name: 'Demo User',
      role: 'viewer',
      status: 'active',
    })

    renderLoginPage({
      authValue: createUseAuthValue({ login }),
      initialEntries: [{ pathname: '/login', state: { from: '/dashboard' } }],
    })

    const submitButton = screen.getByRole('button', { name: '登录' })
    expect(submitButton).toBeDisabled()

    await user.type(screen.getByLabelText('邮箱'), ' user@example.com ')
    await user.type(screen.getByLabelText('密码'), 'Password123456!')

    expect(submitButton).not.toBeDisabled()
    await user.keyboard('{Enter}')

    await waitFor(() => expect(login).toHaveBeenCalledWith({ email: 'user@example.com', password: 'Password123456!' }))
    await waitFor(() => expect(screen.getByText('dashboard page')).toBeInTheDocument())
  })

  it('请求期间按钮 disabled，防重复提交', async () => {
    let resolveLogin: (() => void) | undefined
    const login = vi.fn().mockImplementation(
      () =>
        new Promise<void>((resolve) => {
          resolveLogin = resolve
        }),
    )

    renderLoginPage({
      authValue: createUseAuthValue({ login }),
    })

    fireEvent.change(screen.getByLabelText('邮箱'), { target: { value: 'user@example.com' } })
    fireEvent.change(screen.getByLabelText('密码'), { target: { value: 'Password123456!' } })

    const submitButton = screen.getByRole('button', { name: '登录' })
    fireEvent.click(submitButton)
    fireEvent.click(screen.getByRole('button', { name: '登录中...' }))

    expect(login).toHaveBeenCalledTimes(1)
    expect(screen.getByRole('button', { name: '登录中...' })).toBeDisabled()

    resolveLogin?.()
    await waitFor(() => expect(screen.getByText('home page')).toBeInTheDocument())
  })

  it.each([
    [
      new AuthApiError({ status: 401, errorCode: 'INVALID_CREDENTIALS', message: 'Invalid credentials' }),
      '邮箱或密码错误。',
    ],
    [
      new AuthApiError({ status: 403, errorCode: 'ACCOUNT_DISABLED', message: 'Account disabled' }),
      '账号已禁用，请联系管理员。',
    ],
    [
      new AuthApiError({ status: 403, errorCode: 'ACCOUNT_PENDING', message: 'Account pending' }),
      '账号待启用，请联系管理员。',
    ],
    [
      new AuthApiError({ status: 429, errorCode: 'LOGIN_RATE_LIMITED', message: 'Too many login attempts' }),
      '尝试过多，请稍后重试。',
    ],
    [
      new AuthApiError({ status: 503, errorCode: 'AUTH_DISABLED', message: 'Auth disabled' }),
      '登录功能暂未启用。',
    ],
    [
      new AuthApiError({ status: 0, errorCode: 'NETWORK_ERROR', message: 'Network request failed', isNetworkError: true }),
      '后端不可用，请稍后重试。',
    ],
  ])('正确映射登录错误提示：%s', async (error, message) => {
    const login = vi.fn().mockRejectedValue(error)
    renderLoginPage({
      authValue: createUseAuthValue({ login }),
    })

    fireEvent.change(screen.getByLabelText('邮箱'), { target: { value: 'user@example.com' } })
    fireEvent.change(screen.getByLabelText('密码'), { target: { value: 'Password123456!' } })
    fireEvent.click(screen.getByRole('button', { name: '登录' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(message)
  })

  it('已登录访问 /login 时自动跳转到来源页', async () => {
    renderLoginPage({
      authValue: createUseAuthValue({
        status: 'authenticated',
        user: {
          public_id: 'public-auth-demo',
          email: 'user@example.com',
          display_name: 'Demo User',
          role: 'viewer',
          status: 'active',
        },
      }),
      initialEntries: [{ pathname: '/login', state: { from: '/dashboard' } }],
    })

    await waitFor(() => expect(screen.getByText('dashboard page')).toBeInTheDocument())
  })

  it('Flag 关闭时显示未启用状态', () => {
    vi.stubEnv('VITE_AUTH_V1_ENABLED', 'false')

    renderLoginPage()

    expect(screen.getByText('登录未启用')).toBeInTheDocument()
  })
})
