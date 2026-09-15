import { LockOutlined, LoginOutlined } from '@ant-design/icons'
import { useEffect, useState } from 'react'
import { useLocation, useNavigate, useSearchParams } from 'react-router'
import { adminLogin, adminMe, AdminApiError } from '../../api/admin'
import { AdminNotice } from '../../components/admin/AdminUi'
import { useAdminSession } from '../../layouts/AdminSessionContext'

function safeNext(value: string | null) {
  return value?.startsWith('/admin/') && value !== '/admin/login' ? value : '/admin/overview'
}

export function AdminLoginPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const [params] = useSearchParams()
  const { setSession } = useAdminSession()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<AdminApiError | null>(null)
  const [retryAt, setRetryAt] = useState<number | null>(null)
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    if (!retryAt) return
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [retryAt])

  const submit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (busy || (retryAt !== null && retryAt > now)) return
    setBusy(true)
    setError(null)
    void adminLogin(username.trim(), password).then(() => adminMe()).then((session) => {
      setSession(session)
      navigate(safeNext(params.get('next') ?? (location.state as { from?: string } | null)?.from ?? null), { replace: true })
    }).catch((reason: unknown) => {
      const apiError = reason instanceof AdminApiError ? reason : new AdminApiError({ code: 'ADMIN_LOGIN_FAILED', message: '登录失败，请检查账号和密码' }, 401)
      setError(apiError)
      if (apiError.status === 429 && apiError.retryAfter) setRetryAt(Date.now() + apiError.retryAfter * 1000)
    }).finally(() => setBusy(false))
  }

  const remaining = retryAt ? Math.max(0, Math.ceil((retryAt - now) / 1000)) : 0
  return <main className="admin-login-shell"><div className="admin-login-glow" aria-hidden="true" /><section className="admin-login-card"><div className="admin-login-brand"><span className="admin-state-mark">Q</span><div><strong>QCmaker</strong><small>管理工作空间</small></div></div><p className="admin-eyebrow">ADMIN / AUTHENTICATION</p><h1>欢迎回到管理后台</h1><p className="admin-login-lead">使用独立管理员会话查看系统与资源状态，工作台数据互不影响。</p>{error?.code === 'ADMIN_DISABLED' && <AdminNotice tone="warning">管理后台当前未启用，请联系维护人员开启管理服务。</AdminNotice>}{error?.code === 'ADMIN_NOT_INITIALIZED' && <AdminNotice tone="warning">管理后台尚未初始化，请先完成管理员设置。</AdminNotice>}{error && error.code !== 'ADMIN_DISABLED' && error.code !== 'ADMIN_NOT_INITIALIZED' && <AdminNotice tone="danger">{error.message}{remaining > 0 && ` · 请在 ${remaining} 秒后重试`}</AdminNotice>}<form onSubmit={submit} className="admin-login-form"><label className="admin-field"><span>管理员账号</span><div className="admin-login-input"><LockOutlined /><input aria-label="管理员账号" autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} required /></div></label><label className="admin-field"><span>密码</span><div className="admin-login-input"><LockOutlined /><input aria-label="管理员密码" type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} required /></div></label><button type="submit" className="admin-button admin-button--primary admin-login-submit" disabled={busy || remaining > 0}>{busy ? '正在验证…' : <><LoginOutlined />进入管理工作空间</>}</button></form><p className="admin-login-hint">登录成功后，会话按服务端安全策略管理，超时后需要重新登录。</p></section></main>
}
