import { Collapse } from 'antd';
import { ChapterReporting } from '../components/reporting/ChapterReporting';
import { BarChartOutlined, CheckOutlined, LineChartOutlined, PieChartOutlined, RobotOutlined, ThunderboltOutlined } from '@ant-design/icons';
import { Alert, Button, Card, Radio, Select, Space, Tag, message } from 'antd';
import { useEffect, useMemo, useRef, useState } from 'react';
import ReactECharts from 'echarts-for-react/lib/core';
import * as echarts from 'echarts/core';
import { BarChart, LineChart, PieChart } from 'echarts/charts';
import { GridComponent, TitleComponent, TooltipComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
echarts.use([BarChart, LineChart, PieChart, GridComponent, TitleComponent, TooltipComponent, CanvasRenderer]);
import { useNavigate } from 'react-router';
import { generateChart, recommendChart } from '../api/visualization';
import { chartInsight } from '../api/insight';
import { errorMessage } from '../api/client';
import { StepPage } from '../components/StepPage';
import { useWizard } from '../context/WizardContext';
import { loadDataset } from '../storage/db';
import type { ChartInsightResponse, ChartRecommendation, ChartResponse, DatasetResponse } from '../types/api';
export function VisualizationPage() {
    const navigate = useNavigate();
    const { state } = useWizard();
    return <main className="step-page"><header className="page-heading"><div><h1>图表工具</h1><p>按需补充独立图表；逐章生成的图表已随正文保存，无须在此重新制作。</p></div><Button onClick={()=>navigate('/authoring')}>返回逐章编写</Button></header><ChapterReporting kind="chart"/><Collapse items={[{key:"legacy",label:"旧数据集图表",children:<VisualizationEditor key={JSON.stringify([state.currentProjectId, state.dataRef, state.datasetRevision])}/>}]}/></main>;
}

export function LegacyVisualizationPage() {
    const { state } = useWizard();
    return <VisualizationEditor key={JSON.stringify([state.currentProjectId, state.dataRef, state.datasetRevision])} />;
}

function VisualizationEditor() {
    const { state, setChart } = useWizard();
    const [dataset, setDataset] = useState<DatasetResponse | null>(null);
    const [type, setType] = useState<'bar' | 'line' | 'pie'>('bar');
    const [x, setX] = useState<string>();
    const [y, setY] = useState<string>();
    const [aggregation, setAggregation] = useState<'none' | 'sum' | 'mean' | 'count' | undefined>();
    const [result, setResult] = useState<ChartResponse | null>(null);
    const [busy, setBusy] = useState(false);
    const [insight, setInsight] = useState<ChartInsightResponse | null>(null);
    const [insightLoading, setInsightLoading] = useState(false);
    const chartRef = useRef<ReactECharts>(null);
    const navigate = useNavigate();
    // A synchronous lock covers recommendation, generation, and confirmation alike.
    const request = useRef(0);
    const locked = useRef(false);
    useEffect(() => {
        let active = true;
        if (state.dataRef) void loadDataset(state.dataRef).then(local => {
            if (!active || !local) return;
            setDataset({ dataset_id: local.dataset_id, revision: local.revision, confirmed_revision: local.revision, filename: local.filename, columns: local.columns, rows: local.rows, report: local.report });
            setX(local.columns[0]?.name);
            setY(local.columns.find(c => c.inferred_type === 'number' || c.inferred_type === 'percent')?.name);
        }).catch(e => { if (active) message.error(errorMessage(e)); });
        return () => { active = false; request.current += 1; };
    }, [state.dataRef, state.datasetRevision]);
    const options = dataset?.columns.map(c => ({ label: `${c.name} · ${c.inferred_type}`, value: c.name })) ?? [];
    const create = async (source: 'manual' | 'rules' | 'ai' = 'manual') => {
        if (!dataset || locked.current) return;
        locked.current = true;
        const id = ++request.current;
        const current = () => request.current === id;
        setBusy(true);
        setInsightLoading(source === 'ai');
        setResult(null);
        setInsight(null);
        try {
            let advice: ChartInsightResponse | null = null;
            let selection: Pick<ChartRecommendation, 'chart_type' | 'x_axis' | 'y_axis' | 'aggregation'> = { chart_type: type, x_axis: x ?? '', y_axis: y ?? '', aggregation };
            if (source === 'rules') selection = await recommendChart(dataset.columns, dataset.rows.slice(0, 50));
            if (source === 'ai') {
                advice = await chartInsight(dataset.dataset_id, dataset.revision);
                selection = advice.recommendation;
            }
            if (!current()) return;
            if (source !== 'manual') {
                setType(selection.chart_type);
                setX(selection.x_axis);
                setY(selection.y_axis);
                setAggregation(selection.aggregation);
            }
            if (!selection.x_axis || (!selection.y_axis && selection.aggregation !== 'count')) return;
            const next = await generateChart({ ...selection, dataset_id: dataset.dataset_id, revision: dataset.revision });
            if (!current()) return;
            setResult({ ...next, option: { ...next.option, animation: false } });
            setInsight(advice);
        } catch (e) {
            if (current()) message.error(errorMessage(e));
        } finally {
            if (current()) {
                locked.current = false;
                setBusy(false);
                setInsightLoading(false);
            }
        }
    };
    const confirm = async () => {
        const instance = chartRef.current?.getEchartsInstance();
        if (!instance || !result || locked.current) return;
        locked.current = true;
        const id = ++request.current;
        setBusy(true);
        try {
            const blob = await (await fetch(instance.getDataURL({ pixelRatio: 2, backgroundColor: '#ffffff' }))).blob();
            if (request.current !== id) return;
            await setChart(result.option, blob);
            if (request.current === id) navigate('/ppt');
        } catch (e) {
            if (request.current === id) message.error(errorMessage(e));
        } finally {
            if (request.current === id) { locked.current = false; setBusy(false); }
        }
    };
    const typeOptions = useMemo(() => [{ label: <><BarChartOutlined /> 柱状图</>, value: 'bar' }, { label: <><LineChartOutlined /> 折线图</>, value: 'line' }, { label: <><PieChartOutlined /> 饼图</>, value: 'pie' }], []);
    return <StepPage wide eyebrow="05 · VISUALIZE" title="建立数据证据" description="AI 顾问结合数据画像选型并给出解读；图表只读取已确认的后端 revision。" actions={<><Button icon={<RobotOutlined />} disabled={!dataset || busy || insightLoading} loading={insightLoading} onClick={() => void create('ai')}>AI 图表顾问</Button><Button icon={<ThunderboltOutlined />} disabled={!dataset || busy || insightLoading} onClick={() => void create('rules')}>规则推荐</Button><Button disabled={!dataset || busy} onClick={() => void create()} loading={busy && !insightLoading}>生成预览</Button><Button type="primary" icon={<CheckOutlined />} disabled={!result || busy || insightLoading} onClick={() => void confirm()}>确认图表</Button></>}>{!dataset ? <Alert type="warning" showIcon message="未找到已确认数据"/> : <div className="chart-layout"><Card className="chart-controls" title="图表口径"><label>图表类型</label><Radio.Group optionType="button" value={type} options={typeOptions} disabled={busy || insightLoading} onChange={e => { setType(e.target.value); setResult(null); setInsight(null); }}/><label>X 轴 · 分类</label><Select value={x} options={options} disabled={busy || insightLoading} onChange={value => { setX(value); setResult(null); setInsight(null); }}/><label>Y 轴 · 数值</label><Select value={y} options={options} disabled={busy || insightLoading} onChange={value => { setY(value); setResult(null); setInsight(null); }}/><label>重复类别聚合</label><Select allowClear placeholder="使用图表默认值" value={aggregation} disabled={busy || insightLoading} onChange={value => { setAggregation(value); setResult(null); setInsight(null); }} options={['none', 'sum', 'mean', 'count'].map(value => ({ value, label: value }))}/>{result && <div className="processing-box"><b>实际处理口径</b><Space wrap><Tag color="cyan">{result.processing.aggregation}</Tag><Tag>{result.processing.grouped_categories} 个重复类别</Tag><Tag>{result.processing.converted_row_ids.length} 行已转换</Tag></Space>{result.processing.warnings.map(item => <p key={item}>{item}</p>)}</div>}
      {insight && <Alert className="insight-panel" style={{ marginTop: 12 }} type={insight.source === 'ai' ? 'success' : 'warning'} showIcon icon={<RobotOutlined />} message={<span>{insight.source === 'ai' ? 'AI 解读' : `已回退规则推荐（${insight.caveats[0] ?? 'AI 暂不可用'}）`} <Tag style={{ marginLeft: 6 }}>{insight.model}</Tag></span>} description={<div><p style={{ marginBottom: 6 }}><b>选型理由：</b>{insight.recommendation.reason}</p>{insight.insight && <p style={{ marginBottom: 6 }}>{insight.insight}</p>}{insight.caveats.length > 0 && insight.source === 'ai' && <ul style={{ paddingLeft: 18, margin: 0 }}>{insight.caveats.map((item, index) => <li key={index}><small>{item}</small></li>)}</ul>}</div>}/>}</Card><Card className="chart-canvas" title={state.topic}>{result ? <ReactECharts echarts={echarts} notMerge ref={chartRef} option={result.option} style={{ height: 500 }}/> : <div className="chart-placeholder"><BarChartOutlined /><b>选择字段后生成图表</b><span>确认统计口径，避免图表悄悄改变事实</span></div>}</Card></div>}</StepPage>;
}
