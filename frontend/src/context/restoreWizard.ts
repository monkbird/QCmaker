import { getDataset, uploadData } from '../api/data'
import { loadChartImage, loadDataset, loadProjectState, saveDataset } from '../storage/db'
import { createInitialState } from './wizardReducer'
import type { WizardState } from './wizardTypes'

const clearResults = { discussionSessionId: null, lastEventSeq: 0, discussionSummary: null, chartOption: null, chartImageRef: null, pptResult: null }

export async function restoreWizard(saved: Partial<WizardState>): Promise<{ state: WizardState; notice: string | null }> {
  const projectId = saved.currentProjectId ?? crypto.randomUUID()
  const project = await loadProjectState(projectId)
  // Legacy split records cannot prove which dataset their artifacts belong to.
  let state: WizardState = { ...createInitialState(), ...saved, ...clearResults, ...(project?.snapshot ?? {}), currentProjectId: projectId, hydration: 'ready' }
  let notice: string | null = null
  if (state.dataRef) {
    const local = await loadDataset(state.dataRef)
    if (!local || local.projectId !== projectId) {
      state = { ...state, ...clearResults, dataRef: null, datasetRevision: null, dataConfirmed: false }
    } else {
      try {
        const remote = await getDataset(local.dataset_id)
        const changed = remote.revision !== local.revision || state.datasetRevision !== remote.revision
        await saveDataset({ ...local, ...remote, updatedAt: Date.now() })
        state = { ...state, ...(changed || remote.confirmed_revision !== remote.revision ? clearResults : {}), datasetRevision: remote.revision, dataConfirmed: remote.confirmed_revision === remote.revision }
        if (changed) notice = '已同步服务器上的最新数据版本，请重新生成下游成果'
      } catch (error) {
        if (typeof error === 'object' && error !== null && 'code' in error && error.code === 'SESSION_NOT_FOUND') {
          const fresh = await uploadData(new File([local.sourceFile], local.filename))
          await saveDataset({ ...local, ...fresh, updatedAt: Date.now() })
          state = { ...state, ...clearResults, datasetRevision: fresh.revision, dataConfirmed: false }
          notice = '数据集已过期，已重新上传本地原文件；此前清洗未保留，请重新检测和确认'
        } else {
          // Failed verification pauses server-dependent work without proving artifacts stale.
          // Preserve them in the next snapshot so a successful refresh can resume them.
          state = { ...state, dataConfirmed: false }
          notice = '无法校验服务器数据，已暂停下游操作；请恢复连接后刷新'
        }
      }
    }
  } else state = { ...state, ...clearResults, datasetRevision: null, dataConfirmed: false }
  if (state.chartImageRef && !(await loadChartImage(state.chartImageRef))) state = { ...state, chartImageRef: null, chartOption: null, pptResult: null }
  if (state.pptResult && Date.parse(state.pptResult.expires_at) <= Date.now()) state = { ...state, pptResult: null }
  return { state, notice }
}
