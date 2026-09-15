import { AdminError } from './AdminUi'
import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { newIdempotencyKey } from '../../api/admin'

export interface ConfirmOperationPayload {
  reason: string
  confirmText?: string
  currentPassword?: string
  idempotencyKey: string
}

interface ConfirmOperationProps {
  error?: unknown
  open: boolean
  title: string
  target: string
  scope: string
  impact: string
  requireText?: string
  requireRecentPassword?: boolean
  extra?: ReactNode | (() => ReactNode)
  isValid?: boolean | (() => boolean)
  submitting?: boolean
  onCancel: () => void
  onConfirm: (payload: ConfirmOperationPayload) => void
}

function actionWord(title: string) {
  if (title.includes('重试')) return '重试'
  if (title.includes('复位')) return '复位'
  if (title.includes('删除')) return '删除'
  if (title.includes('清空')) return '清空'
  if (title.includes('结束')) return '结束'
  if (title.includes('恢复')) return '恢复'
  if (title.includes('吊销')) return '吊销'
  if (title.includes('轮换')) return '轮换'
  if (title.includes('维护')) return '执行'
  if (title.includes('探测')) return '探测'
  if (title.includes('密码')) return '改密'
  if (title.includes('保存') || title.includes('更新') || title.includes('修改')) return '保存'
  return '确认'
}

export function ConfirmOperation(props: ConfirmOperationProps) {
  if (!props.open) return null
  const operationKey = `${props.title}\u0000${props.scope}\u0000${props.target}`
  return <ConfirmOperationDialog key={operationKey} {...props} />
}

function ConfirmOperationDialog({ error, title, target, scope, impact, requireText, requireRecentPassword = false, extra, isValid = true, submitting = false, onCancel, onConfirm }: Omit<ConfirmOperationProps, 'open'>) {
  const [reason, setReason] = useState('')
  const [typed, setTyped] = useState('')
  const [password, setPassword] = useState('')
  const [idempotencyKey] = useState(() => newIdempotencyKey())

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !submitting) onCancel()
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [onCancel, submitting])

  const valid = typeof isValid === 'function' ? isValid() : isValid
  const canConfirm = useMemo(() => Boolean(reason.trim()) && (!requireText || typed === requireText) && (!requireRecentPassword || password.length > 0) && valid && !submitting, [password, reason, requireRecentPassword, requireText, submitting, typed, valid])
  const word = actionWord(title)

  return <div className="admin-dialog-layer" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onCancel() }}>
    <section className="admin-dialog admin-dialog--danger" role="dialog" aria-modal="true" aria-labelledby="confirm-operation-title">
      <header className="admin-dialog-head"><div><p className="admin-eyebrow">需要确认的管理操作</p><h2 id="confirm-operation-title">{title}</h2></div><button type="button" className="admin-icon-button" aria-label="关闭弹窗" onClick={onCancel}>×</button></header>
      <div className="admin-dialog-body">{Boolean(error) && <AdminError error={error} />}
        <div className="admin-danger-mark" aria-hidden="true">!</div>
        <dl className="admin-confirm-facts"><div><dt>目标</dt><dd>{target}</dd></div><div><dt>操作范围</dt><dd>{scope}</dd></div><div><dt>影响</dt><dd>{impact}</dd></div></dl>
        <p className="admin-warning-copy">请确认目标与影响范围。操作将写入审计日志；不可逆的外部动作可能以部分完成状态返回，请通过操作编号查询结果。</p>
        {typeof extra === 'function' ? extra() : extra}
        {requireText && <label className="admin-field">输入 <strong>{requireText}</strong> 确认<input aria-label="输入确认内容" value={typed} onChange={(event) => setTyped(event.target.value)} autoComplete="off" /></label>}
        {requireRecentPassword && <label className="admin-field">近期管理员密码<input aria-label="近期管理员密码" type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" /></label>}
        <label className="admin-field">操作原因<input aria-label="操作原因" value={reason} onChange={(event) => setReason(event.target.value)} placeholder="请填写本次操作原因" /></label>
      </div>
      <footer className="admin-dialog-actions"><button type="button" className="admin-button" onClick={onCancel}>取消</button><button type="button" className="admin-button admin-button--danger" disabled={!canConfirm} onClick={() => onConfirm({ reason: reason.trim(), confirmText: requireText ? typed : undefined, currentPassword: requireRecentPassword ? password : undefined, idempotencyKey })}>{submitting ? '提交中…' : `确认${word}`}</button></footer>
    </section>
  </div>
}
