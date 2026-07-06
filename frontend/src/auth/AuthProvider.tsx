import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import {
  AuthApiError,
  changePassword as changePasswordRequest,
  getCurrentUser,
  login as loginRequest,
  logout as logoutRequest,
  logoutAll as logoutAllRequest,
} from '../api/auth'
import type {
  AuthStatus,
  AuthUser,
  ChangePasswordRequest,
  LoginRequest,
} from '../types/auth'
import { AuthContext, type AuthContextValue } from './AuthContext'
import { isAuthUiEnabled } from './flags'

type AuthState = {
  status: AuthStatus
  user: AuthUser | null
  error: Error | null
}

type SessionBootstrapResult =
  | { status: 'authenticated'; user: AuthUser }
  | { status: 'disabled'; user: null }
  | { status: 'unauthenticated'; user: null }
  | { status: 'error'; user: null; error: Error }

let bootstrapPromise: Promise<SessionBootstrapResult> | null = null

async function resolveCurrentSession(): Promise<SessionBootstrapResult> {
  try {
    const response = await getCurrentUser()
    return {
      status: 'authenticated',
      user: response.user,
    }
  } catch (error) {
    if (error instanceof AuthApiError) {
      if (error.status === 401) {
        return { status: 'unauthenticated', user: null }
      }
      if (error.status === 503 && error.errorCode === 'AUTH_DISABLED') {
        return { status: 'disabled', user: null }
      }
      if (error.status === 403) {
        return { status: 'unauthenticated', user: null }
      }
    }

    return {
      status: 'error',
      user: null,
      error: error instanceof Error ? error : new Error('Failed to restore session'),
    }
  }
}

function getBootstrapPromise() {
  if (!bootstrapPromise) {
    bootstrapPromise = resolveCurrentSession().finally(() => {
      bootstrapPromise = null
    })
  }
  return bootstrapPromise
}

function normalizeEnabledState(enabled: boolean): AuthState {
  if (!enabled) {
    return {
      status: 'disabled',
      user: null,
      error: null,
    }
  }

  return {
    status: 'loading',
    user: null,
    error: null,
  }
}

type AuthProviderProps = {
  children: ReactNode
}

export function AuthProvider({ children }: AuthProviderProps) {
  const authUiEnabled = isAuthUiEnabled()
  const [state, setState] = useState<AuthState>(() => normalizeEnabledState(authUiEnabled))

  const applyBootstrapResult = useCallback((result: SessionBootstrapResult) => {
    if (result.status === 'authenticated') {
      setState({
        status: 'authenticated',
        user: result.user,
        error: null,
      })
      return
    }

    if (result.status === 'disabled') {
      setState({
        status: 'disabled',
        user: null,
        error: null,
      })
      return
    }

    if (result.status === 'unauthenticated') {
      setState({
        status: 'unauthenticated',
        user: null,
        error: null,
      })
      return
    }

    setState({
      status: 'error',
      user: null,
      error: result.error,
    })
  }, [])

  const refreshUser = useCallback(async () => {
    if (!isAuthUiEnabled()) {
      setState({
        status: 'disabled',
        user: null,
        error: null,
      })
      return
    }

    setState((current) => ({
      ...current,
      status: 'loading',
      error: null,
    }))

    const result = await resolveCurrentSession()
    applyBootstrapResult(result)
  }, [applyBootstrapResult])

  useEffect(() => {
    let active = true

    if (!authUiEnabled) {
      setState({
        status: 'disabled',
        user: null,
        error: null,
      })
      return () => {
        active = false
      }
    }

    setState((current) => ({
      status: current.user ? 'authenticated' : 'loading',
      user: current.user,
      error: null,
    }))

    void getBootstrapPromise().then((result) => {
      if (!active) {
        return
      }
      applyBootstrapResult(result)
    })

    return () => {
      active = false
    }
  }, [applyBootstrapResult, authUiEnabled])

  const login = useCallback(async (request: LoginRequest) => {
    const response = await loginRequest(request)
    setState({
      status: 'authenticated',
      user: response.user,
      error: null,
    })
    return response.user
  }, [])

  const logout = useCallback(async () => {
    try {
      await logoutRequest()
    } finally {
      setState({
        status: isAuthUiEnabled() ? 'unauthenticated' : 'disabled',
        user: null,
        error: null,
      })
    }
  }, [])

  const changePassword = useCallback(async (request: ChangePasswordRequest) => {
    const response = await changePasswordRequest(request)
    setState({
      status: isAuthUiEnabled() ? 'unauthenticated' : 'disabled',
      user: null,
      error: null,
    })
    return response
  }, [])

  const logoutAll = useCallback(async () => {
    const response = await logoutAllRequest()
    setState({
      status: isAuthUiEnabled() ? 'unauthenticated' : 'disabled',
      user: null,
      error: null,
    })
    return response
  }, [])

  const clearError = useCallback(() => {
    setState((current) => ({
      ...current,
      error: null,
      status: current.status === 'error' ? 'unauthenticated' : current.status,
    }))
  }, [])

  const value = useMemo<AuthContextValue>(
    () => ({
      user: state.user,
      status: state.status,
      error: state.error,
      login,
      logout,
      refreshUser,
      changePassword,
      logoutAll,
      clearError,
    }),
    [changePassword, clearError, login, logout, logoutAll, refreshUser, state.error, state.status, state.user],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
