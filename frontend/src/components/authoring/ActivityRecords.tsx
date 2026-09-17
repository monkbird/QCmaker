import { Alert, Button, Card, Input, List, Select, Space, message } from 'antd'
import { useEffect, useState } from 'react'
import { api, errorMessage } from '../../api/client'

type Entry = { event_id?:string; revision?:number; event_type:string; title:string; object:string; owner:string; activity_start:string|null; activity_end:string|null; observations:string; mechanism:string; contribution_note:string; status:string }
const blank:Entry={event_type:'investigation',title:'',object:'',owner:'',activity_start:null,activity_end:null,observations:'',mechanism:'',contribution_note:'',status:'pending'}
export function ActivityRecords({project,onChanged}:{project:string;onChanged:()=>void}) {
  const [entries,setEntries]=useState<Entry[]>([])
  const [draft,setDraft]=useState<Entry>({...blank})
  const [busy,setBusy]=useState(false)
  const [error,setError]=useState('')
  const root=`/projects/${encodeURIComponent(project)}/activities`
  useEffect(()=>{let alive=true;void api.get<{activities:Entry[]}>(root).then(r=>{if(alive)setEntries(r.data.activities)}).catch(e=>{if(alive)setError(errorMessage(e))});return()=>{alive=false}},[root])
  return <Card title="实际活动记录" style={{marginTop:16}}>
    <Alert type="info" message="按实际发生时间记录；计划、待核实与实际记录分别标注，上传日期不代替实施时间。"/>
    {error&&<Alert type="error" message={error}/>}
    <Space direction="vertical" style={{width:'100%'}}>
      <Select aria-label="活动类别" value={draft.event_type} options={[['investigation','现状调查'],['confirmation','要因确认'],['implementation','对策实施'],['effect','效果检查'],['consolidation','巩固跟踪']].map(([value,label])=>({value,label}))} onChange={v=>setDraft({...draft,event_type:v})}/>
      <Input aria-label="活动名称" placeholder="活动名称" value={draft.title} onChange={e=>setDraft({...draft,title:e.target.value})}/>
      <Input aria-label="活动对象" placeholder="调查或实施对象" value={draft.object} onChange={e=>setDraft({...draft,object:e.target.value})}/>
      <Input aria-label="活动负责人" placeholder="负责人（未知可留空）" value={draft.owner} onChange={e=>setDraft({...draft,owner:e.target.value})}/>
      <Space><label>发生日期<Input type="date" aria-label="活动开始日期" value={draft.activity_start??''} onChange={e=>setDraft({...draft,activity_start:e.target.value||null})}/></label><label>结束日期<Input type="date" aria-label="活动结束日期" value={draft.activity_end??''} onChange={e=>setDraft({...draft,activity_end:e.target.value||null})}/></label></Space>
      <Select aria-label="记录性质" value={draft.status} options={[{value:'pending',label:'待核实'},{value:'planned',label:'计划安排'},{value:'actual',label:'实际发生'}]} onChange={v=>setDraft({...draft,status:v})}/>
      <Input.TextArea aria-label="活动观察记录" placeholder="采取的措施、实际观察及缺项" value={draft.observations} onChange={e=>setDraft({...draft,observations:e.target.value})}/>
      <Input.TextArea aria-label="作用机制" placeholder="措施作用机制（不能替代测量证据）" value={draft.mechanism} onChange={e=>setDraft({...draft,mechanism:e.target.value})}/>
      <Input.TextArea aria-label="贡献说明" placeholder="贡献说明及依据；不确定时不分配贡献比例" value={draft.contribution_note} onChange={e=>setDraft({...draft,contribution_note:e.target.value})}/>
      <Space><Button type="primary" loading={busy} disabled={!draft.title.trim()} onClick={async()=>{setBusy(true);try{const result=await api.post<Entry>(root,{...draft,expected_revision:draft.revision??0});setEntries(old=>[...old.filter(x=>x.event_id!==result.data.event_id),result.data]);setDraft({...blank});onChanged();message.success('活动记录已保存')}catch(e){setError(errorMessage(e))}finally{setBusy(false)}}}>保存活动记录</Button><Button onClick={()=>setDraft({...blank})}>新建记录</Button></Space>
      <List dataSource={entries} renderItem={item=><List.Item actions={[<Button key="edit" onClick={()=>setDraft(item)}>修订</Button>]}><List.Item.Meta title={`${item.title} · 修订 ${item.revision}`} description={`${item.activity_start??'时间待补'} — ${item.activity_end??'结束时间待补'} · ${item.status==='actual'?'实际发生':item.status==='planned'?'计划':'待核实'} · ${item.observations}`}/></List.Item>}/>
    </Space>
  </Card>
}
