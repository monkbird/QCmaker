import { BarChartOutlined, CloudServerOutlined, DatabaseOutlined, FilePptOutlined, HddOutlined, TeamOutlined } from '@ant-design/icons'
import { useCallback, useEffect, useState } from 'react'
import { getDashboardOverview } from '../../api/admin'
import type { DashboardOverview } from '../../types/admin'
import { AdminError, AdminEmpty, AdminLoading, AdminPageHeader, FreshnessBadge, MetricTile, Panel, StatusBadge, TrendChart, formatBytes, formatDate, formatHealthName, formatHealthStatus, formatMoney, formatNumber, metricValue } from '../../components/admin/AdminUi'

export function OverviewPage() {
  const [data, setData] = useState<DashboardOverview | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [loading, setLoading] = useState(true)
  const load = useCallback(async () => {
    try { setError(null); const next = await getDashboardOverview(); setData(next) } catch (reason) { setError(reason) } finally { setLoading(false) }
  }, [])
  useEffect(() => { void load(); const timer = window.setInterval(() => { void load() }, 180000); return () => window.clearInterval(timer) }, [load])

  return <div className="admin-page"><AdminPageHeader eyebrow="01 · OPERATIONS" title="总览看板" description="聚合健康、预算、用量与运营事件，数据按服务端时间更新。" actions={<><button type="button" className="admin-button" onClick={() => void load()}>刷新看板</button><FreshnessBadge freshness={data?.health.freshness} calculatedAt={data?.health.calculated_at} /></>} />{Boolean(error) && Boolean(data) && <AdminError error={error} onRetry={() => void load()} />}{loading && !data ? <Panel><AdminLoading label="正在读取总览指标…" /></Panel> : error && !data ? <AdminError error={error} onRetry={() => void load()} /> : data ? <>
    {data.health.status !== 'healthy' && <AdminNoticeForOverview status={data.health.status} message={data.health.message} />}
    <div className="admin-metrics"><MetricTile label="今日成本" value={formatMoney(data.usage_today.cost_usd)} note={`${formatNumber(data.usage_today.requests)} 次模型调用`} icon={<BarChartOutlined />} /><MetricTile label="存续会话" value={metricValue(data.sessions, 'active')} note={`${metricValue(data.sessions, 'running')} 执行中`} icon={<TeamOutlined />} /><MetricTile label="待恢复会话" value={metricValue(data.sessions, 'needs_recovery')} note="需检查执行租约" tone={Number(data.sessions.needs_recovery ?? 0) > 0 ? 'warning' : 'default'} icon={<TeamOutlined />} /><MetricTile label="成果登记" value={metricValue(data.files, 'ready')} note={`${metricValue(data.files, 'missing')} 条缺失`} icon={<FilePptOutlined />} /><MetricTile label="存储占用" value={formatBytes(data.storage.used_bytes)} note={`${formatBytes(data.storage.free_bytes)} 可用`} icon={<HddOutlined />} /><MetricTile label="系统健康" value={<StatusBadge value={formatHealthStatus(data.health.status)} />} note={'本地依赖检查'} tone={data.health.status === 'healthy' ? 'positive' : 'warning'} icon={<CloudServerOutlined />} /></div>
    <div className="admin-dashboard-grid"><Panel title="成本与调用趋势" description="时间范围由服务端补齐空桶，展示实际账本记录。" actions={<FreshnessBadge freshness={data.usage_today.freshness} />} className="admin-panel--chart"><div className="admin-chart-total"><strong>{formatMoney(data.usage_today.cost_usd)}</strong><span>今日累计</span></div><TrendChart points={data.trend ?? []} metric="cost_usd" /><div className="admin-legend"><span><i />成本 USD</span><span><i className="violet" />空桶保持为 0</span></div></Panel><Panel title="预算状态" description="未知成本与供应商超额分别统计。"><BudgetSummary overview={data} /></Panel></div>
    <div className="admin-dashboard-bottom"><Panel title="运营动态" description="最近的结构化事件；详情以纯文本展示。"><ActivityList events={data.activity ?? []} /></Panel><Panel title="本地健康检查" description="显示数据库、存储和知识库等本地依赖状态。"><div className="admin-service-grid">{data.health.checks.length ? data.health.checks.map((check) => <div className="admin-service" key={check.key ?? check.name}><DatabaseOutlined /><div><h3>{formatHealthName(check.name ?? check.key)}</h3><small>{check.message ?? '本地检查已完成'}</small></div><StatusBadge value={formatHealthStatus(check.status)} /></div>) : <AdminEmpty title="暂无健康明细" description="服务端尚未返回检查项。" />}</div></Panel></div>
  </> : <AdminEmpty />}</div>
}

function AdminNoticeForOverview({ status, message }: { status: string; message?: string }) {
  return <div className="admin-notice admin-notice--warning"><CloudServerOutlined /><span>系统当前为 {formatHealthStatus(status)} 状态。{message ?? '部分数据可能滞后，请查看系统状态页。'}</span></div>
}

function BudgetSummary({ overview }: { overview: DashboardOverview }) {
  const budget = overview.budget
  const percent = budget.progress_percent
  return <div className="admin-budget-body"><div className="admin-budget-amount"><strong>{formatMoney(budget.limit_usd)}</strong><span>预算上限</span></div><div className="admin-budget-meta"><span>已知成本 {formatMoney(budget.known_cost_usd)}</span><span>{percent === null || percent === undefined ? '零预算 / 暂停付费调用' : `${percent.toFixed(1)}%`}</span></div><div className="admin-progress"><span style={{ width: `${Math.min(100, Math.max(0, percent ?? 0))}%` }} /><span className="reserved" style={{ width: `${Math.min(100, Math.max(0, percent === null || percent === undefined ? 0 : Number(budget.reserved_usd ?? 0) / Math.max(Number(budget.limit_usd ?? 1), 1) * 100))}%` }} /></div><div className="admin-budget-lines"><div><span>预留中</span><strong>{formatMoney(budget.reserved_usd)}</strong></div><div><span>可用余额</span><strong>{formatMoney(budget.remaining_usd)}</strong></div><div><span>未知成本</span><strong>{formatMoney(budget.usage_unknown_usd)}</strong></div><div><span>供应商超额</span><strong>{formatMoney(budget.provider_overrun_usd)}</strong></div></div><FreshnessBadge freshness={budget.freshness} calculatedAt={budget.calculated_at} /></div>
}

function ActivityList({ events }: { events: DashboardOverview['activity'] }) {
  if (!events?.length) return <AdminEmpty title="暂无运营动态" description="操作事件会在服务端记录后显示。" />
  return <div className="admin-activity-list">{events.map((event) => <article className="admin-activity-item" key={event.id}><span className="admin-activity-icon"><BarChartOutlined /></span><div className="admin-activity-copy"><strong>{event.message}</strong><small>{event.category} · {event.operation_id ? `操作 ${event.operation_id}` : '系统事件'}</small></div><time className="admin-activity-time">{formatDate(event.created_at)}</time></article>)}</div>
}
