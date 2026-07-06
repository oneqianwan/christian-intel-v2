import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../../App'
import { AlertsPage } from '../AlertsPage'

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
    dismissAlert: vi.fn(),
    listAlerts: vi.fn(),
    listWatchTargets: vi.fn(),
    markAlertRead: vi.fn(),
    markAllAlertsRead: vi.fn(),
  }
})

import {
  dismissAlert,
  listAlerts,
  listWatchTargets,
  markAllAlertsRead,
} from '../../api/watchAlerts'

const mockedDismissAlert = vi.mocked(dismissAlert)
const mockedListAlerts = vi.mocked(listAlerts)
const mockedListWatchTargets = vi.mocked(listWatchTargets)
const mockedMarkAllAlertsRead = vi.mocked(markAllAlertsRead)

describe('AlertsPage authenticated-user mode', () => {
  beforeEach(() => {
    vi.stubEnv('VITE_WATCH_ALERT_UI_ENABLED', 'true')
    vi.stubEnv('VITE_WATCH_ALERT_USER_OWNERSHIP_ENABLED', 'true')
    vi.stubEnv('VITE_AUTH_V1_ENABLED', 'true')
    authState.refreshUser.mockReset()
    authState.status = 'unauthenticated'
    authState.user = null
    mockedDismissAlert.mockReset()
    mockedListAlerts.mockReset()
    mockedListWatchTargets.mockReset()
    mockedMarkAllAlertsRead.mockReset()
  })

  afterEach(() => {
    vi.unstubAllEnvs()
  })

  it('does not request alerts while unauthenticated', () => {
    render(
      <MemoryRouter>
        <AlertsPage />
      </MemoryRouter>,
    )

    expect(mockedListAlerts).not.toHaveBeenCalled()
    expect(mockedListWatchTargets).not.toHaveBeenCalled()
  })

  it('redirects /alerts to login when authenticated-user mode is enabled', async () => {
    render(
      <MemoryRouter initialEntries={['/alerts']}>
        <App />
      </MemoryRouter>,
    )

    expect(await screen.findByText('账号登录')).toBeInTheDocument()
    expect(mockedListAlerts).not.toHaveBeenCalled()
  })

  it('loads alerts for the authenticated user', async () => {
    authState.status = 'authenticated'
    authState.user = { public_id: 'user-a' }
    mockedListWatchTargets.mockResolvedValue({
      items: [],
      page: 1,
      page_size: 100,
      total: 0,
    })
    mockedListAlerts.mockResolvedValue({
      items: [
        {
          id: 'alert-1',
          watch_target_id: 'watch-1',
          signal_id: 'signal-1',
          title: 'New alert',
          summary: 'Needs attention',
          severity: 'high',
          status: 'unread',
          source_url: null,
          created_at: '2026-01-01T00:00:00Z',
          read_at: null,
          dismissed_at: null,
        },
      ],
      page: 1,
      page_size: 10,
      total: 1,
    })

    render(
      <MemoryRouter>
        <AlertsPage />
      </MemoryRouter>,
    )

    await waitFor(() => expect(mockedListAlerts).toHaveBeenCalledTimes(1))
    expect(await screen.findByText('New alert')).toBeInTheDocument()
    expect(mockedListWatchTargets).toHaveBeenCalled()
  })

  it('uses the shared bulk read action after authenticated load', async () => {
    authState.status = 'authenticated'
    authState.user = { public_id: 'user-a' }
    mockedListWatchTargets.mockResolvedValue({
      items: [],
      page: 1,
      page_size: 100,
      total: 0,
    })
    mockedListAlerts.mockResolvedValue({
      items: [
        {
          id: 'alert-1',
          watch_target_id: 'watch-1',
          signal_id: 'signal-1',
          title: 'New alert',
          summary: 'Needs attention',
          severity: 'high',
          status: 'unread',
          source_url: null,
          created_at: '2026-01-01T00:00:00Z',
          read_at: null,
          dismissed_at: null,
        },
      ],
      page: 1,
      page_size: 10,
      total: 1,
    })
    mockedMarkAllAlertsRead.mockResolvedValue(1)

    render(
      <MemoryRouter>
        <AlertsPage />
      </MemoryRouter>,
    )

    await screen.findByText('New alert')
    fireEvent.click(screen.getByRole('button', { name: 'Mark All Read' }))

    await waitFor(() => expect(mockedMarkAllAlertsRead).toHaveBeenCalledTimes(1))
  })
})
