import { StrictMode } from 'react'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ChangePasswordResponse, LogoutAllResponse } from '../../types/auth'
import { AuthProvider } from '../AuthProvider'
import { useAuth } from '../useAuth'
import { AuthApiError } from '../../api/auth'
import * as authApi from '../../api/auth'

vi.mock('../../api/auth', async () => {
  const actual = await vi.importActual<typeof import('../../api/auth')>('../../api/auth')
  return {
    ...actual,
    getCurrentUser: vi.fn(),
    login: vi.fn(),
    logout: vi.fn(),
    changePassword: vi.fn(),
    logoutAll: vi.fn(),
  }
})

const mockedGetCurrentUser = vi.mocked(authApi.getCurrentUser)
const mockedLogin = vi.mocked(authApi.login)
const mockedLogout = vi.mocked(authApi.logout)
const mockedChangePassword = vi.mocked(authApi.changePassword)
const mockedLogoutAll = vi.mocked(authApi.logoutAll)

const demoUser = {
  public_id: 'public-auth-demo',
  email: 'user@example.com',
  display_name: 'Demo User',
  role: 'admin' as const,
  status: 'active' as const,
}

function AuthProbe() {
  const { user, status, error, login, logout, refreshUser, changePassword, logoutAll } = useAuth()

  return (
    <div>
      <div data-testid="status">{status}</div>
      <div data-testid="user-email">{user?.email || ''}</div>
      <div data-testid="error">{error?.message || ''}</div>
      <button
        type="button"
        onClick={() => {
          void login({
            email: 'user@example.com',
            password: 'Password123456!',
          })
        }}
      >
        login
      </button>
      <button
        type="button"
        onClick={() => {
          void logout()
        }}
      >
        logout
      </button>
      <button
        type="button"
        onClick={() => {
          void refreshUser()
        }}
      >
        refresh
      </button>
      <button
        type="button"
        onClick={() => {
          void changePassword({
            current_password: 'Password123456!',
            new_password: 'UpdatedPassword123!',
            confirm_password: 'UpdatedPassword123!',
          } satisfies Parameters<typeof changePassword>[0])
        }}
      >
        change-password
      </button>
      <button
        type="button"
        onClick={() => {
          void logoutAll()
        }}
      >
        logout-all
      </button>
    </div>
  )
}

function renderProvider(ui = <AuthProbe />) {
  return render(<AuthProvider>{ui}</AuthProvider>)
}

function createDeferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((innerResolve, innerReject) => {
    resolve = innerResolve
    reject = innerReject
  })
  return { promise, resolve, reject }
}

describe('AuthProvider', () => {
  beforeEach(() => {
    vi.stubEnv('VITE_AUTH_V1_ENABLED', 'true')
    vi.stubEnv('VITE_AUTH_REQUIRED', 'false')
    mockedGetCurrentUser.mockReset()
    mockedLogin.mockReset()
    mockedLogout.mockReset()
    mockedChangePassword.mockReset()
    mockedLogoutAll.mockReset()
  })

  afterEach(() => {
    vi.unstubAllEnvs()
  })

  it('flag 关闭时不请求 /auth/me', () => {
    vi.stubEnv('VITE_AUTH_V1_ENABLED', 'false')

    renderProvider()

    expect(screen.getByTestId('status')).toHaveTextContent('disabled')
    expect(mockedGetCurrentUser).not.toHaveBeenCalled()
  })

  it('flag 开启时初始化请求 /auth/me，并在 200 时进入 authenticated', async () => {
    mockedGetCurrentUser.mockResolvedValue({
      user: demoUser,
    })

    renderProvider()

    expect(screen.getByTestId('status')).toHaveTextContent('loading')
    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('authenticated'))
    expect(screen.getByTestId('user-email')).toHaveTextContent('user@example.com')
    expect(mockedGetCurrentUser).toHaveBeenCalledTimes(1)
  })

  it('me 返回 401 时进入 unauthenticated', async () => {
    mockedGetCurrentUser.mockRejectedValue(
      new AuthApiError({
        status: 401,
        errorCode: 'AUTH_REQUIRED',
        message: 'Auth required',
      }),
    )

    renderProvider()

    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('unauthenticated'))
    expect(screen.getByTestId('user-email')).toHaveTextContent('')
  })

  it('me 返回 503 时安全进入 disabled', async () => {
    mockedGetCurrentUser.mockRejectedValue(
      new AuthApiError({
        status: 503,
        errorCode: 'AUTH_DISABLED',
        message: 'Auth disabled',
      }),
    )

    renderProvider()

    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('disabled'))
  })

  it('网络失败进入 error，重试后可恢复', async () => {
    mockedGetCurrentUser
      .mockRejectedValueOnce(
        new AuthApiError({
          status: 0,
          errorCode: 'NETWORK_ERROR',
          message: 'Network request failed',
          isNetworkError: true,
        }),
      )
      .mockResolvedValueOnce({
        user: demoUser,
      })

    renderProvider()

    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('error'))
    fireEvent.click(screen.getByRole('button', { name: 'refresh' }))
    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('authenticated'))
  })

  it('登录成功更新 user，logout 清理 user，changePassword 与 logoutAll 成功后回到未登录', async () => {
    mockedGetCurrentUser.mockRejectedValue(
      new AuthApiError({
        status: 401,
        errorCode: 'AUTH_REQUIRED',
        message: 'Auth required',
      }),
    )
    mockedLogin.mockResolvedValue({ user: demoUser })
    mockedLogout.mockResolvedValue({ success: true })
    mockedChangePassword.mockResolvedValue({
      success: true,
      reauthentication_required: true,
    } satisfies ChangePasswordResponse)
    mockedLogoutAll.mockResolvedValue({
      success: true,
      revoked_count: 3,
    } satisfies LogoutAllResponse)

    renderProvider()
    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('unauthenticated'))

    fireEvent.click(screen.getByRole('button', { name: 'login' }))
    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('authenticated'))

    fireEvent.click(screen.getByRole('button', { name: 'logout' }))
    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('unauthenticated'))

    fireEvent.click(screen.getByRole('button', { name: 'login' }))
    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('authenticated'))

    fireEvent.click(screen.getByRole('button', { name: 'change-password' }))
    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('unauthenticated'))

    fireEvent.click(screen.getByRole('button', { name: 'login' }))
    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('authenticated'))

    fireEvent.click(screen.getByRole('button', { name: 'logout-all' }))
    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('unauthenticated'))
  })

  it('不会使用 localStorage token 或 x-session-id', async () => {
    const localStorageSpy = vi.spyOn(window.localStorage.__proto__, 'setItem')
    const sessionStorageSpy = vi.spyOn(window.sessionStorage.__proto__, 'setItem')
    mockedGetCurrentUser.mockResolvedValue({
      user: demoUser,
    })

    renderProvider()

    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('authenticated'))
    expect(localStorageSpy).not.toHaveBeenCalled()
    expect(sessionStorageSpy).not.toHaveBeenCalled()
  })

  it('StrictMode 下不会产生重复初始化请求风暴', async () => {
    const deferred = createDeferred<{ user: typeof demoUser }>()
    mockedGetCurrentUser.mockReturnValue(deferred.promise)

    render(
      <StrictMode>
        <AuthProvider>
          <AuthProbe />
        </AuthProvider>
      </StrictMode>,
    )

    await waitFor(() => expect(mockedGetCurrentUser).toHaveBeenCalledTimes(1))
    deferred.resolve({ user: demoUser })
    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('authenticated'))
  })

  it('卸载后不会抛出状态更新错误', async () => {
    const deferred = createDeferred<{ user: typeof demoUser }>()
    mockedGetCurrentUser.mockReturnValue(deferred.promise)
    const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})

    const view = renderProvider()
    view.unmount()
    deferred.resolve({ user: demoUser })
    await Promise.resolve()

    expect(consoleErrorSpy).not.toHaveBeenCalled()
    consoleErrorSpy.mockRestore()
  })
})
