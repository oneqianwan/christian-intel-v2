import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { OrgDetailPage } from '../OrgDetailPage'

vi.mock('../../features/watchAlerts/identity', () => ({
  isWatchAlertUiEnabled: () => false,
}))

vi.mock('../../components/WatchButton', () => ({
  WatchButton: () => null,
}))

const fetchMock = vi.fn()
vi.stubGlobal('fetch', fetchMock)

const orgPayload = {
  id: 'org-victory',
  name: 'Victory Philippines',
  english_name: null,
  short_name: null,
  country: 'Philippines',
  city: 'Manila',
  type: 'Church Network',
  denomination: 'Evangelical',
  website: 'https://victory.org.ph',
  founded_year: '1984',
  member_count: null,
  employee_count: null,
  annual_revenue: null,
  description: 'Sample description',
  mission_statement: 'Sample mission',
  leader: { name: 'Leader', title: 'Pastor', bio_url: null },
  scores: {
    people: { total: 64, grade: 'B' },
    digital: { total: 28, grade: 'C' },
    intel: { total: 65, grade: 'B' },
    composite: { total: 157 },
  },
  flags: {},
  social: {},
}

const relationsPayload = {
  relations: [],
  graph: {
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
    nodes: [],
    edges: [],
    summary: {
      node_count: 1,
      edge_count: 0,
      verified_edge_count: 0,
      unverified_edge_count: 0,
      missing_evidence_count: 0,
    },
    warnings: [{ code: 'no_relations', message: 'No graph relations found for this organization' }],
    found: true,
    depth: 1,
    limit: 50,
    include_unverified: false,
  },
}

const timelinePayload = { items: [] }

const contactPayload = {
  organization: {
    id: 'org-victory',
    name: 'Victory Philippines',
    source_url: 'https://org.example.com/source',
    source_name: 'manual_seed',
    organization_confidence: 0.82,
    updated_at: '2026-07-11T09:00:00Z',
  },
  contacts: [],
  summary: {
    contact_count: 0,
    email_count: 0,
    phone_count: 0,
    social_count: 0,
    website_count: 0,
    verified_count: 0,
    missing_source_count: 0,
    outreach_candidate_count: 0,
  },
  warnings: ['contact_missing'],
  found: true,
}

const recommendationPayload = {
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
  recommendations: [],
  warnings: ['missing_contact_source'],
  found: true,
}

const actionPlanPayload = {
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

const renderPage = () =>
  render(
    <MemoryRouter initialEntries={['/dashboard/org/org-victory']}>
      <Routes>
        <Route path="/dashboard/org/:orgId" element={<OrgDetailPage />} />
      </Routes>
    </MemoryRouter>,
  )

describe('OrgDetailPage action plan wiring', () => {
  beforeEach(() => {
    fetchMock.mockReset()
  })

  afterEach(() => {
    vi.clearAllMocks()
  })

  it('renders ActionPlanCard from real action-plan api payload', async () => {
    fetchMock
      .mockResolvedValueOnce({ ok: true, json: vi.fn().mockResolvedValue(orgPayload) })
      .mockResolvedValueOnce({ ok: true, json: vi.fn().mockResolvedValue(relationsPayload) })
      .mockResolvedValueOnce({ ok: true, json: vi.fn().mockResolvedValue(timelinePayload) })
      .mockResolvedValueOnce({ ok: true, json: vi.fn().mockResolvedValue(contactPayload) })
      .mockResolvedValueOnce({ ok: true, json: vi.fn().mockResolvedValue(recommendationPayload) })
      .mockResolvedValueOnce({ ok: true, json: vi.fn().mockResolvedValue(actionPlanPayload) })

    renderPage()

    await waitFor(() => {
      expect(screen.getByTestId('action-plan-card')).toBeInTheDocument()
    })

    expect(screen.getByTestId('action-plan-card')).toHaveTextContent('Victory Philippines')
    expect(screen.getByTestId('action-plan-card')).toHaveTextContent('Bridge Ministry')
    expect(screen.getByTestId('action-plan-card')).toHaveTextContent('recommended_channel')
    expect(screen.getByTestId('action-plan-card')).toHaveTextContent('email')
    expect(screen.getByTestId('action-plan-card')).toHaveTextContent('risk_level')
    expect(screen.getByTestId('action-plan-card')).toHaveTextContent('confidence')
    expect(screen.getByTestId('action-plan-card')).toHaveTextContent('Prepare transparent outreach')
    expect(screen.getByTestId('action-plan-card')).toHaveTextContent('public_channel_confirmed')
    expect(screen.getByTestId('action-plan-card')).toHaveTextContent('contact_unverified')
    expect(screen.getByTestId('action-plan-card')).toHaveTextContent('partner via unit_test_evidence')
  })

  it('shows blocked action plan state from api payload', async () => {
    fetchMock
      .mockResolvedValueOnce({ ok: true, json: vi.fn().mockResolvedValue(orgPayload) })
      .mockResolvedValueOnce({ ok: true, json: vi.fn().mockResolvedValue(relationsPayload) })
      .mockResolvedValueOnce({ ok: true, json: vi.fn().mockResolvedValue(timelinePayload) })
      .mockResolvedValueOnce({ ok: true, json: vi.fn().mockResolvedValue(contactPayload) })
      .mockResolvedValueOnce({ ok: true, json: vi.fn().mockResolvedValue(recommendationPayload) })
      .mockResolvedValueOnce({
        ok: true,
        json: vi.fn().mockResolvedValue({
          ...actionPlanPayload,
          target_org: null,
          summary: {
            ...actionPlanPayload.summary,
            plan_available: false,
            step_count: 0,
            blocked: true,
            block_reasons: ['no_recommendation_candidates_found'],
            recommended_channel: 'research_first',
            risk_level: 'high',
            confidence: 0,
          },
          action_plan: [],
          warnings: ['no_recommendation_candidates_found'],
        }),
      })

    renderPage()

    await waitFor(() => {
      expect(screen.getByTestId('action-plan-card-blocked')).toBeInTheDocument()
    })

    expect(screen.getByTestId('action-plan-card-blocked')).toHaveTextContent('当前数据库没有足够数据生成可执行行动计划。')
    expect(screen.queryByTestId('action-plan-card-steps')).not.toBeInTheDocument()
  })

  it('shows action plan error and does not render fake plan on api failure', async () => {
    fetchMock
      .mockResolvedValueOnce({ ok: true, json: vi.fn().mockResolvedValue(orgPayload) })
      .mockResolvedValueOnce({ ok: true, json: vi.fn().mockResolvedValue(relationsPayload) })
      .mockResolvedValueOnce({ ok: true, json: vi.fn().mockResolvedValue(timelinePayload) })
      .mockResolvedValueOnce({ ok: true, json: vi.fn().mockResolvedValue(contactPayload) })
      .mockResolvedValueOnce({ ok: true, json: vi.fn().mockResolvedValue(recommendationPayload) })
      .mockResolvedValueOnce({ ok: false, json: vi.fn() })

    renderPage()

    await waitFor(() => {
      expect(screen.getByText('行动计划加载失败。')).toBeInTheDocument()
    })

    expect(screen.queryByTestId('action-plan-card')).not.toBeInTheDocument()
    expect(screen.queryByText('Prepare transparent outreach')).not.toBeInTheDocument()
  })
})
