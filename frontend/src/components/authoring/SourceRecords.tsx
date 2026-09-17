import { Alert, Button, Card, Input, List, Select, Space, Tag, message } from 'antd'
import { useState } from 'react'
import { api, errorMessage } from '../../api/client'

type SourceKind = 'web' | 'user' | 'simulation'
type OriginKind = 'documented' | 'user_reported' | 'hypothesis' | 'simulation' | 'pending'
type SourceRecord = {
  source_id: string
  source_kind: SourceKind
  origin_kind: OriginKind
  locator: string
  text: string
  revision?: number
}

const blank: SourceRecord = { source_id: '', source_kind: 'user', origin_kind: 'pending', locator: '', text: '' }
const kindLabels: Record<SourceKind, string> = { user: '人工记录', web: '网页来源', simulation: '模拟来源' }

export function SourceRecords({ project, onChanged }: { project: string; onChanged: () => void }) {
  const [draft, setDraft] = useState<SourceRecord>({ ...blank })
  const [entries, setEntries] = useState<SourceRecord[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const root = `/projects/${encodeURIComponent(project)}/sources`

  const updateKind = (source_kind: SourceKind) => setDraft(current => ({
    ...current,
    source_kind,
    origin_kind: source_kind === 'simulation' ? 'simulation' : current.origin_kind === 'simulation' ? 'pending' : current.origin_kind,
  }))

  const save = async () => {
    if (!draft.source_id.trim() || !draft.locator.trim() || !draft.text.trim()) return
    setBusy(true)
    setError('')
    try {
      const response = await api.post<SourceRecord>(root, { ...draft, source_id: draft.source_id.trim(), locator: draft.locator.trim(), text: draft.text.trim(), expected_revision: 0 })
      setEntries(current => [response.data, ...current.filter(item => item.source_id !== response.data.source_id)])
      setDraft({ ...blank })
      onChanged()
      message.success('来源记录已登记')
    } catch (cause) {
      setError(errorMessage(cause))
    } finally {
      setBusy(false)
    }
  }

  return <Card title="来源记录" style={{ marginTop: 16 }}>
    <Alert type="info" message="登记人工记录、网页来源或模拟依据；来源登记不会自动核实，模拟来源始终保留模拟标识。" />
    {error && <Alert type="error" message={error} style={{ marginTop: 12 }} />}
    <Space direction="vertical" style={{ width: '100%', marginTop: 12 }}>
      <Input aria-label="来源名称或ID" placeholder="来源名称或 ID" value={draft.source_id} onChange={event => setDraft({ ...draft, source_id: event.target.value })} />
      <Select aria-label="来源类型" value={draft.source_kind} options={Object.entries(kindLabels).map(([value, label]) => ({ value, label }))} onChange={updateKind} />
      <Select aria-label="来源性质" value={draft.origin_kind} disabled={draft.source_kind === 'simulation'} options={[['documented', '已记录资料'], ['user_reported', '人员报告'], ['hypothesis', '假设'], ['simulation', '模拟'], ['pending', '待核实']].map(([value, label]) => ({ value, label }))} onChange={origin_kind => setDraft({ ...draft, origin_kind })} />
      <Input aria-label="定位" placeholder="定位 URL / 台账位置" value={draft.locator} onChange={event => setDraft({ ...draft, locator: event.target.value })} />
      <Input.TextArea aria-label="完整内容" placeholder="完整记录内容或网页摘录" autoSize={{ minRows: 4 }} value={draft.text} onChange={event => setDraft({ ...draft, text: event.target.value })} />
      <Button type="primary" loading={busy} disabled={!draft.source_id.trim() || !draft.locator.trim() || !draft.text.trim()} onClick={() => void save()}>登记来源</Button>
      <List dataSource={entries} renderItem={item => <List.Item><List.Item.Meta title={<span>{item.source_id} <Tag>{kindLabels[item.source_kind]}</Tag>{item.origin_kind === 'simulation' && <Tag color="warning">模拟</Tag>}</span>} description={`${item.locator} · 修订 ${item.revision ?? 1}`} /></List.Item>} />
    </Space>
  </Card>
}
