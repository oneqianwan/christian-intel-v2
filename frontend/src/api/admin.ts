import { buildApiUrl } from '../services/api'
import type { UserRole, UserStatus } from '../types/auth'

export interface AdminUser {
  public_id: string
  email: string
  display_name: string
  role: UserRole
  status: UserStatus
  email_verified_at?: string | null
  last_login_at?: string | null
  created_at: string
  updated_at: string
}

export interface AdminUserListResponse {
  items: AdminUser[]
  total: number
  limit: number
  offset: number
}

export interface AdminSessionRevokeResponse {
  success: boolean
  revoked_count: number
}

type RequestOptions = {
  method?: 'GET' | 'POST' | 'PATCH'
  body?: unknown
  signal?: AbortSignal
}

type AdminApiErrorPayload = {
  status: number
  errorCode: string
  message: string
  isNetworkError?: boolean
}

export class AdminApiError extends Error {
  status: number
  errorCode: string
  isNetworkError: boolean

  constructor(payload: AdminApiErrorPayload) {
    super(payload.message)
    this.name = 'AdminApiError'
    this.status = payload.status
    this.errorCode = payload.errorCode
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

async function parseAdminError(response: Response): Promise<AdminApiError> {
  const payload = await parseJsonSafely(response)
  const detail =
    payload && typeof payload === 'object' && 'detail' in payload
      ? (payload as { detail?: unknown }).detail
      : undefined
  const detailObject = detail && typeof detail === 'object' && !Array.isArray(detail) ? detail : undefined
  const payloadObject = payload && typeof payload === 'object' && !Array.isArray(payload) ? payload : undefined

  return new AdminApiError({
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

    throw new AdminApiError({
      status: 0,
      errorCode: 'NETWORK_ERROR',
      message: 'Network request failed',
      isNetworkError: true,
    })
  }

  if (!response.ok) {
    throw await parseAdminError(response)
  }

  if (response.status === 204) {
    return undefined as T
  }

  const payload = await parseJsonSafely(response)
  return (payload ?? undefined) as T
}

function encodePublicId(publicId: string) {
  return encodeURIComponent(publicId)
}

export function listAdminUsers(signal?: AbortSignal) {
  return request<AdminUserListResponse>('/admin/users', { method: 'GET', signal })
}

export function getAdminUser(userId: string, signal?: AbortSignal) {
  return request<AdminUser>(`/admin/users/${encodePublicId(userId)}`, { method: 'GET', signal })
}

export function updateAdminUserRole(userId: string, role: UserRole, signal?: AbortSignal) {
  return request<AdminUser>(`/admin/users/${encodePublicId(userId)}/role`, {
    method: 'PATCH',
    body: { role },
    signal,
  })
}

export function updateAdminUserStatus(userId: string, status: UserStatus, signal?: AbortSignal) {
  return request<AdminUser>(`/admin/users/${encodePublicId(userId)}/status`, {
    method: 'PATCH',
    body: { status },
    signal,
  })
}

export function revokeAdminUserSessions(userId: string, signal?: AbortSignal) {
  return request<AdminSessionRevokeResponse>(`/admin/users/${encodePublicId(userId)}/sessions/revoke`, {
    method: 'POST',
    signal,
  })
}
