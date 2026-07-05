export type WatchEntityType = 'organization' | 'knowledge_entity'
export type WatchTargetStatus = 'active' | 'paused' | 'disabled'
export type WatchFrequency = 'daily' | 'weekly' | 'manual'
export type WatchRunStatus = 'pending' | 'running' | 'success' | 'failed' | 'skipped'
export type WatchSignalType =
  | 'new_intelligence'
  | 'website_change'
  | 'new_news'
  | 'new_video'
  | 'leadership_change'
  | 'contact_change'
  | 'score_change'
  | 'relation_change'
export type WatchSeverity = 'low' | 'medium' | 'high' | 'critical'
export type AlertStatus = 'unread' | 'read' | 'dismissed'

export type JsonValue =
  | string
  | number
  | boolean
  | null
  | JsonValue[]
  | { [key: string]: JsonValue }

export interface PaginatedResponse<T> {
  items: T[]
  page: number
  page_size: number
  total: number
}

export interface WatchTarget {
  id: string
  entity_id: string
  entity_type: WatchEntityType
  status: WatchTargetStatus
  frequency: WatchFrequency
  last_checked_at: string | null
  next_check_at: string | null
  last_success_at: string | null
  consecutive_failures: number
  created_at: string
  updated_at: string
}

export interface CreateWatchTargetRequest {
  entity_id: string
  entity_type: WatchEntityType
  frequency?: WatchFrequency
}

export interface UpdateWatchTargetRequest {
  status?: WatchTargetStatus
  frequency?: WatchFrequency
}

export interface WatchRunResult {
  run_id: string
  watch_target_id: string
  status: WatchRunStatus
  items_found: number
  signals_created: number
  started_at: string | null
  finished_at: string | null
}

export interface WatchSignal {
  id: string
  watch_target_id: string
  entity_id: string
  signal_type: WatchSignalType
  title: string
  summary: string | null
  severity: WatchSeverity
  evidence_id: string | null
  source_url: string | null
  old_value_json: JsonValue
  new_value_json: JsonValue
  detected_at: string
  created_at: string
  metadata_json: JsonValue
}

export interface WatchAlert {
  id: string
  watch_target_id: string
  signal_id: string
  title: string
  summary: string | null
  severity: WatchSeverity
  status: AlertStatus
  source_url: string | null
  created_at: string
  read_at: string | null
  dismissed_at: string | null
}

export interface WatchTargetListParams {
  status?: WatchTargetStatus
  entity_type?: WatchEntityType
  page?: number
  page_size?: number
}

export interface WatchSignalListParams {
  signal_type?: WatchSignalType
  severity?: WatchSeverity
  page?: number
  page_size?: number
}

export interface WatchAlertListParams {
  status?: AlertStatus
  severity?: WatchSeverity
  watch_target_id?: string
  page?: number
  page_size?: number
}

export interface AlertUnreadCountResponse {
  unread_count: number
}

export interface AlertReadAllResponse {
  updated_count: number
}

export interface ApiErrorPayload {
  error_code?: string
  message?: string
  detail?: string | Record<string, unknown> | unknown[]
}

export class WatchAlertApiError extends Error {
  status: number
  code: string
  details?: unknown
  userMessage: string

  constructor(params: { status: number; code: string; message: string; userMessage: string; details?: unknown }) {
    super(params.message)
    this.name = 'WatchAlertApiError'
    this.status = params.status
    this.code = params.code
    this.details = params.details
    this.userMessage = params.userMessage
  }
}
