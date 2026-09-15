import type { ReactNode } from 'react'
import { AlertOutlined, CheckCircleOutlined, CloseCircleOutlined, InfoCircleOutlined, LoadingOutlined, ReloadOutlined } from '@ant-design/icons'
import { AdminApiError } from '../../api/admin'
import type { AdminFreshness, AdminPage, DashboardMetric } from '../../types/admin'

export function toPage<T>(value: AdminPage<T> | T[] | { items?: T[]; total?: number; limit?: number; offset?: number } | null | undefined): AdminPage<T> {
  if (Array.isArray(value)) return { items: value, total: value.length, limit: value.length, offset: 0 }
  return { items: value?.items ?? [], total: value?.total ?? value?.items?.length ?? 0, limit: value?.limit ?? 50, offset: value?.offset ?? 0 }
}

export function formatDate(value?: string | null) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.valueOf())) return value
  return new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(date)
}

export function formatBucket(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.valueOf())) return value.replace('T', ' ').slice(0, 16)
  const hasHour = /T\d{2}:|\d{2}:\d{2}/.test(value)
  return new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit', ...(hasHour ? { hour: '2-digit' as const, minute: '2-digit' as const } : {}) }).format(date)
}

export function formatHealthStatus(value?: string | null) {
  const normalized = String(value ?? '').toLowerCase()
  if (normalized === 'healthy' || normalized === 'ready' || normalized === 'ok') return '正常'
  if (normalized === 'degraded' || normalized === 'partial' || normalized === 'warning') return '部分降级'
  if (normalized === 'unavailable' || normalized === 'error' || normalized === 'failed') return '不可用'
  return '未知'
}

export function formatHealthName(value?: string | null) {
  const normalized = String(value ?? '').toLowerCase()
  const labels: Record<string, string> = { wal: '数据库日志', data: '数据目录', generated_ppts: '成果目录', logs: '日志目录' }
  if (labels[normalized]) return labels[normalized]
  if (normalized.includes('sqlite') || normalized.includes('database') || normalized.includes('db')) return '数据库'
  if (normalized.includes('filesystem') || normalized.includes('disk') || normalized.includes('storage')) return '存储空间'
  if (normalized.includes('chroma') || normalized.includes('vector') || normalized.includes('rag')) return '知识库'
  if (normalized.includes('process') || normalized.includes('server') || normalized.includes('app')) return '服务进程'
  if (!value) return '依赖检查'
  return value
}

export function formatLongDate(value?: string | null) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.valueOf())) return value
  return new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' }).format(date)
}

export function formatMoney(value?: string | number | null) {
  if (value === undefined || value === null || value === '') return '—'
  const parsed = Number(value)
  return Number.isFinite(parsed) ? `$${parsed.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : String(value)
}

export function formatNumber(value?: number | string | null) {
  if (value === undefined || value === null || value === '') return '—'
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed.toLocaleString('zh-CN') : String(value)
}

export function formatBytes(value?: number | null) {
  if (value === undefined || value === null) return '—'
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  if (value < 1024 * 1024 * 1024) return `${(value / (1024 * 1024)).toFixed(1)} MB`
  return `${(value / (1024 * 1024 * 1024)).toFixed(2)} GB`
}

export function safeText(value: unknown) {
  if (value === undefined || value === null || value === '') return '—'
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return String(value)
  try { return JSON.stringify(value) } catch { return '[无法展示]' }
}

export function AdminPageHeader({ eyebrow, title, description, actions }: { eyebrow: string; title: string; description: string; actions?: ReactNode }) {
  return <header className="admin-page-header"><div><p className="admin-eyebrow">{eyebrow}</p><h1>{title}</h1><p className="admin-page-description">{description}</p></div>{actions && <div className="admin-page-actions">{actions}</div>}</header>
}

export function Panel({ title, description, actions, children, className = '' }: { title?: string; description?: string; actions?: ReactNode; children: ReactNode; className?: string }) {
  return <section className={`admin-panel ${className}`}><>{(title || description || actions) && <header className="admin-panel-head"><div>{title && <h2>{title}</h2>}{description && <p>{description}</p>}</div>{actions && <div className="admin-panel-actions">{actions}</div>}</header>}</><div className="admin-panel-body">{children}</div></section>
}

export function MetricTile({ label, value, note, icon, tone = 'default' }: { label: string; value: ReactNode; note?: ReactNode; icon?: ReactNode; tone?: 'default' | 'positive' | 'warning' | 'danger' }) {
  return <article className={`admin-metric admin-metric--${tone}`}><div className="admin-metric-label">{icon}<span>{label}</span></div><div className="admin-metric-value">{value}</div>{note && <p className="admin-metric-note">{note}</p>}</article>
}

export function StatusBadge({ value, tone }: { value: string; tone?: 'positive' | 'warning' | 'danger' | 'blue' | 'muted' }) {
  const normalized = tone ?? (/(healthy|ready|finished|succeeded|正常|已确认|已完成|fresh|connected)/i.test(value) ? 'positive' : /(error|failed|missing|cancelled|expired|unavailable|不可用|失败|缺失|已结束)/i.test(value) ? 'danger' : /(warning|partial|running|pending|degraded|部分降级|待恢复|执行中|过期)/i.test(value) ? 'warning' : 'muted')
  return <span className={`admin-badge admin-badge--${normalized}`}><i aria-hidden="true" />{value}</span>
}

export function FreshnessBadge({ freshness, calculatedAt }: { freshness?: AdminFreshness; calculatedAt?: string }) {
  if (!freshness && !calculatedAt) return null
  const value = freshness === 'fresh' ? '数据新鲜' : freshness === 'stale' ? '数据滞后' : freshness === 'degraded' ? '局部降级' : '新鲜度未知'
  return <span className="admin-freshness" title={calculatedAt ? `计算于 ${formatLongDate(calculatedAt)}` : undefined}>{value}</span>
}

export function AdminLoading({ label = '正在读取管理数据…' }: { label?: string }) {
  return <div className="admin-state-inline"><LoadingOutlined spin /><span>{label}</span></div>
}

export function AdminEmpty({ title = '暂无数据', description = '当前筛选范围没有可展示的记录。' }: { title?: string; description?: string }) {
  return <div className="admin-empty"><InfoCircleOutlined /><strong>{title}</strong><p>{description}</p></div>
}

export function AdminError({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const apiError = error instanceof AdminApiError ? error : null
  return <div className="admin-error" role="alert"><CloseCircleOutlined /><div><strong>{apiError?.message ?? '管理数据读取失败'}</strong>{apiError?.requestId && <small>请求编号：{apiError.requestId}</small>}</div>{onRetry && <button type="button" className="admin-button admin-button--small" onClick={onRetry}><ReloadOutlined />重试</button>}</div>
}

export function AdminNotice({ children, tone = 'info' }: { children: ReactNode; tone?: 'info' | 'warning' | 'danger' | 'success' }) {
  const Icon = tone === 'danger' ? CloseCircleOutlined : tone === 'warning' ? AlertOutlined : tone === 'success' ? CheckCircleOutlined : InfoCircleOutlined
  return <div className={`admin-notice admin-notice--${tone}`}><Icon />{children}</div>
}

export function AdminDrawer({ open, title, onClose, children }: { open: boolean; title: string; onClose: () => void; children: ReactNode }) {
  if (!open) return null
  return <div className="admin-drawer-layer" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}><aside className="admin-drawer" role="dialog" aria-modal="true" aria-labelledby="admin-drawer-title"><header className="admin-dialog-head"><div><p className="admin-eyebrow">详情</p><h2 id="admin-drawer-title">{title}</h2></div><button type="button" className="admin-icon-button" aria-label="关闭详情" onClick={onClose}>×</button></header><div className="admin-drawer-body">{children}</div></aside></div>
}

export function TrendChart({ points, metric = 'cost_usd' }: { points: Array<{ bucket: string; cost_usd?: string; tokens?: number; requests?: number }>; metric?: 'cost_usd' | 'tokens' | 'requests' }) {
  if (!points.length) return <AdminEmpty title="暂无趋势数据" description="所选时间范围内还没有可绘制的账本记录。" />
  const values = points.map((point) => Number(point[metric] ?? 0))
  const max = Math.max(...values, 1)
  const width = 720
  const height = 210
  const path = values.map((value, index) => {
    const x = points.length === 1 ? width / 2 : 18 + (index / (points.length - 1)) * (width - 36)
    const y = 16 + (1 - value / max) * (height - 38)
    return `${index === 0 ? 'M' : 'L'} ${x.toFixed(2)} ${y.toFixed(2)}`
  }).join(' ')
  return <div className="admin-trend-chart"><svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="趋势图"><defs><linearGradient id="admin-trend-fill" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stopColor="#9be5ff" stopOpacity=".28" /><stop offset="1" stopColor="#9be5ff" stopOpacity="0" /></linearGradient></defs>{[0, 1, 2, 3].map((line) => <line key={line} x1="18" x2={width - 18} y1={16 + line * 52} y2={16 + line * 52} className="admin-chart-grid" />)}<path d={`${path} L ${width - 18} ${height - 22} L 18 ${height - 22} Z`} fill="url(#admin-trend-fill)" /><path d={path} className="admin-chart-line" fill="none" />{values.map((value, index) => { const x = points.length === 1 ? width / 2 : 18 + (index / (points.length - 1)) * (width - 36); const y = 16 + (1 - value / max) * (height - 38); return <circle key={`${points[index].bucket}-${index}`} cx={x} cy={y} r="3.5" className="admin-chart-point"><title>{`${formatBucket(points[index].bucket)} · ${metric === 'cost_usd' ? formatMoney(String(value)) : formatNumber(value)}`}</title></circle> })}</svg><div className="admin-chart-axis">{points.filter((_, index) => index === 0 || index === points.length - 1 || index === Math.floor(points.length / 2)).map((point) => <span key={point.bucket}>{formatBucket(point.bucket)}</span>)}</div></div>
}

export function metricValue(metric: DashboardMetric | undefined, key: keyof DashboardMetric) {
  const value = metric?.[key]
  if (key === 'cost_usd' || key === 'limit_usd' || key === 'known_cost_usd' || key === 'reserved_usd' || key === 'remaining_usd' || key === 'usage_unknown_usd' || key === 'provider_overrun_usd') return formatMoney(value as string | undefined)
  return formatNumber(value as number | undefined)
}
