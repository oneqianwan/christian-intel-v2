import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { EvidenceBriefCard } from '../EvidenceBriefCard'
import type { PartnershipEvidenceBriefPayload } from '../../types/partnershipEvidenceBrief'

const buildPayload = (): PartnershipEvidenceBriefPayload => ({
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
    supporting_points: ['Public contact channel exists', 'Relationship signal is available'],
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
  recommended_next_actions: ['Review relationship path', 'Prepare transparent outreach'],
  do_not_proceed_if: ['No approved public contact channel remains'],
  audit: {
    generated_by: 'rule_based_evidence_brief',
    no_llm: true,
    source_modules: ['partnership_recommender', 'partnership_action_planner'],
    missing_modules: ['none'],
  },
  warnings: ['contact_unverified', 'target_not_in_recommendations'],
  found: true,
  no_llm: true,
})

describe('EvidenceBriefCard', () => {
  it('renders real evidence brief payload details', () => {
    render(<EvidenceBriefCard payload={buildPayload()} />)

    expect(screen.getByTestId('evidence-brief-card-organization')).toHaveTextContent('Victory Philippines')
    expect(screen.getByTestId('evidence-brief-card-organization')).toHaveTextContent('Bridge Ministry')
    expect(screen.getByTestId('evidence-brief-card-summary')).toHaveTextContent('decision')
    expect(screen.getByTestId('evidence-brief-card-summary')).toHaveTextContent('manual_review')
    expect(screen.getByTestId('evidence-brief-card-summary')).toHaveTextContent('priority')
    expect(screen.getByTestId('evidence-brief-card-summary')).toHaveTextContent('high')
    expect(screen.getByTestId('evidence-brief-card-summary')).toHaveTextContent('confidence')
    expect(screen.getByTestId('evidence-brief-card-summary')).toHaveTextContent('risk_level')
    expect(screen.getByTestId('evidence-brief-card-rationale')).toHaveTextContent('Recommendation is promising but still needs manual validation.')
    expect(screen.getByTestId('evidence-brief-card-rationale')).toHaveTextContent('relationship_path_available')
    expect(screen.getByTestId('evidence-brief-card-evidence')).toHaveTextContent('people_score: 78')
    expect(screen.getByTestId('evidence-brief-card-evidence')).toHaveTextContent('partner via unit_test_evidence')
    expect(screen.getByTestId('evidence-brief-card-evidence')).toHaveTextContent('has_email: true')
    expect(screen.getByTestId('evidence-brief-card-evidence')).toHaveTextContent('recommended_contact.value: connect@bridge.org')
    expect(screen.getByTestId('evidence-brief-card-evidence')).toHaveTextContent('recommendation_score: 84')
    expect(screen.getByTestId('evidence-brief-card-evidence')).toHaveTextContent('plan_available: true')
    expect(screen.getByTestId('evidence-brief-card-risk-register')).toHaveTextContent('risk_code: contact_unverified')
    expect(screen.getByTestId('evidence-brief-card-recommended-actions')).toHaveTextContent('Review relationship path')
    expect(screen.getByTestId('evidence-brief-card-do-not-proceed')).toHaveTextContent('No approved public contact channel remains')
    expect(screen.getByTestId('evidence-brief-card-audit')).toHaveTextContent('no_llm: true')
    expect(screen.getByTestId('evidence-brief-card-audit')).toHaveTextContent('partnership_recommender')
    expect(screen.getByTestId('evidence-brief-card-warnings')).toHaveTextContent('contact_unverified')
  })

  it('shows safe empty state when brief_available is false', () => {
    const payload = buildPayload()
    payload.summary.brief_available = false
    payload.summary.confidence = 0
    payload.target_org = null
    payload.risk_register = []
    payload.recommended_next_actions = []
    payload.do_not_proceed_if = []
    payload.warnings = ['no_recommendation_candidates_found']

    render(<EvidenceBriefCard payload={payload} />)

    expect(screen.getByTestId('evidence-brief-card-empty')).toHaveTextContent('当前数据库没有足够证据生成合作证据简报。')
    expect(screen.getByTestId('evidence-brief-card-warnings')).toHaveTextContent('no_recommendation_candidates_found')
  })

  it('handles null scores and missing contact or relationship details without fabricating data', () => {
    const payload = buildPayload()
    payload.evidence_sections.score_evidence.people_score = null
    payload.evidence_sections.score_evidence.digital_score = null
    payload.evidence_sections.score_evidence.intel_score = null
    payload.evidence_sections.contact_evidence.has_email = false
    payload.evidence_sections.contact_evidence.recommended_contact = null
    payload.evidence_sections.relationship_evidence.has_relationship_path = false
    payload.evidence_sections.relationship_evidence.relationship_path_summary = []

    render(<EvidenceBriefCard payload={payload} />)

    const evidenceSection = screen.getByTestId('evidence-brief-card-evidence')
    expect(evidenceSection).toHaveTextContent('people_score: N/A')
    expect(evidenceSection).toHaveTextContent('digital_score: N/A')
    expect(evidenceSection).toHaveTextContent('intel_score: N/A')
    expect(evidenceSection).toHaveTextContent('has_email: false')
    expect(evidenceSection).toHaveTextContent('recommended_contact: none')
    expect(evidenceSection).toHaveTextContent('has_relationship_path: false')
    expect(within(screen.getByTestId('evidence-brief-card')).queryByText(/whatsapp/i)).not.toBeInTheDocument()
    expect(within(screen.getByTestId('evidence-brief-card')).queryByText(/line id/i)).not.toBeInTheDocument()
  })
})
