export interface RelationshipGraphWarning {
  code: string
  message: string
  edge_id?: string | null
  org_id?: string | null
  organization_name?: string | null
}

export interface RelationshipGraphCenterNode {
  id: string
  graph_id: string
  type: string
  name: string
  region?: string | null
  denomination?: string | null
  people_score?: number | null
  digital_score?: number | null
  intel_score?: number | null
}

export interface RelationshipGraphNode {
  id: string
  entity_id: string
  type: string
  label: string
  name: string
  region?: string | null
  denomination?: string | null
  people_score?: number | null
  digital_score?: number | null
  intel_score?: number | null
  confidence: number
  source_count: number
}

export interface RelationshipGraphEdge {
  id: string
  source: string
  target: string
  relation_type: string
  direction: string
  strength?: number | null
  confidence: number
  is_verified: boolean
  evidence_url?: string | null
  evidence_source?: string | null
  evidence_date?: string | null
  reason: string
  missing_evidence?: boolean
}

export interface RelationshipGraphSummary {
  node_count: number
  edge_count: number
  verified_edge_count: number
  unverified_edge_count: number
  missing_evidence_count: number
}

export interface RelationshipGraphPayload {
  center: RelationshipGraphCenterNode | null
  nodes: RelationshipGraphNode[]
  edges: RelationshipGraphEdge[]
  summary: RelationshipGraphSummary
  warnings: RelationshipGraphWarning[]
  found?: boolean
  depth?: number
  limit?: number
  include_unverified?: boolean
}
