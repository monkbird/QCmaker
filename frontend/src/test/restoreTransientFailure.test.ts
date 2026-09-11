import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { getDataset, uploadData } from '../api/data'
import { restoreWizard } from '../context/restoreWizard'
import { createInitialState } from '../context/wizardReducer'
import type { WizardState } from '../context/wizardTypes'
import { routeForState } from '../hooks/useWizardGuard'
import { clearProject, loadDataset, loadDiscussionEvents, saveChartImage, saveDataset, saveWizardSnapshot } from '../storage/db'
import type { DatasetResponse } from '../types/api'

vi.mock('../api/data', () => ({ getDataset: vi.fn(), uploadData: vi.fn() }))

const remote: DatasetResponse = {
  dataset_id: 'retained-dataset', revision: 2, confirmed_revision: 2, filename: 'x.csv',
  columns: [], rows: [{ row_id: '1', values: { n: 20 } }],
  report: { mode: 'detected', issues: [], applied_rules: [], removed_rows: 0, filled_cells: 0, outliers_detected: 0, type_conversions: 0 },
}
let original: WizardState
beforeEach(async () => {
  vi.resetAllMocks()
  original = {
    ...createInitialState(), hydration: 'ready', configStatus: 'ready', topic: '泵站故障',
    dataRef: 'retained-data', datasetRevision: 2, dataConfirmed: true,
    discussionSessionId: 'retained-session', lastEventSeq: 7,
    discussionSummary: { problem: '故障', root_causes: ['原因'], countermeasures: ['措施'], summary: '结论' },
    chartOption: { title: { text: '故障统计' } }, chartImageRef: 'retained-chart',
    pptResult: { file_id: 'retained-ppt', display_name: '成果.pptx', expires_at: new Date(Date.now() + 3600000).toISOString() },
  }
  await saveDataset({ ...remote, dataRef: original.dataRef!, projectId: original.currentProjectId, sourceFile: new Blob(['n\n20']), updatedAt: 1 })
  await saveChartImage({ chartImageRef: original.chartImageRef!, projectId: original.currentProjectId, blob: new Blob(['chart']), mimeType: 'image/png', updatedAt: 1 })
  await saveWizardSnapshot(original, { type: 'ack', session_id: 'retained-session', event_seq: 7, timestamp: 'now' })
})
afterEach(async () => clearProject(original.currentProjectId))

const artifactFields = ['discussionSessionId', 'lastEventSeq', 'discussionSummary', 'chartOption', 'chartImageRef', 'pptResult'] as const

describe('restoring after temporary dataset verification failures', () => {
  it.each(['NETWORK_ERROR', 'UNAUTHORIZED'])('preserves durable artifacts across repeated %s failures and resumes at the same revision', async (code) => {
    vi.mocked(getDataset).mockRejectedValue({ code, message: 'Temporarily unavailable' })
    for (let refresh = 0; refresh < 2; refresh++) {
      const paused = await restoreWizard({ currentProjectId: original.currentProjectId })
      expect(paused.state.dataConfirmed).toBe(false)
      expect(paused.notice).toBeTruthy()
      for (const field of artifactFields) expect(paused.state[field]).toEqual(original[field])
      for (const path of ['/discussion', '/visualization', '/ppt']) expect(routeForState(path, paused.state)).toBe('/data')
      // Mirrors HYDRATE_SUCCESS persistence, including dataConfirmed=false.
      await saveWizardSnapshot(paused.state)
    }
    vi.mocked(getDataset).mockResolvedValue(remote)
    const resumed = await restoreWizard({ currentProjectId: original.currentProjectId })
    expect(resumed.state.dataConfirmed).toBe(true)
    expect(resumed.notice).toBeNull()
    for (const field of artifactFields) expect(resumed.state[field]).toEqual(original[field])
    expect(routeForState('/ppt', resumed.state)).toBeNull()
    expect(await loadDiscussionEvents('retained-session')).toHaveLength(1)
  })

  it.each([
    { revision: 3, confirmed_revision: 3 },
    { revision: 2, confirmed_revision: null },
  ])('invalidates artifacts when remote validity really changes: %j', async (change) => {
    vi.mocked(getDataset).mockRejectedValue({ code: 'NETWORK_ERROR' })
    await saveWizardSnapshot((await restoreWizard({ currentProjectId: original.currentProjectId })).state)
    vi.mocked(getDataset).mockResolvedValue({ ...remote, ...change })
    const restored = await restoreWizard({ currentProjectId: original.currentProjectId })
    for (const field of artifactFields) expect(restored.state[field]).toEqual(field === 'lastEventSeq' ? 0 : null)
    expect(restored.state.datasetRevision).toBe(change.revision)
  })

  it('invalidates artifacts and replaces an expired dataset from its original source', async () => {
    vi.mocked(getDataset).mockRejectedValue({ code: 'SESSION_NOT_FOUND' })
    vi.mocked(uploadData).mockResolvedValue({ ...remote, dataset_id: 'replacement', revision: 0, confirmed_revision: null })
    const restored = await restoreWizard({ currentProjectId: original.currentProjectId })
    for (const field of artifactFields) expect(restored.state[field]).toEqual(field === 'lastEventSeq' ? 0 : null)
    expect(restored.state.dataConfirmed).toBe(false)
    expect(restored.state.datasetRevision).toBe(0)
    expect((await loadDataset(original.dataRef!))?.dataset_id).toBe('replacement')
  })

  it('still discards an expired PPT while retaining other artifacts during a temporary outage', async () => {
    await saveWizardSnapshot({ ...original, pptResult: { ...original.pptResult!, expires_at: new Date(Date.now() - 1000).toISOString() } })
    vi.mocked(getDataset).mockRejectedValue({ code: 'NETWORK_ERROR' })
    const paused = await restoreWizard({ currentProjectId: original.currentProjectId })
    expect(paused.state.pptResult).toBeNull()
    for (const field of artifactFields.filter((field) => field !== 'pptResult')) expect(paused.state[field]).toEqual(original[field])
  })
})
