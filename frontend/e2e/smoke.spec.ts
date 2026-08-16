import { expect, test } from '@playwright/test'

test('配置页可访问且短按钮保持紧凑', async ({ page }) => {
  await page.route('**/api/config/', route => route.fulfill({ json: { llm_provider:'openai',openai_base_url:'https://api.openai.com/v1',openai_model:'gpt-4o-mini',use_local_llm:false,local_llm_url:'http://127.0.0.1:11434/v1',local_llm_model:'llama3',max_budget_usd:5,has_openai_key:false,has_tavily_key:false,status:'missing',config_revision:0 } }))
  await page.route('**/api/config/usage', route => route.fulfill({ json: { budget_usd:'5',reserved_usd:'0',known_cost_usd:'0',remaining_usd:'5',unknown_cost:false,usage_by_model:[] } }))
  await page.route('**/api/config/providers', route => route.fulfill({ json: { providers:[{id:'openai',name:'OpenAI',region:'global',base_url:'https://api.openai.com/v1',api_style:'openai',docs_url:'https://platform.openai.com/docs',verified_at:'2026-08-16'},{id:'deepseek',name:'DeepSeek 深度求索',region:'cn',base_url:'https://api.deepseek.com',api_style:'openai',docs_url:'https://api-docs.deepseek.com/api/list-models',verified_at:'2026-08-16'}] } }))
  await page.route('**/api/config/models', route => route.fulfill({ json: { models:['deepseek-v4-flash','deepseek-v4-pro'],source:'remote' } }))
  await page.goto('/config')
  await expect(page.getByRole('heading', { name: '模型与预算' })).toBeVisible()
  await page.getByLabel('模型服务商').click()
  await page.getByText('DeepSeek 深度求索').click()
  await expect(page.getByLabel('API 地址')).toHaveValue('https://api.deepseek.com')
  await page.getByLabel('API Key').fill('test-key')
  await page.getByLabel(/模型名称/).fill('deepseek-')
  await expect(page.locator('.ant-select-dropdown:visible .ant-select-item-option-content',{hasText:'deepseek-v4-pro'})).toBeVisible()
  const shortButtons=page.locator('button').filter({hasText:/^.{1,4}$/})
  for(let index=0;index<await shortButtons.count();index+=1){expect((await shortButtons.nth(index).boundingBox())?.width).toBeLessThanOrEqual(160)}
})
