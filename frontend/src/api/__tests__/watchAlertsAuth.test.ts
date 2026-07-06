import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  getUnreadAlertCount,
  listAlerts,
  listWatchTargets,
} from '../watchAlerts'

function mockJsonResponse(body: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 200 ? 'OK' : 'ERROR',
    json: vi.fn().mockResolvedValue(body),
  } as unknown as Response
}

describe('watchAlerts auth request behavior', () => {
  beforeEach(() => {
    vi.stubEnv('VITE_API_BASE_URL', 'http://127.0.0.1:8001/api')
    window.localStorage.clear()
    vi.restoreAllMocks()
  })

  afterEach(() => {
    vi.unstubAllEnvs()
    vi.restoreAllMocks()
    window.localStorage.clear()
  })

  it('uses x-session-id in legacy-session mode', async () => {
    vi.stubEnv('VITE_WATCH_ALERT_UI_ENABLED', 'true')
    vi.stubEnv('VITE_WATCH_ALERT_USER_OWNERSHIP_ENABLED', 'false')
    vi.stubEnv('VITE_AUTH_V1_ENABLED', 'false')
    window.localStorage.setItem('x-session-id', 'legacy-123')

    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      mockJsonResponse({ items: [], page: 1, page_size: 10, total: 0 }),
    )

    await listWatchTargets({ page: 1, page_size: 10 })

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [, init] = fetchMock.mock.calls[0]
    const headers = new Headers(init?.headers)
    expect(headers.get('x-session-id')).toBe('legacy-123')
    expect(init?.credentials).toBeUndefined()
  })

  it('uses credentials include without x-session-id in authenticated-user mode', async () => {
    vi.stubEnv('VITE_WATCH_ALERT_UI_ENABLED', 'true')
    vi.stubEnv('VITE_WATCH_ALERT_USER_OWNERSHIP_ENABLED', 'true')
    vi.stubEnv('VITE_AUTH_V1_ENABLED', 'true')
    window.localStorage.setItem('x-session-id', 'legacy-should-not-leak')

    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      mockJsonResponse({ items: [], page: 1, page_size: 10, total: 0 }),
    )

    await listAlerts({ page: 1, page_size: 10 })

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [, init] = fetchMock.mock.calls[0]
    const headers = new Headers(init?.headers)
    expect(init?.credentials).toBe('include')
    expect(headers.get('x-session-id')).toBeNull()
    expect(headers.get('X-Session-Id')).toBeNull()
  })

  it('fails safe without calling fetch in invalid mode', async () => {
    vi.stubEnv('VITE_WATCH_ALERT_UI_ENABLED', 'true')
    vi.stubEnv('VITE_WATCH_ALERT_USER_OWNERSHIP_ENABLED', 'true')
    vi.stubEnv('VITE_AUTH_V1_ENABLED', 'false')

    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(mockJsonResponse({ unread_count: 0 }))

    await expect(getUnreadAlertCount()).rejects.toMatchObject({
      status: 503,
      code: 'WATCH_ALERT_IDENTITY_INVALID',
    })
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('rejects legacy requests without a stored session id', async () => {
    vi.stubEnv('VITE_WATCH_ALERT_UI_ENABLED', 'true')
    vi.stubEnv('VITE_WATCH_ALERT_USER_OWNERSHIP_ENABLED', 'false')
    vi.stubEnv('VITE_AUTH_V1_ENABLED', 'false')

    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      mockJsonResponse({ items: [], page: 1, page_size: 10, total: 0 }),
    )

    await expect(listWatchTargets({ page: 1, page_size: 10 })).rejects.toMatchObject({
      status: 401,
      code: 'AUTH_REQUIRED',
    })
    expect(fetchMock).not.toHaveBeenCalled()
  })
})
