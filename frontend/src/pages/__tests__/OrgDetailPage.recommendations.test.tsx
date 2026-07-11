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

const renderPage = () =>
  render(
    <MemoryRouter initialEntries={['/dashboard/org/org-victory']}>
      <Routes>
        <Route path="/dashboard/org/:orgId" element={<OrgDetailPage />} />
      </Routes>
    </MemoryRouter>,
  )

describe('OrgDetailPage recommendation wiring', () => {
  beforeEach(() => {
    fetchMock.mockReset()
  })

  afterEach(() => {
    vi.clearAllMocks()
  })

  it('renders RecommendationCard from real recommendations api payload', async () => {
    fetchMock
      .mockResolvedValueOnce({ ok: true, json: vi.fn().mockResolvedValue(orgPayload) })
      .mockResolvedValueOnce({ ok: true, json: vi.fn().mockResolvedValue(relationsPayload) })
      .mockResolvedValueOnce({ ok: true, json: vi.fn().mockResolvedValue(timelinePayload) })
      .mockResolvedValueOnce({ ok: true, json: vi.fn().mockResolvedValue(contactPayload) })
      .mockResolvedValueOnce({ ok: true, json: vi.fn().mockResolvedValue(recommendationPayload) })

    renderPage()

    await waitFor(() => {
      expect(screen.getByTestId('recommendation-card')).toBeInTheDocument()
    })

    expect(screen.getByTestId('recommendation-card')).toHaveTextContent('Victory Philippines')
    expect(screen.getByTestId('recommendation-card')).toHaveTextContent('Bridge Ministry')
    expect(screen.getByTestId('recommendation-card')).toHaveTextContent('recommendation_score: 84')
    expect(screen.getByTestId('recommendation-card')).toHaveTextContent('priority: high')
    expect(screen.getByTestId('recommendation-card')).toHaveTextContent('relationship_path_available')
    expect(screen.getByTestId('recommendation-card')).toHaveTextContent('people_score: 78')
    expect(screen.getByTestId('recommendation-card')).toHaveTextContent('has_relationship_path: true')
    expect(screen.getByTestId('recommendation-card')).toHaveTextContent('has_email: true')
    expect(screen.getByTestId('recommendation-card')).toHaveTextContent('missing_contact_source')
    expect(screen.getByTestId('recommendation-card')).toHaveTextContent('weak_relationship_signal')
  })

  it('shows recommendation error and does not render fake recommendations on api failure', async () => {
    fetchMock
      .mockResolvedValueOnce({ ok: true, json: vi.fn().mockResolvedValue(orgPayload) })
      .mockResolvedValueOnce({ ok: true, json: vi.fn().mockResolvedValue(relationsPayload) })
      .mockResolvedValueOnce({ ok: true, json: vi.fn().mockResolvedValue(timelinePayload) })
      .mockResolvedValueOnce({ ok: true, json: vi.fn().mockResolvedValue(contactPayload) })
      .mockResolvedValueOnce({ ok: false, json: vi.fn() })

    renderPage()

    await waitFor(() => {
      expect(screen.getByText('推荐数据加载失败。')).toBeInTheDocument()
    })

    expect(screen.queryByTestId('recommendation-card')).not.toBeInTheDocument()
    expect(screen.queryByText('Bridge Ministry')).not.toBeInTheDocument()
  })

  it('renders empty recommendation state when api returns no recommendations', async () => {
    fetchMock
      .mockResolvedValueOnce({ ok: true, json: vi.fn().mockResolvedValue(orgPayload) })
      .mockResolvedValueOnce({ ok: true, json: vi.fn().mockResolvedValue(relationsPayload) })
      .mockResolvedValueOnce({ ok: true, json: vi.fn().mockResolvedValue(timelinePayload) })
      .mockResolvedValueOnce({ ok: true, json: vi.fn().mockResolvedValue(contactPayload) })
      .mockResolvedValueOnce({
        ok: true,
        json: vi.fn().mockResolvedValue({
          ...recommendationPayload,
          recommendations: [],
          summary: {
            ...recommendationPayload.summary,
            recommended_count: 0,
            high_priority_count: 0,
            with_contact_count: 0,
            with_relationship_path_count: 0,
          },
        }),
      })

    renderPage()

    await waitFor(() => {
      expect(screen.getByTestId('recommendation-card-empty')).toBeInTheDocument()
    })

    expect(screen.getByTestId('recommendation-card-empty')).toHaveTextContent('当前数据库没有足够候选生成推荐。')
  })
})
