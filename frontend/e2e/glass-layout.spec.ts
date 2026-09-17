import { expect, test } from '@playwright/test'

test('glass workspace keeps controls reachable at desktop and narrow widths', async ({ page }) => {
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname
    if (path === '/api/config/profiles') return route.fulfill({ json: {
      config_revision: 1, active_profile_id: 'p1', profiles: [{ profile_id: 'p1', config_revision: 1, active: true,
        credential_configured: {}, draft: { name: '现场方案', default_model: { service_id: 'svc', model: 'example-model' },
          roles: {}, services: [{ service_id: 'svc', provider: 'openai', base_url: 'https://api.openai.com/v1' }], search: null } }],
    } })
    if (path === '/api/config/providers') return route.fulfill({ json: { providers: [{
      id: 'openai', name: 'OpenAI', region: 'global', base_url: 'https://api.openai.com/v1',
      api_style: 'openai', docs_url: 'https://platform.openai.com/docs', verified_at: '2026-09-12',
    }] } })
    if (path === '/api/rag/documents') return route.fulfill({ json: { documents: [] } })
    return route.fulfill({ json: {} })
  })
  await page.goto('/config')
  await expect(page.getByRole('heading', { name: '模型与协同' })).toBeVisible()
  await expect(page.getByText('服务与默认模型')).toBeVisible()
  // Prevent the material from silently regressing to an opaque painted card.
  const material = await page.locator('.ant-card').filter({ hasText: '服务与默认模型' }).evaluate(element => {
    const style = getComputedStyle(element)
    return { fill: style.backgroundColor, filter: style.backdropFilter }
  })
  const alpha = material.fill.startsWith('rgba(') ? Number(material.fill.split(',').at(-1)?.replace(')', '')) : 1
  expect(alpha).toBeLessThan(0.4)
  expect(material.filter).toContain('blur(')
  const nav = page.getByRole('navigation', { name: '课题步骤' })
  await expect(nav.getByRole('button', { name: '配置' })).toHaveAttribute('aria-current', 'step')
  for (const width of [1440, 1280, 1024, 768, 390]) {
    await page.setViewportSize({ width, height: 960 })
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    const dock = await page.locator('.action-dock').boundingBox()
    expect(dock).not.toBeNull()
    expect(dock!.x).toBeGreaterThanOrEqual(0)
    expect(dock!.x + dock!.width).toBeLessThanOrEqual(width)
    for (const base of await page.locator('.brand-mark, .step-link-icon, .icon-action, .model-refresh').all()) {
      if (!await base.isVisible()) continue
      const icon = base.locator('svg').first()
      if (!await icon.count()) continue
      const outer = await base.boundingBox()
      const inner = await icon.boundingBox()
      expect(outer).not.toBeNull()
      expect(inner).not.toBeNull()
      expect(Math.abs(outer!.x + outer!.width / 2 - inner!.x - inner!.width / 2)).toBeLessThanOrEqual(1)
      expect(Math.abs(outer!.y + outer!.height / 2 - inner!.y - inner!.height / 2)).toBeLessThanOrEqual(1)
    }
    for (const field of await page.locator('.ant-card').filter({ hasText: '角色分工' }).locator('input').all()) {
      const bounds = await field.boundingBox()
      expect(bounds).not.toBeNull()
      expect(bounds!.x).toBeGreaterThanOrEqual(0)
      expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(width)
    }
    await page.screenshot({ path: `test-results/glass-config-${width}.png`, fullPage: true, animations: 'disabled' })
  }
  await page.setViewportSize({ width: 1440, height: 960 })
  await page.screenshot({ path: 'test-results/glass-config-1440-final.png', fullPage: true, animations: 'disabled' })
})
