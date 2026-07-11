export type ContactPointType = 'website' | 'email' | 'phone' | 'social_profile'

export interface ContactOrganization {
  id: string
  name: string
  source_url?: string | null
  source_name?: string | null
  organization_confidence?: number | null
  updated_at?: string | null
}

export interface ContactPoint {
  id: string
  type: ContactPointType
  platform?: string | null
  label: string
  value: string
  normalized_value: string
  source_url?: string | null
  source_name?: string | null
  confidence?: number | null
  verification_status: string
  is_verified: boolean
  usage?: string | null
  warnings: string[]
}

export interface ContactSummary {
  contact_count: number
  email_count: number
  phone_count: number
  social_count: number
  website_count: number
  verified_count: number
  missing_source_count: number
  outreach_candidate_count: number
}

export interface ContactPayload {
  organization: ContactOrganization | null
  contacts: ContactPoint[]
  summary: ContactSummary
  warnings: string[]
  found?: boolean
}
