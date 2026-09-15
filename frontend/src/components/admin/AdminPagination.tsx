export function AdminPagination({ offset, total, size = 200, busy = false, onChange }: { offset: number; total: number; size?: number; busy?: boolean; onChange: (offset: number) => void }) {
  if (total <= size && offset === 0) return null
  return <div className="admin-panel-footer"><button className="admin-button" disabled={busy || offset === 0} onClick={() => onChange(Math.max(0, offset - size))}>上一页</button><span>第 {Math.floor(offset / size) + 1} 页 · 共 {total} 条</span><button className="admin-button" disabled={busy || offset + size >= total} onClick={() => onChange(offset + size)}>下一页</button></div>
}
