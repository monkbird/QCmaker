import { useEffect } from 'react'
import { Navigate, Outlet, useLocation } from 'react-router'
import { adminMe } from '../api/admin'
import type { AdminApiError } from '../api/admin'
import { useAdminSession } from './AdminSessionContext'

export function AdminUnavailable({ error }: { error: AdminApiError | null }) {
  const disabled = error?.code === 'ADMIN_DISABLED'
  const uninitialized = error?.code === 'ADMIN_NOT_INITIALIZED'
  return <main className="admin-state-page">
    <div className="admin-state-card">
      <span className="admin-state-mark">Q</span>
      <p className="admin-eyebrow">QCMAKER / ADMIN</p>
      <h1>{disabled ? '管理后台当前未启用' : uninitialized ? '管理后台尚未初始化' : '管理服务暂时不可用'}</h1>
      <p>{disabled ? '请联系维护人员开启管理服务。业务工作台仍可继续使用。' : uninitialized ? '请联系维护人员完成管理员设置后重新打开此页面。' : error?.message ?? '请稍后重试，或联系系统维护人员。'}</p>
      {error?.requestId && <code>请求编号：{error.requestId}</code>}
    </div>
  </main>
}

export function AdminGuard() {
  const { status, error, setChecking, setSession, setError, setUnauthenticated } = useAdminSession()
  const location = useLocation()

  useEffect(() => {
    if (status !== 'idle') return
    setChecking()
    void adminMe().then((session) => {
      setSession(session)
    }).catch((reason: unknown) => {
      const candidate = reason as Partial<AdminApiError> | null
      const apiError = candidate && typeof candidate.status === 'number' && typeof candidate.code === 'string' ? candidate as AdminApiError : { status: 503, code: 'ADMIN_SERVICE_UNAVAILABLE', message: '管理服务暂时不可用，请稍后重试' } as AdminApiError
      if (apiError.status === 401) setUnauthenticated()
      else setError(apiError)
    })
  }, [setChecking, setError, setSession, setUnauthenticated, status])

  if (status === 'checking' || status === 'idle') return <main className="admin-state-page"><div className="admin-state-card" aria-live="polite"><span className="admin-spinner" /><p>正在验证管理会话</p></div></main>
  if (status === 'unauthenticated') return <Navigate to={`/admin/login?next=${encodeURIComponent(`${location.pathname}${location.search}`)}`} replace />
  if (status === 'disabled' || status === 'unavailable') return <AdminUnavailable error={error} />
  return <Outlet />
}
