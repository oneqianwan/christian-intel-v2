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

const API_ORIGIN = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.trim() || 'http://localhost:8000'
const DEFAULT_SESSION_ID = 'session-1'
const SESSION_STORAGE_KEY = 'x-session-id'

const ERROR_MESSAGES: Record<string, string> = {
  ALERT_DISMISSED: '该提醒已被忽略，不能再标记为已读。',
  ALERT_NOT_FOUND: '记录不存在或已被删除。',
  AUTH_REQUIRED: '登录状态无效，请刷新页面后重试。',
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

function getSessionId(): string {
  if (typeof window === 'undefined') {
    return DEFAULT_SESSION_ID
  }

  const stored = window.localStorage.getItem(SESSION_STORAGE_KEY)?.trim()
  return stored || DEFAULT_SESSION_ID
}

function createUrl(path: string, query?: Record<string, string | number | undefined>) {
  const url = new URL(path, API_ORIGIN)
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
    return '登录状态无效，请刷新页面后重试。'
  }
  if (status === 404) {
    return '记录不存在或已被删除。'
  }
  if (status === 409) {
    return '操作冲突：可能是重复操作，或任务正在运行。'
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

async function request<T>(
  path: string,
  init: RequestInit & {
    query?: Record<string, string | number | undefined>
    parseJson?: boolean
  } = {},
): Promise<T> {
  const { query, parseJson = true, ...requestInit } = init
  const headers = new Headers(requestInit.headers)
  headers.set('x-session-id', getSessionId())
  if (requestInit.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  const response = await fetch(createUrl(path, query), {
    ...requestInit,
    headers,
  })

  if (!response.ok) {
    throw await parseApiError(response)
  }

  if (response.status === 204 || !parseJson) {
    return undefined as T
  }

  return response.json() as Promise<T>
}

export const isWatchAlertUiEnabled = () => import.meta.env.VITE_WATCH_ALERT_UI_ENABLED === 'true'

export async function createWatchTarget(requestBody: CreateWatchTargetRequest): Promise<WatchTarget> {
  return request<WatchTarget>('/api/watch-targets', {
    method: 'POST',
    body: JSON.stringify({
      entity_id: requestBody.entity_id,
      entity_type: requestBody.entity_type,
      frequency: requestBody.frequency,
    }),
  })
}

export async function listWatchTargets(
  params: WatchTargetListParams = {},
): Promise<PaginatedResponse<WatchTarget>> {
  return request<PaginatedResponse<WatchTarget>>('/api/watch-targets', {
    method: 'GET',
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
): Promise<WatchTarget> {
  return request<WatchTarget>(`/api/watch-targets/${encodeURIComponent(String(watchTargetId))}`, {
    method: 'PATCH',
    body: JSON.stringify({
      status: requestBody.status,
      frequency: requestBody.frequency,
    }),
  })
}

export async function deleteWatchTarget(watchTargetId: string): Promise<void> {
  await request<void>(`/api/watch-targets/${encodeURIComponent(String(watchTargetId))}`, {
    method: 'DELETE',
    parseJson: false,
  })
}

export async function runWatchTarget(watchTargetId: string): Promise<WatchRunResult> {
  return request<WatchRunResult>(`/api/watch-targets/${encodeURIComponent(String(watchTargetId))}/run`, {
    method: 'POST',
  })
}

export async function listWatchTargetSignals(
  watchTargetId: string,
  params: WatchSignalListParams = {},
): Promise<PaginatedResponse<WatchSignal>> {
  return request<PaginatedResponse<WatchSignal>>(
    `/api/watch-targets/${encodeURIComponent(String(watchTargetId))}/signals`,
    {
      method: 'GET',
      query: {
        signal_type: params.signal_type,
        severity: params.severity,
        page: params.page,
        page_size: params.page_size,
      },
    },
  )
}

export async function listAlerts(params: WatchAlertListParams = {}): Promise<PaginatedResponse<WatchAlert>> {
  return request<PaginatedResponse<WatchAlert>>('/api/alerts', {
    method: 'GET',
    query: {
      status: params.status,
      severity: params.severity,
      watch_target_id: params.watch_target_id,
      page: params.page,
      page_size: params.page_size,
    },
  })
}

export async function getUnreadAlertCount(): Promise<number> {
  const response = await request<AlertUnreadCountResponse>('/api/alerts/unread-count', {
    method: 'GET',
  })
  return response.unread_count
}

export async function markAlertRead(alertId: string): Promise<WatchAlert> {
  return request<WatchAlert>(`/api/alerts/${encodeURIComponent(String(alertId))}/read`, {
    method: 'PATCH',
  })
}

export async function dismissAlert(alertId: string): Promise<WatchAlert> {
  return request<WatchAlert>(`/api/alerts/${encodeURIComponent(String(alertId))}/dismiss`, {
    method: 'PATCH',
  })
}

export async function markAllAlertsRead(): Promise<number> {
  const response = await request<AlertReadAllResponse>('/api/alerts/read-all', {
    method: 'POST',
  })
  return response.updated_count
}
