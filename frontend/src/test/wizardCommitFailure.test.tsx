import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { WizardProvider, useWizard } from '../context/WizardContext'
import { createInitialState } from '../context/wizardReducer'
import { saveWizardSnapshot } from '../storage/db'

vi.mock('../api/config', () => ({ getConfig: vi.fn(async () => ({ status: 'ready' })) }))
vi.mock('../context/restoreWizard', () => ({ restoreWizard: vi.fn(async () => ({ state: { ...createInitialState(), hydration: 'ready', currentProjectId: 'p', discussionSessionId: 's' }, notice: null })) }))
vi.mock('../storage/db', () => ({ saveWizardSnapshot: vi.fn(async () => {}), saveDataset: vi.fn(), saveChartImage: vi.fn(), clearProject: vi.fn() }))
afterEach(cleanup)

it('retries a failed event transaction when the server replays that event', async () => {
  const { result } = renderHook(() => useWizard(), { wrapper: WizardProvider })
  await waitFor(() => expect(result.current.state.configStatus).toBe('ready'))
  const event = { type: 'ack' as const, session_id: 's', event_seq: 1, timestamp: '' }
  vi.mocked(saveWizardSnapshot).mockClear()
  vi.mocked(saveWizardSnapshot).mockRejectedValueOnce(new Error('disk full'))
  await act(async () => { await expect(result.current.appendEvent(event)).rejects.toThrow('disk full') })
  await act(async () => { await result.current.appendEvent(event) })
  expect(saveWizardSnapshot).toHaveBeenCalledTimes(2)
})

it('rejects an async result captured before switching projects', async () => {
  const { result } = renderHook(() => useWizard(), { wrapper: WizardProvider })
  await waitFor(() => expect(result.current.state.configStatus).toBe('ready'))
  const finishOldPpt = result.current.setPpt
  await act(async () => { await result.current.reset() })
  await act(async () => { await expect(finishOldPpt({ file_id: 'old', display_name: 'old.pptx', expires_at: '2099-01-01' })).rejects.toThrow('项目或数据已变化') })
  expect(result.current.state.pptResult).toBeNull()
})
