import type {
  ContactSnapshot,
  RecommendationNextAction,
  RecommendationPriority,
  RelationshipSnapshot,
  ScoreSnapshot,
} from './partnershipRecommendation'

export type ActionPlanRecommendedChannel =
  | 'email'
  | 'website'
  | 'phone'
  | 'social'
  | 'research_first'
  | 'manual_review'

export type ActionPlanRiskLevel = 'low' | 'medium' | 'high'
export type ActionPlanStepType =
  | 'research'
  | 'verify_contact'
  | 'review_relationship'
  | 'prepare_outreach'
  | 'contact'
  | 'monitor'
  | 'skip'

export type ActionPlanStepChannel = 'email' | 'website' | 'phone' | 'social' | 'internal_review' | 'none'
export type ActionPlanContactType = 'email' | 'phone' | 'website' | 'social_profile' | 'none'
export type ActionPlanStepPriority = 'high' | 'medium' | 'low'

export interface ActionPlanOrganization {
  id: string
  name: string
  source_url?: string | null
  source_name?: string | null
  updated_at?: string | null
}

export interface ActionPlanTargetOrganization {
  id: string
  name: string
  source_url?: string | null
  source_name?: string | null
}

export interface ActionPlanSummary {
  plan_available: boolean
  step_count: number
  blocked: boolean
  block_reasons: string[]
  recommended_channel: ActionPlanRecommendedChannel
  risk_level: ActionPlanRiskLevel
  confidence: number
}

export interface ActionPlanContactUsage {
  type: ActionPlanContactType
  value?: string | null
  source_url?: string | null
  is_verified: boolean
}

export interface ActionPlanStep {
  step_number: number
  action_type: ActionPlanStepType
  title: string
  description: string
  channel: ActionPlanStepChannel
  depends_on: number[]
  required_evidence: string[]
  uses_contact: ActionPlanContactUsage
  risk_flags: string[]
  success_criteria: string[]
  do_not_proceed_if: string[]
  priority: ActionPlanStepPriority
}

export interface ActionPlanRecommendationSnapshot {
  target_org_id?: string | null
  target_org_name?: string | null
  recommendation_score: number
  priority: RecommendationPriority
  confidence: number
  reason_codes: string[]
  risks: string[]
  warnings: string[]
  recommended_next_action: RecommendationNextAction
}

export interface ActionPlanEvidence {
  score_snapshot: ScoreSnapshot
  relationship_snapshot: RelationshipSnapshot
  contact_snapshot: ContactSnapshot
  recommendation_snapshot: ActionPlanRecommendationSnapshot
}

export interface PartnershipActionPlanPayload {
  organization: ActionPlanOrganization | null
  target_org: ActionPlanTargetOrganization | null
  summary: ActionPlanSummary
  action_plan: ActionPlanStep[]
  evidence: ActionPlanEvidence
  warnings: string[]
  found?: boolean
  intent?: string
  source?: string
  generated_by?: string
  no_llm?: boolean
}
