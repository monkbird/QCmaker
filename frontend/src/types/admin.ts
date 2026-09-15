export type AdminFreshness = 'fresh' | 'stale' | 'unknown' | 'degraded'
export type AdminHealthStatus = 'healthy' | 'degraded' | 'unavailable' | 'unknown'
export type AdminLevel = 'info' | 'warning' | 'error'
export type AdminCategory = 'usage' | 'maintenance' | 'discussion' | 'ppt' | 'rag' | 'config' | 'security' | 'system'
export type AdminOperationState = 'pending' | 'running' | 'succeeded' | 'partial' | 'failed' | 'cancelled'

export interface AdminUser {
  user_id: string
  username: string
  is_active: boolean
}

export interface AdminMeResponse {
  user: AdminUser
  csrf_token: string
  server_time: string
  idle_expires_at: string
  absolute_expires_at: string
}

export interface AdminApiErrorShape {
  code: string
  message: string
  request_id?: string
  details?: Record<string, unknown>
}

export interface AdminPage<T> {
  items: T[]
  total: number
  limit: number
  offset: number
  next_cursor?: string | null
  total_is_estimate?: boolean
}

export interface FreshnessMeta {
  calculated_at?: string
  data_source?: string
  freshness?: AdminFreshness
}

export interface HealthCheck extends FreshnessMeta {
  key?: string
  name?: string
  status: AdminHealthStatus | string
  message?: string
  latency_ms?: number | null
}

export interface HealthView extends FreshnessMeta {
  status: AdminHealthStatus | string
  checks: HealthCheck[]
  message?: string
}

export interface DashboardMetric extends FreshnessMeta {
  revision?: number
  cost_usd?: string
  requests?: number
  input_tokens?: number
  output_tokens?: number
  embedding_tokens?: number
  count?: number
  active?: number
  running?: number
  needs_recovery?: number
  ready?: number
  missing?: number
  expired?: number
  used_bytes?: number
  free_bytes?: number
  limit_usd?: string
  known_cost_usd?: string
  reserved_usd?: string
  remaining_usd?: string
  usage_unknown_usd?: string
  provider_overrun_usd?: string
  progress_percent?: number | null
}

export interface TrendPoint {
  bucket: string
  cost_usd?: string
  tokens?: number
  requests?: number
  input_tokens?: number
  output_tokens?: number
  embedding_tokens?: number
}

export interface ActivityEvent {
  id: string
  level: AdminLevel | string
  category: AdminCategory | string
  event_key?: string
  message: string
  operation_id?: string | null
  context?: Record<string, unknown>
  created_at: string
}

export interface DashboardOverview {
  health: HealthView
  budget: DashboardMetric
  usage_today: DashboardMetric
  sessions: DashboardMetric
  files: DashboardMetric
  storage: DashboardMetric
  trend?: TrendPoint[]
  activity?: ActivityEvent[]
}

export interface UsageSummary extends FreshnessMeta {
  range?: string
  from?: string
  to?: string
  cost_usd: string
  input_tokens: number
  output_tokens: number
  embedding_tokens: number
  requests: number
  usage_unknown_usd: string
  provider_overrun_usd: string
  overrun_cleared_usd: string
  buckets: TrendPoint[]
}

export interface UsageByModelRow {
  provider: string
  model: string
  input_tokens: number
  output_tokens: number
  embedding_tokens: number
  requests: number
  cost_usd: string
}

export interface ReservationView {
  id: string
  request_id?: string | null
  provider?: string
  model?: string
  amount_usd: string
  status: string
  created_at: string
  expires_at?: string | null
  released_at?: string | null
  reason?: string | null
}

export interface DatasetListItem {
  dataset_id: string
  filename: string
  revision: number
  confirmed_revision?: number | null
  row_count: number
  column_count: number
  expires_at?: string | null
  created_at?: string
  status: string
}

export interface DatasetDetail extends DatasetListItem {
  columns: Array<{ name: string; inferred_type?: string }>
  quality: { issue_count: number; missing_cells: number; outliers: number; report_mode?: string }
}

export interface DiscussionListItem {
  session_id: string
  project_id?: string | null
  topic: string
  status: string
  command_status?: string | null
  event_count: number
  generation?: number
  lease_owner?: string | null
  lease_until?: string | null
  created_at: string
  updated_at?: string
}

export interface DiscussionEventView {
  event_seq: number
  type: string
  agent?: string | null
  message?: string | null
  content?: string | null
  created_at?: string
}

export interface CommandView {
  command_id: string
  status: string
  kind?: string
  summary?: string
  error_code?: string | null
  created_at?: string
  updated_at?: string
}

export interface FileRecordView {
  file_id: string
  display_name: string
  kind?: string
  status: string
  size_bytes?: number | null
  created_at: string
  expires_at?: string | null
  integrity_status?: string | null
}

export interface RagProjectView {
  project_id: string
  name: string
  document_count: number
  chunk_count: number
  legacy?: boolean
  freshness?: AdminFreshness
}

export interface RagDocumentView {
  document_id: string
  filename: string
  chunk_count: number
  collection_count?: number
  created_at?: string
  metadata_summary?: Record<string, string | number | boolean | null>
}

export interface RagCollectionView {
  name: string
  model_fingerprint?: string | null
  project_count?: number
  document_count?: number
  status?: string
}

export interface LogLine {
  created_at?: string
  level: string
  message: string
  truncated?: boolean
}

export interface LogChunk {
  lines: LogLine[]
  cursor?: string | null
  file_identity?: string | null
  freshness?: AdminFreshness
}

export interface StorageView extends FreshnessMeta {
  items?: Array<{ name: string; used_bytes: number; file_count?: number; status?: string }>
  used_bytes?: number
  free_bytes?: number
}

export interface SessionView {
  session_id: string
  user_id?: string
  username?: string
  ip?: string | null
  user_agent?: string | null
  created_at: string
  last_activity_at?: string
  last_request_at?: string
  idle_expires_at: string
  absolute_expires_at: string
  current?: boolean
  revoked_at?: string | null
}

export interface SecuritySettingsView {
  enabled: boolean
  source?: string
  values?: Record<string, string | boolean | number | null>
  allowed_ips_configured?: boolean
  session_idle_minutes?: number
  session_absolute_hours?: number
  csrf_token_ttl_minutes?: number
  max_sessions?: number
}

export interface ConfigFieldView {
  key: string
  label?: string
  value: string | number | boolean | null
  source: string
  editable: boolean
  requires_restart?: boolean
  secret?: boolean
  description?: string
  options?: string[]
}

export interface ConfigView {
  revision: number
  fields: ConfigFieldView[]
  requires_restart?: boolean
}

export interface AuditLogView {
  id: string
  actor_name: string
  action: string
  target_type?: string | null
  target_id?: string | null
  request_id: string
  operation_id?: string | null
  result: string
  error_code?: string | null
  reason?: string | null
  before_summary?: string | null
  after_summary?: string | null
  detail?: Record<string, unknown>
  created_at: string
}

export interface AdminOperation {
  intended?: Record<string, unknown> | null
  operation_id: string
  kind?: string
  scope?: string
  state: AdminOperationState | string
  attempt_count?: number
  error_code?: string | null
  retryable?: boolean
  result?: Record<string, unknown> | null
  created_at?: string
  updated_at?: string
}

export interface MutationAccepted {
  operation_id?: string | null
  state?: AdminOperationState | string
  result?: Record<string, unknown>
  error_code?: string | null
}
