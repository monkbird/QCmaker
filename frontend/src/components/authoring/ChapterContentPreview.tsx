import ReactECharts from 'echarts-for-react/lib/core';
import * as echarts from 'echarts/core';
import { BarChart, LineChart } from 'echarts/charts';
import { GridComponent, TitleComponent, TooltipComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import type { ContentBlock } from '../../types/authoring';
import './ChapterContentPreview.css';

echarts.use([BarChart, LineChart, GridComponent, TitleComponent, TooltipComponent, CanvasRenderer]);

type StructuredBlock = ContentBlock & { chart_type?: 'bar' | 'line' | 'pareto'; unit?: string; origin_kind?: string };
const marker = (block: StructuredBlock) => ({ simulation: '【模拟】', hypothesis: '【假设】', pending: '【待核实】' } as Record<string, string>)[block.origin_kind ?? ''] ?? '';

export function ChapterContentPreview({ blocks }: { blocks: ContentBlock[] }) {
  return <div className="chapter-content-preview" aria-label="结构化内容预览">
    {blocks.map((raw, index) => {
      const block = raw as StructuredBlock;
      if (block.kind === 'table') {
        const columns = block.columns ?? Object.keys(block.rows?.[0] ?? {});
        return <section className="chapter-preview-table" key={index}><h4>{marker(block)}{block.title ?? '章节表格'}</h4><table><thead><tr>{columns.map(column => <th key={column}>{column}</th>)}</tr></thead><tbody>{(block.rows ?? []).map((row, rowIndex) => <tr key={rowIndex}>{columns.map(column => <td key={column}>{String(row[column] ?? '待补')}</td>)}</tr>)}</tbody></table></section>;
      }
      if ((block.kind as string) === 'chart') {
        const sourceRows = (block.rows ?? []).filter((row): row is { label: string; value: number } => typeof row.label === 'string' && typeof row.value === 'number' && Number.isFinite(row.value));
        const rows = block.chart_type === 'pareto' ? [...sourceRows].sort((a, b) => b.value - a.value || a.label.localeCompare(b.label)) : sourceRows;
        const chartType = block.chart_type === 'line' ? 'line' : 'bar';
        const total = rows.reduce((sum, row) => sum + row.value, 0);
        const cumulative = total > 0 ? rows.reduce<number[]>((result, row, rowIndex) => { result.push((result[rowIndex - 1] ?? 0) + row.value / total * 100); return result; }, []) : [];
        const paretoSeries = block.chart_type === 'pareto' ? [{ type: 'bar' as const, name: block.unit ?? '数值', data: rows.map(row => row.value) }, { type: 'line' as const, name: '累计占比', yAxisIndex: 1, data: cumulative, smooth: false }] : [{ type: chartType, data: rows.map(row => row.value), smooth: chartType === 'line' }];
        return <section className="chapter-preview-chart" key={index}><h4>{marker(block)}{block.title ?? '章节图表'} <small>（{block.unit ?? '数值'}）</small></h4><ReactECharts option={{ tooltip: { trigger: 'axis' }, grid: { left: 48, right: block.chart_type === 'pareto' ? 58 : 18, top: 18, bottom: 42 }, xAxis: { type: 'category', data: rows.map(row => row.label) }, yAxis: block.chart_type === 'pareto' ? [{ type: 'value', name: block.unit }, { type: 'value', name: '累计占比%', min: 0, max: 100 }] : { type: 'value', name: block.unit }, series: paretoSeries }} style={{ height: 260 }} notMerge lazyUpdate /></section>;
      }
      return null;
    })}
  </div>;
}
