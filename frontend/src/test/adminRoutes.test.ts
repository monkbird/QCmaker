import { describe, expect, it } from 'vitest'
import { adminRoutePaths } from '../routes/adminRoutes'

describe('admin route surface', () => {
  it('keeps login and all twelve protected modules under /admin', () => {
    expect(adminRoutePaths).toEqual([
      '/admin/login', '/admin/overview', '/admin/usage', '/admin/budget', '/admin/datasets', '/admin/discussions',
      '/admin/files', '/admin/rag', '/admin/logs', '/admin/system', '/admin/security', '/admin/config', '/admin/audit',
    ])
  })
})
