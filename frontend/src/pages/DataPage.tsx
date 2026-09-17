import { CheckOutlined, CloudUploadOutlined, ExperimentOutlined, RobotOutlined, RollbackOutlined } from '@ant-design/icons';
import { Alert, Button, Card, Checkbox, Empty, Select, Space, Table, Tag, message } from 'antd';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router';
import { applyCleaning, confirmData, previewCleaning, undoCleaning, uploadData } from '../api/data';
import { adviseCleaning } from '../api/insight';
import { errorMessage } from '../api/client';
import { StepPage } from '../components/StepPage';
import { useWizard } from '../context/WizardContext';
import { loadDataset, listProjectDatasets, type StoredDataset } from '../storage/db';
import type { CleaningAction, CleaningAdviceResponse, CleaningApplyRequest, CleaningIssue, CleaningRule, DatasetResponse } from '../types/api';
import { MaterialWorkspace } from '../components/materials/MaterialWorkspace';
const actionLabel: Record<CleaningAction, string> = { keep: '保留', drop_rows: '删除行', median: '中位数填补', forward_fill: '向下填充', convert_number: '转数值', convert_percent: '转百分比' };
const issueLabel: Record<CleaningIssue['issue_type'], string> = { empty_row: '空行', total_row: '合计行', missing: '缺失值', outlier: '异常值', type_conversion: '类型转换' };
function defaultAction(issue: CleaningIssue): CleaningAction {
    return (issue.suggested_actions.find(action => action !== 'keep') ?? 'keep') as CleaningAction;
}
interface Preview {
    request: CleaningApplyRequest;
    signature: string;
    rows: DatasetResponse['rows'];
}
export function DataPage() {
    const { state, storeDataset, confirmDataset } = useWizard();
    const [dataset, setDataset] = useState<DatasetResponse | null>(null);
    const [datasets,setDatasets] = useState<StoredDataset[]>([]);
    useEffect(()=>{let active=true;void listProjectDatasets(state.currentProjectId).then(items=>{if(active)setDatasets(items)});return()=>{active=false}},[state.currentProjectId,state.dataRef,state.datasetRevision]);
    const [file, setFile] = useState<File | null>(null);
    const [selected, setSelected] = useState<number[]>([]);
    const [overrides, setOverrides] = useState<Record<number, CleaningAction>>({});
    const [preview, setPreview] = useState<Preview | null>(null);
    const [advice, setAdvice] = useState<CleaningAdviceResponse | null>(null);
    const [busy, setBusy] = useState(false);
    const [page, setPage] = useState(1);
    const [pageSize, setPageSize] = useState(50);
    const locked = useRef(false);
    const navigate = useNavigate();
    useEffect(() => {
        let disposed = false;
        if (state.dataRef)
            void loadDataset(state.dataRef).then(local => {
                if (!local || disposed)
                    return;
                setDataset({ ...local, confirmed_revision: state.dataConfirmed ? local.revision : null });
                setFile(new File([local.sourceFile], local.filename));
            }).catch(e => message.error(errorMessage(e)));
        return () => { disposed = true; };
    }, [state.dataRef, state.datasetRevision, state.dataConfirmed]);
    const rules = useMemo<CleaningRule[]>(() => selected.flatMap(index => {
        const issue = dataset?.report.issues[index];
        return issue ? [{ action: overrides[index] ?? defaultAction(issue), column: issue.column, row_ids: [...issue.row_ids] }] : [];
    }), [selected, overrides, dataset]);
    const request = dataset ? { dataset_id: dataset.dataset_id, base_revision: dataset.revision, rules } : null;
    const signature = JSON.stringify(request);
    const activePreview = preview?.signature === signature ? preview : null;
    const clearDerived = () => { setSelected([]); setOverrides({}); setPreview(null); setAdvice(null); setPage(1); };
    const run = async (operation: () => Promise<void>) => {
        if (locked.current)
            return;
        locked.current = true;
        setBusy(true);
        try {
            await operation();
        }
        catch (error) {
            message.error(errorMessage(error));
        }
        finally {
            locked.current = false;
            setBusy(false);
        }
    };
    const upload = (next: File) => run(async () => {
        if (next.size > 10 * 1024 * 1024)
            throw new Error('文件不能超过 10MB');
        const result = await uploadData(next);
        // A replacement is a new dataset, even when both versions are zero.
        await storeDataset(result, next);
        setDataset(result);
        setFile(next);
        clearDerived();
        message.success('文件已检测，原始值尚未修改');
    });
    const doPreview = () => run(async () => {
        if (!request || !rules.length)
            return;
        const snapshot = structuredClone(request);
        const result = await previewCleaning(snapshot);
        setPreview({ request: snapshot, signature: JSON.stringify(snapshot), rows: result.preview_rows });
        setPage(1);
    });
    const apply = () => run(async () => {
        if (!activePreview || !file)
            return;
        const result = await applyCleaning(activePreview.request);
        await storeDataset(result, file, state.dataRef ?? undefined);
        setDataset(result);
        clearDerived();
        message.success('清洗已应用，请核验当前数据');
    });
    const undo = () => run(async () => {
        if (!dataset || !file)
            return;
        const result = await undoCleaning(dataset.dataset_id, dataset.revision);
        await storeDataset(result, file, state.dataRef ?? undefined);
        setDataset(result);
        clearDerived();
        message.success('已恢复原始数据，请重新确认');
    });
    const confirm = () => run(async () => {
        if (!dataset || activePreview)
            return;
        await confirmData(dataset.dataset_id, dataset.revision);
        await confirmDataset();
        message.success('数据已确认，可用于图表或研讨');
    });
    const askAdvice = () => run(async () => {
        if (!dataset)
            return;
        setAdvice(await adviseCleaning(dataset.dataset_id));
        message.success('AI 清洗建议已生成');
    });
    const useAdvice = () => {
        if (!advice || !dataset || busy)
            return;
        const items = advice.items.filter(item => dataset.report.issues[item.index]?.suggested_actions.includes(item.action));
        setSelected(items.filter(item => item.action !== 'keep').map(item => item.index));
        setOverrides(Object.fromEntries(items.map(item => [item.index, item.action])));
        setPreview(null);
    };
    const columns = dataset?.columns.map(column => ({
        title: <span>{column.name}<small className="column-type">{column.inferred_type}</small></span>,
        key: column.name,
        render: (_: unknown, row: DatasetResponse['rows'][number]) => {
            const value = row.values[column.name];
            return column.display_format === 'percent' && typeof value === 'number' ? `${Number((value * 100).toFixed(6))}%` : String(value ?? '—');
        },
    })) ?? [];
    const displayed = activePreview?.rows ?? dataset?.rows ?? [];
    return <StepPage wide eyebrow="TOOLS · MATERIALS" title="资料与数据" description="参考资料和表格可随时补充；确认表格数据后可用于图表与研讨。" aside={dataset && <Space><Tag>版本 {dataset.revision}</Tag><Tag color={state.dataConfirmed ? 'success' : 'processing'}>{state.dataConfirmed ? '已确认' : '待确认'}</Tag></Space>} actions={<>
      <Button onClick={() => navigate('/authoring')}>返回逐章编写</Button><Button disabled={!state.dataConfirmed} onClick={() => navigate('/discussion')}>数据研讨</Button>
      <Button icon={<RollbackOutlined />} disabled={busy || !dataset || dataset.revision === 0} onClick={() => void undo()}>恢复原始数据</Button>
      <Button icon={<RobotOutlined />} disabled={busy || !dataset} onClick={() => void askAdvice()}>AI 清洗建议</Button>
      {activePreview ? <><Button disabled={busy} onClick={() => setPreview(null)}>取消预览</Button><Button icon={<ExperimentOutlined />} disabled={busy} onClick={() => void apply()}>应用预览规则</Button></> : <Button icon={<ExperimentOutlined />} disabled={busy || !rules.length} onClick={() => void doPreview()}>预览影响</Button>}
      <Button type="primary" icon={<CheckOutlined />} disabled={busy || !dataset || !!activePreview || dataset.rows.length === 0} onClick={() => void confirm()}>确认数据</Button>
    </>}>
    <MaterialWorkspace projectId={state.currentProjectId} />
    {!!datasets.length && <Select aria-label="当前项目数据集" style={{width:'100%',marginBottom:16}} value={state.dataRef} options={datasets.map(item=>({value:item.dataRef,label:`${item.filename} · v${item.revision}`}))} onChange={ref=>void run(async()=>{const item=datasets.find(x=>x.dataRef===ref);if(!item)return;const response=await import('../api/data').then(m=>m.getDataset(item.dataset_id));await storeDataset(response,new File([item.sourceFile],item.filename),ref);clearDerived()})}/>}
    {!dataset ? <label className="upload-zone"><input type="file" aria-label="选择数据文件" accept=".csv,.xls,.xlsx" hidden disabled={busy} onChange={e => { const next = e.target.files?.[0]; if (next)
            void upload(next); e.target.value = ''; }}/><CloudUploadOutlined /><b>{busy ? '正在检测…' : '选择数据文件'}</b><span>CSV / XLS / XLSX · 最大 10MB · 5000 行</span></label> : <div className="data-layout">
      <Card className="issue-panel" title={`检测项 · ${dataset.report.issues.length}`} extra={<label className="replace-file"><input hidden aria-label="替换数据文件" type="file" accept=".csv,.xls,.xlsx" disabled={busy} onChange={e => { const next = e.target.files?.[0]; if (next)
            void upload(next); e.target.value = ''; }}/>替换文件</label>}>
        {dataset.report.issues.length === 0 ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="未发现明显问题"/> : <div className="issue-list">{dataset.report.issues.map((issue, index) => <div key={`${issue.issue_type}-${index}`}>
          <Checkbox disabled={busy} checked={selected.includes(index)} onChange={e => { setSelected(current => e.target.checked ? [...current, index] : current.filter(x => x !== index)); setPreview(null); }}><span><b>{issueLabel[issue.issue_type]}</b><small>{issue.column ?? '整行'} · {issue.row_ids.length} 行</small></span></Checkbox>
          <Select aria-label={`第${index + 1}项处理方式`} size="small" disabled={busy} value={overrides[index] ?? defaultAction(issue)} options={issue.suggested_actions.map(value => ({ value, label: actionLabel[value as CleaningAction] ?? value }))} onChange={value => { setOverrides(current => ({ ...current, [index]: value })); setPreview(null); }}/>
          <Button type="link" size="small" onClick={() => { const position = displayed.findIndex(row => issue.row_ids.includes(row.row_id)); if (position >= 0)
                    setPage(Math.floor(position / pageSize) + 1); }}>定位首行</Button>
        </div>)}</div>}
        {advice && <Alert style={{ marginTop: 12 }} type="info" showIcon message={`AI 顾问：${advice.overall}`} description={<div>{advice.items.map((item, index) => <p key={index}>{dataset.report.issues[item.index] && <><Tag>{actionLabel[item.action]}</Tag>{item.reason}</>}</p>)}<Button disabled={busy} size="small" onClick={useAdvice}>按建议勾选</Button><small> 模型：{advice.model}</small></div>}/>}
      </Card>
      <Card className="table-panel" title={activePreview ? '规则预览（尚未应用）' : '当前数据'} extra={<span>{displayed.length} 行 × {columns.length} 列</span>}>
        {activePreview && <Alert type="info" message="确认预览后应用规则；取消预览可以保留当前数据。"/>}
        <Table rowKey="row_id" size="small" columns={columns} dataSource={displayed} scroll={{ x: 'max-content', y: 480 }} pagination={{ current: page, pageSize, showSizeChanger: true, pageSizeOptions: [20, 50, 100, 200], showTotal: total => `共 ${total} 行`, onChange: (next, size) => { setPage(next); setPageSize(size); } }}/>
      </Card>
    </div>}
  </StepPage>;
}
