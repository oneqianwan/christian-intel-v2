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
  action_plan: [],
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

const evidenceBriefPayload = {
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

const renderPage = () =>
  render(
    <MemoryRouter initialEntries={['/dashboard/org/org-victory']}>
      <Routes>
        <Route path="/dashboard/org/:orgId" element={<OrgDetailPage />} />
      </Routes>
    </MemoryRouter>,
  )

describe('OrgDetailPage evidence brief wiring', () => {
  beforeEach(() => {
    fetchMock.mockReset()
  })

  afterEach(() => {
    vi.clearAllMocks()
  })

  it('renders EvidenceBriefCard from real evidence-brief api payload', async () => {
    fetchMock
      .mockResolvedValueOnce({ ok: true, json: vi.fn().mockResolvedValue(orgPayload) })
      .mockResolvedValueOnce({ ok: true, json: vi.fn().mockResolvedValue(relationsPayload) })
      .mockResolvedValueOnce({ ok: true, json: vi.fn().mockResolvedValue(timelinePayload) })
      .mockResolvedValueOnce({ ok: true, json: vi.fn().mockResolvedValue(contactPayload) })
      .mockResolvedValueOnce({ ok: true, json: vi.fn().mockResolvedValue(recommendationPayload) })
      .mockResolvedValueOnce({ ok: true, json: vi.fn().mockResolvedValue(actionPlanPayload) })
      .mockResolvedValueOnce({ ok: true, json: vi.fn().mockResolvedValue(evidenceBriefPayload) })

    renderPage()

    await waitFor(() => {
      expect(screen.getByTestId('evidence-brief-card')).toBeInTheDocument()
    })

    expect(screen.getByTestId('evidence-brief-card')).toHaveTextContent('Victory Philippines')
    expect(screen.getByTestId('evidence-brief-card')).toHaveTextContent('Bridge Ministry')
    expect(screen.getByTestId('evidence-brief-card')).toHaveTextContent('manual_review')
    expect(screen.getByTestId('evidence-brief-card')).toHaveTextContent('high')
    expect(screen.getByTestId('evidence-brief-card')).toHaveTextContent('0.84')
    expect(screen.getByTestId('evidence-brief-card')).toHaveTextContent('Recommendation is promising but still needs manual validation.')
    expect(screen.getByTestId('evidence-brief-card')).toHaveTextContent('people_score: 78')
    expect(screen.getByTestId('evidence-brief-card')).toHaveTextContent('risk_code: contact_unverified')
    expect(screen.getByTestId('evidence-brief-card')).toHaveTextContent('no_llm: true')
    expect(screen.getByTestId('evidence-brief-card')).toHaveTextContent('contact_unverified')
  })

  it('shows safe empty state from api payload when brief_available is false', async () => {
    fetchMock
      .mockResolvedValueOnce({ ok: true, json: vi.fn().mockResolvedValue(orgPayload) })
      .mockResolvedValueOnce({ ok: true, json: vi.fn().mockResolvedValue(relationsPayload) })
      .mockResolvedValueOnce({ ok: true, json: vi.fn().mockResolvedValue(timelinePayload) })
      .mockResolvedValueOnce({ ok: true, json: vi.fn().mockResolvedValue(contactPayload) })
      .mockResolvedValueOnce({ ok: true, json: vi.fn().mockResolvedValue(recommendationPayload) })
      .mockResolvedValueOnce({ ok: true, json: vi.fn().mockResolvedValue(actionPlanPayload) })
      .mockResolvedValueOnce({
        ok: true,
        json: vi.fn().mockResolvedValue({
          ...evidenceBriefPayload,
          target_org: null,
          summary: {
            ...evidenceBriefPayload.summary,
            brief_available: false,
            confidence: 0,
            evidence_count: 0,
            missing_evidence_count: 3,
            recommended_channel: 'research_first',
          },
          warnings: ['no_recommendation_candidates_found'],
        }),
      })

    renderPage()

    await waitFor(() => {
      expect(screen.getByTestId('evidence-brief-card-empty')).toBeInTheDocument()
    })

    expect(screen.getByTestId('evidence-brief-card-empty')).toHaveTextContent('当前数据库没有足够证据生成合作证据简报。')
  })

  it('shows evidence brief error and does not render fake brief on api failure', async () => {
    fetchMock
      .mockResolvedValueOnce({ ok: true, json: vi.fn().mockResolvedValue(orgPayload) })
      .mockResolvedValueOnce({ ok: true, json: vi.fn().mockResolvedValue(relationsPayload) })
      .mockResolvedValueOnce({ ok: true, json: vi.fn().mockResolvedValue(timelinePayload) })
      .mockResolvedValueOnce({ ok: true, json: vi.fn().mockResolvedValue(contactPayload) })
      .mockResolvedValueOnce({ ok: true, json: vi.fn().mockResolvedValue(recommendationPayload) })
      .mockResolvedValueOnce({ ok: true, json: vi.fn().mockResolvedValue(actionPlanPayload) })
      .mockResolvedValueOnce({ ok: false, json: vi.fn() })

    renderPage()

    await waitFor(() => {
      expect(screen.getByText('证据简报加载失败。')).toBeInTheDocument()
    })

    expect(screen.queryByTestId('evidence-brief-card')).not.toBeInTheDocument()
    expect(screen.queryByText('Recommendation is promising but still needs manual validation.')).not.toBeInTheDocument()
  })
})
