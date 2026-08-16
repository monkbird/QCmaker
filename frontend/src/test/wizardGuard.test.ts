import { describe, expect, it } from 'vitest'
import { routeForState } from '../hooks/useWizardGuard'
import { createInitialState } from '../context/wizardReducer'

describe('routeForState',()=>{
  it('allows the topic page before a topic is selected',()=>{
    const state={...createInitialState(),hydration:'ready' as const,configStatus:'ready' as const}
    expect(routeForState('/topic',state)).toBeNull()
  })

  it('redirects later steps to the first missing prerequisite',()=>{
    const state={...createInitialState(),hydration:'ready' as const,configStatus:'ready' as const}
    expect(routeForState('/data',state)).toBe('/topic')
  })
})
