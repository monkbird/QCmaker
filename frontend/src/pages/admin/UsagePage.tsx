import { AdminPagination } from '../../components/admin/AdminPagination'
import { DownloadOutlined, SearchOutlined } from '@ant-design/icons'
import { useCallback, useEffect, useState } from 'react'
import { exportUsage, getUsageByModel, getUsageSummary } from '../../api/admin'
import type { UsageByModelRow, UsageSummary } from '../../types/admin'
import { AdminEmpty, AdminError, AdminLoading, AdminPageHeader, MetricTile, Panel, TrendChart, formatMoney, formatNumber, toPage } from '../../components/admin/AdminUi'

const ranges = [{ key: '24h', label: '24 小时' }, { key: '7d', label: '7 天' }, { key: '30d', label: '30 天' }, { key: 'all', label: '全历史' }]

export function UsagePage() {
  const [offset, setOffset] = useState(0)
  const [total, setTotal] = useState(0)
  const [range, setRange] = useState('7d')
  const [summary, setSummary] = useState<UsageSummary | null>(null)
  const [rows, setRows] = useState<UsageByModelRow[]>([])
  const [error, setError] = useState<unknown>(null)
  const [loading, setLoading] = useState(true)
  const [exporting, setExporting] = useState(false)
  const load = useCallback(async () => {
    setLoading(true); setError(null)
    try { const [nextSummary, nextRows] = await Promise.all([getUsageSummary({ range }), getUsageByModel({ range, limit: 200, offset })]); setSummary(nextSummary); setRows(toPage(nextRows).items); setTotal(toPage(nextRows).total) } catch (reason) { setError(reason) } finally { setLoading(false) }
  }, [range, offset])
  useEffect(() => { void load() }, [load])
  const download = () => { setExporting(true); void exportUsage({ range, scope: 'filtered' }).then((blob) => { const url = URL.createObjectURL(blob); const link = document.createElement('a'); link.href = url; link.download = `QCmaker-usage-${range}.csv`; link.click(); window.setTimeout(() => URL.revokeObjectURL(url), 1000) }).catch((reason) => setError(reason)).finally(() => setExporting(false)) }

  return <div className="admin-page"><AdminPageHeader eyebrow="02 · LEDGER" title="用量与成本" description="按服务端 UTC 半开区间统计，未知成本与供应商超额单独保留。" actions={<><button type="button" className="admin-button" onClick={() => void load()}>刷新</button><button type="button" className="admin-button admin-button--primary" disabled={exporting || !summary} onClick={download}><DownloadOutlined />{exporting ? '导出中…' : '导出当前筛选'}</button></>} /><div className="admin-toolbar"><div className="admin-segmented" aria-label="时间范围">{ranges.map((item) => <button key={item.key} type="button" className={range === item.key ? 'is-active' : ''} aria-pressed={range === item.key} onClick={() => { setRange(item.key); setOffset(0) }}>{item.label}</button>)}</div><span className="admin-freshness">页面与 CSV 使用同一筛选</span></div>{Boolean(error) && Boolean(summary) && <AdminError error={error} onRetry={() => void load()} />}{error && !summary ? <AdminError error={error} onRetry={() => void load()} /> : loading && !summary ? <Panel><AdminLoading label="正在汇总用量账本…" /></Panel> : summary ? <><div className="admin-summary-strip"><MetricTile label="已结算成本" value={formatMoney(summary.cost_usd)} note={`${summary.range ?? range} · ${summary.requests.toLocaleString()} 次调用`} /><MetricTile label="输入 Token" value={formatNumber(summary.input_tokens)} note="仅统计已记账调用" /><MetricTile label="输出 Token" value={formatNumber(summary.output_tokens)} note="仅统计已记账调用" /></div><div className="admin-dashboard-grid"><Panel title="用量趋势" description="空桶由服务端补齐，避免时间跨度被误读。"><TrendChart points={summary.buckets ?? []} metric="cost_usd" /></Panel><Panel title="异常占用" description="不会因过期或资源删除自动释放。"><div className="admin-budget-lines"><div><span>未知成本</span><strong>{formatMoney(summary.usage_unknown_usd)}</strong></div><div><span>供应商超额</span><strong>{formatMoney(summary.provider_overrun_usd)}</strong></div><div><span>已清理超额</span><strong>{formatMoney(summary.overrun_cleared_usd)}</strong></div><div><span>向量 Token</span><strong>{formatNumber(summary.embedding_tokens)}</strong></div></div></Panel></div><Panel title="按服务商与模型" description="三类 Token 分列，金额使用 Decimal 字符串格式。" className="admin-panel--flush">{rows.length ? <div className="admin-table-scroll"><table className="admin-table"><thead><tr><th>服务商</th><th>模型</th><th>输入 Token</th><th>输出 Token</th><th>向量 Token</th><th>调用</th><th>成本</th></tr></thead><tbody>{rows.map((row) => <tr key={`${row.provider}/${row.model}`}><td>{row.provider}</td><td><strong>{row.model}</strong></td><td>{formatNumber(row.input_tokens)}</td><td>{formatNumber(row.output_tokens)}</td><td>{formatNumber(row.embedding_tokens)}</td><td>{formatNumber(row.requests)}</td><td>{formatMoney(row.cost_usd)}</td></tr>)}</tbody></table></div> : <AdminEmpty title="暂无模型用量" description="当前时间范围没有已结算记录。" />}<div className="admin-panel-footer"><span><SearchOutlined /> 服务端稳定排序</span><span>{rows.length} 个模型</span></div></Panel></> : <AdminEmpty title="暂无用量汇总" />}<AdminPagination offset={offset} total={total} size={200} busy={loading} onChange={setOffset} /></div>
}
