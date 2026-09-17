import { Collapse } from 'antd';
import { useNavigate } from 'react-router';
import { ChapterReporting } from '../components/reporting/ChapterReporting';
import { CheckCircleOutlined, DownloadOutlined, FilePptOutlined, RocketOutlined } from '@ant-design/icons';
import { Alert, Button, Card, Input, List, Tag, message } from 'antd';
import { useEffect, useMemo, useRef, useState } from 'react';
import { downloadPpt, generatePpt } from '../api/ppt';
import { errorMessage } from '../api/client';
import { StepPage } from '../components/StepPage';
import { useWizard } from '../context/WizardContext';
import { loadChartImage, loadDataset } from '../storage/db';
const blobBase64 = (blob: Blob) => new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(',', 2)[1] ?? '');
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob);
});
export function PPTPage() { const navigate=useNavigate(); return <main className="step-page"><header className="page-heading"><div><span className="eyebrow">03 · DELIVER</span><h1>成果检查与导出</h1><p>汇总各章，检查缺项与版本变化，再导出成果。章节中的表格与图表会一同导出。</p></div><Button onClick={()=>navigate('/authoring')}>返回逐章编写</Button></header><ChapterReporting kind="export"/><Collapse items={[{key:'legacy',label:'旧流程成果（仅兼容历史研讨，不代表完整QC章节）',children:<LegacyPPTPage/>}]}/></main> }
function LegacyPPTPage() {
    const { state, setPpt } = useWizard();
    const [name, setName] = useState((state.topic ?? 'QC成果').slice(0, 80));
    const [dataSummary, setDataSummary] = useState('');
    const [busy, setBusy] = useState(false);
    const [downloading, setDownloading] = useState(false);
    const latest = useRef(state);
    useEffect(() => { latest.current = state; }, [state]);
    useEffect(() => {
        let disposed = false;
        if (state.dataRef)
            void loadDataset(state.dataRef).then(data => {
                if (!data || disposed)
                    return;
                const stats = data.columns.filter(c => ['number', 'percent'].includes(c.inferred_type)).map(column => {
                    const values = data.rows.map(row => row.values[column.name]).filter(value => value !== null && value !== '').map(Number).filter(Number.isFinite);
                    if (!values.length)
                        return `${column.name}：无有效数值`;
                    const format = (value: number) => column.display_format === 'percent' ? `${Number((value * 100).toFixed(4))}%` : String(Number(value.toFixed(4)));
                    return `${column.name}：有效${values.length}项，范围${format(Math.min(...values))}—${format(Math.max(...values))}，均值${format(values.reduce((sum, value) => sum + value, 0) / values.length)}`;
                });
                setDataSummary(`数据版本 ${data.revision}，共 ${data.rows.length} 行、${data.columns.length} 列。\n${stats.join('\n')}`);
            }).catch(e => message.error(errorMessage(e)));
        return () => { disposed = true; };
    }, [state.dataRef, state.datasetRevision]);
    const checklist = useMemo(() => [{ label: '课题', ok: Boolean(state.topic) }, { label: '已确认数据', ok: state.dataConfirmed && !!dataSummary }, { label: '结构化研讨纪要', ok: Boolean(state.discussionSummary) }, { label: '图表图片', ok: Boolean(state.chartImageRef) }], [state, dataSummary]);
    const ready = checklist.every(item => item.ok) && !!name.trim();
    const create = async () => {
        if (busy || !ready || !state.topic || !state.discussionSummary || !state.chartImageRef)
            return;
        const source = state;
        setBusy(true);
        try {
            const stored = await loadChartImage(source.chartImageRef!);
            if (!stored)
                throw new Error('图表图片已丢失，请返回上一步重新确认');
            if (stored.blob.size > 5 * 1024 * 1024)
                throw new Error('图表图片超过 5MB');
            const result = await generatePpt({ project_name: name.trim(), topic: source.topic!, data_summary: dataSummary, discussion_summary: source.discussionSummary!, chart_images: [await blobBase64(stored.blob)] });
            if (latest.current !== source)
                throw new Error('项目已变化，请重新生成成果');
            await setPpt(result);
            message.success('QC 成果文件已生成');
        }
        catch (error) {
            message.error(errorMessage(error));
        }
        finally {
            setBusy(false);
        }
    };
    const download = async () => {
        if (!state.pptResult || downloading)
            return;
        setDownloading(true);
        try {
            await downloadPpt(state.pptResult.file_id, state.pptResult.display_name);
        }
        catch (error) {
            message.error(errorMessage(error));
        }
        finally {
            setDownloading(false);
        }
    };
    return <StepPage eyebrow="06 · DELIVER" title="生成 QC 成果" description="将课题、数据统计、研讨纪要和图表组成中文成果，长内容自动分页。" actions={<>
    {state.pptResult && <Button icon={<DownloadOutlined />} loading={downloading} onClick={() => void download()}>下载 PPT</Button>}
    <Button type="primary" icon={<RocketOutlined />} disabled={!ready} loading={busy} onClick={() => void create()}>生成 PPT</Button>
  </>}>
    <div className="ppt-layout"><Card className="deliver-card"><div className="ppt-icon"><FilePptOutlined /></div><label htmlFor="report-name">成果名称</label><Input id="report-name" value={name} maxLength={80} onChange={e => setName(e.target.value)}/>
      <List className="deliver-list" dataSource={checklist} renderItem={item => <List.Item><span>{item.label}</span>{item.ok ? <Tag color="success" icon={<CheckCircleOutlined />}>已就绪</Tag> : <Tag>缺失</Tag>}</List.Item>}/>
      {!ready && <Alert type="warning" showIcon message="请补齐流程成果并填写成果名称"/>}
      {state.pptResult && <Alert type="success" showIcon message={state.pptResult.display_name} description={`有效期至 ${new Date(state.pptResult.expires_at).toLocaleString()}`}/>}
    </Card><section className="slide-preview"><header><span>REPORT OUTLINE</span><b>成果结构示意</b></header><p>下方为内容结构。实际页数随文本与图表数量变化，请下载后检查排版。</p>{['课题简介', '现状与数据', '原因分析', '对策与建议', '数据图表', '总结'].map((title, index) => <article key={title}><i>{String(index + 1).padStart(2, '0')}</i><div><small>QC REPORT</small><b>{title}</b></div></article>)}</section></div>
  </StepPage>;
}
