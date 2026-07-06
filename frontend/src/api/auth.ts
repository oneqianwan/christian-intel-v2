import { buildApiUrl } from '../services/api'
import type {
  AuthApiErrorPayload,
  ChangePasswordRequest,
  ChangePasswordResponse,
  LoginRequest,
  LoginResponse,
  LogoutAllResponse,
  LogoutResponse,
} from '../types/auth'

type RequestOptions = {
  method?: 'GET' | 'POST'
  body?: unknown
  signal?: AbortSignal
}

export class AuthApiError extends Error {
  status: number
  errorCode: string
  retryAfterSeconds?: number
  isNetworkError: boolean

  constructor(payload: AuthApiErrorPayload) {
    super(payload.message)
    this.name = 'AuthApiError'
    this.status = payload.status
    this.errorCode = payload.errorCode
    this.retryAfterSeconds = payload.retryAfterSeconds
    this.isNetworkError = Boolean(payload.isNetworkError)
  }
}

async function parseJsonSafely(response: Response): Promise<unknown> {
  const text = await response.text()
  if (!text) {
    return null
  }

  try {
    return JSON.parse(text) as unknown
  } catch {
    return text
  }
}

async function parseAuthError(response: Response): Promise<AuthApiError> {
  const payload = await parseJsonSafely(response)
  const detail =
    payload && typeof payload === 'object' && 'detail' in payload
      ? (payload as { detail?: unknown }).detail
      : undefined

  const detailObject = detail && typeof detail === 'object' && !Array.isArray(detail) ? detail : undefined
  const payloadObject = payload && typeof payload === 'object' && !Array.isArray(payload) ? payload : undefined
  const retryAfterHeader = response.headers.get('Retry-After')
  const retryAfterSeconds = retryAfterHeader ? Number.parseInt(retryAfterHeader, 10) : undefined

  return new AuthApiError({
    status: response.status,
    errorCode:
      (detailObject as { error_code?: string } | undefined)?.error_code ||
      (payloadObject as { error_code?: string } | undefined)?.error_code ||
      `HTTP_${response.status}`,
    message:
      (detailObject as { message?: string } | undefined)?.message ||
      (payloadObject as { message?: string } | undefined)?.message ||
      response.statusText ||
      'Request failed',
    retryAfterSeconds: Number.isFinite(retryAfterSeconds) ? retryAfterSeconds : undefined,
  })
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers = new Headers()
  const requestInit: RequestInit = {
    method: options.method || 'GET',
    credentials: 'include',
    headers,
    signal: options.signal,
  }

  if (options.body !== undefined) {
    headers.set('Content-Type', 'application/json')
    requestInit.body = JSON.stringify(options.body)
  }

  let response: Response
  try {
    response = await fetch(buildApiUrl(path), requestInit)
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw error
    }

    throw new AuthApiError({
      status: 0,
      errorCode: 'NETWORK_ERROR',
      message: 'Network request failed',
      isNetworkError: true,
    })
  }

  if (!response.ok) {
    throw await parseAuthError(response)
  }

  if (response.status === 204) {
    return undefined as T
  }

  const payload = await parseJsonSafely(response)
  return (payload ?? undefined) as T
}

export function login(requestBody: LoginRequest, signal?: AbortSignal) {
  return request<LoginResponse>('/auth/login', {
    method: 'POST',
    body: requestBody,
    signal,
  })
}

export function logout(signal?: AbortSignal) {
  return request<LogoutResponse>('/auth/logout', {
    method: 'POST',
    signal,
  })
}

export function getCurrentUser(signal?: AbortSignal) {
  return request<LoginResponse>('/auth/me', {
    method: 'GET',
    signal,
  })
}

export function changePassword(requestBody: ChangePasswordRequest, signal?: AbortSignal) {
  return request<ChangePasswordResponse>('/auth/change-password', {
    method: 'POST',
    body: requestBody,
    signal,
  })
}

export function logoutAll(signal?: AbortSignal) {
  return request<LogoutAllResponse>('/auth/logout-all', {
    method: 'POST',
    signal,
  })
}
