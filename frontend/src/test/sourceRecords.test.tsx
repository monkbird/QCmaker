import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

const { post } = vi.hoisted(() => ({ post: vi.fn() }))
vi.mock('../api/client', () => ({ api: { post }, errorMessage: () => '保存失败' }))
import { SourceRecords } from '../components/authoring/SourceRecords'

describe('SourceRecords', () => {
  it('registers a simulation source with an immutable simulation nature', async () => {
    post.mockResolvedValueOnce({ data: { source_id: 'sim-1', source_kind: 'simulation', origin_kind: 'simulation', locator: '台账-1', text: '模拟值', revision: 1 } })
    const changed = vi.fn()
    const user = userEvent.setup()
    render(<SourceRecords project="project-1" onChanged={changed} />)
    await user.type(screen.getByLabelText('来源名称或ID'), 'sim-1')
    await user.click(screen.getByRole('combobox', { name: '来源类型' }))
    await user.click(await screen.findByText('模拟来源'))
    await user.type(screen.getByLabelText('定位'), '台账-1')
    await user.type(screen.getByLabelText('完整内容'), '模拟值')
    await user.click(screen.getByRole('button', { name: '登记来源' }))
    expect(post).toHaveBeenCalledWith('/projects/project-1/sources', expect.objectContaining({ source_id: 'sim-1', source_kind: 'simulation', origin_kind: 'simulation', expected_revision: 0 }))
    expect(changed).toHaveBeenCalledTimes(1)
    expect(screen.getByText('模拟')).toBeInTheDocument()
  })
})
