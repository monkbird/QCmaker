import type {
  ActivityEvent,
  AdminApiErrorShape,
  AdminMeResponse,
  AdminOperation,
  AdminPage,
  AuditLogView,
  CommandView,
  ConfigView,
  DatasetDetail,
  DatasetListItem,
  DashboardOverview,
  DiscussionEventView,
  DiscussionListItem,
  FileRecordView,
  HealthView,
  LogChunk,
  MutationAccepted,
  RagCollectionView,
  RagDocumentView,
  RagProjectView,
  ReservationView,
  SecuritySettingsView,
  SessionView,
  StorageView,
  TrendPoint,
  UsageByModelRow,
  UsageSummary,
} from '../types/admin'

const ADMIN_API_BASE = '/api/admin'
const writeMethods = new Set(['POST', 'PUT', 'PATCH', 'DELETE'])
let csrfToken: string | null = null
let meSnapshot: AdminMeResponse | null = null
const adminEvents = new EventTarget()

export interface AdminRequestOptions {
  method?: string
  body?: unknown
  headers?: HeadersInit
  activity?: boolean
  idempotencyKey?: string
  skipCsrf?: boolean
  retryOnCsrf?: boolean
  responseType?: 'json' | 'blob' | 'text'
  signal?: AbortSignal
}

export class AdminApiError extends Error {
  readonly code: string
  readonly status: number
  readonly requestId?: string
  readonly details?: Record<string, unknown>
  readonly retryAfter?: number

  constructor(shape: AdminApiErrorShape, status: number, retryAfter?: number) {
    super(shape.message)
    this.name = 'AdminApiError'
    this.code = shape.code
    this.status = status
    this.requestId = shape.request_id
    this.details = shape.details
    this.retryAfter = retryAfter
  }
}

export function getAdminCsrfToken() {
  return csrfToken
}

export function getAdminUser() {
  return meSnapshot?.user ?? null
}

export function clearAdminMemory() {
  csrfToken = null
  meSnapshot = null
}

export function subscribeAdminUnauthorized(listener: () => void) {
  const handler = () => listener()
  adminEvents.addEventListener('unauthorized', handler)
  return () => adminEvents.removeEventListener('unauthorized', handler)
}

function buildUrl(path: string) {
  return `${ADMIN_API_BASE}${path.startsWith('/') ? path : `/${path}`}`
}

function isBodyObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !(value instanceof Blob) && !(value instanceof FormData) && !(value instanceof URLSearchParams) && !(value instanceof ArrayBuffer)
}

async function readPayload(response: Response, responseType: AdminRequestOptions['responseType'] = 'json') {
  if (response.status === 204 || responseType === 'text') return response.text()
  if (responseType === 'blob') return response.blob()
  const text = await response.text()
  if (!text) return undefined
  try {
    return JSON.parse(text) as unknown
  } catch {
    return text
  }
}

function errorPayload(payload: unknown, status: number): AdminApiErrorShape {
  if (typeof payload === 'object' && payload !== null && 'code' in payload && 'message' in payload) {
    const candidate = payload as Partial<AdminApiErrorShape>
    return {
      code: String(candidate.code),
      message: String(candidate.message),
      request_id: candidate.request_id,
      details: candidate.details,
    }
  }
  return {
    code: status === 401 ? 'ADMIN_SESSION_EXPIRED' : status === 403 ? 'ADMIN_FORBIDDEN' : status >= 500 ? 'ADMIN_SERVICE_UNAVAILABLE' : 'ADMIN_REQUEST_FAILED',
    message: status >= 500 ? '管理服务暂时不可用，请稍后重试' : '管理请求失败，请检查输入后重试',
  }
}

function serializeBody(body: unknown): BodyInit | undefined {
  if (body === undefined || body === null) return undefined
  if (isBodyObject(body)) return JSON.stringify(body)
  if (body instanceof URLSearchParams) return body.toString()
  if (typeof body === 'string' || body instanceof Blob || body instanceof FormData || body instanceof ArrayBuffer || body instanceof URLSearchParams) return body
  return undefined
}

export async function adminRequest<T = unknown>(path: string, options: AdminRequestOptions = {}): Promise<T> {
  const method = (options.method ?? 'GET').toUpperCase()
  const isWrite = writeMethods.has(method)
  const headers = new Headers(options.headers)
  if (isBodyObject(options.body) && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  if (isWrite && !options.skipCsrf && csrfToken) headers.set('X-CSRF-Token', csrfToken)
  if (isWrite && options.activity) headers.set('X-Admin-User-Activity', '1')
  if (options.idempotencyKey) headers.set('Idempotency-Key', options.idempotencyKey)

  const response = await fetch(buildUrl(path), {
    method,
    credentials: 'include',
    cache: 'no-store',
    headers,
    body: serializeBody(options.body),
    signal: options.signal,
  })
  const payload = await readPayload(response, options.responseType)
  if (!response.ok) {
    const shape = errorPayload(payload, response.status)
    if (response.status === 403 && (shape.code === 'ADMIN_CSRF_EXPIRED' || shape.code === 'ADMIN_CSRF_INVALID') && isWrite && options.retryOnCsrf !== false) {
      await adminMe()
      return adminRequest<T>(path, { ...options, retryOnCsrf: false })
    }
    if (response.status === 401) {
      clearAdminMemory()
      adminEvents.dispatchEvent(new Event('unauthorized'))
    }
    const retryAfterRaw = response.headers.get('Retry-After')
    const retryAfter = retryAfterRaw ? Number(retryAfterRaw) : undefined
    throw new AdminApiError(shape, response.status, Number.isFinite(retryAfter) ? retryAfter : undefined)
  }
  return payload as T
}

function setSession(next: AdminMeResponse) {
  csrfToken = next.csrf_token
  meSnapshot = next
  return next
}

export async function adminLogin(username: string, password: string) {
  const response = await adminRequest<AdminMeResponse>('/auth/login', { method: 'POST', body: { username, password }, skipCsrf: true })
  return setSession(response)
}

export async function adminMe() {
  const response = await adminRequest<AdminMeResponse>('/auth/me')
  return setSession(response)
}

export function adminLogout() {
  return adminRequest<{ revoked: boolean }>('/auth/logout', { method: 'POST', activity: true }).finally(clearAdminMemory)
}

export function adminActivity() {
  return adminRequest<Pick<AdminMeResponse, 'server_time' | 'idle_expires_at' | 'absolute_expires_at'>>('/auth/activity', { method: 'POST', body: {}, activity: true }).then((next) => {
    if (!meSnapshot) return adminMe()
    meSnapshot = { ...meSnapshot, ...next }
    return meSnapshot
  })
}

export function adminReauth(currentPassword: string) {
  return adminRequest<{ reauthenticated_at: string }>('/auth/reauth', { method: 'POST', body: { current_password: currentPassword }, activity: true })
}

export function adminChangePassword(oldPassword: string, newPassword: string, reason: string) {
  return adminRequest<{ relogin_required: boolean }>('/auth/change-password', { method: 'POST', body: { old_password: oldPassword, new_password: newPassword, reason }, activity: true })
}

export function newIdempotencyKey() {
  return crypto.randomUUID()
}

export function adminWrite<T = MutationAccepted>(path: string, body: unknown, options: Omit<AdminRequestOptions, 'method' | 'body' | 'idempotencyKey'> & { method?: string; idempotencyKey?: string } = {}) {
  return adminRequest<T>(path, { ...options, method: options.method ?? 'POST', body, activity: options.activity ?? true, idempotencyKey: options.idempotencyKey ?? newIdempotencyKey() })
}

type MutationOptions = Pick<AdminRequestOptions, 'idempotencyKey'>

function query(params: Record<string, string | number | boolean | undefined | null>) {
  const result = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') result.set(key, String(value))
  })
  const value = result.toString()
  return value ? `?${value}` : ''
}

export const getDashboardOverview = () => adminRequest<DashboardOverview>('/dashboard/overview')
export const getDashboardTrends = (range: string, metric: string) => adminRequest<{ items: TrendPoint[] }>(`/dashboard/trends${query({ range, metric })}`)
export const getDashboardActivity = (params: Record<string, string | number | undefined>) => adminRequest<AdminPage<ActivityEvent>>(`/dashboard/activity${query(params)}`)
export const getUsageSummary = (params: Record<string, string | number | undefined>) => adminRequest<UsageSummary>(`/usage/summary${query(params)}`)
export const getUsageByModel = (params: Record<string, string | number | undefined>) => adminRequest<AdminPage<UsageByModelRow>>(`/usage/by-model${query(params)}`)
export const getReservations = (params: Record<string, string | number | undefined>) => adminRequest<AdminPage<ReservationView>>(`/budget/reservations${query(params)}`)
export const resetOverrun = (body: { reason: string; confirm_text: string }, options: MutationOptions = {}) => adminWrite<MutationAccepted>('/budget/reset-overrun', body, options)
export const updateBudgetLimit = (body: { expected_revision: number; max_budget_usd: string; reason: string; confirm_text: string }, options: MutationOptions = {}) => adminWrite<MutationAccepted>('/budget/limit', body, { method: 'PUT', ...options })
export const exportUsage = (params: Record<string, string | number | undefined>) => adminRequest<Blob>(`/usage/export.csv${query(params)}`, { responseType: 'blob', activity: true })

export const getDatasets = (params: Record<string, string | number | boolean | undefined>) => adminRequest<AdminPage<DatasetListItem>>(`/datasets${query(params)}`)
export const getDatasetDetail = (id: string) => adminRequest<DatasetDetail>(`/datasets/${encodeURIComponent(id)}`)
export const deleteDataset = (id: string, body: { reason: string; confirm_text: string }, options: MutationOptions = {}) => adminWrite<MutationAccepted>(`/datasets/${encodeURIComponent(id)}`, body, { method: 'DELETE', ...options })
export const purgeExpiredDatasets = (body: { scope: string; dry_run: boolean; reason: string; confirm_text: string }, options: MutationOptions = {}) => adminWrite<MutationAccepted>('/datasets/purge-expired', body, options)

export const getDiscussions = (params: Record<string, string | number | undefined>) => adminRequest<AdminPage<DiscussionListItem>>(`/discussions${query(params)}`)
export const getDiscussionEvents = (id: string, params: Record<string, string | number | undefined>) => adminRequest<AdminPage<DiscussionEventView>>(`/discussions/${encodeURIComponent(id)}/events${query(params)}`)
export const getDiscussionCommands = (id: string, params: Record<string, string | number | undefined>) => adminRequest<AdminPage<CommandView>>(`/discussions/${encodeURIComponent(id)}/commands${query(params)}`)
export const recoverDiscussionLease = (id: string, body: { reason: string; confirm_text: string }, options: MutationOptions = {}) => adminWrite<MutationAccepted>(`/discussions/${encodeURIComponent(id)}/lease-recover`, body, options)
export const forceEndDiscussion = (id: string, body: { reason: string; confirm_text: string }, options: MutationOptions = {}) => adminWrite<MutationAccepted>(`/discussions/${encodeURIComponent(id)}/force-end`, body, options)

export const getFiles = (params: Record<string, string | number | undefined>) => adminRequest<AdminPage<FileRecordView>>(`/files${query(params)}`)
export const getPpts = (params: Record<string, string | number | undefined>) => adminRequest<AdminPage<FileRecordView>>(`/ppts${query(params)}`)
export const deletePpt = (id: string, body: { reason: string; confirm_text: string }, options: MutationOptions = {}) => adminWrite<MutationAccepted>(`/ppts/${encodeURIComponent(id)}`, body, { method: 'DELETE', ...options })
export const downloadPpt = (id: string) => adminRequest<Blob>(`/ppts/${encodeURIComponent(id)}/download`, { responseType: 'blob', activity: true })

export const getRagProjects = (params: Record<string, string | number | undefined>) => adminRequest<AdminPage<RagProjectView>>(`/rag/projects${query(params)}`)
export const getRagDocuments = (id: string, params: Record<string, string | number | undefined>) => adminRequest<AdminPage<RagDocumentView>>(`/rag/projects/${encodeURIComponent(id)}/documents${query(params)}`)
export const getRagCollections = () => adminRequest<AdminPage<RagCollectionView>>('/rag/collections')
export const deleteRagDocument = (projectId: string, documentId: string, body: { reason: string; confirm_text: string }, options: MutationOptions = {}) => adminWrite<MutationAccepted>(`/rag/projects/${encodeURIComponent(projectId)}/documents/${encodeURIComponent(documentId)}`, body, { method: 'DELETE', ...options })
export const purgeRagProject = (projectId: string, body: { reason: string; confirm_text: string; batch_size?: number }, options: MutationOptions = {}) => adminWrite<MutationAccepted>(`/rag/projects/${encodeURIComponent(projectId)}/purge`, body, options)

export const getHealth = () => adminRequest<HealthView>('/system/health')
export const getLogs = (params: Record<string, string | number | boolean | undefined>) => adminRequest<LogChunk>(`/system/logs${query(params)}`)
export const getStorage = () => adminRequest<StorageView>('/system/storage')
export const probeLlm = (body: { provider: string; model: string; reason: string; confirm_text: string }, options: MutationOptions = {}) => adminWrite<MutationAccepted>('/system/probe/llm', body, options)
export const runMaintenance = (body: { scope: string; dry_run: boolean; reason: string; confirm_text: string }, options: MutationOptions = {}) => adminWrite<MutationAccepted>('/system/maintenance', body, options)
export const getOperation = (id: string) => adminRequest<AdminOperation>(`/operations/${encodeURIComponent(id)}`)

export const getSecuritySessions = (params: Record<string, string | number | undefined>) => adminRequest<AdminPage<SessionView>>(`/security/sessions${query(params)}`)
export const revokeSession = (id: string, body: { reason: string; confirm_text: string }, options: MutationOptions = {}) => adminWrite<MutationAccepted>(`/security/sessions/${encodeURIComponent(id)}/revoke`, body, options)
export const revokeAllSessions = (body: { reason: string; confirm_text: string }, options: MutationOptions = {}) => adminWrite<MutationAccepted>('/security/sessions/revoke-all', body, options)
export const getSecuritySettings = () => adminRequest<SecuritySettingsView>('/security/settings')
export const rotateAccessToken = (body: { current_password: string; reason: string; confirm_text: string }, options: MutationOptions = {}) => adminWrite<MutationAccepted>('/security/rotate-access-token', body, options)

export const getAdminConfig = () => adminRequest<ConfigView>('/config')
export const updateAdminConfig = (body: { expected_revision: number; values: Record<string, unknown>; reason: string }, options: MutationOptions = {}) => adminWrite<MutationAccepted>('/config', body, { method: 'PUT', ...options })
export const getAudit = (params: Record<string, string | number | undefined>) => adminRequest<AdminPage<AuditLogView>>(`/audit${query(params)}`)

export const getOperations = (params: Record<string, string | number | undefined>) => adminRequest<AdminPage<AdminOperation>>(`/operations${query(params)}`)
export const retryOperation = (id: string, body: { reason: string; confirm_text: string }, options: MutationOptions = {}) => adminWrite<AdminOperation>(`/operations/${encodeURIComponent(id)}/retry`, body, options)
