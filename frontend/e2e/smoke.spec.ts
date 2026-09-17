import { expect, test } from '@playwright/test'

test('配置页可访问且短按钮保持紧凑', async ({ page }) => {
  await page.route('**/api/config/providers', route => route.fulfill({ json: { providers:[{id:'openai',name:'OpenAI',region:'global',base_url:'https://api.openai.com/v1',api_style:'openai',docs_url:'https://platform.openai.com/docs',verified_at:'2026-08-16'},{id:'deepseek',name:'DeepSeek 深度求索',region:'cn',base_url:'https://api.deepseek.com',api_style:'openai',docs_url:'https://api-docs.deepseek.com/api/list-models',verified_at:'2026-08-16'}] } }))
  await page.route('**/api/config/profiles', route => route.fulfill({ json: { config_revision: 4, active_profile_id: 'p1', profiles: [{ profile_id: 'p1', config_revision: 4, active: true, credential_configured: {}, draft: { name: '现场方案', default_model: { service_id: 'svc', model: 'example-model' }, roles: {}, services: [{ service_id: 'svc', provider: 'openai', base_url: 'https://api.openai.com/v1' }], search: null } }] } }))
  await page.route('**/api/config/models', route => route.fulfill({ json: { models:['deepseek-v4-flash','deepseek-v4-pro'],source:'remote' } }))
  await page.goto('/config')
  await expect(page.getByRole('heading', { name: '模型与协同' })).toBeVisible()
  await page.locator('.ant-card').filter({ hasText: '服务与默认模型' }).locator('.ant-select').first().click()
  await page.getByText('DeepSeek 深度求索').click()
  const services = page.locator('.ant-card').filter({ hasText: '服务与默认模型' })
  await expect(services.locator('input.ant-input').first()).toHaveValue('https://api.deepseek.com')
  await services.locator('input[type="password"]').fill('test-key')
  await page.getByRole('button', { name: '获取模型' }).click()
  await expect(page.getByRole('button', { name: '获取模型' })).toBeVisible()
  const shortButtons=page.locator('button').filter({hasText:/^.{1,4}$/})
  for(let index=0;index<await shortButtons.count();index+=1){expect((await shortButtons.nth(index).boundingBox())?.width).toBeLessThanOrEqual(160)}
})
