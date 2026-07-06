import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { WatchButton } from '../WatchButton'

const authState = {
  refreshUser: vi.fn().mockResolvedValue(undefined),
  status: 'unauthenticated' as 'loading' | 'authenticated' | 'unauthenticated',
  user: null as null | { public_id: string },
}

vi.mock('../../auth/useAuth', () => ({
  useAuth: () => authState,
}))

vi.mock('../../api/watchAlerts', () => ({
  createWatchTarget: vi.fn(),
  deleteWatchTarget: vi.fn(),
  listWatchTargets: vi.fn(),
  runWatchTarget: vi.fn(),
  updateWatchTarget: vi.fn(),
}))

import {
  createWatchTarget,
  listWatchTargets,
} from '../../api/watchAlerts'

const mockedCreateWatchTarget = vi.mocked(createWatchTarget)
const mockedListWatchTargets = vi.mocked(listWatchTargets)

function LoginDestination() {
  const location = useLocation()
  return <div data-testid="login-state">{JSON.stringify(location.state)}</div>
}

function renderWatchButton() {
  return render(
    <MemoryRouter initialEntries={['/dashboard/org/org-1?tab=detail']}>
      <Routes>
        <Route path="/dashboard/org/:id" element={<WatchButton entityId="org-1" entityType="organization" />} />
        <Route path="/login" element={<LoginDestination />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('WatchButton authenticated-user mode', () => {
  beforeEach(() => {
    vi.stubEnv('VITE_WATCH_ALERT_UI_ENABLED', 'true')
    vi.stubEnv('VITE_WATCH_ALERT_USER_OWNERSHIP_ENABLED', 'true')
    vi.stubEnv('VITE_AUTH_V1_ENABLED', 'true')
    authState.refreshUser.mockReset()
    authState.status = 'unauthenticated'
    authState.user = null
    mockedCreateWatchTarget.mockReset()
    mockedListWatchTargets.mockReset()
  })

  afterEach(() => {
    vi.unstubAllEnvs()
  })

  it('does not request watch state while unauthenticated and redirects to login on click', async () => {
    renderWatchButton()

    expect(await screen.findByRole('button', { name: '登录后关注' })).toBeInTheDocument()
    expect(mockedListWatchTargets).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { name: '登录后关注' }))

    await waitFor(() => expect(screen.getByTestId('login-state')).toBeInTheDocument())
    expect(screen.getByTestId('login-state').textContent).toContain('/dashboard/org/org-1?tab=detail')
  })

  it('does not request watch state while auth status is loading', async () => {
    authState.status = 'loading'

    renderWatchButton()

    expect(await screen.findByRole('button', { name: 'Checking login...' })).toBeDisabled()
    expect(mockedListWatchTargets).not.toHaveBeenCalled()
  })

  it('loads watch state for the authenticated user', async () => {
    authState.status = 'authenticated'
    authState.user = { public_id: 'user-a' }
    mockedListWatchTargets.mockResolvedValue({
      items: [
        {
          id: 'watch-1',
          entity_id: 'org-1',
          entity_type: 'organization',
          status: 'active',
          frequency: 'daily',
          last_checked_at: null,
          next_check_at: null,
          last_success_at: null,
          consecutive_failures: 0,
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z',
        },
      ],
      page: 1,
      page_size: 100,
      total: 1,
    })

    renderWatchButton()

    await waitFor(() => expect(mockedListWatchTargets).toHaveBeenCalled())
    expect(await screen.findByText('Watching')).toBeInTheDocument()
    expect(mockedCreateWatchTarget).not.toHaveBeenCalled()
  })
})
