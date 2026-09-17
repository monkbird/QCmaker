import { describe, expect, it } from 'vitest'
import { routeForState } from '../hooks/useWizardGuard'
import { createInitialState } from '../context/wizardReducer'

describe('routeForState',()=>{
  it('allows the topic page before a topic is selected',()=>{
    const state={...createInitialState(),hydration:'ready' as const,configStatus:'ready' as const}
    expect(routeForState('/topic',state)).toBeNull()
  })

  it('allows source collection and chapter drafting without Excel or model configuration',()=>{
    const state={...createInitialState(),hydration:'ready' as const,configStatus:'ready' as const}
    expect(routeForState('/data',state)).toBeNull()
    expect(routeForState('/authoring',{...state,configStatus:'missing'})).toBeNull()
    expect(routeForState('/topic',{...state,configStatus:'missing'})).toBeNull()
    expect(routeForState('/ppt',state)).toBeNull()
  })

  it('retains prerequisites only for the legacy discussion workflow',()=>{
    const state={...createInitialState(),hydration:'ready' as const,configStatus:'ready' as const,topic:'课题'}
    expect(routeForState('/discussion',state)).toBe('/data')
  })
})
