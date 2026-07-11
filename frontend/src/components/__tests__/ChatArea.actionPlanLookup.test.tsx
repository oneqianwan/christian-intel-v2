import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ChatArea from '../ChatArea'
import type { PartnershipActionPlanPayload } from '../../types/partnershipActionPlan'
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

const actionPlanPayload: PartnershipActionPlanPayload = {
  organization: {
    id: 'org-victory',
    name: 'Victory Philippines',
    source_url: 'https://victory.org.ph/source',
    source_name: 'manual_seed',
    updated_at: '2026-07-11T09:00:00Z',
  },
  target_org: {
    id: 'org-bridge',
    name: 'Bridge Ministry',
    source_url: 'https://bridge.org/source',
    source_name: 'manual_seed',
  },
  summary: {
    plan_available: true,
    step_count: 2,
    blocked: false,
    block_reasons: [],
    recommended_channel: 'email',
    risk_level: 'medium',
    confidence: 0.88,
  },
  action_plan: [
    {
      step_number: 1,
      action_type: 'prepare_outreach',
      title: 'Prepare transparent outreach',
      description: 'Prepare a transparent outreach note.',
      channel: 'email',
      depends_on: [],
      required_evidence: ['public_channel_confirmed'],
      uses_contact: {
        type: 'email',
        value: 'connect@bridge.org',
        source_url: 'https://bridge.org/source',
        is_verified: false,
      },
      risk_flags: ['contact_unverified'],
      success_criteria: ['Draft reviewed internally'],
      do_not_proceed_if: ['No approved public contact channel remains'],
      priority: 'high',
    },
    {
      step_number: 2,
      action_type: 'contact',
      title: 'Send outreach',
      description: 'Send a transparent introductory message through a public channel.',
      channel: 'email',
      depends_on: [1],
      required_evidence: ['outreach_copy_approved'],
      uses_contact: {
        type: 'email',
        value: 'connect@bridge.org',
        source_url: 'https://bridge.org/source',
        is_verified: false,
      },
      risk_flags: ['contact_unverified'],
      success_criteria: ['Message sent through public channel'],
      do_not_proceed_if: ['Manual review blocks outreach'],
      priority: 'medium',
    },
  ],
  evidence: {
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
    recommendation_snapshot: {
      target_org_id: 'org-bridge',
      target_org_name: 'Bridge Ministry',
      recommendation_score: 84,
      priority: 'high',
      confidence: 0.91,
      reason_codes: ['relationship_path_available', 'contact_available'],
      risks: ['missing_contact_source'],
      warnings: ['weak_relationship_signal'],
      recommended_next_action: 'contact',
    },
  },
  warnings: ['contact_unverified'],
  found: true,
}

const renderChatArea = () =>
  render(
    <MemoryRouter>
      <ChatArea showSettings={false} onToggleSettings={() => {}} />
    </MemoryRouter>,
  )

describe('ChatArea action plan lookup wiring', () => {
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

  it('renders ActionPlanCard when assistant message carries partnership_action_plan payload', async () => {
    useConversationStore.getState().addConversation({
      id: 'conv-1',
      title: 'Action Plan Lookup',
      created_at: '2026-07-10T00:00:00Z',
      updated_at: '2026-07-10T00:00:00Z',
    })
    useMessageStore.getState().addMessage('conv-1', {
      id: 'assistant-1',
      role: 'assistant',
      content: 'Victory Philippines 的合作行动计划如下（来自数据库规则，不是文本猜测）：',
      sources: [],
      delivery_type: 'text',
      status: 'completed',
      partnership_action_plan: actionPlanPayload,
    })

    renderChatArea()

    expect(await screen.findByText(/来自数据库规则，不是文本猜测/)).toBeInTheDocument()
    expect(screen.getByTestId('action-plan-card')).toHaveTextContent('Victory Philippines')
    expect(screen.getByTestId('action-plan-card')).toHaveTextContent('Bridge Ministry')
    expect(screen.getByTestId('action-plan-card')).toHaveTextContent('Prepare transparent outreach')
  })

  it('does not render ActionPlanCard when message only contains action-plan-like text', async () => {
    useConversationStore.getState().addConversation({
      id: 'conv-2',
      title: 'No Action Plan Payload',
      created_at: '2026-07-10T00:00:00Z',
      updated_at: '2026-07-10T00:00:00Z',
    })
    useMessageStore.getState().addMessage('conv-2', {
      id: 'assistant-2',
      role: 'assistant',
      content: '纯文本里提到 next steps、email、risk_level 和 Bridge Ministry，但没有结构化 partnership_action_plan payload。',
      sources: [],
      delivery_type: 'text',
      status: 'completed',
    })

    renderChatArea()

    expect(await screen.findByText(/没有结构化 partnership_action_plan payload/)).toBeInTheDocument()
    expect(screen.queryByTestId('action-plan-card')).not.toBeInTheDocument()
  })

  it('renders action plan card after stream done event arrives with partnership_action_plan payload', async () => {
    useConversationStore.getState().addConversation({
      id: 'conv-stream',
      title: 'Action Plan Stream',
      created_at: '2026-07-10T00:00:00Z',
      updated_at: '2026-07-10T00:00:00Z',
    })
    createConversationMock.mockResolvedValue({
      id: 'conv-stream',
      title: 'Action Plan Stream',
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
          full_content: 'Victory Philippines action plan is listed below (from database rules, not guesses):',
          partnership_action_plan: actionPlanPayload,
          delivery: {
            sources: [],
            delivery_type: 'text',
          },
        })
      },
    )

    renderChatArea()

    fireEvent.change(screen.getByPlaceholderText('输入你的问题，支持机构查询、投资匹配、图谱关系、全球新闻...'), {
      target: { value: 'What are the next steps for Victory Philippines?' },
    })
    fireEvent.click(screen.getByRole('button', { name: '发送' }))

    await waitFor(() => {
      expect(screen.getByTestId('action-plan-card')).toBeInTheDocument()
    })

    expect(screen.getByText(/from database rules, not guesses/i)).toBeInTheDocument()
    expect(screen.getByTestId('action-plan-card')).toHaveTextContent('Prepare transparent outreach')
  })
})
