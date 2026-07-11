import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ChatArea from '../ChatArea'
import type { PartnershipRecommendationPayload } from '../../types/partnershipRecommendation'
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

const recommendationPayload: PartnershipRecommendationPayload = {
  organization: {
    id: 'org-victory',
    name: 'Victory Philippines',
    source_url: 'https://victory.org.ph/source',
    source_name: 'manual_seed',
    updated_at: '2026-07-11T09:00:00Z',
  },
  summary: {
    candidate_count: 3,
    recommended_count: 1,
    high_priority_count: 1,
    with_contact_count: 1,
    with_relationship_path_count: 1,
    warning_count: 1,
  },
  recommendations: [
    {
      target_org: {
        id: 'org-bridge',
        name: 'Bridge Ministry',
        country: 'Philippines',
        city: 'Manila',
        denomination: 'Evangelical',
        source_url: 'https://bridge.org/source',
        source_name: 'manual_seed',
      },
      recommendation_score: 84,
      priority: 'high',
      confidence: 0.91,
      reason_codes: ['relationship_path_available', 'contact_available'],
      explanation: '推荐原因：与当前机构存在关系路径，存在可用联系方式。',
      score_snapshot: {
        people_score: 78,
        digital_score: 74,
        intel_score: 81,
      },
      relationship_snapshot: {
        has_relationship_path: true,
        relationship_count: 1,
        strongest_relationship_type: 'partner',
        relationship_path_summary: ['partner via unit_test_evidence'],
      },
      contact_snapshot: {
        has_website: true,
        has_email: true,
        has_phone: false,
        has_social: true,
        contact_count: 3,
        verified_contact_count: 0,
        missing_source_count: 1,
      },
      risks: ['missing_contact_source'],
      warnings: ['weak_relationship_signal'],
      recommended_next_action: 'contact',
    },
  ],
  warnings: ['missing_contact_source'],
  found: true,
}

const renderChatArea = () =>
  render(
    <MemoryRouter>
      <ChatArea showSettings={false} onToggleSettings={() => {}} />
    </MemoryRouter>,
  )

describe('ChatArea recommendation lookup wiring', () => {
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

  it('renders RecommendationCard when assistant message carries partnership_recommendations payload', async () => {
    useConversationStore.getState().addConversation({
      id: 'conv-1',
      title: 'Recommendation Lookup',
      created_at: '2026-07-10T00:00:00Z',
      updated_at: '2026-07-10T00:00:00Z',
    })
    useMessageStore.getState().addMessage('conv-1', {
      id: 'assistant-1',
      role: 'assistant',
      content: 'Victory Philippines 推荐合作对象如下（来自数据库记录，不是推测）：',
      sources: [],
      delivery_type: 'text',
      status: 'completed',
      partnership_recommendations: recommendationPayload,
    })

    renderChatArea()

    expect(await screen.findByText(/来自数据库记录，不是推测/)).toBeInTheDocument()
    expect(screen.getByTestId('recommendation-card')).toHaveTextContent('Victory Philippines')
    expect(screen.getByTestId('recommendation-card')).toHaveTextContent('Bridge Ministry')
    expect(screen.getByTestId('recommendation-card')).toHaveTextContent('recommendation_score: 84')
  })

  it('does not render RecommendationCard when message only contains recommendation-like text', async () => {
    useConversationStore.getState().addConversation({
      id: 'conv-2',
      title: 'No Recommendation Payload',
      created_at: '2026-07-10T00:00:00Z',
      updated_at: '2026-07-10T00:00:00Z',
    })
    useMessageStore.getState().addMessage('conv-2', {
      id: 'assistant-2',
      role: 'assistant',
      content: '纯文本里提到 Bridge Ministry、84 分和 partner via evidence，但没有结构化 partnership_recommendations payload。',
      sources: [],
      delivery_type: 'text',
      status: 'completed',
    })

    renderChatArea()

    expect(await screen.findByText(/没有结构化 partnership_recommendations payload/)).toBeInTheDocument()
    expect(screen.queryByTestId('recommendation-card')).not.toBeInTheDocument()
  })

  it('renders recommendation card after stream done event arrives with partnership_recommendations payload', async () => {
    useConversationStore.getState().addConversation({
      id: 'conv-stream',
      title: 'Recommendation Stream',
      created_at: '2026-07-10T00:00:00Z',
      updated_at: '2026-07-10T00:00:00Z',
    })
    createConversationMock.mockResolvedValue({
      id: 'conv-stream',
      title: 'Recommendation Stream',
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
          full_content: 'Victory Philippines partnership recommendations are listed below (from database records, not guesses):',
          partnership_recommendations: recommendationPayload,
          delivery: {
            sources: [],
            delivery_type: 'text',
          },
        })
      },
    )

    renderChatArea()

    fireEvent.change(screen.getByPlaceholderText('输入你的问题，支持机构查询、投资匹配、图谱关系、全球新闻...'), {
      target: { value: 'Who should Victory Philippines partner with?' },
    })
    fireEvent.click(screen.getByRole('button', { name: '发送' }))

    await waitFor(() => {
      expect(screen.getByTestId('recommendation-card')).toBeInTheDocument()
    })

    expect(screen.getByText(/from database records, not guesses/i)).toBeInTheDocument()
    expect(screen.getByTestId('recommendation-card')).toHaveTextContent('Bridge Ministry')
  })
})
