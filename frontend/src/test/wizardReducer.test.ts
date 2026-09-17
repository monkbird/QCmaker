import { describe, expect, it } from 'vitest'
import { createInitialState, wizardReducer } from '../context/wizardReducer'

describe('wizardReducer', () => {
  it('preserves source data and previous artifacts on a title edit and flags them for review', () => {
    const current = { ...createInitialState(), hydration: 'ready' as const, topic: '旧课题', dataRef: 'd1', datasetRevision: 2, dataConfirmed: true, discussionSummary: { problem: 'p', root_causes: [], countermeasures: [], summary: 's' }, chartImageRef: 'img', pptResult: { file_id: 'f', display_name: 'a', expires_at: 'x' } }
    const next = wizardReducer(current, { type: 'SET_TOPIC', payload: '新课题' })
    expect(next.dataRef).toBe('d1')
    expect(next.dataConfirmed).toBe(true)
    expect(next.discussionSummary).toEqual(current.discussionSummary)
    expect(next.pptResult).toEqual(current.pptResult)
    expect(next.legacyArtifactsStale).toBe(true)
  })
  it('keeps dataset references when another dataset is selected', () => {
    const state = { ...createInitialState(), dataRef: 'd1', datasetRefs: ['d1'] }
    const next = wizardReducer(state, { type: 'SET_DATA_REF', payload: { dataRef: 'd2', revision: 1 } })
    expect(next.datasetRefs).toEqual(['d1', 'd2'])
  })
  it('ignores duplicate websocket events', () => {
    const state = { ...createInitialState(), lastEventSeq: 4 }
    expect(wizardReducer(state, { type: 'APPEND_DISCUSSION_EVENT', payload: { type: 'ack', session_id: 's', event_seq: 4, timestamp: 'x' } })).toBe(state)
  })
})
