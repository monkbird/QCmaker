import { expect, it, vi } from 'vitest'
import { api } from '../api/client'
import { downloadPpt } from '../api/ppt'

it('downloads through the authenticated API client', async () => {
  const anchor = document.createElement('a')
  vi.spyOn(document, 'createElement').mockReturnValue(anchor)
  vi.spyOn(anchor, 'click').mockImplementation(() => undefined)
  vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: vi.fn(() => 'blob:test'), revokeObjectURL: vi.fn() }))
  const request = vi.spyOn(api, 'get').mockResolvedValue({ data: new Blob(['ppt']) })
  await downloadPpt('file-id', '成果.pptx')
  expect(request).toHaveBeenCalledWith('/ppt/download/file-id', { responseType: 'blob' })
  expect(anchor.download).toBe('成果.pptx')
  expect(anchor.click).toHaveBeenCalled()
  vi.restoreAllMocks()
})
