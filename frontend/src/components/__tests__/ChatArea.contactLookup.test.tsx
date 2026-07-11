import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ChatArea from '../ChatArea'
import type { ContactPayload } from '../../types/contactIntelligence'
import { useConversationStore } from '../../stores/conversationStore'
import { useMessageStore } from '../../stores/messageStore'

const authState = {
  refreshUser: vi.fn().mockResolvedValue(undefined),
  status: 'unauthenticated' as 'authenticated' | 'unauthenticated' | 'loading',
  user: null as null | { public_id: string },
}

const sendChatStreamMock = vi.fn()
const createConversationMock = vi.fn()
const fetchMessagesMock = vi.fn()

vi.mock('../../auth/useAuth', () => ({
  useAuth: () => authState,
}))

vi.mock('../../components/AgentAlerts', () => ({
  default: () => null,
}))

vi.mock('../../components/CollectionPanel', () => ({
  CollectionPanel: () => null,
}))

vi.mock('../../components/TaskPanel', () => ({
  TaskPanel: () => null,
}))

vi.mock('../../components/OntologyFilter', () => ({
  OntologyFilter: () => null,
}))

vi.mock('../../services/api', () => ({
  ChatApiError: class ChatApiError extends Error {
    status = 500
    code = 'TEST'
    isNetworkError = false
  },
  buildApiUrl: (path: string) => `/api${path}`,
  sendChatStream: (...args: unknown[]) => sendChatStreamMock(...args),
  fetchMessages: (...args: unknown[]) => fetchMessagesMock(...args),
  createConversation: (...args: unknown[]) => createConversationMock(...args),
}))

const fetchMock = vi.fn()
vi.stubGlobal('fetch', fetchMock)

const contactPayload: ContactPayload = {
  organization: {
    id: 'org-victory',
    name: 'Victory Philippines',
    source_url: 'https://org.example.com/source',
    source_name: 'manual_seed',
    organization_confidence: 0.82,
    updated_at: '2026-07-11T09:00:00Z',
  },
  contacts: [
    {
      id: 'contact-email',
      type: 'email',
      label: 'Public Email',
      value: 'info@victory.org.ph',
      normalized_value: 'info@victory.org.ph',
      source_url: null,
      source_name: 'manual_seed',
      confidence: null,
      verification_status: 'unverified',
      is_verified: false,
      usage: 'research',
      warnings: ['field_level_source_missing'],
    },
    {
      id: 'contact-website',
      type: 'website',
      label: 'Official Website',
      value: 'https://victory.org.ph',
      normalized_value: 'https://victory.org.ph',
      source_url: 'https://org.example.com/source',
      source_name: 'manual_seed',
      confidence: null,
      verification_status: 'unverified',
      is_verified: false,
      usage: 'research',
      warnings: [],
    },
  ],
  summary: {
    contact_count: 2,
    email_count: 1,
    phone_count: 0,
    social_count: 0,
    website_count: 1,
    verified_count: 0,
    missing_source_count: 1,
    outreach_candidate_count: 0,
  },
  warnings: ['field_level_source_missing'],
  found: true,
}

const renderChatArea = () =>
  render(
    <MemoryRouter>
      <ChatArea showSettings={false} onToggleSettings={() => {}} />
    </MemoryRouter>,
  )

describe('ChatArea contact lookup wiring', () => {
  beforeEach(() => {
    Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
      configurable: true,
      value: vi.fn(),
    })
    useConversationStore.getState().reset()
    useMessageStore.getState().reset()
    fetchMock.mockReset()
    fetchMock.mockResolvedValue({ json: vi.fn().mockResolvedValue([]) })
    sendChatStreamMock.mockReset()
    createConversationMock.mockReset()
    fetchMessagesMock.mockReset()
    fetchMessagesMock.mockResolvedValue([])
    authState.status = 'unauthenticated'
    authState.user = null
    vi.stubEnv('VITE_CHAT_USER_OWNERSHIP_ENABLED', 'false')
    vi.stubEnv('VITE_AUTH_V1_ENABLED', 'false')
  })

  afterEach(() => {
    vi.clearAllMocks()
    vi.unstubAllEnvs()
  })

  it('renders ContactCard when assistant message carries contact_lookup payload', async () => {
    useConversationStore.getState().addConversation({
      id: 'conv-1',
      title: 'Contact Lookup',
      created_at: '2026-07-10T00:00:00Z',
      updated_at: '2026-07-10T00:00:00Z',
    })
    useMessageStore.getState().addMessage('conv-1', {
      id: 'assistant-1',
      role: 'assistant',
      content: 'Victory Philippines 的公开联系方式如下（来自数据库记录，不是推测）：',
      sources: [],
      delivery_type: 'text',
      status: 'completed',
      contact_lookup: contactPayload,
    })

    renderChatArea()

    expect(await screen.findByText(/来自数据库记录，不是推测/)).toBeInTheDocument()
    expect(screen.getByTestId('contact-card')).toHaveTextContent('Victory Philippines')
    expect(screen.getByTestId('contact-card')).toHaveTextContent('info@victory.org.ph')
  })

  it('does not render ContactCard when message only contains contact-like text', async () => {
    useConversationStore.getState().addConversation({
      id: 'conv-2',
      title: 'No Contact Payload',
      created_at: '2026-07-10T00:00:00Z',
      updated_at: '2026-07-10T00:00:00Z',
    })
    useMessageStore.getState().addMessage('conv-2', {
      id: 'assistant-2',
      role: 'assistant',
      content: '这里是一段纯文本，写着 info@victory.org.ph 和 +63 2 1234 5678，但没有结构化 contact_lookup payload。',
      sources: [],
      delivery_type: 'text',
      status: 'completed',
    })

    renderChatArea()

    expect(await screen.findByText(/没有结构化 contact_lookup payload/)).toBeInTheDocument()
    expect(screen.queryByTestId('contact-card')).not.toBeInTheDocument()
  })

  it('renders contact card after stream done event arrives with contact_lookup payload', async () => {
    useConversationStore.getState().addConversation({
      id: 'conv-stream',
      title: 'Contact Stream',
      created_at: '2026-07-10T00:00:00Z',
      updated_at: '2026-07-10T00:00:00Z',
    })
    createConversationMock.mockResolvedValue({
      id: 'conv-stream',
      title: 'Contact Stream',
      created_at: '2026-07-10T00:00:00Z',
      updated_at: '2026-07-10T00:00:00Z',
    })
    sendChatStreamMock.mockImplementation(
      async (
        _message: string,
        _conversationId: string | null,
        onEvent: (type: string, data: Record<string, unknown>) => void,
      ) => {
        onEvent('done', {
          type: 'done',
          message_id: 'assistant-stream',
          full_content: 'Victory Philippines public contact channels are listed below (from database records, not guesses):',
          contact_lookup: contactPayload,
          delivery: {
            sources: [],
            delivery_type: 'text',
          },
        })
      },
    )

    renderChatArea()

    fireEvent.change(screen.getByPlaceholderText('输入你的问题，支持机构查询、投资匹配、图谱关系、全球新闻...'), {
      target: { value: 'How can I contact Victory Philippines?' },
    })
    fireEvent.click(screen.getByRole('button', { name: '发送' }))

    await waitFor(() => {
      expect(screen.getByTestId('contact-card')).toBeInTheDocument()
    })

    expect(screen.getByText(/from database records, not guesses/i)).toBeInTheDocument()
    expect(screen.getByTestId('contact-card')).toHaveTextContent('https://victory.org.ph')
  })
})
