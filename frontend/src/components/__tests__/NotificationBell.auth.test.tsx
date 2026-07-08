import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { WatchAlertApiError } from '../../types/watchAlerts'
import NotificationBell from '../NotificationBell'

const authState = {
  refreshUser: vi.fn().mockResolvedValue(undefined),
  status: 'unauthenticated' as 'authenticated' | 'unauthenticated' | 'loading',
  user: null as null | { public_id: string },
}

vi.mock('../../auth/useAuth', () => ({
  useAuth: () => authState,
}))

vi.mock('../../api/watchAlerts', async () => {
  const actual = await vi.importActual<typeof import('../../api/watchAlerts')>('../../api/watchAlerts')
  return {
    ...actual,
    getUnreadAlertCount: vi.fn(),
    hasWatchAlertSession: vi.fn(() => false),
  }
})

import { getUnreadAlertCount, hasWatchAlertSession } from '../../api/watchAlerts'

const mockedGetUnreadAlertCount = vi.mocked(getUnreadAlertCount)
const mockedHasWatchAlertSession = vi.mocked(hasWatchAlertSession)

function renderBell() {
  return render(
    <MemoryRouter>
      <NotificationBell />
    </MemoryRouter>,
  )
}

describe('NotificationBell authenticated-user mode', () => {
  beforeEach(() => {
    vi.stubEnv('VITE_WATCH_ALERT_UI_ENABLED', 'true')
    vi.stubEnv('VITE_WATCH_ALERT_USER_OWNERSHIP_ENABLED', 'true')
    vi.stubEnv('VITE_AUTH_V1_ENABLED', 'true')
    authState.refreshUser.mockReset()
    authState.status = 'unauthenticated'
    authState.user = null
    mockedGetUnreadAlertCount.mockReset()
    mockedHasWatchAlertSession.mockReset()
    mockedHasWatchAlertSession.mockReturnValue(false)
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllEnvs()
  })

  it('does not poll when unauthenticated', () => {
    renderBell()

    expect(screen.queryByRole('button', { name: /通知铃铛/i })).not.toBeInTheDocument()
    expect(mockedGetUnreadAlertCount).not.toHaveBeenCalled()
  })

  it('polls with the authenticated user session and renders the unread badge', async () => {
    authState.status = 'authenticated'
    authState.user = { public_id: 'user-a' }
    mockedGetUnreadAlertCount.mockResolvedValue(3)

    renderBell()

    await waitFor(() => expect(mockedGetUnreadAlertCount).toHaveBeenCalledTimes(1))
    expect(await screen.findByText('3')).toBeInTheDocument()
  })

  it('refreshes auth and stops repeat polling after a 401', async () => {
    authState.status = 'authenticated'
    authState.user = { public_id: 'user-a' }
    mockedGetUnreadAlertCount.mockRejectedValue(
      new WatchAlertApiError({
        status: 401,
        code: 'AUTH_REQUIRED',
        message: 'Authentication required',
        userMessage: '登录状态已失效，请重新登录',
      }),
    )

    renderBell()

    await waitFor(() => expect(authState.refreshUser).toHaveBeenCalledTimes(1))
    expect(mockedGetUnreadAlertCount).toHaveBeenCalledTimes(1)
  })

  it('ignores aborted polling requests without showing the generic red error', async () => {
    authState.status = 'authenticated'
    authState.user = { public_id: 'user-a' }
    mockedGetUnreadAlertCount.mockRejectedValue(new DOMException('aborted', 'AbortError'))

    renderBell()

    await waitFor(() => expect(mockedGetUnreadAlertCount).toHaveBeenCalledTimes(1))
    expect(screen.queryByText('操作失败，请稍后重试')).not.toBeInTheDocument()
  })
})
