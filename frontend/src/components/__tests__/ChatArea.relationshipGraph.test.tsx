import { fireEvent, render, screen, waitFor } from '@testing-library/react'
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

const relationshipGraph = {
  center: {
    id: 'org-victory',
    graph_id: 'org:org-victory',
    type: 'organization',
    name: 'Victory Philippines',
    region: 'Philippines',
    denomination: 'Evangelical',
    people_score: 64,
    digital_score: 28,
    intel_score: 65,
  },
  nodes: [
    {
      id: 'org:org-life',
      entity_id: 'org-life',
      type: 'organization',
      label: 'Life.Church',
      name: 'Life.Church',
      region: 'United States',
      denomination: 'Evangelical',
      people_score: 70,
      digital_score: 50,
      intel_score: 60,
      confidence: 0.82,
      source_count: 2,
    },
  ],
  edges: [
    {
      id: 'edge-1',
      source: 'org:org-victory',
      target: 'org:org-life',
      relation_type: 'partner',
      direction: 'outbound',
      strength: 0.7,
      confidence: 0.82,
      is_verified: true,
      evidence_url: 'https://example.com/partner-proof',
      evidence_source: 'Public partnership page',
      evidence_date: '2026-07-10',
      reason: '公开来源显示两者存在合作关系',
      missing_evidence: false,
    },
  ],
  summary: {
    node_count: 2,
    edge_count: 1,
    verified_edge_count: 1,
    unverified_edge_count: 0,
    missing_evidence_count: 0,
  },
  warnings: [],
  found: true,
  depth: 1,
  limit: 50,
  include_unverified: false,
}

const renderChatArea = () =>
  render(
    <MemoryRouter>
      <ChatArea showSettings={false} onToggleSettings={() => {}} />
    </MemoryRouter>,
  )

describe('ChatArea relationship graph wiring', () => {
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

  it('renders IntelGraph when assistant message carries relationship_graph payload', async () => {
    useConversationStore.getState().addConversation({
      id: 'conv-1',
      title: 'Graph',
      created_at: '2026-07-10T00:00:00Z',
      updated_at: '2026-07-10T00:00:00Z',
    })
    useMessageStore.getState().addMessage('conv-1', {
      id: 'assistant-1',
      role: 'assistant',
      content: 'Victory Philippines 的关系图谱目前有 1 条有证据关系。',
      sources: [],
      delivery_type: 'text',
      status: 'completed',
      relationship_graph: relationshipGraph,
    })

    renderChatArea()

    expect(await screen.findByText('Victory Philippines 的关系图谱目前有 1 条有证据关系。')).toBeInTheDocument()
    expect(screen.getByTestId('intel-graph')).toHaveTextContent('Life.Church')
  })

  it('does not render IntelGraph when message only contains graph-like text', async () => {
    useConversationStore.getState().addConversation({
      id: 'conv-2',
      title: 'No Graph Payload',
      created_at: '2026-07-10T00:00:00Z',
      updated_at: '2026-07-10T00:00:00Z',
    })
    useMessageStore.getState().addMessage('conv-2', {
      id: 'assistant-2',
      role: 'assistant',
      content: '说明 Victory Philippines 的关系图谱，但这里没有结构化 relationship_graph payload。',
      sources: [],
      delivery_type: 'text',
      status: 'completed',
    })

    renderChatArea()

    expect(await screen.findByText(/这里没有结构化 relationship_graph payload/)).toBeInTheDocument()
    expect(screen.queryByTestId('intel-graph')).not.toBeInTheDocument()
  })

  it('renders graph after stream done event arrives with relationship_graph payload', async () => {
    useConversationStore.getState().addConversation({
      id: 'conv-stream',
      title: 'Graph Stream',
      created_at: '2026-07-10T00:00:00Z',
      updated_at: '2026-07-10T00:00:00Z',
    })
    createConversationMock.mockResolvedValue({
      id: 'conv-stream',
      title: 'Graph Stream',
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
          full_content: '以下关系来自数据库证据，不是推测。',
          relationship_graph: relationshipGraph,
          delivery: {
            sources: [],
            delivery_type: 'text',
          },
        })
      },
    )

    renderChatArea()

    fireEvent.change(screen.getByPlaceholderText('输入你的问题，支持机构查询、投资匹配、图谱关系、全球新闻...'), {
      target: { value: '说明 Victory Philippines 的关系图谱' },
    })
    fireEvent.click(screen.getByRole('button', { name: '发送' }))

    await waitFor(() => {
      expect(screen.getByTestId('intel-graph')).toBeInTheDocument()
    })

    expect(screen.getByText('以下关系来自数据库证据，不是推测。')).toBeInTheDocument()
    expect(screen.getByTestId('intel-graph')).toHaveTextContent('Life.Church')
  })
})
