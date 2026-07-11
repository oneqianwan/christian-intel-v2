import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ActionPlanCard } from '../ActionPlanCard'
import type { PartnershipActionPlanPayload } from '../../types/partnershipActionPlan'

const buildPayload = (): PartnershipActionPlanPayload => ({
  organization: {
    id: 'org-harbor',
    name: 'Harbor Church',
    source_url: 'https://harbor.org/source',
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
    step_count: 3,
    blocked: false,
    block_reasons: [],
    recommended_channel: 'email',
    risk_level: 'medium',
    confidence: 0.86,
  },
  action_plan: [
    {
      step_number: 1,
      action_type: 'review_relationship',
      title: 'Review relationship path',
      description: 'Review the existing relationship path before direct outreach.',
      channel: 'internal_review',
      depends_on: [],
      required_evidence: ['relationship_path_available'],
      uses_contact: {
        type: 'none',
        value: null,
        source_url: null,
        is_verified: false,
      },
      risk_flags: ['weak_relationship_signal'],
      success_criteria: ['Validated relationship path relevance'],
      do_not_proceed_if: ['Relationship evidence cannot be verified'],
      priority: 'high',
    },
    {
      step_number: 2,
      action_type: 'prepare_outreach',
      title: 'Prepare transparent outreach',
      description: 'Prepare a transparent outreach note based on public evidence.',
      channel: 'email',
      depends_on: [1],
      required_evidence: ['contact_available', 'public_channel_confirmed'],
      uses_contact: {
        type: 'email',
        value: 'connect@bridge.org',
        source_url: 'https://bridge.org/source',
        is_verified: false,
      },
      risk_flags: ['contact_unverified', 'contact_source_missing'],
      success_criteria: ['Draft reviewed internally'],
      do_not_proceed_if: ['No approved public contact channel remains'],
      priority: 'high',
    },
    {
      step_number: 3,
      action_type: 'contact',
      title: 'Send outreach',
      description: 'Send a transparent introductory message through the recorded public email.',
      channel: 'email',
      depends_on: [2],
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
  warnings: ['contact_source_missing', 'contact_unverified'],
  found: true,
  no_llm: true,
})

describe('ActionPlanCard', () => {
  it('renders real action plan payload details', () => {
    render(<ActionPlanCard payload={buildPayload()} />)

    expect(screen.getByTestId('action-plan-card-organization')).toHaveTextContent('Harbor Church')
    expect(screen.getByTestId('action-plan-card-organization')).toHaveTextContent('Bridge Ministry')
    expect(screen.getByTestId('action-plan-card-summary')).toHaveTextContent('recommended_channel')
    expect(screen.getByTestId('action-plan-card-summary')).toHaveTextContent('email')
    expect(screen.getByTestId('action-plan-card-summary')).toHaveTextContent('risk_level')
    expect(screen.getByTestId('action-plan-card-summary')).toHaveTextContent('medium')
    expect(screen.getByTestId('action-plan-card-summary')).toHaveTextContent('confidence')
    expect(screen.getByTestId('action-plan-card-steps')).toHaveTextContent('Review relationship path')
    expect(screen.getByTestId('action-plan-card-steps')).toHaveTextContent('step_number: 1')
    expect(screen.getByTestId('action-plan-card-steps')).toHaveTextContent('action_type: review_relationship')
    expect(screen.getByTestId('action-plan-card-steps')).toHaveTextContent('channel: email')
    expect(screen.getByTestId('action-plan-card-steps')).toHaveTextContent('relationship_path_available')
    expect(screen.getByTestId('action-plan-card-steps')).toHaveTextContent('connect@bridge.org')
    expect(screen.getByTestId('action-plan-card-steps')).toHaveTextContent('contact_unverified')
    expect(screen.getByTestId('action-plan-card-steps')).toHaveTextContent('Validated relationship path relevance')
    expect(screen.getByTestId('action-plan-card-steps')).toHaveTextContent('Manual review blocks outreach')
    expect(screen.getByTestId('action-plan-card-evidence')).toHaveTextContent('people_score: 78')
    expect(screen.getByTestId('action-plan-card-evidence')).toHaveTextContent('has_relationship_path: true')
    expect(screen.getByTestId('action-plan-card-evidence')).toHaveTextContent('has_email: true')
    expect(screen.getByTestId('action-plan-card-evidence')).toHaveTextContent('recommendation_score: 84')
    expect(screen.getByTestId('action-plan-card-warnings')).toHaveTextContent('contact_source_missing')
  })

  it('shows blocked state without fabricating steps', () => {
    const payload = buildPayload()
    payload.summary.plan_available = false
    payload.summary.blocked = true
    payload.summary.step_count = 0
    payload.summary.block_reasons = ['no_recommendation_candidates_found']
    payload.action_plan = []
    payload.warnings = ['no_recommendation_candidates_found']

    render(<ActionPlanCard payload={payload} />)

    expect(screen.getByTestId('action-plan-card-blocked')).toHaveTextContent('当前数据库没有足够数据生成可执行行动计划。')
    expect(screen.queryByTestId('action-plan-card-steps')).not.toBeInTheDocument()
    expect(screen.getByTestId('action-plan-card-block-reasons')).toHaveTextContent('no_recommendation_candidates_found')
  })

  it('handles empty action plan and uses_contact type none without fabricating contact data', () => {
    const payload = buildPayload()
    payload.action_plan = [
      {
        ...payload.action_plan[0],
        uses_contact: {
          type: 'none',
          value: null,
          source_url: null,
          is_verified: false,
        },
      },
    ]
    payload.summary.step_count = 1

    render(<ActionPlanCard payload={payload} />)

    expect(screen.getByTestId('action-plan-card-steps')).toHaveTextContent('type: none')
    expect(screen.getByTestId('action-plan-card-steps')).toHaveTextContent('value: none')
    expect(within(screen.getByTestId('action-plan-card')).queryByText(/whatsapp/i)).not.toBeInTheDocument()
    expect(within(screen.getByTestId('action-plan-card')).queryByText(/info@/i)).not.toBeInTheDocument()
  })
})
