import type {
  ActionPlanContactUsage,
  ActionPlanRecommendedChannel,
  ActionPlanRiskLevel,
} from './partnershipActionPlan'
import type {
  RecommendationPriority,
  RelationshipSnapshot,
  ScoreSnapshot,
} from './partnershipRecommendation'

export type EvidenceBriefDecision = 'proceed' | 'research_more' | 'manual_review' | 'do_not_contact'
export type EvidenceBriefPriority = 'high' | 'medium' | 'low'
export type EvidenceBriefRiskSeverity = 'low' | 'medium' | 'high'

export interface EvidenceBriefOrganization {
  id: string
  name: string
  source_url?: string | null
  source_name?: string | null
  updated_at?: string | null
}

export interface EvidenceBriefTargetOrganization {
  id: string
  name: string
  source_url?: string | null
  source_name?: string | null
}

export interface EvidenceBriefSummary {
  brief_available: boolean
  decision: EvidenceBriefDecision
  priority: EvidenceBriefPriority
  confidence: number
  risk_level: EvidenceBriefRiskSeverity
  evidence_count: number
  missing_evidence_count: number
  recommended_channel?: ActionPlanRecommendedChannel | null
}

export interface DecisionRationale {
  headline: string
  reason_codes: string[]
  supporting_points: string[]
  limiting_factors: string[]
}

export interface ScoreEvidence extends ScoreSnapshot {
  strengths: string[]
  weaknesses: string[]
  warnings: string[]
}

export interface RelationshipEvidence extends RelationshipSnapshot {
  warnings: string[]
}

export interface ContactEvidence {
  has_website: boolean
  has_email: boolean
  has_phone: boolean
  has_social: boolean
  contact_count: number
  verified_contact_count: number
  missing_source_count: number
  recommended_contact?: ActionPlanContactUsage | null
  warnings: string[]
}

export interface RecommendationEvidence {
  recommendation_score?: number | null
  priority?: RecommendationPriority | null
  confidence: number
  reason_codes: string[]
  risks: string[]
  warnings: string[]
}

export interface ActionPlanEvidence {
  plan_available: boolean
  blocked: boolean
  step_count: number
  recommended_channel?: ActionPlanRecommendedChannel | null
  risk_level?: ActionPlanRiskLevel | null
  first_steps: string[]
  warnings: string[]
}

export interface EvidenceSections {
  score_evidence: ScoreEvidence
  relationship_evidence: RelationshipEvidence
  contact_evidence: ContactEvidence
  recommendation_evidence: RecommendationEvidence
  action_plan_evidence: ActionPlanEvidence
}

export interface RiskRegisterItem {
  risk_code: string
  severity: EvidenceBriefRiskSeverity
  description: string
  mitigation: string
}

export interface EvidenceBriefAudit {
  generated_by: string
  no_llm: boolean
  source_modules: string[]
  missing_modules: string[]
}

export interface PartnershipEvidenceBriefPayload {
  organization: EvidenceBriefOrganization | null
  target_org: EvidenceBriefTargetOrganization | null
  summary: EvidenceBriefSummary
  decision_rationale: DecisionRationale
  evidence_sections: EvidenceSections
  risk_register: RiskRegisterItem[]
  recommended_next_actions: string[]
  do_not_proceed_if: string[]
  audit: EvidenceBriefAudit
  warnings: string[]
  found?: boolean
  intent?: string
  source?: string
  generated_by?: string
  no_llm?: boolean
}
