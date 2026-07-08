import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ChatArea from '../ChatArea'
import { useConversationStore } from '../../stores/conversationStore'
import { useMessageStore } from '../../stores/messageStore'

const authState = {
  refreshUser: vi.fn().mockResolvedValue(undefined),
  status: 'unauthenticated' as 'authenticated' | 'unauthenticated' | 'loading',
  user: null as null | { public_id: string },
}

vi.mock('../../auth/useAuth', () => ({
  useAuth: () => authState,
}))

const fetchMock = vi.fn()
vi.stubGlobal('fetch', fetchMock)

describe('ChatArea authenticated-user mode UI gating', () => {
  beforeEach(() => {
    fetchMock.mockReset()
    fetchMock.mockResolvedValue({ json: vi.fn().mockResolvedValue([]) })
    authState.refreshUser.mockReset()
    authState.status = 'unauthenticated'
    authState.user = null
    useConversationStore.getState().reset()
    useMessageStore.getState().reset()
  })

  afterEach(() => {
    vi.unstubAllEnvs()
  })

  it('shows login required state while unauthenticated and does not request chat data', () => {
    vi.stubEnv('VITE_CHAT_USER_OWNERSHIP_ENABLED', 'true')
    vi.stubEnv('VITE_AUTH_V1_ENABLED', 'true')

    render(
      <MemoryRouter initialEntries={['/']}>
        <ChatArea showSettings={false} onToggleSettings={() => {}} />
      </MemoryRouter>,
    )

    expect(screen.getByText('需要登录')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '去登录' })).toBeInTheDocument()
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('shows loading state while auth is loading and does not request chat data', () => {
    vi.stubEnv('VITE_CHAT_USER_OWNERSHIP_ENABLED', 'true')
    vi.stubEnv('VITE_AUTH_V1_ENABLED', 'true')
    authState.status = 'loading'

    render(
      <MemoryRouter>
        <ChatArea showSettings={false} onToggleSettings={() => {}} />
      </MemoryRouter>,
    )

    expect(screen.getByText('检查登录状态中')).toBeInTheDocument()
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('shows invalid config state when chat ownership enabled but auth disabled', () => {
    vi.stubEnv('VITE_CHAT_USER_OWNERSHIP_ENABLED', 'true')
    vi.stubEnv('VITE_AUTH_V1_ENABLED', 'false')

    render(
      <MemoryRouter>
        <ChatArea showSettings={false} onToggleSettings={() => {}} />
      </MemoryRouter>,
    )

    expect(screen.getByText('配置错误')).toBeInTheDocument()
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('preserves legacy chat mode behavior when ownership flag is disabled', () => {
    vi.stubEnv('VITE_CHAT_USER_OWNERSHIP_ENABLED', 'false')
    vi.stubEnv('VITE_AUTH_V1_ENABLED', 'false')

    render(
      <MemoryRouter>
        <ChatArea showSettings={false} onToggleSettings={() => {}} />
      </MemoryRouter>,
    )

    expect(screen.getByText('基督教情报系统')).toBeInTheDocument()
  })
})
