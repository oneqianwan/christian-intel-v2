import {
  type AlertReadAllResponse,
  type AlertUnreadCountResponse,
  type CreateWatchTargetRequest,
  type PaginatedResponse,
  type UpdateWatchTargetRequest,
  type WatchAlert,
  type WatchAlertListParams,
  WatchAlertApiError,
  type WatchRunResult,
  type WatchSignal,
  type WatchSignalListParams,
  type WatchTarget,
  type WatchTargetListParams,
} from '../types/watchAlerts'
import { buildApiUrl } from '../services/api'
import {
  getWatchAlertIdentityMode,
  getWatchAlertInvalidConfigMessage,
  isAuthenticatedOwnershipEnabled,
  isWatchAlertUiEnabled,
} from '../features/watchAlerts/identity'

const SESSION_STORAGE_KEY = 'x-session-id'

const ERROR_MESSAGES: Record<string, string> = {
  ALERT_DISMISSED: '该提醒已被忽略，不能再标记为已读。',
  ALERT_NOT_FOUND: '记录不存在或已被删除。',
  AUTH_REQUIRED: '登录状态已失效，请重新登录',
  WATCH_ALERT_NOTIFICATIONS_DISABLED: 'Watch / Alert 功能当前未启用。',
  WATCH_ALERT_V1_DISABLED: 'Watch / Alert 功能当前未启用。',
  WATCH_RUN_ALREADY_RUNNING: '监控任务正在运行，请稍后再试。',
  WATCH_RUN_FAILED: '监控执行失败，请稍后重试。',
  WATCH_TARGET_ALREADY_EXISTS: '该对象已在 Watchlist 中，无需重复添加。',
  WATCH_TARGET_DISABLED: '该监控目标已被禁用。',
  WATCH_TARGET_ENTITY_NOT_FOUND: '目标实体不存在。',
  WATCH_TARGET_EXISTS: '该对象已在 Watchlist 中，无需重复添加。',
  WATCH_TARGET_NOT_FOUND: '记录不存在或已被删除。',
}

function getStoredSessionId(): string | null {
  if (typeof window === 'undefined') {
    return null
  }

  const stored = window.localStorage.getItem(SESSION_STORAGE_KEY)?.trim()
  return stored || null
}

export function hasWatchAlertSession() {
  return Boolean(getStoredSessionId())
}

function createInvalidConfigurationError() {
  const status = 503
  const code = 'WATCH_ALERT_IDENTITY_INVALID'
  const message = getWatchAlertInvalidConfigMessage()
  return new WatchAlertApiError({
    status,
    code,
    message,
    userMessage: message,
  })
}

function createNetworkError() {
  return new WatchAlertApiError({
    status: 0,
    code: 'NETWORK_ERROR',
    message: 'Network request failed',
    userMessage: '后端不可用，请稍后重试。',
  })
}

function createAuthRequiredError() {
  const status = 401
  const code = 'AUTH_REQUIRED'
  const message = 'Authentication required'
  return new WatchAlertApiError({
    status,
    code,
    message,
    userMessage: getUserMessage(status, code, message),
  })
}

function createUrl(path: string, query?: Record<string, string | number | undefined>) {
  const url = new URL(buildApiUrl(path))
  if (!query) {
    return url
  }

  const searchParams = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined) {
      continue
    }
    searchParams.set(key, String(value))
  }
  url.search = searchParams.toString()
  return url
}

function getUserMessage(status: number, code: string, message: string) {
  if (ERROR_MESSAGES[code]) {
    return ERROR_MESSAGES[code]
  }
  if (status === 401) {
    return '登录状态已失效，请重新登录'
  }
  if (status === 403) {
    return '当前账号没有访问权限。'
  }
  if (status === 404) {
    return '记录不存在或已被删除。'
  }
  if (status === 409) {
    return '操作冲突：可能是重复操作，或任务正在运行。'
  }
  if (status === 429) {
    return '请求过于频繁，请稍后再试。'
  }
  if (status === 422) {
    return '请求参数无效，请检查后重试。'
  }
  if (status === 503) {
    return 'Watch / Alert 功能当前未启用。'
  }
  return message || '请求失败，请稍后重试。'
}

async function parseApiError(response: Response): Promise<WatchAlertApiError> {
  let payload: unknown = null

  try {
    payload = await response.json()
  } catch {
    payload = null
  }

  const detail =
    payload && typeof payload === 'object' && 'detail' in payload
      ? (payload as { detail?: unknown }).detail
      : undefined

  const detailObject = detail && typeof detail === 'object' && !Array.isArray(detail) ? detail : undefined
  const payloadObject = payload && typeof payload === 'object' && !Array.isArray(payload) ? payload : undefined

  const code =
    (detailObject as { error_code?: string } | undefined)?.error_code ||
    (payloadObject as { error_code?: string } | undefined)?.error_code ||
    `HTTP_${response.status}`

  const message =
    (detailObject as { message?: string } | undefined)?.message ||
    (payloadObject as { message?: string } | undefined)?.message ||
    (typeof detail === 'string' ? detail : '') ||
    response.statusText ||
    'Request failed'

  return new WatchAlertApiError({
    status: response.status,
    code,
    message,
    userMessage: getUserMessage(response.status, code, message),
    details: detail ?? payload,
  })
}

function buildWatchAlertRequestOptions(
  requestInit: RequestInit,
): RequestInit {
  const identityMode = getWatchAlertIdentityMode()
  const headers = new Headers(requestInit.headers)

  if (requestInit.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  if (identityMode === 'invalid') {
    throw createInvalidConfigurationError()
  }

  if (identityMode === 'authenticated-user') {
    headers.delete('x-session-id')
    headers.delete('X-Session-Id')
    return {
      ...requestInit,
      credentials: 'include',
      headers,
    }
  }

  if (identityMode !== 'legacy-session') {
    throw createAuthRequiredError()
  }

  const sessionId = getStoredSessionId()
  if (!sessionId) {
    throw createAuthRequiredError()
  }

  headers.set('x-session-id', sessionId)
  return {
    ...requestInit,
    headers,
  }
}

async function request<T>(
  path: string,
  init: RequestInit & {
    query?: Record<string, string | number | undefined>
    parseJson?: boolean
  } = {},
): Promise<T> {
  const { query, parseJson = true, ...requestInit } = init
  const finalRequestInit = buildWatchAlertRequestOptions(requestInit)

  let response: Response
  try {
    response = await fetch(createUrl(path, query), finalRequestInit)
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw error
    }
    throw createNetworkError()
  }

  if (!response.ok) {
    throw await parseApiError(response)
  }

  if (response.status === 204 || !parseJson) {
    return undefined as T
  }

  return response.json() as Promise<T>
}

export const WATCH_ALERT_UNREAD_REFRESH_EVENT = 'watch-alerts:unread-refresh'
export {
  getWatchAlertIdentityMode,
  isAuthenticatedOwnershipEnabled,
  isWatchAlertUiEnabled,
}

export function dispatchWatchAlertUnreadRefresh() {
  if (typeof window === 'undefined') {
    return
  }
  window.dispatchEvent(new CustomEvent(WATCH_ALERT_UNREAD_REFRESH_EVENT))
}

type WatchAlertRequestOptions = {
  signal?: AbortSignal
}

export async function createWatchTarget(
  requestBody: CreateWatchTargetRequest,
  options: WatchAlertRequestOptions = {},
): Promise<WatchTarget> {
  return request<WatchTarget>('/watch-targets', {
    method: 'POST',
    signal: options.signal,
    body: JSON.stringify({
      entity_id: requestBody.entity_id,
      entity_type: requestBody.entity_type,
      frequency: requestBody.frequency,
    }),
  })
}

export async function listWatchTargets(
  params: WatchTargetListParams = {},
  options: WatchAlertRequestOptions = {},
): Promise<PaginatedResponse<WatchTarget>> {
  return request<PaginatedResponse<WatchTarget>>('/watch-targets', {
    method: 'GET',
    signal: options.signal,
    query: {
      status: params.status,
      entity_type: params.entity_type,
      page: params.page,
      page_size: params.page_size,
    },
  })
}

export async function updateWatchTarget(
  watchTargetId: string,
  requestBody: UpdateWatchTargetRequest,
  options: WatchAlertRequestOptions = {},
): Promise<WatchTarget> {
  return request<WatchTarget>(`/watch-targets/${encodeURIComponent(String(watchTargetId))}`, {
    method: 'PATCH',
    signal: options.signal,
    body: JSON.stringify({
      status: requestBody.status,
      frequency: requestBody.frequency,
    }),
  })
}

export async function deleteWatchTarget(
  watchTargetId: string,
  options: WatchAlertRequestOptions = {},
): Promise<void> {
  await request<void>(`/watch-targets/${encodeURIComponent(String(watchTargetId))}`, {
    method: 'DELETE',
    signal: options.signal,
    parseJson: false,
  })
}

export async function runWatchTarget(
  watchTargetId: string,
  options: WatchAlertRequestOptions = {},
): Promise<WatchRunResult> {
  return request<WatchRunResult>(`/watch-targets/${encodeURIComponent(String(watchTargetId))}/run`, {
    method: 'POST',
    signal: options.signal,
  })
}

export async function listWatchTargetSignals(
  watchTargetId: string,
  params: WatchSignalListParams = {},
  options: WatchAlertRequestOptions = {},
): Promise<PaginatedResponse<WatchSignal>> {
  return request<PaginatedResponse<WatchSignal>>(
    `/watch-targets/${encodeURIComponent(String(watchTargetId))}/signals`,
    {
      method: 'GET',
      signal: options.signal,
      query: {
        signal_type: params.signal_type,
        severity: params.severity,
        page: params.page,
        page_size: params.page_size,
      },
    },
  )
}

export async function listAlerts(
  params: WatchAlertListParams = {},
  options: WatchAlertRequestOptions = {},
): Promise<PaginatedResponse<WatchAlert>> {
  return request<PaginatedResponse<WatchAlert>>('/alerts', {
    method: 'GET',
    signal: options.signal,
    query: {
      status: params.status,
      severity: params.severity,
      watch_target_id: params.watch_target_id,
      page: params.page,
      page_size: params.page_size,
    },
  })
}

export async function getUnreadAlertCount(options: WatchAlertRequestOptions = {}): Promise<number> {
  const response = await request<AlertUnreadCountResponse>('/alerts/unread-count', {
    method: 'GET',
    signal: options.signal,
  })
  return response.unread_count
}

export async function markAlertRead(
  alertId: string,
  options: WatchAlertRequestOptions = {},
): Promise<WatchAlert> {
  return request<WatchAlert>(`/alerts/${encodeURIComponent(String(alertId))}/read`, {
    method: 'PATCH',
    signal: options.signal,
  })
}

export async function dismissAlert(
  alertId: string,
  options: WatchAlertRequestOptions = {},
): Promise<WatchAlert> {
  return request<WatchAlert>(`/alerts/${encodeURIComponent(String(alertId))}/dismiss`, {
    method: 'PATCH',
    signal: options.signal,
  })
}

export async function markAllAlertsRead(options: WatchAlertRequestOptions = {}): Promise<number> {
  const response = await request<AlertReadAllResponse>('/alerts/read-all', {
    method: 'POST',
    signal: options.signal,
  })
  return response.updated_count
}
