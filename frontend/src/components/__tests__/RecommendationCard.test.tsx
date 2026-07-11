import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { RecommendationCard } from '../RecommendationCard'
import type { PartnershipRecommendationPayload } from '../../types/partnershipRecommendation'

const buildPayload = (): PartnershipRecommendationPayload => ({
  organization: {
    id: 'org-victory',
    name: 'Victory Philippines',
    source_url: 'https://victory.org.ph/source',
    source_name: 'manual_seed',
    updated_at: '2026-07-11T09:00:00Z',
  },
  summary: {
    candidate_count: 3,
    recommended_count: 2,
    high_priority_count: 1,
    with_contact_count: 2,
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
      reason_codes: ['relationship_path_available', 'contact_available', 'same_country'],
      explanation: '推荐原因：与当前机构存在关系路径，存在可用联系方式，与当前机构位于同一国家。',
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
  warnings: ['no_recommendation_candidates_found'],
  found: true,
})

describe('RecommendationCard', () => {
  it('renders real recommendation payload details', () => {
    render(<RecommendationCard payload={buildPayload()} />)

    expect(screen.getByTestId('recommendation-card-organization')).toHaveTextContent('Victory Philippines')
    expect(screen.getByTestId('recommendation-card-summary')).toHaveTextContent('候选机构数')
    expect(screen.getByTestId('recommendation-card-list')).toHaveTextContent('Bridge Ministry')
    expect(screen.getByTestId('recommendation-card-list')).toHaveTextContent('recommendation_score: 84')
    expect(screen.getByTestId('recommendation-card-list')).toHaveTextContent('priority: high')
    expect(screen.getByTestId('recommendation-card-list')).toHaveTextContent('confidence: 0.91')
    expect(screen.getByTestId('recommendation-card-list')).toHaveTextContent('relationship_path_available')
    expect(screen.getByTestId('recommendation-card-list')).toHaveTextContent('推荐原因')
    expect(screen.getByTestId('recommendation-card-list')).toHaveTextContent('people_score: 78')
    expect(screen.getByTestId('recommendation-card-list')).toHaveTextContent('digital_score: 74')
    expect(screen.getByTestId('recommendation-card-list')).toHaveTextContent('intel_score: 81')
    expect(screen.getByTestId('recommendation-card-list')).toHaveTextContent('has_relationship_path: true')
    expect(screen.getByTestId('recommendation-card-list')).toHaveTextContent('relationship_count: 1')
    expect(screen.getByTestId('recommendation-card-list')).toHaveTextContent('strongest_relationship_type: partner')
    expect(screen.getByTestId('recommendation-card-list')).toHaveTextContent('has_email: true')
    expect(screen.getByTestId('recommendation-card-list')).toHaveTextContent('contact_count: 3')
    expect(screen.getByTestId('recommendation-card-list')).toHaveTextContent('missing_contact_source')
    expect(screen.getByTestId('recommendation-card-list')).toHaveTextContent('weak_relationship_signal')
    expect(screen.getByTestId('recommendation-card-list')).toHaveTextContent('recommended_next_action: contact')
    expect(screen.getByRole('link', { name: /target_source_url:/i })).toHaveAttribute('href', 'https://bridge.org/source')
    expect(screen.getByTestId('recommendation-card-warnings')).toHaveTextContent('no_recommendation_candidates_found')
  })

  it('shows empty state and handles null scores without fabricating data', () => {
    const payload = buildPayload()
    payload.recommendations = [
      {
        ...payload.recommendations[0],
        score_snapshot: {
          people_score: null,
          digital_score: null,
          intel_score: null,
        },
      },
    ]

    render(<RecommendationCard payload={payload} />)

    expect(screen.getByTestId('recommendation-card-list')).toHaveTextContent('people_score: N/A')
    expect(screen.getByTestId('recommendation-card-list')).toHaveTextContent('digital_score: N/A')
    expect(screen.getByTestId('recommendation-card-list')).toHaveTextContent('intel_score: N/A')
  })

  it('shows empty recommendation state and does not fabricate contact channels', () => {
    const payload = buildPayload()
    payload.recommendations = []
    payload.summary.recommended_count = 0
    payload.summary.high_priority_count = 0
    payload.summary.with_contact_count = 0
    payload.summary.with_relationship_path_count = 0

    render(<RecommendationCard payload={payload} />)

    expect(screen.getByTestId('recommendation-card-empty')).toHaveTextContent('当前数据库没有足够候选生成推荐。')
    expect(screen.queryByTestId('recommendation-card-list')).not.toBeInTheDocument()
    expect(screen.queryByText(/info@/i)).not.toBeInTheDocument()
    expect(within(screen.getByTestId('recommendation-card')).queryByText('WhatsApp')).not.toBeInTheDocument()
  })
})
