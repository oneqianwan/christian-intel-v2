import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ChatArea from '../ChatArea'
import type { PartnershipEvidenceBriefPayload } from '../../types/partnershipEvidenceBrief'
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

const evidenceBriefPayload: PartnershipEvidenceBriefPayload = {
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
    brief_available: true,
    decision: 'manual_review',
    priority: 'high',
    confidence: 0.84,
    risk_level: 'medium',
    evidence_count: 5,
    missing_evidence_count: 1,
    recommended_channel: 'email',
  },
  decision_rationale: {
    headline: 'Recommendation is promising but still needs manual validation.',
    reason_codes: ['relationship_path_available', 'contact_available'],
    supporting_points: ['Public contact channel exists'],
    limiting_factors: ['contact_unverified'],
  },
  evidence_sections: {
    score_evidence: {
      people_score: 78,
      digital_score: 74,
      intel_score: 81,
      strengths: ['strong_people_score'],
      weaknesses: ['missing_recent_updates'],
      warnings: ['stale_score_signal'],
    },
    relationship_evidence: {
      has_relationship_path: true,
      relationship_count: 1,
      strongest_relationship_type: 'partner',
      relationship_path_summary: ['partner via unit_test_evidence'],
      warnings: ['weak_relationship_signal'],
    },
    contact_evidence: {
      has_website: true,
      has_email: true,
      has_phone: false,
      has_social: true,
      contact_count: 3,
      verified_contact_count: 0,
      missing_source_count: 1,
      recommended_contact: {
        type: 'email',
        value: 'connect@bridge.org',
        source_url: 'https://bridge.org/source',
        is_verified: false,
      },
      warnings: ['contact_unverified'],
    },
    recommendation_evidence: {
      recommendation_score: 84,
      priority: 'high',
      confidence: 0.91,
      reason_codes: ['relationship_path_available', 'contact_available'],
      risks: ['missing_contact_source'],
      warnings: ['target_not_in_recommendations'],
    },
    action_plan_evidence: {
      plan_available: true,
      blocked: false,
      step_count: 2,
      recommended_channel: 'email',
      risk_level: 'medium',
      first_steps: ['Review relationship path', 'Prepare transparent outreach'],
      warnings: ['contact_unverified'],
    },
  },
  risk_register: [
    {
      risk_code: 'contact_unverified',
      severity: 'medium',
      description: 'The public contact channel is not yet verified.',
      mitigation: 'Confirm the source before outreach.',
    },
  ],
  recommended_next_actions: ['Review relationship path'],
  do_not_proceed_if: ['No approved public contact channel remains'],
  audit: {
    generated_by: 'rule_based_evidence_brief',
    no_llm: true,
    source_modules: ['partnership_recommender'],
    missing_modules: [],
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

describe('ChatArea evidence brief lookup wiring', () => {
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

  it('renders EvidenceBriefCard when assistant message carries partnership_evidence_brief payload', async () => {
    useConversationStore.getState().addConversation({
      id: 'conv-1',
      title: 'Evidence Brief Lookup',
      created_at: '2026-07-10T00:00:00Z',
      updated_at: '2026-07-10T00:00:00Z',
    })
    useMessageStore.getState().addMessage('conv-1', {
      id: 'assistant-1',
      role: 'assistant',
      content: 'Victory Philippines 的合作证据简报如下（来自数据库规则，不是文本猜测）：',
      sources: [],
      delivery_type: 'text',
      status: 'completed',
      partnership_evidence_brief: evidenceBriefPayload,
    })

    renderChatArea()

    expect(await screen.findByText(/来自数据库规则，不是文本猜测/)).toBeInTheDocument()
    expect(screen.getByTestId('evidence-brief-card')).toHaveTextContent('Victory Philippines')
    expect(screen.getByTestId('evidence-brief-card')).toHaveTextContent('Bridge Ministry')
    expect(screen.getByTestId('evidence-brief-card')).toHaveTextContent('manual_review')
  })

  it('does not render EvidenceBriefCard when message only contains evidence-like text', async () => {
    useConversationStore.getState().addConversation({
      id: 'conv-2',
      title: 'No Evidence Payload',
      created_at: '2026-07-10T00:00:00Z',
      updated_at: '2026-07-10T00:00:00Z',
    })
    useMessageStore.getState().addMessage('conv-2', {
      id: 'assistant-2',
      role: 'assistant',
      content: '纯文本里提到 decision、risk_level、Bridge Ministry 和 contact_unverified，但没有结构化 partnership_evidence_brief payload。',
      sources: [],
      delivery_type: 'text',
      status: 'completed',
    })

    renderChatArea()

    expect(await screen.findByText(/没有结构化 partnership_evidence_brief payload/)).toBeInTheDocument()
    expect(screen.queryByTestId('evidence-brief-card')).not.toBeInTheDocument()
  })

  it('renders evidence brief card after stream done event arrives with partnership_evidence_brief payload', async () => {
    useConversationStore.getState().addConversation({
      id: 'conv-stream',
      title: 'Evidence Brief Stream',
      created_at: '2026-07-10T00:00:00Z',
      updated_at: '2026-07-10T00:00:00Z',
    })
    createConversationMock.mockResolvedValue({
      id: 'conv-stream',
      title: 'Evidence Brief Stream',
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
          full_content: 'Victory Philippines evidence brief is listed below (from database rules, not guesses):',
          partnership_evidence_brief: evidenceBriefPayload,
          delivery: {
            sources: [],
            delivery_type: 'text',
          },
        })
      },
    )

    renderChatArea()

    fireEvent.change(screen.getByPlaceholderText('输入你的问题，支持机构查询、投资匹配、图谱关系、全球新闻...'), {
      target: { value: 'Give me an evidence brief for Victory Philippines.' },
    })
    fireEvent.click(screen.getByRole('button', { name: '发送' }))

    await waitFor(() => {
      expect(screen.getByTestId('evidence-brief-card')).toBeInTheDocument()
    })

    expect(screen.getByText(/from database rules, not guesses/i)).toBeInTheDocument()
    expect(screen.getByTestId('evidence-brief-card')).toHaveTextContent('Recommendation is promising but still needs manual validation.')
  })
})
