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

const graphPayload = {
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
  warnings: [{ code: 'unverified_filtered', message: '1 unverified edge filtered out' }],
  found: true,
  depth: 1,
  limit: 50,
  include_unverified: false,
}

const timelinePayload = { items: [] }

const renderPage = () =>
  render(
    <MemoryRouter initialEntries={['/dashboard/org/org-victory']}>
      <Routes>
        <Route path="/dashboard/org/:orgId" element={<OrgDetailPage />} />
      </Routes>
    </MemoryRouter>,
  )

describe('OrgDetailPage relationship graph wiring', () => {
  beforeEach(() => {
    fetchMock.mockReset()
  })

  afterEach(() => {
    vi.clearAllMocks()
  })

  it('renders IntelGraph from real relations api payload', async () => {
    fetchMock
      .mockResolvedValueOnce({ ok: true, json: vi.fn().mockResolvedValue(orgPayload) })
      .mockResolvedValueOnce({ ok: true, json: vi.fn().mockResolvedValue({ relations: [], graph: graphPayload }) })
      .mockResolvedValueOnce({ ok: true, json: vi.fn().mockResolvedValue(timelinePayload) })

    renderPage()

    await waitFor(() => {
      expect(screen.getByTestId('intel-graph')).toBeInTheDocument()
    })

    expect(screen.getByTestId('intel-graph')).toHaveTextContent('Victory Philippines')
    expect(screen.getByTestId('intel-graph')).toHaveTextContent('Life.Church')
    expect(screen.getByTestId('intel-graph')).toHaveTextContent('unverified_filtered')
  })

  it('shows graph error and does not render fake relations on api failure', async () => {
    fetchMock
      .mockResolvedValueOnce({ ok: true, json: vi.fn().mockResolvedValue(orgPayload) })
      .mockResolvedValueOnce({ ok: false, json: vi.fn() })
      .mockResolvedValueOnce({ ok: true, json: vi.fn().mockResolvedValue(timelinePayload) })

    renderPage()

    await waitFor(() => {
      expect(screen.getByText('关系图谱加载失败，当前不显示任何假关系。')).toBeInTheDocument()
    })

    expect(screen.queryByTestId('intel-graph')).not.toBeInTheDocument()
  })

  it('renders empty graph state when api returns empty graph', async () => {
    fetchMock
      .mockResolvedValueOnce({ ok: true, json: vi.fn().mockResolvedValue(orgPayload) })
      .mockResolvedValueOnce({
        ok: true,
        json: vi.fn().mockResolvedValue({
          relations: [],
          graph: {
            ...graphPayload,
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
          },
        }),
      })
      .mockResolvedValueOnce({ ok: true, json: vi.fn().mockResolvedValue(timelinePayload) })

    renderPage()

    await waitFor(() => {
      expect(screen.getByTestId('intel-graph-empty')).toBeInTheDocument()
    })

    expect(screen.getByTestId('intel-graph-warnings')).toHaveTextContent('no_relations')
  })
})
