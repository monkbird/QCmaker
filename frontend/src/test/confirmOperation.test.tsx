import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { ConfirmOperation } from '../components/admin/ConfirmOperation'

afterEach(cleanup)

describe('ConfirmOperation', () => {
  it('requires reason and exact target confirmation before invoking a dangerous write', () => {
    const onConfirm = vi.fn()
    render(<ConfirmOperation open title="删除数据集" target="dataset-17" scope="仅该数据集" impact="不会删除会话快照" requireText="dataset-17" onCancel={vi.fn()} onConfirm={onConfirm} />)
    const action = screen.getByRole('button', { name: '确认删除' })
    expect(action).toBeDisabled()
    fireEvent.change(screen.getByLabelText('操作原因'), { target: { value: '过期数据清理' } })
    fireEvent.change(screen.getByLabelText('输入确认内容'), { target: { value: 'dataset-17' } })
    expect(action).toBeEnabled()
    fireEvent.click(action)
    expect(onConfirm).toHaveBeenCalledWith(expect.objectContaining({ reason: '过期数据清理', confirmText: 'dataset-17', idempotencyKey: expect.any(String) }))
  })

  it('requires a recent password when a high-risk operation asks for reauthentication', () => {
    render(<ConfirmOperation open title="轮换业务令牌" target="业务访问令牌" scope="全局业务调用" impact="新请求需要重新接入" requireRecentPassword onCancel={vi.fn()} onConfirm={vi.fn()} />)
    expect(screen.getByLabelText('近期管理员密码')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '确认轮换' })).toBeDisabled()
  })

  it('keeps one idempotency key while the open operation is retried', () => {
    const onConfirm = vi.fn()
    const { rerender } = render(<ConfirmOperation open title="删除文件" target="file-1" scope="该文件" impact="删除后不可恢复" requireText="file-1" onCancel={vi.fn()} onConfirm={onConfirm} />)
    fireEvent.change(screen.getByLabelText('操作原因'), { target: { value: '重试幂等测试' } })
    fireEvent.change(screen.getByLabelText('输入确认内容'), { target: { value: 'file-1' } })
    fireEvent.click(screen.getByRole('button', { name: '确认删除' }))
    rerender(<ConfirmOperation open title="删除文件" target="file-1" scope="该文件" impact="删除后不可恢复" requireText="file-1" onCancel={vi.fn()} onConfirm={onConfirm} />)
    fireEvent.click(screen.getByRole('button', { name: '确认删除' }))
    const firstKey = onConfirm.mock.calls[0][0].idempotencyKey
    const secondKey = onConfirm.mock.calls[1][0].idempotencyKey
    expect(firstKey).toBe(secondKey)
  })
})
