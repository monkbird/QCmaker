import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { getAdminUser, subscribeAdminUnauthorized } from '../api/admin'
import type { AdminApiError } from '../api/admin'
import type { AdminMeResponse, AdminUser } from '../types/admin'

export type AdminAuthState = 'idle' | 'checking' | 'authenticated' | 'unauthenticated' | 'disabled' | 'unavailable'

interface AdminSessionValue {
  status: AdminAuthState
  session: AdminMeResponse | null
  error: AdminApiError | null
  setChecking: () => void
  setSession: (session: AdminMeResponse) => void
  setError: (error: AdminApiError) => void
  setUnauthenticated: () => void
}

const Context = createContext<AdminSessionValue | null>(null)

export function AdminSessionProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AdminAuthState>('idle')
  const [session, setSessionState] = useState<AdminMeResponse | null>(null)
  const [error, setErrorState] = useState<AdminApiError | null>(null)

  useEffect(() => subscribeAdminUnauthorized(() => {
    setStatus('unauthenticated')
    setSessionState(null)
  }), [])

  const value = useMemo<AdminSessionValue>(() => ({
    status,
    session,
    error,
    setChecking: () => setStatus('checking'),
    setSession: (next) => { setSessionState(next); setErrorState(null); setStatus('authenticated') },
    setError: (next) => { setErrorState(next); setStatus(next.code === 'ADMIN_DISABLED' || next.code === 'ADMIN_NOT_INITIALIZED' ? 'disabled' : 'unavailable') },
    setUnauthenticated: () => { setSessionState(null); setStatus('unauthenticated') },
  }), [error, session, status])

  return <Context.Provider value={value}>{children}</Context.Provider>
}

export function useAdminSession() {
  const value = useContext(Context)
  if (!value) throw new Error('AdminSessionProvider missing')
  return value
}

export function currentAdminUser(): AdminUser | null {
  return getAdminUser()
}
