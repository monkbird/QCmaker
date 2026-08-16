import { describe, expect, it } from 'vitest'
import { errorMessage } from '../api/client'
describe('api errors',()=>{it('keeps structured message',()=>expect(errorMessage({code:'X',message:'明确错误'})).toBe('明确错误'))})
