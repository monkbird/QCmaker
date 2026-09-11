import { describe, expect, it } from 'vitest'
import { createInitialState, wizardReducer } from '../context/wizardReducer'
import { routeForState } from '../hooks/useWizardGuard'

describe('review: dataset lifecycle', () => {
  it('permits discussion after first upload and confirmation', () => {
    let state = { ...createInitialState(), hydration: 'ready' as const, configStatus: 'ready' as const, topic: '泵站故障' }
    state = wizardReducer(state, { type: 'SET_DATA_REF', payload: { dataRef: 'ds1', revision: 0 } }) as typeof state
    state = wizardReducer(state, { type: 'CONFIRM_DATA' }) as typeof state
    expect(state.datasetRevision).toBe(0)
    expect(routeForState('/discussion', state)).toBeNull()
  })
  it('updates revision and invalidates artifacts on cleaned data', () => {
    const state = { ...createInitialState(), dataRef: 'd', datasetRevision: 0, dataConfirmed: true, chartImageRef: 'old' }
    const next = wizardReducer(state, { type: 'SET_DATA_REF', payload: { dataRef: 'd', revision: 1 } })
    expect(next.datasetRevision).toBe(1)
    expect(next.chartImageRef).toBeNull()
    expect(next.dataConfirmed).toBe(false)
  })
  it('does not accept late events from an old discussion', () => {
    const state = { ...createInitialState(), discussionSessionId: 'new', lastEventSeq: 2 }
    const next = wizardReducer(state, { type: 'APPEND_DISCUSSION_EVENT', payload: { type: 'ack', session_id: 'old', event_seq: 20, timestamp: 'now' } })
    expect(next).toBe(state)
  })
})
