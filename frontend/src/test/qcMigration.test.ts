import { describe, expect, it } from 'vitest'
import { createInitialState, wizardReducer } from '../context/wizardReducer'

describe('legacy project hydration', () => {
  it('retains old data confirmation without treating it as verified chapter evidence', () => {
    const next = wizardReducer(createInitialState(), { type: 'HYDRATE_SUCCESS', payload: { dataRef: 'legacy', datasetRevision: 3, dataConfirmed: true } })
    expect(next.datasetRefs).toEqual(['legacy'])
    expect(next.chapterRefs).toEqual([])
    expect(next.materialRefs).toEqual([])
    expect(next.dataConfirmed).toBe(true)
  })
})
