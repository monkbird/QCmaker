import {
  Alert,
  Button,
  Card,
  Form,
  Input,
  List,
  Select,
  Spin,
  Tag,
  Modal,
  Collapse,
  Progress,
  Space,
  message,
} from "antd";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { ChapterReview } from "../components/authoring/ChapterReview";
import { ActivityRecords } from "../components/authoring/ActivityRecords";
import { SourceRecords } from "../components/authoring/SourceRecords";
import { MaterialWorkspace } from "../components/materials/MaterialWorkspace";
import {
  generateChapter,
  getAuthoringContext,
  listChapters,
  listEvidence,
  reviewChapter,
  saveAuthoringContext,
  saveChapter,
  verifyChapterEvidence,
  checkTimeline,
  chapterHistory, previewChange, applyChange,
  recommendEvidence,
} from "../api/authoring";
import { useWizard } from "../context/WizardContext";
import type {
  ChapterSnapshot,
  ScenarioCard,
  EvidenceRef,
  ContentBlock,
  MetricSpec,
} from "../types/authoring";
type PathItem = {
  chapter_id: string;
  slug: string;
  title: string;
  purpose: string;
  expected_conclusion?: string;
  analysis_methods?: string[];
  next_input?: string;
  standard_basis?: string;
};
export function AuthoringPage() {
  const { state } = useWizard();
  return <AuthoringEditor key={state.currentProjectId} project={state.currentProjectId} topic={state.topic??''}/>;
}
function AuthoringEditor({project,topic}:{project:string;topic:string}) {
  const navigate = useNavigate();
  const alive = useRef(true);
  const operationLock = useRef(false);
  const [busy,setBusy] = useState(false);
  const [chapters, setChapters] = useState<ChapterSnapshot[]>([]);
  const [path, setPath] = useState<PathItem[]>([]);
  const [selected, setSelected] = useState<ChapterSnapshot>();
  const [context, setContext] = useState<ScenarioCard>();
  const [evidence, setEvidence] = useState<EvidenceRef[]>([]);
  const [chosen, setChosen] = useState<EvidenceRef[]>([]);
  const [timeline, setTimeline] = useState<{ warnings: string[]; flags: string[] }>({ warnings: [], flags: [] });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>();
  const [history, setHistory] = useState<ChapterSnapshot[]>([]);
  const [impact, setImpact] = useState<{preview_id:string;affected_chapters:string[]}>();
  const [impactSelected, setImpactSelected] = useState<string[]>([]);
  const [recommendations,setRecommendations]=useState<Awaited<ReturnType<typeof recommendEvidence>>['suggestions']>([]);
  const refresh = async () => {
    setLoading(true);
    try {
      const [c, s, e, t] = await Promise.all([
        listChapters(project),
        getAuthoringContext(project),
        listEvidence(project),
        checkTimeline(project),
      ]);
      if (!alive.current) return;
      setError(undefined);
      setPath(c.path);
      setChapters(c.chapters);
      setContext(s.revision===0 ? {...s,topic:s.topic??topic} : s);
      setEvidence(e.refs); setTimeline(t);
      if (selected) {
        const found = c.chapters.find(
          (x) => x.chapter_id === selected.chapter_id,
        );
        if (found) setSelected(found);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "章节工作台暂不可用");
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => {
    alive.current = true;
    void refresh();
    return () => { alive.current = false; };
  }, [project]);
  const open = (item: PathItem) => {
    setHistory([]);
    setRecommendations([]);
    setChosen(chapters.find(x=>x.chapter_id===item.chapter_id)?.evidence_refs ?? []);
    setSelected(
      chapters.find((x) => x.chapter_id === item.chapter_id) ?? {
        project_id: project,
        chapter_id: item.chapter_id,
        revision: 0,
        path_version: "T/CAQ 10201-2020",
        content_blocks: [],
        metrics: [],
        evidence_refs: [],
        content_state: "empty",
        review_state: "pending",
        evidence_state: "missing",
        stale: false,
        stale_reasons: [],
      },
    );
  };
  const run = async (fn: () => Promise<ChapterSnapshot>) => {
    if (operationLock.current) return;
    operationLock.current = true; setBusy(true);
    try {
      const next = await fn();
      if (!alive.current) return;
      setSelected(next);
      setChosen(next.evidence_refs);
      await refresh();
    } catch (e) {
      message.error(e instanceof Error ? e.message : "保存失败");
    } finally {
      operationLock.current = false;
      if (alive.current) setBusy(false);
    }
  };
  const loadHistory = async () => { if (!selected) return; try { const result=await chapterHistory(project, selected.chapter_id); setHistory(result.snapshots); } catch (e) { message.error(e instanceof Error ? e.message : '历史读取失败'); } };
  const saveReviewed = (text:string,blocks:ContentBlock[],metrics:MetricSpec[],contentState?:'draft'|'complete') => {
    if(!selected)return;
    const structural=blocks.filter(block=>block.kind!=='text');
    const before={metrics:selected.metrics,blocks:selected.content_blocks.filter(block=>block.kind!=='text')};
    const after={metrics,blocks:structural};
    const previousText=selected.content_blocks.filter(block=>block.kind==='text').map(block=>block.text).join('\n');
    // Preserve the generated text/table/chart order and provenance on an unchanged save.
    let outgoing=blocks;
    if(text!==previousText){
      const textBlocks=blocks.filter(block=>block.kind==='text');
      const origin=textBlocks.some(block=>block.origin_kind==='simulation')?'simulation':'pending';
      let inserted=false;
      outgoing=blocks.flatMap(block=>{
        if(block.kind!=='text')return [block];
        if(inserted)return [];
        inserted=true;return [{...block,text,origin_kind:origin}];
      });
      if(!inserted)outgoing=[{kind:'text',text,origin_kind:origin},...outgoing];
    }
    const save=()=>run(()=>saveChapter(project,selected.chapter_id,selected.revision,outgoing,metrics,chosen,contentState));
    if(JSON.stringify(before)!==JSON.stringify(after)){
      Modal.confirm({title:'逐项核对指标与事实内容变化',width:760,okText:'已核对，保存为待审核版本',cancelText:'返回编辑',content:<div><p>请核对基线、目标、数据性质、要因及措施。保存不会自动标记事实已核实。</p><h4>原版本</h4><pre style={{whiteSpace:'pre-wrap',maxHeight:220,overflow:'auto'}}>{JSON.stringify(before,null,2)}</pre><h4>拟保存版本</h4><pre style={{whiteSpace:'pre-wrap',maxHeight:220,overflow:'auto'}}>{JSON.stringify(after,null,2)}</pre></div>,onOk:save});
    }else void save();
  };
  const saveScene = async () => { if (!context) return; try { const saved=await saveAuthoringContext(project, context, context.revision); setContext(saved); message.success('场景已保存'); } catch (e) { const err=e as {code?:string;message?:string}; if (err.code==='CHANGE_PREVIEW_REQUIRED') { try { const p=await previewChange(project,context.revision,context); setImpact(p); setImpactSelected(p.affected_chapters); } catch (previewError) { message.error(previewError instanceof Error?previewError.message:'影响分析失败'); } } else message.error(err.message??'场景保存失败'); } };
  const selectedIndex = selected ? path.findIndex(item => item.chapter_id === selected.chapter_id) : -1;
  const completedCount = path.filter(item => {
    const chapter = chapters.find(current => current.chapter_id === item.chapter_id);
    return Boolean(chapter && !chapter.stale && chapter.content_state === 'complete' && chapter.review_state === 'approved');
  }).length;
  const completionPercent = path.length ? Math.round(completedCount / path.length * 100) : 0;
  const chapterStatus = (chapter: ChapterSnapshot | undefined) => chapter
    ? `修订${chapter.revision} · 内容${chapter.content_state} · 审核${chapter.review_state} · 证据${chapter.evidence_state}`
    : '尚未保存';
  const auxiliaryItems = [
    { key: 'context', label: '场景设置', children: <Card title="场景卡" bordered={false}>
      <Form layout="vertical">
        <Form.Item label="课题名称"><Input value={context?.topic??''} onChange={e=>setContext({...context!,topic:e.target.value})}/></Form.Item>
        <Form.Item label="地区/地点"><Input value={context?.region ?? ""} onChange={e=>setContext({ ...context!, region: e.target.value })}/></Form.Item>
        <Form.Item label="工程或作业对象"><Input value={context?.object_name ?? ""} onChange={e=>setContext({ ...context!, object_name: e.target.value })}/></Form.Item>
        <Form.Item label="现有问题"><Input.TextArea value={context?.current_problem ?? ""} onChange={e=>setContext({ ...context!, current_problem: e.target.value })}/></Form.Item>
        <Form.Item label="目标来源"><Select value={context?.objective_source ?? "self_defined"} options={[{ value: "self_defined", label: "自定目标" }, { value: "directive", label: "指令性目标" }]} onChange={(v) => setContext({ ...context!, objective_source: v })}/></Form.Item>
        <Form.Item label="活动时间"><Input placeholder="按实际发生时间填写，未知可留空" value={context?.activity_time ?? ""} onChange={e=>setContext({ ...context!, activity_time: e.target.value })}/></Form.Item>
        <details><summary>补充场景条件（未知可留空）</summary>{([['location','具体地点'],['environment','环境条件'],['season','季节'],['personnel_range','人员能力及数量范围'],['equipment','机械设备'],['method','作业工法'],['constraints','受限条件']] as const).map(([field,label])=><Form.Item key={field} label={label}><Input value={context?.[field]??''} onChange={e=>setContext({...context!,[field]:e.target.value})}/></Form.Item>)}</details>
        <Button onClick={() => void saveScene()}>保存场景</Button>
      </Form>
    </Card> },
    { key: 'materials', label: '资料、活动与依据', children: <>
      <MaterialWorkspace projectId={project} onSourcesChanged={()=>{void listEvidence(project).then(e=>{if(alive.current)setEvidence(e.refs)})}} />
      <ActivityRecords project={project} onChanged={()=>void refresh()}/>
      <SourceRecords project={project} onChanged={()=>{void listEvidence(project).then(e=>{if(alive.current)setEvidence(e.refs)})}}/>
      <Card title="本章依据"><Select mode="multiple" style={{width:'100%'}} value={chosen.map(x=>`${x.source_kind}:${x.source_id}:${x.source_version}:${x.locator}`)} options={evidence.map(x=>({value:`${x.source_kind}:${x.source_id}:${x.source_version}:${x.locator}`,label:`${x.source_id} · ${x.locator}`}))} onChange={values=>setChosen(evidence.filter(x=>values.includes(`${x.source_kind}:${x.source_id}:${x.source_version}:${x.locator}`)))}/></Card>
      {selected&&<Card title="资料相关性建议"><Button onClick={async()=>{try{const result=await recommendEvidence(project,selected.chapter_id);if(alive.current)setRecommendations(result.suggestions)}catch(e){message.error(e instanceof Error?e.message:'推荐读取失败')}}}>按本章用途定位资料</Button><p>仅按全文解析内容定位候选依据，不替代事实核实。</p><List dataSource={recommendations} locale={{emptyText:'尚无推荐，可手动选择本章依据'}} renderItem={item=><List.Item actions={[<Button key="accept" onClick={()=>setChosen(old=>old.some(ref=>JSON.stringify(ref)===JSON.stringify(item.ref))?old:[...old,item.ref])}>采用依据</Button>]}><List.Item.Meta title={`${item.ref.source_id} · ${item.ref.locator}`} description={`${item.reason}；${item.supports}；${item.cannot_support}`}/></List.Item>}/></Card>}
    </> },
    { key: 'timeline', label: '活动时间检查', children: <Card bordered={false}><Alert type={context?.activity_time ? "info" : "warning"} message={context?.activity_time ? "已记录活动时间，请继续核对材料记录时间与实际发生时间" : "活动发生时间待补，上传时间不能代替活动时间"}/>{timeline.warnings.concat(timeline.flags).map(item=><Alert key={item} type="warning" message={item}/>)}</Card> },
  ];
  const chapterDirectory = <Card title="章节目录" extra={<Button type="primary" onClick={() => navigate('/ppt')}>成果检查与导出</Button>}>
    <p>作者确认 {completedCount}/{path.length} 章（以已保存内容和审核状态为准）</p>
    <Progress percent={completionPercent} status={completionPercent === 100 ? 'success' : 'active'} />
    <List bordered dataSource={path} renderItem={(item) => {
      const saved = chapters.find(x => x.chapter_id === item.chapter_id);
      const active = selected?.chapter_id === item.chapter_id;
      return <List.Item className={active ? 'authoring-chapter-active' : undefined} actions={[<Button key="open" type={active ? 'primary' : 'default'} onClick={() => open(item)}>{active ? '当前章节' : '编写/打开'}</Button>]}>
        <List.Item.Meta title={<Space><span>{item.title}</span>{saved?.content_state === 'complete' && <Tag color="green">内容已形成</Tag>}{saved?.review_state === 'approved' && <Tag color="blue">已审核</Tag>}</Space>} description={saved ? chapterStatus(saved) : item.expected_conclusion ?? item.purpose} />
      </List.Item>;
    }} />
  </Card>;
  if (loading && !path.length) return <Spin tip="正在恢复章节工作台" />;
  return (
    <div className="authoring-page">
      <h1>逐章编写与审核</h1>
      <p>内容形成、作者审核、事实核实分别记录；缺少资料可保留待核实项继续。</p>
      {error && (
        <Alert
          type="error"
          message={error}
          action={<Button onClick={() => void refresh()}>重试</Button>}
        />
      )}
      {selected ? <Collapse items={[{ key: 'chapters', label: `章节目录（当前第 ${selectedIndex + 1} 章）`, children: chapterDirectory }]} /> : chapterDirectory}
      {selected && (
        <Card title={`${path.find(item=>item.chapter_id===selected.chapter_id)?.title ?? '当前章节'} · 写作要求`} extra={<Space>
          <Button disabled={busy || selectedIndex <= 0} onClick={() => open(path[selectedIndex - 1])}>‹ 前一章</Button>
          <Button disabled={busy || selectedIndex < 0 || selectedIndex >= path.length - 1} onClick={() => open(path[selectedIndex + 1])}>后一章 ›</Button>
        </Space>}>
          <p>{path.find(item=>item.chapter_id===selected.chapter_id)?.expected_conclusion}</p>
          <p>建议图表：{path.find(item=>item.chapter_id===selected.chapter_id)?.analysis_methods?.join('、')}</p>
          <details><summary>查看本章范围与前后衔接</summary><p>标准依据：{path.find(item=>item.chapter_id===selected.chapter_id)?.standard_basis}</p><p>{path.find(item=>item.chapter_id===selected.chapter_id)?.purpose}</p><p>传递给后续章节：{path.find(item=>item.chapter_id===selected.chapter_id)?.next_input}</p></details>
        </Card>
      )}
      {selected && (
        <fieldset disabled={busy} style={{border:0,padding:0}}><ChapterReview
          snapshot={selected}
          onSave={saveReviewed}
          onGenerate={() =>
            void run(async () => {
              if (context?.revision===0) setContext(await saveAuthoringContext(project,context,0));
              return generateChapter(
                project,
                selected.chapter_id,
                selected.revision,
                crypto.randomUUID(),
                chosen,
              );
            })
          }
          onReview={(s, n) =>
            void run(() =>
              reviewChapter(
                project,
                selected.chapter_id,
                s,
                "author",
                n,
                selected.revision,
              ),
            )
          }
          onVerify={(s, g) =>
            void run(() =>
              verifyChapterEvidence(
                project,
                selected.chapter_id,
                s,
                "author",
                g,
                selected.revision,
                chosen,
              ),
            )
          }
        /></fieldset>
      )}
      <Collapse items={auxiliaryItems} style={{ marginTop: 16 }} />
      {selected && <Card title="章节历史"><Button onClick={()=>void loadHistory()}>查看历史版本</Button><Select style={{minWidth:260,marginLeft:8}} placeholder="选择历史修订" options={history.map(x=>({value:x.revision,label:`修订 ${x.revision} · ${x.content_state}`}))} onChange={revision=>{const old=history.find(x=>x.revision===revision);if(old)setSelected(old)}}/><Button disabled={!history.length||selected.revision===Math.max(...history.map(x=>x.revision))} onClick={()=>{const latest=Math.max(...chapters.filter(x=>x.chapter_id===selected.chapter_id).map(x=>x.revision),0);void run(()=>saveChapter(project,selected.chapter_id,latest,selected.content_blocks,selected.metrics,selected.evidence_refs))}}>恢复为新版本</Button></Card>}
      <Modal title="场景变更影响分析" open={!!impact} onCancel={()=>setImpact(undefined)} onOk={async()=>{if(!impact||!context)return;try{await applyChange(project,{preview_id:impact.preview_id,expected_revision:context.revision,context,chapter_ids:impactSelected});setImpact(undefined);await refresh();message.success('变更已应用，请复核所选章节')}catch(e){message.error(e instanceof Error?e.message:'变更应用失败')}}}>
        <p>请选择需要重新审核的关联章节：</p><Select mode="multiple" style={{width:'100%'}} value={impactSelected} options={impact?.affected_chapters.map(id=>({value:id,label:id}))} onChange={setImpactSelected}/>
      </Modal>
      <Tag>版本：{context?.revision ?? 1}</Tag>
    </div>
  );
}
