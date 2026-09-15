import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { useDiscussionSocket } from '../hooks/useDiscussionSocket'
import { loadDiscussionEvents } from '../storage/db'
import type { DiscussionEvent } from '../types/discussion'

vi.mock('../storage/db', () => ({ loadDiscussionEvents: vi.fn(async () => []) }))
class FakeSocket {
  static OPEN = 1
  static instances: FakeSocket[] = []
  readyState = 1
  onopen: (() => void) | null = null
  onmessage: ((event: { data: string }) => void) | null = null
  onclose: (() => void) | null = null
  sent: Record<string, unknown>[] = []
  constructor() { FakeSocket.instances.push(this) }
  send(value: string) { this.sent.push(JSON.parse(value)) }
  close() { this.readyState = 3; this.onclose?.() }
  event(value: Partial<DiscussionEvent>) { this.onmessage?.({ data: JSON.stringify({ session_id: 's', timestamp: '', ...value }) }) }
}
const options = () => ({ topic: 't', datasetId: 'd', revision: 0, projectId: 'p', enabled: true, sessionId: 's', lastEventSeq: 0, onSession: vi.fn(), onEvent: vi.fn(async () => {}) })
beforeEach(() => { FakeSocket.instances = []; vi.stubGlobal('WebSocket', FakeSocket); vi.mocked(loadDiscussionEvents).mockResolvedValue([]) })
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.useRealTimers() })
async function socket() { await waitFor(() => expect(FakeSocket.instances).toHaveLength(1)); return FakeSocket.instances[0] }

it('waits for dataset readiness and restores finished events without connecting', async () => {
  const opts = options()
  vi.mocked(loadDiscussionEvents).mockResolvedValue([{ type: 'finished', session_id: 's', event_seq: 1, timestamp: '' }])
  const { result, rerender } = renderHook(({ enabled }) => useDiscussionSocket({ ...opts, enabled }), { initialProps: { enabled: false } })
  expect(FakeSocket.instances).toHaveLength(0)
  rerender({ enabled: true })
  await waitFor(() => expect(result.current.status).toBe('finished'))
  expect(FakeSocket.instances).toHaveLength(0)
})

it('persists events in order before advancing the cursor', async () => {
  const opts = options()
  let release!: () => void
  opts.onEvent.mockImplementationOnce(() => new Promise<void>(resolve => { release = resolve }))
  const { result } = renderHook(() => useDiscussionSocket(opts))
  const ws = await socket()
  act(() => { ws.event({ type: 'ack', event_seq: 1 }); ws.event({ type: 'round_done', event_seq: 2 }) })
  await waitFor(() => expect(opts.onEvent).toHaveBeenCalledTimes(1))
  expect(result.current.events).toHaveLength(0)
  await act(async () => { release() })
  await waitFor(() => expect(result.current.events.map(event => event.event_seq)).toEqual([1, 2]))
})

it('shows recoverable errors and sends recover on retry', async () => {
  const { result } = renderHook(() => useDiscussionSocket(options()))
  const ws = await socket()
  act(() => ws.event({ type: 'error', event_seq: 1, recoverable: true, error: { code: 'TEMP', message: '暂时失败' } }))
  await waitFor(() => expect(result.current.status).toBe('failed'))
  expect(result.current.error).toBe('暂时失败')
  act(() => result.current.retry())
  expect(ws.sent.at(-1)?.type).toBe('recover')
})

it('restarts a locally saved session whose start never reached the server', async () => {
  renderHook(() => useDiscussionSocket(options()))
  const ws = await socket()
  await act(async () => ws.onopen?.())
  expect(ws.sent[0].type).toBe('resume')
  act(() => ws.event({ type: 'error', event_seq: 0, error: { code: 'SESSION_NOT_FOUND', message: 'missing' } }))
  await waitFor(() => expect(ws.sent.at(-1)?.type).toBe('start'))
  expect(ws.sent.at(-1)).toMatchObject({ dataset_id: 'd', revision: 0, project_id: 'p' })
})

it('does not acknowledge a failed persistence operation', async () => {
  const opts = options(); opts.onEvent.mockRejectedValueOnce(new Error('disk full'))
  const { result } = renderHook(() => useDiscussionSocket(opts))
  const ws = await socket()
  act(() => ws.event({ type: 'ack', event_seq: 1 }))
  await waitFor(() => expect(result.current.error).toContain('保存失败'))
  expect(result.current.events).toHaveLength(0)
})

it('offers retry after automatic reconnects are exhausted and clears timers on unmount', async () => {
  vi.useFakeTimers()
  const { result, unmount } = renderHook(() => useDiscussionSocket(options()))
  await act(async () => {})
  for (let index = 0; index < 6; index++) {
    act(() => FakeSocket.instances.at(-1)?.close())
    await act(async () => { await vi.advanceTimersByTimeAsync(10000) })
  }
  expect(result.current.status).toBe('failed')
  expect(result.current.error).toContain('次数已用尽')
  act(() => result.current.retry())
  await act(async () => {})
  expect(FakeSocket.instances).toHaveLength(7)
  act(() => FakeSocket.instances.at(-1)?.close())
  unmount()
  expect(vi.getTimerCount()).toBe(0)
})

it('recovers after reconnect when retry was requested offline', async () => {
  const { result } = renderHook(() => useDiscussionSocket(options()))
  const ws = await socket()
  act(() => ws.event({ type: 'error', event_seq: 1, recoverable: true, error: { code: 'TEMP', message: 'retry' } }))
  await waitFor(() => expect(result.current.recoverable).toBe(true))
  act(() => { ws.close(); result.current.retry() })
  await waitFor(() => expect(FakeSocket.instances).toHaveLength(2))
  const next = FakeSocket.instances[1]
  await act(async () => next.onopen?.())
  act(() => next.event({ type: 'ack', event_seq: 1, session_status: 'round_error' }))
  await waitFor(() => expect(next.sent.at(-1)?.type).toBe('recover'))
  expect(result.current.status).toBe('connected')
})

it('stops reconnecting and sending commands after an administrator cancellation', async () => {
  const { result } = renderHook(() => useDiscussionSocket(options()))
  const ws = await socket()
  await act(async () => ws.onopen?.())
  const instanceCount = FakeSocket.instances.length
  act(() => ws.event({ type: 'cancelled', event_seq: 1, session_status: 'cancelled' }))
  await waitFor(() => expect(result.current.status).toBe('cancelled'))
  expect(result.current.error).toBe('管理员已终止该研讨会话')
  expect(ws.readyState).toBe(3)
  expect(result.current.sendMessage('不要再发送')).toBe(false)
  act(() => result.current.retry())
  expect(FakeSocket.instances).toHaveLength(instanceCount)
})
