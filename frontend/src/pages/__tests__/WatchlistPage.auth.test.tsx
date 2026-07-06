import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../../App'
import { WatchlistPage } from '../WatchlistPage'

const authState = {
  refreshUser: vi.fn().mockResolvedValue(undefined),
  status: 'unauthenticated' as 'authenticated' | 'unauthenticated' | 'loading',
  user: null as null | { public_id: string },
}

vi.mock('../../auth/useAuth', () => ({
  useAuth: () => authState,
}))

vi.mock('../../api/watchAlerts', () => ({
  deleteWatchTarget: vi.fn(),
  listWatchTargets: vi.fn(),
  runWatchTarget: vi.fn(),
  updateWatchTarget: vi.fn(),
}))

const fetchMock = vi.fn()
vi.stubGlobal('fetch', fetchMock)

import { listWatchTargets } from '../../api/watchAlerts'

const mockedListWatchTargets = vi.mocked(listWatchTargets)

describe('WatchlistPage authenticated-user mode', () => {
  beforeEach(() => {
    vi.stubEnv('VITE_WATCH_ALERT_UI_ENABLED', 'true')
    vi.stubEnv('VITE_WATCH_ALERT_USER_OWNERSHIP_ENABLED', 'true')
    vi.stubEnv('VITE_AUTH_V1_ENABLED', 'true')
    authState.refreshUser.mockReset()
    authState.status = 'unauthenticated'
    authState.user = null
    mockedListWatchTargets.mockReset()
    fetchMock.mockReset()
  })

  afterEach(() => {
    vi.unstubAllEnvs()
  })

  it('does not request watch data while unauthenticated', () => {
    render(
      <MemoryRouter>
        <WatchlistPage />
      </MemoryRouter>,
    )

    expect(mockedListWatchTargets).not.toHaveBeenCalled()
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('redirects /watchlist to login when authenticated-user mode is enabled', async () => {
    render(
      <MemoryRouter initialEntries={['/watchlist']}>
        <App />
      </MemoryRouter>,
    )

    expect(await screen.findByText('账号登录')).toBeInTheDocument()
    expect(mockedListWatchTargets).not.toHaveBeenCalled()
  })

  it('does not request watch data while auth state is loading', () => {
    authState.status = 'loading'

    render(
      <MemoryRouter>
        <WatchlistPage />
      </MemoryRouter>,
    )

    expect(mockedListWatchTargets).not.toHaveBeenCalled()
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('loads the authenticated user watchlist and renders the empty state', async () => {
    authState.status = 'authenticated'
    authState.user = { public_id: 'user-a' }
    mockedListWatchTargets.mockResolvedValue({
      items: [],
      page: 1,
      page_size: 10,
      total: 0,
    })

    render(
      <MemoryRouter>
        <WatchlistPage />
      </MemoryRouter>,
    )

    await waitFor(() => expect(mockedListWatchTargets).toHaveBeenCalledTimes(1))
    expect(await screen.findByText('You are not watching any organizations yet.')).toBeInTheDocument()
  })
})
