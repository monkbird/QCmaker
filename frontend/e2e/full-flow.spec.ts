import { expect, test } from '@playwright/test'

test('六步流程、规则预览、分页、刷新失效和鉴权下载', async ({ page }) => {
  const config = { llm_provider: 'openai', openai_base_url: 'https://api.openai.com/v1', openai_model: 'test', use_local_llm: false, local_llm_url: '', local_llm_model: '', has_openai_key: true, has_tavily_key: false, status: 'ready', config_revision: 1, role_models: {}, credential_providers: [] }
  const rawRows = Array.from({ length: 230 }, (_, i) => ({ row_id: `row_${i + 1}`, values: { category: `站点-${i + 1}`, rate: i === 1 ? null : '90%' } }))
  let dataset = {
    dataset_id: 'ds_browser', revision: 0, confirmed_revision: null as number | null, filename: 'data.csv',
    columns: [{ name: 'category', inferred_type: 'string', display_format: 'plain', missing_count: 0, outlier_count: 0 }, { name: 'rate', inferred_type: 'percent', display_format: 'percent', missing_count: 1, outlier_count: 0 }],
    rows: rawRows as Array<{ row_id: string; values: { category: string; rate: string | number | null } }>,
    report: { mode: 'detected', issues: [{ issue_type: 'missing', column: 'rate', row_ids: ['row_2'], suggested_actions: ['forward_fill', 'keep'] }, { issue_type: 'type_conversion', column: 'rate', row_ids: ['row_1'], suggested_actions: ['convert_percent', 'keep'] }], applied_rules: [] as unknown[], removed_rows: 0, filled_cells: 0, outliers_detected: 0, type_conversions: 0 },
  }
  const summary = { problem: '泵站故障', root_causes: ['维护不及时'], countermeasures: ['逐项检查设备'], summary: '依据当前数据形成改进建议' }
  let lastPreview: unknown
  let downloadToken: string | undefined
  let startCommand: Record<string, unknown> | undefined
  let datasetUnavailable = false
  await page.route('**/api/**', async route => {
    const req = route.request()
    const path = new URL(req.url()).pathname
    const body = req.method() === 'POST' && req.headers()['content-type']?.includes('json') ? req.postDataJSON() : {}
    const ok = (json: unknown) => route.fulfill({ json })
    if (path === '/api/config/') return ok(config)
    if (path === '/api/config/providers') return ok({ providers: [] })
    if (path === '/api/rag/documents') return ok({ documents: [] })
    if (path === '/api/topic/chat') {
      expect(body.project_id).toBeTruthy()
      return ok({ response: '降低泵站设备故障次数', references_used: 0 })
    }
    if (path === '/api/data/ds_browser' && datasetUnavailable) return route.abort('failed')
    if (path === '/api/data/upload' || path === '/api/data/ds_browser') return ok(dataset)
    if (path === '/api/data/preview') {
      lastPreview = body
      return ok({ dataset_id: dataset.dataset_id, base_revision: dataset.revision, preview_rows: dataset.rows.map(row => ({ ...row, values: { ...row.values, rate: .9 } })), report: dataset.report })
    }
    if (path === '/api/data/apply') {
      expect(body).toEqual(lastPreview)
      dataset = { ...dataset, revision: dataset.revision + 1, rows: dataset.rows.map(row => ({ ...row, values: { ...row.values, rate: .9 } })), report: { ...dataset.report, issues: [], applied_rules: body.rules } }
      return ok(dataset)
    }
    if (path === '/api/data/confirm') { dataset.confirmed_revision = dataset.revision; return ok(dataset) }
    if (path === '/api/visualization/insight') return ok({ recommendation: { chart_type: 'bar', x_axis: 'category', y_axis: 'rate', aggregation: 'mean', reason: '按均值比较' }, insight: '均值为90%', caveats: [], source: 'ai', model: 'test' })
    if (path === '/api/visualization/generate') {
      expect(body.aggregation).toBe('mean')
      return ok({ option: { xAxis: { type: 'category', data: ['站点-1', '站点-2'] }, yAxis: { type: 'value' }, series: [{ type: 'bar', data: [.9, .9] }] }, processing: { aggregation: 'mean', converted_row_ids: [], grouped_categories: 0, warnings: [] } })
    }
    if (path === '/api/ppt/generate') {
      expect(body.chart_images[0].length).toBeGreaterThan(50)
      return ok({ file_id: 'file-browser', display_name: '成果.pptx', expires_at: '2099-01-01T00:00:00Z' })
    }
    if (path === '/api/ppt/download/file-browser') {
      downloadToken = req.headers()['x-api-token']
      return route.fulfill({ body: Buffer.from('offline-ppt-download'), contentType: 'application/vnd.openxmlformats-officedocument.presentationml.presentation' })
    }
    return route.fulfill({ status: 404, json: { code: 'TEST_UNEXPECTED_ROUTE', message: path } })
  })
  await page.routeWebSocket('**/discussion/ws*', ws => {
    let seq = 0
    ws.onMessage(raw => {
      const command = JSON.parse(String(raw))
      const send = (payload: Record<string, unknown>) => ws.send(JSON.stringify({ session_id: command.session_id, event_seq: ++seq, timestamp: '2026-09-09T00:00:00Z', ...payload }))
      if (command.type === 'start') {
        startCommand = command
        send({ type: 'ack' })
        send({ type: 'agent_message', agent: 'analyst', content: '根据230行数据分析' })
        send({ type: 'round_done' })
      } else if (command.type === 'finish') {
        send({ type: 'ack' })
        send({ type: 'error', recoverable: true, error: { code: 'DISCUSSION_SUMMARY_INVALID', message: '纪要格式无效，请恢复当前轮次后重试' } })
      } else if (command.type === 'recover') {
        send({ type: 'ack' }); send({ type: 'finished', summary })
      }
    })
  })
  await page.goto('/topic')
  await page.getByPlaceholder('补充对象、现状、目标或时间范围…').fill('泵站设备故障次数偏高')
  await page.getByRole('button', { name: '发送消息' }).click()
  await expect(page.getByText('降低泵站设备故障次数', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '确认课题' }).click()
  await page.getByRole('button', { name: '确认并进入数据' }).click()
  await page.getByLabel('选择数据文件').setInputFiles({ name: 'data.csv', mimeType: 'text/csv', buffer: Buffer.from('category,rate\nA,90%') })
  await expect(page.getByText('站点-1', { exact: true })).toBeVisible()
  await page.locator('.ant-pagination-item-5').click()
  await expect(page.getByText('站点-201', { exact: true })).toBeVisible()
  await page.getByRole('checkbox').nth(0).check()
  await page.getByRole('button', { name: '预览影响' }).click()
  await expect(page.getByRole('button', { name: '应用预览规则' })).toBeVisible()
  await page.getByRole('checkbox').nth(1).check()
  await expect(page.getByRole('button', { name: '应用预览规则' })).toHaveCount(0)
  await page.getByRole('button', { name: '预览影响' }).click()
  await page.getByRole('button', { name: '应用预览规则' }).click()
  await expect(page.getByText('版本 1', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '确认数据' }).click()
  await expect(page.getByText('根据230行数据分析')).toBeVisible()
  expect(startCommand?.dataset_id).toBe('ds_browser')
  expect(startCommand?.revision).toBe(1)
  expect(startCommand?.project_id).toBeTruthy()
  await page.getByRole('button', { name: '结束并生成纪要' }).click()
  await expect(page.getByText('纪要格式无效，请恢复当前轮次后重试')).toBeVisible()
  await expect(page.getByRole('button', { name: '进入图表设计' })).toHaveCount(0)
  await page.getByRole('button', { name: '恢复当前轮次' }).click()
  await page.getByRole('button', { name: '进入图表设计' }).click()
  await page.getByRole('button', { name: 'AI 图表顾问' }).click()
  await expect(page.getByText('均值为90%')).toBeVisible()
  await page.getByRole('button', { name: '确认图表' }).click()
  await page.getByRole('button', { name: '生成 PPT' }).click()
  await expect(page.getByText('成果.pptx', { exact: true })).toBeVisible()
  const download = page.waitForEvent('download')
  await page.getByRole('button', { name: '下载 PPT' }).click()
  expect((await download).suggestedFilename()).toBe('成果.pptx')
  expect(downloadToken).toBe('e2e-access-token')
  await page.reload()
  await expect(page.getByRole('button', { name: '下载 PPT' })).toBeVisible()
  datasetUnavailable = true
  await page.reload()
  await expect(page.getByText(/无法校验服务器数据/)).toBeVisible()
  await expect(page.getByRole('heading', { name: '检测与确认数据' })).toBeVisible()
  await expect(page.getByRole('button', { name: '下载 PPT' })).toHaveCount(0)
  datasetUnavailable = false
  await page.reload()
  await expect(page.getByText(/无法校验服务器数据/)).toHaveCount(0)
  await page.goto('/ppt')
  await expect(page.getByText('成果.pptx', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '下载 PPT' })).toBeVisible()
  await page.goto('/topic')
  await page.getByRole('button', { name: '确认课题' }).click()
  await page.getByRole('dialog').getByRole('textbox').fill('提高排涝站维护及时率')
  await page.getByRole('button', { name: '确认并进入数据' }).click()
  await expect(page.getByRole('heading', { name: '检测与确认数据' })).toBeVisible()
  await page.goto('/ppt')
  await expect(page.getByRole('heading', { name: '检测与确认数据' })).toBeVisible()
  await expect(page.getByRole('button', { name: '下载 PPT' })).toHaveCount(0)
})
