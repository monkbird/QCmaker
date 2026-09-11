import { expect, it, vi } from 'vitest'
import { llmApi } from '../api/client'
import { topicChat } from '../api/topic'

it('limits long conversations to the server history window and includes project scope', async () => {
  const post = vi.spyOn(llmApi, 'post').mockResolvedValue({ data: { response: 'ok', references_used: 0 } })
  const history = Array.from({ length: 80 }, (_, index) => ({ role: index % 2 ? 'assistant' as const : 'user' as const, content: String(index) }))
  await topicChat('new question', history, 'project')
  expect(post.mock.calls[0][1]).toEqual({ message: 'new question', history: history.slice(-50), project_id: 'project' })
  post.mockRestore()
})
