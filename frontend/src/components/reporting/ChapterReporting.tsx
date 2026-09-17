import { Alert, Button, Card, Checkbox, List, Radio, Select, Space, Tag, message } from 'antd'
import { useCallback, useEffect, useRef, useState } from 'react'
import ReactECharts from 'echarts-for-react'
import { createChapterChart, exportChapters, getArtifacts, getReportChapters, preflightChapters } from '../../api/reporting'
import { downloadPpt } from '../../api/ppt'
import { errorMessage } from '../../api/client'
import { useWizard } from '../../context/WizardContext'
import type { Preflight, ReportArtifact, ReportChapters } from '../../types/reporting'

export function ChapterReporting({kind}:{kind:'chart'|'export'}) {
  const {state} = useWizard()
  return <ReportEditor key={state.currentProjectId} project={state.currentProjectId} kind={kind}/>
}

function ReportEditor({project,kind}:{project:string;kind:'chart'|'export'}) {
  const [data,setData] = useState<ReportChapters>({chapters:[],path:[]})
  const [artifacts,setArtifacts] = useState<ReportArtifact[]>([])
  const [selected,setSelected] = useState<string[]>([])
  const [selectedCharts,setSelectedCharts] = useState<string[]>([])
  const [chapterId,setChapterId] = useState<string>()
  const [metricId,setMetricId] = useState<string>()
  const [chartType,setChartType] = useState('bar')
  const [aggregation,setAggregation] = useState('none')
  const [mode,setMode] = useState<'draft'|'confirmed'>('draft')
  const [report,setReport] = useState<Preflight>()
  const [busy,setBusy] = useState(false)
  const [error,setError] = useState('')
  const [chart,setChart] = useState<ReportArtifact>()
  const alive = useRef(true)
  const lock = useRef(false)
  const operation = useRef<{input:string;id:string} | undefined>(undefined)
  const load = useCallback(async () => {
    const [chapters,items] = await Promise.all([getReportChapters(project),getArtifacts(project)])
    if (!alive.current) return
    setData(chapters);setArtifacts(items)
    setSelected(previous=>previous.length?previous.filter(id=>chapters.chapters.some(c=>c.chapter_id===id)):chapters.chapters.map(c=>c.chapter_id))
  },[project])
  useEffect(()=>{alive.current=true;void load().catch(e=>setError(errorMessage(e)));return()=>{alive.current=false}},[load])
  const chapter = data.chapters.find(c=>c.chapter_id===chapterId)
  const titles = Object.fromEntries(data.path.map(c=>[c.chapter_id,c.title]))
  const chapters = Object.fromEntries(data.chapters.filter(c=>selected.includes(c.chapter_id)).map(c=>[c.chapter_id,c.revision]))
  const charts = Object.fromEntries(artifacts.filter(a=>selectedCharts.includes(a.artifact_id)).map(a=>[a.artifact_id,a.content_version]))
  const act = async (action:()=>Promise<void>) => {
    if(lock.current)return
    lock.current=true;setBusy(true);setError('')
    try{await action()}catch(e){if(alive.current)setError(errorMessage(e))}finally{lock.current=false;if(alive.current)setBusy(false)}
  }
  const operationId = (input:unknown) => {
    const encoded=JSON.stringify(input)
    if(operation.current?.input!==encoded)operation.current={input:encoded,id:crypto.randomUUID()}
    return operation.current!.id
  }
  return <Card title={kind==='chart'?'按章节版本生成图表':'按章节快照导出成果'} style={{marginBottom:24}}>
    <Space direction="vertical" style={{width:'100%'}}>
      <Alert type="info" showIcon message="资料不足也可导出草稿；作者认可写法不等于事实已核实。"/>
      {error&&<Alert type="error" showIcon message={error}/>}
      <Button loading={busy} onClick={()=>void act(load)}>刷新章节与历史成果</Button>
      {!data.chapters.length&&<Alert type="warning" message="尚无已保存章节，请先到“章节”编辑或生成草稿。"/>}
      {kind==='chart'?<>
        <Select aria-label="选择图表章节" placeholder="选择已保存章节" value={chapterId} style={{minWidth:240}} options={data.chapters.map(c=>({value:c.chapter_id,label:`${titles[c.chapter_id]??c.chapter_id} · v${c.revision}`}))} onChange={v=>{setChapterId(v);setMetricId(undefined);setChart(undefined)}}/>
        <Select aria-label="图表指标" placeholder="选择指标" value={metricId} style={{minWidth:240}} options={chapter?.metrics.map(m=>({value:m.metric_id,label:`${m.name} (${m.unit})`}))} onChange={v=>{setMetricId(v);setChart(undefined)}}/>
        <Select aria-label="图表类型" value={chartType} style={{minWidth:160}} options={[['bar','柱形图'],['line','折线图'],['pie','饼图'],['pareto','排列图'],['cause_tree','原因树']].map(([value,label])=>({value,label}))} onChange={v=>{setChartType(v);setChart(undefined)}}/>
        <Select aria-label="统计方式" value={aggregation} style={{minWidth:200}} options={[{value:'none',label:'逐项展示'},{value:'sum',label:'同类求和'},{value:'weighted_rate',label:'按分母加权比例'}]} onChange={v=>{setAggregation(v);setChart(undefined)}}/>
        <Button type="primary" loading={busy} disabled={!chapter||(!metricId&&chartType!=='cause_tree')} onClick={()=>void act(async()=>{
          const spec={project_id:project,chapter_id:chapter!.chapter_id,revision:chapter!.revision,metric_id:metricId??'causes',chart_type:chartType,aggregation}
          const result=await createChapterChart(spec,operationId(spec));if(alive.current)setChart(result);await load()
        })}>生成并保存图表</Button>
        {chart?.payload.option&&<ReactECharts option={chart.payload.option} style={{height:420}}/>}
      </>:<>
        <Checkbox.Group value={selected} onChange={v=>{setSelected(v.map(String));setReport(undefined)}} options={data.chapters.map(c=>({value:c.chapter_id,label:`${titles[c.chapter_id]??c.chapter_id} · v${c.revision} · ${c.review_state==='approved'?'作者已审核':'待审核'}`}))}/>
        <Select mode="multiple" aria-label="附加章节图表" placeholder="选择要附加的图表" value={selectedCharts} style={{width:'100%'}} options={artifacts.filter(a=>a.artifact_kind==='chart').map(a=>({value:a.artifact_id,label:`${a.artifact_id.slice(0,8)} · ${a.stale?'待复核':'当前版本'}`}))} onChange={v=>{setSelectedCharts(v);setReport(undefined)}}/>
        <Radio.Group value={mode} onChange={e=>setMode(e.target.value)} options={[{value:'draft',label:'草稿（允许缺证据）'},{value:'confirmed',label:'作者确认稿（保留模拟标识）'}]}/>
        <Space><Button loading={busy} disabled={!selected.length} onClick={()=>void act(async()=>{const r=await preflightChapters(project,chapters,charts);if(alive.current)setReport(r)})}>导出前检查</Button>
        <Button type="primary" loading={busy} disabled={!selected.length||!report||report.blocked} onClick={()=>void act(async()=>{
          const input={project,chapters,charts,mode};await exportChapters(project,chapters,charts,mode,operationId(input));await load();if(alive.current)message.success('成果已生成，输入版本及标识已保留')
        })}>生成PPT</Button></Space>
        {report&&<List size="small" dataSource={report.issues} renderItem={i=><List.Item><Tag color={i.severity==='error'?'error':'warning'}>{i.severity==='error'?'阻止导出':'提示'}</Tag>{i.message}</List.Item>}/>}
      </>}
      <List header="历史成果（保留各次输入版本）" dataSource={artifacts.filter(a=>a.artifact_kind===kind)} renderItem={a=><List.Item actions={a.payload.file?[<Button key="download" onClick={()=>void downloadPpt(a.payload.file!.file_id,a.payload.file!.display_name).catch(e=>message.error(errorMessage(e)))}>下载</Button>]:[<Button key="view" onClick={()=>setChart(a)}>查看图表</Button>]}><List.Item.Meta title={a.payload.file?.display_name??a.artifact_id} description={`${new Date(a.generated_at).toLocaleString()} · ${a.stale?'待复核：'+a.stale_reasons.join('；'):'版本已固定'}`}/></List.Item>}/>
    </Space>
  </Card>
}
