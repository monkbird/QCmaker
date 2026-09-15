import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  adminLogin,
  adminMe,
  adminRequest,
  clearAdminMemory,
  getAdminCsrfToken,
} from '../api/admin'

const jsonResponse = (body: unknown, status = 200, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json', ...headers } })

describe('admin api client', () => {
  beforeEach(() => {
    clearAdminMemory()
    vi.stubGlobal('fetch', vi.fn())
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('keeps the CSRF token in memory and sends same-origin credentials without the business token', async () => {
    const fetchMock = vi.mocked(fetch)
    fetchMock.mockResolvedValueOnce(jsonResponse({
      user: { user_id: 'u1', username: 'admin', is_active: true },
      csrf_token: 'csrf-1',
      server_time: '2026-09-13T00:00:00Z',
      idle_expires_at: '2026-09-13T00:30:00Z',
      absolute_expires_at: '2026-09-13T08:00:00Z',
    }))
    await adminLogin('admin', 'password')
    expect(getAdminCsrfToken()).toBe('csrf-1')

    fetchMock.mockResolvedValueOnce(jsonResponse({ items: [], total: 0, limit: 50, offset: 0 }))
    await adminRequest('/datasets')
    const [, init] = fetchMock.mock.calls[1]
    expect(init?.credentials).toBe('include')
    expect(new Headers(init?.headers).get('x-api-token')).toBeNull()
    expect(new Headers(init?.headers).get('x-csrf-token')).toBeNull()
  })

  it('adds CSRF, activity and idempotency headers only when a write opts into them', async () => {
    const fetchMock = vi.mocked(fetch)
    fetchMock.mockResolvedValueOnce(jsonResponse({
      user: { user_id: 'u1', username: 'admin', is_active: true },
      csrf_token: 'csrf-2',
      server_time: '2026-09-13T00:00:00Z',
      idle_expires_at: '2026-09-13T00:30:00Z',
      absolute_expires_at: '2026-09-13T08:00:00Z',
    }))
    await adminLogin('admin', 'password')
    fetchMock.mockResolvedValueOnce(jsonResponse({ operation_id: 'op-1', state: 'succeeded' }))
    await adminRequest('/datasets/d1', {
      method: 'DELETE',
      body: { reason: '清理测试数据', confirm_text: 'd1' },
      activity: true,
      idempotencyKey: 'idem-1',
    })
    const [, init] = fetchMock.mock.calls[1]
    const headers = new Headers(init?.headers)
    expect(headers.get('x-csrf-token')).toBe('csrf-2')
    expect(headers.get('x-admin-user-activity')).toBe('1')
    expect(headers.get('idempotency-key')).toBe('idem-1')
    expect(JSON.parse(String(init?.body))).toEqual({ reason: '清理测试数据', confirm_text: 'd1' })
  })

  it('refreshes me once for an expired CSRF token and retries the original write', async () => {
    const fetchMock = vi.mocked(fetch)
    fetchMock.mockResolvedValueOnce(jsonResponse({
      user: { user_id: 'u1', username: 'admin', is_active: true }, csrf_token: 'old-token',
      server_time: '2026-09-13T00:00:00Z', idle_expires_at: '2026-09-13T00:30:00Z', absolute_expires_at: '2026-09-13T08:00:00Z',
    }))
    await adminLogin('admin', 'password')
    fetchMock.mockResolvedValueOnce(jsonResponse({ code: 'ADMIN_CSRF_EXPIRED', message: 'csrf expired', request_id: 'r1' }, 403))
    fetchMock.mockResolvedValueOnce(jsonResponse({
      user: { user_id: 'u1', username: 'admin', is_active: true }, csrf_token: 'new-token',
      server_time: '2026-09-13T00:01:00Z', idle_expires_at: '2026-09-13T00:31:00Z', absolute_expires_at: '2026-09-13T08:00:00Z',
    }))
    fetchMock.mockResolvedValueOnce(jsonResponse({ operation_id: 'op-2', state: 'succeeded' }))
    await adminRequest('/budget/reset-overrun', { method: 'POST', body: { reason: 'manual' } })
    expect(getAdminCsrfToken()).toBe('new-token')
    expect(fetchMock).toHaveBeenCalledTimes(4)
    const [, retryInit] = fetchMock.mock.calls[3]
    expect(new Headers(retryInit?.headers).get('x-csrf-token')).toBe('new-token')
  })

  it('stores CSRF returned by a me refresh without changing user activity', async () => {
    const fetchMock = vi.mocked(fetch)
    fetchMock.mockResolvedValueOnce(jsonResponse({
      user: { user_id: 'u1', username: 'admin', is_active: true }, csrf_token: 'csrf-me',
      server_time: '2026-09-13T00:00:00Z', idle_expires_at: '2026-09-13T00:30:00Z', absolute_expires_at: '2026-09-13T08:00:00Z',
    }))
    await adminMe()
    const [, init] = fetchMock.mock.calls[0]
    expect(init?.credentials).toBe('include')
    expect(new Headers(init?.headers).get('x-admin-user-activity')).toBeNull()
    expect(getAdminCsrfToken()).toBe('csrf-me')
  })
})
