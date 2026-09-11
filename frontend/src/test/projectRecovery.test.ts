import { beforeEach, describe, expect, it, vi } from 'vitest'
import { restoreWizard } from '../context/restoreWizard'
import { createInitialState } from '../context/wizardReducer'
import { clearProject, loadDataset, loadDiscussionEvents, saveDataset, saveWizardSnapshot } from '../storage/db'
import { getDataset } from '../api/data'
vi.mock('../api/data', () => ({ getDataset: vi.fn(), uploadData: vi.fn() }))

const report = { mode: 'detected' as const, issues: [], applied_rules: [], removed_rows: 0, filled_cells: 0, outliers_detected: 0, type_conversions: 0 }
const remote = { dataset_id: 'ds', revision: 2, confirmed_revision: 2, filename: 'x.csv', columns: [], rows: [{ row_id: '1', values: { n: 20 } }], report }
beforeEach(() => vi.clearAllMocks())
describe('project recovery and transactions', () => {
  it('replaces local rows when remote revision changes and clears all artifacts', async () => {
    const state = { ...createInitialState(), currentProjectId: 'recover', dataRef: 'recover-data', datasetRevision: 1, dataConfirmed: true, discussionSessionId: 's', chartImageRef: 'old', discussionSummary: { problem: 'old', root_causes: [], countermeasures: [], summary: 'old' } }
    await saveDataset({ ...remote, revision: 1, rows: [{ row_id: '1', values: { n: 10 } }], dataRef: state.dataRef, projectId: state.currentProjectId, sourceFile: new Blob(['n\n10']), updatedAt: 1 })
    await saveWizardSnapshot(state)
    vi.mocked(getDataset).mockResolvedValue(remote)
    const restored = await restoreWizard({ currentProjectId: state.currentProjectId })
    expect((await loadDataset(state.dataRef))?.rows[0].values.n).toBe(20)
    expect(restored.state.datasetRevision).toBe(2)
    expect(restored.state.discussionSummary).toBeNull()
    expect(restored.state.chartImageRef).toBeNull()
    await clearProject(state.currentProjectId)
  })
  it('persists null artifacts and tracks even unfinished sessions for deletion', async () => {
    const state = { ...createInitialState(), currentProjectId: 'clear', discussionSessionId: 'unfinished', lastEventSeq: 1 }
    await saveWizardSnapshot(state, { type: 'ack', session_id: 'unfinished', event_seq: 1, timestamp: 'now' })
    await saveWizardSnapshot({ ...state, discussionSessionId: null, lastEventSeq: 0 })
    const restored = await restoreWizard({ currentProjectId: 'clear' })
    expect(restored.state.discussionSummary).toBeNull()
    await clearProject('clear')
    expect(await loadDiscussionEvents('unfinished')).toEqual([])
  })
})
