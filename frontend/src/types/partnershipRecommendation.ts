export type RecommendationPriority = 'high' | 'medium' | 'low'
export type RecommendationNextAction = 'research_more' | 'contact' | 'review_manually' | 'skip'

export interface RecommendationOrganization {
  id: string
  name: string
  source_url?: string | null
  source_name?: string | null
  updated_at?: string | null
}

export interface RecommendationTargetOrganization {
  id: string
  name: string
  country?: string | null
  city?: string | null
  denomination?: string | null
  source_url?: string | null
  source_name?: string | null
}

export interface RecommendationSummary {
  candidate_count: number
  recommended_count: number
  high_priority_count: number
  with_contact_count: number
  with_relationship_path_count: number
  warning_count: number
}

export interface ScoreSnapshot {
  people_score?: number | null
  digital_score?: number | null
  intel_score?: number | null
}

export interface RelationshipSnapshot {
  has_relationship_path: boolean
  relationship_count: number
  strongest_relationship_type?: string | null
  relationship_path_summary: string[]
}

export interface ContactSnapshot {
  has_website: boolean
  has_email: boolean
  has_phone: boolean
  has_social: boolean
  contact_count: number
  verified_contact_count: number
  missing_source_count: number
}

export interface PartnershipRecommendation {
  target_org: RecommendationTargetOrganization
  recommendation_score: number
  priority: RecommendationPriority
  confidence: number
  reason_codes: string[]
  explanation: string
  score_snapshot: ScoreSnapshot
  relationship_snapshot: RelationshipSnapshot
  contact_snapshot: ContactSnapshot
  risks: string[]
  warnings: string[]
  recommended_next_action: RecommendationNextAction
}

export interface PartnershipRecommendationPayload {
  organization: RecommendationOrganization | null
  summary: RecommendationSummary
  recommendations: PartnershipRecommendation[]
  warnings: string[]
  found?: boolean
}
