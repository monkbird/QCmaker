import { useCallback, useEffect, useState } from 'react'
import { adminReauth, getOperation, getOperations, retryOperation } from '../../api/admin'
import type { AdminOperation } from '../../types/admin'
import { ConfirmOperation, type ConfirmOperationPayload } from './ConfirmOperation'
import { AdminDrawer, AdminEmpty, AdminError, Panel, StatusBadge, formatDate, safeText } from './AdminUi'

function targetText(op: AdminOperation) {
  for (const key of ['dataset_id', 'session_id', 'file_id', 'document_id', 'project_id', 'scope', 'field']) {
    const value = op.intended?.[key]
    if (value) return Array.isArray(value) ? value.join(',') : String(value)
  }
  return op.scope ?? ''
}
export function OperationRecords() {
  const [rows, setRows] = useState<AdminOperation[]>([])
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const [state, setState] = useState('')
  const [lookup, setLookup] = useState('')
  const [selected, setSelected] = useState<AdminOperation | null>(null)
  const [retry, setRetry] = useState<AdminOperation | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [submitting, setSubmitting] = useState(false)
  const load = useCallback(async () => {
    try { const result = await getOperations({ state: state || undefined, limit: 20, offset }); setRows(result.items); setTotal(result.total) }
    catch (reason) { setError(reason) }
  }, [offset, state])
  useEffect(() => { void load() }, [load])
  const running = rows.some(row => ['pending', 'running'].includes(row.state)) || Boolean(selected && ['pending', 'running'].includes(selected.state))
  useEffect(() => {
    if (!running) return
    const timer = window.setInterval(() => { void load(); if (selected) void getOperation(selected.operation_id).then(setSelected).catch(setError) }, 3000)
    return () => window.clearInterval(timer)
  }, [load, running, selected])
  const inspect = async (id: string) => {
    setError(null)
    try { setSelected(await getOperation(id)) } catch (reason) { setError(reason) }
  }
  const submit = async (payload: ConfirmOperationPayload) => {
    if (!retry) return
    setSubmitting(true); setError(null)
    try {
      await adminReauth(payload.currentPassword ?? '')
      const result = await retryOperation(retry.operation_id, { reason: payload.reason, confirm_text: payload.confirmText ?? '' }, { idempotencyKey: payload.idempotencyKey })
      setRetry(null); setSelected(result); await load()
    } catch (reason) { setError(reason) } finally { setSubmitting(false) }
  }
  return <><Panel title="操作记录与重试" description="超时后先查询原操作。仅允许重试的失败或部分完成任务会显示重试入口。" actions={<button className="admin-button" onClick={() => void load()}>刷新操作记录</button>}>
    <div className="admin-toolbar"><select aria-label="操作状态筛选" value={state} onChange={event => { setState(event.target.value); setOffset(0) }}><option value="">全部状态</option><option value="running">执行中</option><option value="failed">失败</option><option value="partial">部分完成</option><option value="succeeded">已完成</option></select><input aria-label="查询操作编号" value={lookup} onChange={event => setLookup(event.target.value)} placeholder="输入操作编号" /><button className="admin-button" disabled={!lookup.trim()} onClick={() => void inspect(lookup.trim())}>查询操作</button></div>
    {Boolean(error) && <AdminError error={error} />}
    {rows.length ? <div className="admin-table-scroll"><table className="admin-table"><thead><tr><th>更新时间</th><th>操作编号</th><th>范围</th><th>状态</th><th>详情</th></tr></thead><tbody>{rows.map(row => <tr key={row.operation_id}><td>{formatDate(row.updated_at)}</td><td>{row.operation_id}</td><td>{row.scope}</td><td><StatusBadge value={row.state} /></td><td><button className="admin-button" onClick={() => void inspect(row.operation_id)}>查看操作</button></td></tr>)}</tbody></table></div> : <AdminEmpty title="暂无操作记录" />}
    <div className="admin-panel-footer"><button className="admin-button" disabled={offset === 0} onClick={() => setOffset(value => Math.max(0, value - 20))}>上一页</button><span>共 {total} 条</span><button className="admin-button" disabled={offset + 20 >= total} onClick={() => setOffset(value => value + 20)}>下一页</button></div>
  </Panel><AdminDrawer open={Boolean(selected)} title="操作详情" onClose={() => setSelected(null)}>{selected && <><p>{selected.operation_id}</p><StatusBadge value={selected.state} /><p>重试次数：{selected.attempt_count ?? 0}</p><div className="admin-code-block">{safeText({ scope: selected.scope, result: selected.result, error: selected.error_code })}</div>{selected.retryable && ['failed', 'partial'].includes(selected.state) && <button className="admin-button admin-button--danger" onClick={() => { setRetry(selected); setSelected(null) }}>重试原操作</button>}</>}</AdminDrawer>
    {retry && <ConfirmOperation error={error} open title="重试管理操作" target={targetText(retry)} scope={retry.scope ?? '原操作范围'} impact="沿用原操作编号继续处理，请先核对已有结果。" requireText={targetText(retry)} requireRecentPassword submitting={submitting} onCancel={() => setRetry(null)} onConfirm={payload => void submit(payload)} />}
  </>
}
