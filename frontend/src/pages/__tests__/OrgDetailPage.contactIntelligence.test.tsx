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
  contacts: [
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
      id: 'contact-phone',
      type: 'phone',
      label: 'Public Phone',
      value: '+63 2 1234 5678',
      normalized_value: '+63 2 1234 5678',
      source_url: 'https://org.example.com/source',
      source_name: 'manual_seed',
      confidence: null,
      verification_status: 'unverified',
      is_verified: false,
      usage: 'research',
      warnings: [],
    },
    {
      id: 'contact-facebook',
      type: 'social_profile',
      platform: 'facebook',
      label: 'Facebook',
      value: 'https://facebook.com/victoryph',
      normalized_value: 'https://facebook.com/victoryph',
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
    contact_count: 4,
    email_count: 1,
    phone_count: 1,
    social_count: 1,
    website_count: 1,
    verified_count: 0,
    missing_source_count: 1,
    outreach_candidate_count: 0,
  },
  warnings: ['field_level_source_missing'],
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

describe('OrgDetailPage contact intelligence wiring', () => {
  beforeEach(() => {
    fetchMock.mockReset()
  })

  afterEach(() => {
    vi.clearAllMocks()
  })

  it('renders ContactCard from real contacts api payload', async () => {
    fetchMock
      .mockResolvedValueOnce({ ok: true, json: vi.fn().mockResolvedValue(orgPayload) })
      .mockResolvedValueOnce({ ok: true, json: vi.fn().mockResolvedValue(relationsPayload) })
      .mockResolvedValueOnce({ ok: true, json: vi.fn().mockResolvedValue(timelinePayload) })
      .mockResolvedValueOnce({ ok: true, json: vi.fn().mockResolvedValue(contactPayload) })

    renderPage()

    await waitFor(() => {
      expect(screen.getByTestId('contact-card')).toBeInTheDocument()
    })

    expect(screen.getByTestId('contact-card')).toHaveTextContent('Victory Philippines')
    expect(screen.getByTestId('contact-card')).toHaveTextContent('https://victory.org.ph')
    expect(screen.getByTestId('contact-card')).toHaveTextContent('info@victory.org.ph')
    expect(screen.getByTestId('contact-card')).toHaveTextContent('+63 2 1234 5678')
    expect(screen.getByTestId('contact-card')).toHaveTextContent('https://facebook.com/victoryph')
    expect(screen.getByTestId('contact-card-warnings')).toHaveTextContent('字段级来源缺失')
  })

  it('shows contact error and does not render fake contacts on api failure', async () => {
    fetchMock
      .mockResolvedValueOnce({ ok: true, json: vi.fn().mockResolvedValue(orgPayload) })
      .mockResolvedValueOnce({ ok: true, json: vi.fn().mockResolvedValue(relationsPayload) })
      .mockResolvedValueOnce({ ok: true, json: vi.fn().mockResolvedValue(timelinePayload) })
      .mockResolvedValueOnce({ ok: false, json: vi.fn() })

    renderPage()

    await waitFor(() => {
      expect(screen.getByText('联系方式加载失败，当前不显示任何假联系方式。')).toBeInTheDocument()
    })

    expect(screen.queryByTestId('contact-card')).not.toBeInTheDocument()
    expect(screen.queryByText('info@victory.org.ph')).not.toBeInTheDocument()
  })

  it('renders empty contact state when api returns empty contacts', async () => {
    fetchMock
      .mockResolvedValueOnce({ ok: true, json: vi.fn().mockResolvedValue(orgPayload) })
      .mockResolvedValueOnce({ ok: true, json: vi.fn().mockResolvedValue(relationsPayload) })
      .mockResolvedValueOnce({ ok: true, json: vi.fn().mockResolvedValue(timelinePayload) })
      .mockResolvedValueOnce({
        ok: true,
        json: vi.fn().mockResolvedValue({
          ...contactPayload,
          contacts: [],
          summary: {
            ...contactPayload.summary,
            contact_count: 0,
            email_count: 0,
            phone_count: 0,
            social_count: 0,
            website_count: 0,
          },
          warnings: ['contact_missing'],
        }),
      })

    renderPage()

    await waitFor(() => {
      expect(screen.getByTestId('contact-card-empty')).toBeInTheDocument()
    })

    expect(screen.getByTestId('contact-card-empty')).toHaveTextContent('当前数据库没有记录这个机构的公开联系方式。')
  })
})
