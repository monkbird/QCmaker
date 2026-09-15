import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { AdminGuard } from '../layouts/AdminGuard'
import { AdminSessionProvider } from '../layouts/AdminSessionContext'

vi.mock('../api/admin', () => ({
  adminMe: vi.fn(),
  getAdminUser: vi.fn(),
  clearAdminMemory: vi.fn(),
  subscribeAdminUnauthorized: vi.fn(() => () => undefined),
}))

import { adminMe } from '../api/admin'

afterEach(() => cleanup())

function renderGuard() {
  const router = createMemoryRouter([
    { path: '/admin/overview', element: <AdminGuard />, children: [{ index: true, element: <div>受保护内容</div> }] },
    { path: '/admin/login', element: <div>登录页</div> },
  ], { initialEntries: ['/admin/overview'] })
  return { router, ...render(<AdminSessionProvider><RouterProvider router={router} /></AdminSessionProvider>) }
}

describe('AdminGuard', () => {
  it('does not render protected content before me resolves', async () => {
    vi.mocked(adminMe).mockImplementation(() => new Promise(() => undefined))
    renderGuard()
    expect(screen.getByText('正在验证管理会话')).toBeInTheDocument()
    expect(screen.queryByText('受保护内容')).not.toBeInTheDocument()
  })

  it('renders protected content after a valid me response', async () => {
    vi.mocked(adminMe).mockResolvedValue({
      user: { user_id: 'u1', username: 'admin', is_active: true }, csrf_token: 'csrf', server_time: '2026-09-13T00:00:00Z',
      idle_expires_at: '2026-09-13T00:30:00Z', absolute_expires_at: '2026-09-13T08:00:00Z',
    })
    renderGuard()
    await expect(screen.findByText('受保护内容')).resolves.toBeInTheDocument()
  })

  it('redirects an expired session to login and keeps the intended path', async () => {
    vi.mocked(adminMe).mockRejectedValue({ status: 401, code: 'ADMIN_SESSION_EXPIRED', message: '登录已过期' })
    const { router } = renderGuard()
    await waitFor(() => expect(router.state.location.pathname).toBe('/admin/login'))
    expect(router.state.location.search).toContain('next=%2Fadmin%2Foverview')
  })

  it('shows the explicit disabled state for a closed management service', async () => {
    vi.mocked(adminMe).mockRejectedValue({ status: 503, code: 'ADMIN_DISABLED', message: '管理后台未启用' })
    renderGuard()
    await expect(screen.findByText('管理后台当前未启用')).resolves.toBeInTheDocument()
  })
})
